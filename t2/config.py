import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

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

    tool_db_path: Path = field(default=ROOT / "data" / "tool.db")
    migrations_dir: Path = field(default=ROOT / "migrations")
    data_dir: Path = field(default=ROOT / "data")

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
    env = _read_env_file(ROOT / f".env.{env_name}")
    default_api = (
        "https://api.openstreetmap.org" if env_name == "prod"
        else "https://master.apis.dev.openstreetmap.org"
    )

    toml_path = ROOT / "config.toml"
    with open(toml_path, "rb") as f:
        cfg = tomllib.load(f)

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
        extract_dir = ROOT / extract_dir

    city_section = cfg.get("city", {})
    missing = [k for k in ("slug", "name") if not city_section.get(k)]
    if missing:
        raise ValueError(
            f"{toml_path} is missing [city] {', '.join(missing)} — required since "
            "multi-city; see future-work/multi-city/02-city-config-contract.md."
        )

    export_section = cfg.get("export", {})

    return Config(
        city_slug=str(city_section["slug"]),
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
    )
