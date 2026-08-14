import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The city checkout this process operates on. config.toml, .env.*, and data/
# all resolve against it; only tool assets (migrations/) stay relative to ROOT.
# Defaults to this repo for a combined checkout. A thin per-city repo selects
# itself via run.py --city-dir, which sets T2_CITY_DIR before t2 is imported —
# an env var rather than a flag threaded through, so `python -m t2.*`
# entrypoints and subprocesses spawned by the web app inherit it for free.
CITY_DIR = Path(os.environ.get("T2_CITY_DIR") or ROOT).resolve()

# Which OSM server uploads target: "dev" (sandbox) or "prod". Picks which
# .env file is read. run.py overwrites this from its --env/--prod flag before
# importing the rest of t2; nothing else changes it. Deliberately a module
# attribute, not an environment variable — see README "Targeting dev vs prod".
OSM_ENV = "dev"


@dataclass
class Config:
    city_slug: str
    city_name: str
    city_neighbourhoods_url: str
    source_sqlite_path: str
    default_bbox: tuple[float, float, float, float]
    overpass_url: str
    match_radius_m: float
    match_near_m: float
    checks_enabled: dict[str, bool]
    checks_params: dict[str, dict]
    changesets_per_minute: float
    changeset_comment_template: str

    osm_source: str
    osm_pbf_url: str
    osm_city_bbox: tuple[float, float, float, float]
    osm_extract_dir: Path

    export_attribution: str
    export_import_plan: str

    osm_api_base: str
    osm_client_id: str
    osm_client_secret: str
    osm_redirect_uri: str
    flask_secret_key: str
    fernet_key: str

    # data_root holds checkout-level state: the OSM extract (its own key
    # above), the OAuth token blob, and publish/archive artifacts. Per-city
    # working state — tool.db, tiles, streets, run caches — lives under
    # data_dir = data_root/<slug>, so a second city cannot interleave runs
    # into Toronto's DB or overwrite its tile layer, and snapshot ids in
    # `runs` stay unambiguous (they are per-source-DB, and each city's runs
    # live with that city). With one repo per city both levels sit inside the
    # city checkout; a multi-city checkout still keeps slugs apart.
    data_root: Path = field(default=CITY_DIR / "data")
    tool_db_path: Path = field(default=CITY_DIR / "data" / "tool.db")
    migrations_dir: Path = field(default=ROOT / "migrations")
    data_dir: Path = field(default=CITY_DIR / "data")

    @property
    def osm_extract_json(self) -> Path:
        """The filtered OSM extract stage 2 reads. One definition, so the
        filename is city-derived everywhere instead of a literal in nine
        modules."""
        return self.osm_extract_dir / f"{self.city_slug}-addresses.json"


def _read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def load() -> Config:
    env_name = OSM_ENV.strip().lower()
    if env_name not in ("dev", "prod"):
        raise ValueError(f"OSM_ENV must be 'dev' or 'prod', got {env_name!r}")
    env = _read_env_file(CITY_DIR / f".env.{env_name}")
    default_api = (
        "https://api.openstreetmap.org" if env_name == "prod"
        else "https://master.apis.dev.openstreetmap.org"
    )

    toml_path = CITY_DIR / "config.toml"
    try:
        with open(toml_path, "rb") as f:
            cfg = tomllib.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"No config.toml in {CITY_DIR}. This repo is the engine; city "
            "config lives in a per-city checkout (e.g. toronto-2-address-import). "
            "Point at one with run.py --city-dir <path> or T2_CITY_DIR."
        ) from None

    checks_enabled: dict[str, bool] = {k: bool(v) for k, v in cfg.get("checks", {}).items()}
    checks_params: dict[str, dict] = dict(cfg.get("check_params", {}))

    bbox = tuple(cfg["run_defaults"]["bbox"])
    assert len(bbox) == 4

    osm_section = cfg.get("osm", {})
    osm_source = str(osm_section.get("source", "local"))
    if osm_source not in ("local", "overpass"):
        raise ValueError(f"config.osm.source must be 'local' or 'overpass', got {osm_source!r}")
    osm_pbf_url = str(osm_section.get(
        "pbf_url",
        "https://download.geofabrik.de/north-america/canada/ontario-latest.osm.pbf",
    ))
    if "city_bbox" not in osm_section:
        raise ValueError(
            f"{toml_path} is missing [osm] city_bbox. It was called toronto_bbox "
            "before multi-city; rename the key rather than relying on a default, "
            "so a stale config cannot silently clip a second city to Toronto."
        )
    city_bbox = tuple(osm_section["city_bbox"])
    assert len(city_bbox) == 4
    extract_dir_raw = str(osm_section.get("extract_dir", "data/osm"))
    extract_dir = Path(extract_dir_raw)
    if not extract_dir.is_absolute():
        extract_dir = CITY_DIR / extract_dir

    city_section = cfg.get("city", {})
    missing = [k for k in ("slug", "name") if not city_section.get(k)]
    if missing:
        raise ValueError(
            f"{toml_path} is missing [city] {', '.join(missing)} — required since "
            "multi-city; see future-work/multi-city/02-city-config-contract.md."
        )

    export_section = cfg.get("export", {})

    city_slug = str(city_section["slug"])
    data_dir = CITY_DIR / "data" / city_slug

    # Guard against a pre-slug layout: per-city state used to live directly in
    # data/. A tool.db at the root with none under data/<slug>/ means this
    # checkout has the new code but unmigrated data — running anyway would
    # silently start a fresh, empty DB beside 1,300 runs of history.
    legacy_db = CITY_DIR / "data" / "tool.db"
    if legacy_db.exists() and not (data_dir / "tool.db").exists():
        raise RuntimeError(
            f"{legacy_db} is the pre-multi-city layout. Move the per-city files "
            f"into {data_dir} (tool.db + -wal/-shm, tiles.json, tiles/, "
            "neighbourhoods/, streets.json, osm_current_run*.json, "
            "upload_run_*.osm, multi_fixes/) — see DONE.md 'Slugged data layout'."
        )

    return Config(
        city_slug=city_slug,
        city_name=str(city_section["name"]),
        city_neighbourhoods_url=str(city_section.get("neighbourhoods_url", "")).strip(),
        source_sqlite_path=cfg["source"]["sqlite_path"],
        default_bbox=bbox,  # type: ignore
        overpass_url=cfg["run_defaults"]["overpass_url"],
        match_radius_m=float(cfg["conflation"]["match_radius_m"]),
        match_near_m=float(cfg["conflation"]["match_near_m"]),
        checks_enabled=checks_enabled,
        checks_params=checks_params,
        changesets_per_minute=float(cfg["upload"]["changesets_per_minute"]),
        changeset_comment_template=cfg["upload"]["changeset_comment_template"],
        osm_source=osm_source,
        osm_pbf_url=osm_pbf_url,
        osm_city_bbox=city_bbox,  # type: ignore
        osm_extract_dir=extract_dir,
        export_attribution=str(export_section.get("attribution", "")),
        export_import_plan=str(export_section.get("import_plan", "")),
        osm_api_base=env.get("OSM_API_BASE") or default_api,
        osm_client_id=env.get("OSM_CLIENT_ID", ""),
        osm_client_secret=env.get("OSM_CLIENT_SECRET", ""),
        osm_redirect_uri=env.get("OSM_REDIRECT_URI") or "http://127.0.0.1:5000/oauth/callback",
        flask_secret_key=env.get("FLASK_SECRET_KEY") or "dev-secret",
        fernet_key=env.get("FERNET_KEY", ""),
        data_dir=data_dir,
        tool_db_path=data_dir / "tool.db",
    )
