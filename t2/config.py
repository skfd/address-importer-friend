import os
import re
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


# A [source_fields] value is either a canonical tracker column ("street",
# "full") or "props:<KEY>", a key inside the tracker's per-row props JSON.
# Keys are embedded into SQL string literals, so the charset is restricted.
_PROPS_KEY_RE = re.compile(r"^props:[A-Za-z0-9_]+$")


@dataclass(frozen=True)
class SourceFields:
    """Where each logical field lives in this city's source DB — the per-city
    projection recipe from future-work/multi-city/02-city-config-contract.md.

    The tracker's canonical columns are not dependable across cities (18 of 42
    datasets store the street name component only; Hamilton publishes no
    combined address at all), so every city must say where street/full come
    from, and which optional props exist. An undeclared optional field is an
    absent *capability*: the projection emits SQL NULL for it and every
    feature that reads it is disabled-for-cause (see 03-capability-gating.md),
    never silently run against NULLs.
    """

    street_from: str            # "street" | "full" | "props:<KEY>"
    full_from: str              # "full" | "number+street" (synthesized)
    municipality: str | None    # "props:<KEY>" or None = capability absent
    ward: str | None
    lo_num: str | None
    lo_num_suf: str | None
    hi_num: str | None
    hi_num_suf: str | None
    address_class: str | None
    # "unit" (canonical tracker column) | "props:<KEY>" | None. Declaring it
    # obliges the config to also pick a [units] policy — a declared unit with
    # no policy is the silent-drop failure mode 09-units.md exists to prevent.
    unit: str | None = None

    def declares(self, name: str) -> bool:
        """True when the optional field ``name`` is mapped for this city."""
        return getattr(self, name) is not None

    @property
    def has_ranges(self) -> bool:
        return self.declares("lo_num") and self.declares("hi_num")

    @property
    def address_class_key(self) -> str | None:
        """The props key holding the address class, or None if undeclared."""
        if self.address_class is None:
            return None
        return self.address_class.removeprefix("props:")


_SOURCE_FIELD_OPTIONAL = (
    "municipality", "ward", "lo_num", "lo_num_suf", "hi_num", "hi_num_suf",
    "address_class", "unit",
)


def parse_source_fields(section: dict, origin: str = "config.toml") -> SourceFields:
    """Validate and build the [source_fields] projection recipe.

    Loud by design: a missing section, an unknown key (likely a typo that
    would otherwise silently drop a capability), or a malformed spec all
    raise. ``origin`` names the config file in error messages."""
    if not section:
        raise ValueError(
            f"{origin} is missing [source_fields] — required since multi-city "
            "Tier 2. Declare where street/full come from and which optional "
            "props exist; see future-work/multi-city/02-city-config-contract.md "
            "and config.example.toml for Toronto's worked example."
        )
    known = {"street_from", "full_from", *_SOURCE_FIELD_OPTIONAL}
    unknown = sorted(set(section) - known)
    if unknown:
        raise ValueError(
            f"{origin} [source_fields] has unknown key(s) {unknown}; "
            f"valid keys are {sorted(known)}."
        )

    def _spec(key: str, value, allowed_literals: tuple[str, ...]) -> str:
        if not isinstance(value, str) or not (
            value in allowed_literals or _PROPS_KEY_RE.match(value)
        ):
            raise ValueError(
                f"{origin} [source_fields] {key} = {value!r} is invalid; "
                f"expected one of {allowed_literals} or 'props:<KEY>' "
                "(<KEY> limited to [A-Za-z0-9_])."
            )
        return value

    for req in ("street_from", "full_from"):
        if req not in section:
            raise ValueError(
                f"{origin} [source_fields] is missing {req} — required with no "
                "default, so a config cannot silently inherit another city's "
                "street resolution."
            )
    street_from = _spec("street_from", section["street_from"], ("street", "full"))
    full_from = section["full_from"]
    if full_from not in ("full", "number+street"):
        raise ValueError(
            f"{origin} [source_fields] full_from = {full_from!r} is invalid; "
            "expected 'full' or 'number+street'."
        )
    optional = {
        name: _spec(name, section[name], ("unit",) if name == "unit" else ())
        if name in section else None
        for name in _SOURCE_FIELD_OPTIONAL
    }
    return SourceFields(street_from=street_from, full_from=full_from, **optional)


UNIT_POLICIES = ("collapse-to-civic",)


def parse_units_policy(
    section: dict, sf: SourceFields, origin: str = "config.toml"
) -> str | None:
    """Validate the [units] section against the [source_fields] declaration.

    The two must agree: a source that declares a unit field forces an explicit
    policy choice (09-units.md — the options differ in what data survives, so
    the decision must be in config, not a code default), and a policy without
    a declared unit field is a recipe copied from the wrong city."""
    unknown = sorted(set(section) - {"policy"})
    if unknown:
        raise ValueError(
            f"{origin} [units] has unknown key(s) {unknown}; the only key is 'policy'."
        )
    policy = section.get("policy")
    if policy is None:
        if sf.declares("unit"):
            raise ValueError(
                f"{origin} [source_fields] declares unit = {sf.unit!r} but has "
                "no [units] policy. A unit-bearing source must choose one "
                f"of {list(UNIT_POLICIES)} (see future-work/multi-city/"
                "09-units.md) — dropping units silently is not an option."
            )
        return None
    if policy not in UNIT_POLICIES:
        raise ValueError(
            f"{origin} [units] policy = {policy!r} is invalid; "
            f"expected one of {list(UNIT_POLICIES)}."
        )
    if not sf.declares("unit"):
        raise ValueError(
            f"{origin} [units] policy = {policy!r} but [source_fields] declares "
            "no unit field — nothing to collapse. Declare unit = 'unit' or "
            "'props:<KEY>', or remove the policy."
        )
    return policy


@dataclass
class Config:
    city_slug: str
    city_name: str
    city_neighbourhoods_url: str
    # Declared layer fields (multi-city Tier 4, decided 2026-08-15 when city #4
    # would have grown the sniff list a third time). Empty = legacy sniffing.
    # A declared parent field always prefixes the tile name (a deliberate
    # "district within community" layer, e.g. Quinte West's name+district_n);
    # the sniffed COMMUNITY fallback still prefixes only ambiguous names, so
    # Toronto's and Hamilton's tile names cannot move.
    city_neighbourhood_name_field: str
    city_neighbourhood_parent_field: str
    source_sqlite_path: str
    source_fields: SourceFields
    # None (no unit field) or "collapse-to-civic": one candidate per
    # (number, street, municipality), unit-less row elected representative.
    units_policy: str | None
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
    source_fields = parse_source_fields(cfg.get("source_fields", {}), str(toml_path))

    hood_name_field = str(city_section.get("neighbourhood_name_field", "")).strip()
    hood_parent_field = str(city_section.get("neighbourhood_parent_field", "")).strip()
    if (hood_name_field or hood_parent_field) and not str(
        city_section.get("neighbourhoods_url", "")
    ).strip():
        raise ValueError(
            f"{toml_path} declares [city] neighbourhood_name_field/parent_field "
            "but no neighbourhoods_url — the fields describe that layer; declaring "
            "them without one is a recipe copied from the wrong city."
        )

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
        city_neighbourhood_name_field=hood_name_field,
        city_neighbourhood_parent_field=hood_parent_field,
        source_sqlite_path=cfg["source"]["sqlite_path"],
        source_fields=source_fields,
        units_policy=parse_units_policy(cfg.get("units", {}), source_fields, str(toml_path)),
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
