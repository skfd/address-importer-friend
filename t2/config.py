import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from accordeur import normalize_street

ROOT = Path(__file__).resolve().parent.parent

# The city checkout this process operates on. config.toml, .env.*, and data/
# all resolve against it; only tool assets (migrations/) stay relative to ROOT.
# Defaults to this repo for a combined checkout. A thin per-city repo selects
# itself via run.py --city-dir, which sets T2_CITY_DIR before t2 is imported —
# an env var rather than a flag threaded through, so `python -m t2.*`
# entrypoints and subprocesses spawned by the web app inherit it for free.
CITY_DIR = Path(os.environ.get("T2_CITY_DIR") or ROOT).resolve()

# This tool's own repo. A fact about the engine, not about any city, so it is
# a constant rather than config: it backs the footer's "MIT" licence link and
# stands in for a city that declares no repo of its own.
ENGINE_REPO = "https://github.com/skfd/address-importer-friend"

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
    # "props:<KEY>" | None. A lifecycle-status field (Barrie's STATUS, the
    # Niagara Region's LifeCycleStatus — TODO §11). Declaring it obliges a
    # [status] active_values policy, same lie-together pattern as unit:
    # a source that publishes Pending/Proposed rows forces an explicit
    # decision about which values are importable reality.
    status: str | None = None
    # "number" (canonical column, the default) | "full" — the housenumber is
    # the leading whitespace token of the combined column. Waterloo publishes
    # ONLY CIVIC_ADDR; its tracker number column is 100% NULL (2026-08-16).
    # Rejected together with full_from = "number+street" (circular).
    number_from: str = "number"

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
    "address_class", "unit", "status",
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
    known = {"street_from", "full_from", "number_from", *_SOURCE_FIELD_OPTIONAL}
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
    number_from = section.get("number_from", "number")
    if number_from not in ("number", "full") and not _PROPS_KEY_RE.match(
        str(number_from)
    ):
        raise ValueError(
            f"{origin} [source_fields] number_from = {number_from!r} is invalid; "
            "expected 'number' (canonical column), 'full' (leading token of "
            "the combined column), or 'props:<KEY>' (Thunder Bay's ADDRESS "
            "carries the qualifier the integer column drops)."
        )
    if number_from == "full" and full_from == "number+street":
        raise ValueError(
            f"{origin} [source_fields] number_from = 'full' with full_from = "
            "'number+street' is circular — the combined column would be "
            "synthesized from the number it is supposed to provide."
        )
    optional = {
        name: _spec(
            name,
            section[name],
            ("unit", "full-after-street") if name == "unit" else (),
        )
        if name in section else None
        for name in _SOURCE_FIELD_OPTIONAL
    }
    if optional["unit"] == "full-after-street" and full_from != "full":
        raise ValueError(
            f"{origin} [source_fields] unit = 'full-after-street' requires "
            "full_from = 'full' — a synthesized combined column cannot carry "
            "a unit tail."
        )
    return SourceFields(
        street_from=street_from, full_from=full_from,
        number_from=number_from, **optional,
    )


# "collapse-to-civic": one candidate per civic address, units discarded.
# "per-door-or-collapse": each civic group is classified by its unit numbering
#   (t2/units.py) and becomes either one node per front door carrying
#   addr:unit, or one node for the building carrying addr:flats. Opt-in per
#   city — Guelph's source geocodes every unit and its townhouse rows are real
#   doors; Toronto and Hamilton stack units on the parcel point and stay on
#   collapse-to-civic. Every query, match and dedup path gates on this value
#   so those cities remain byte-identical.
UNIT_POLICIES = ("collapse-to-civic", "per-door-or-collapse")


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


def parse_status_policy(
    section: dict, sf: SourceFields, origin: str = "config.toml"
) -> tuple[str, ...] | None:
    """Validate the [status] section against the [source_fields] declaration.

    Same lie-together contract as units (TODO §11, opened by the Niagara
    Region's 260 Proposed rows and made blocking by Barrie's 3,369 Pending):
    a source that declares a lifecycle-status field forces an explicit list of
    the values that count as importable reality, and an active_values list
    without a declared field is a recipe copied from the wrong city. Rows
    whose status is not in the list (including NULL) are excluded from every
    source query."""
    unknown = sorted(set(section) - {"active_values"})
    if unknown:
        raise ValueError(
            f"{origin} [status] has unknown key(s) {unknown}; the only key is "
            "'active_values'."
        )
    values = section.get("active_values")
    if values is None:
        if sf.declares("status"):
            raise ValueError(
                f"{origin} [source_fields] declares status = {sf.status!r} but "
                "has no [status] active_values. A source with lifecycle states "
                "must say which values are importable (e.g. ['Current']) — "
                "ingesting Pending/Proposed rows silently is not an option."
            )
        return None
    if not sf.declares("status"):
        raise ValueError(
            f"{origin} [status] active_values = {values!r} but [source_fields] "
            "declares no status field — nothing to filter. Declare "
            "status = 'props:<KEY>', or remove the section."
        )
    if (
        not isinstance(values, list)
        or not values
        or not all(isinstance(v, str) and v.strip() for v in values)
    ):
        raise ValueError(
            f"{origin} [status] active_values = {values!r} is invalid; expected "
            "a non-empty list of non-empty strings."
        )
    return tuple(values)


# Tags the engine derives per candidate. A city may add constant tags of its
# own, but never redefine one of these: a typo in config silently overriding a
# conflated street would be indistinguishable from a conflation bug.
@dataclass(frozen=True)
class Links:
    """Where this city's operator-facing chrome points.

    Tier 1 de-Torontoized the engine's behaviour; its *chrome* stayed Toronto's
    until 2026-08-29, so Guelph's and Hamilton's operators were shown Toronto's
    repo, Toronto's OSM thread and Toronto's open-data licence. Everything here
    is optional: a city that declares nothing gets the engine's own links and no
    city-specific credit, never another city's.
    """

    #: This city checkout's repo. Footer "GitHub", and the static export's
    #: "Run the live tool". Falls back to the engine's repo.
    repo: str = ""
    #: The OSM community thread where this import is discussed. Hidden when
    #: absent — a city that has not announced yet has nowhere to point.
    discussion: str = ""
    #: The import proposal or evidence document this checkout publishes; the
    #: static-export banner describes the snapshot as evidence for it.
    proposal: str = ""
    #: The source's open-data licence, credited in the footer beside OSM's.
    #: Distinct from `[export] source_license`, which is the SPDX id written
    #: onto the changeset: this is a name and a URL for a human to click.
    open_data_name: str = ""
    open_data_url: str = ""


_LINK_KEYS = ("repo", "discussion", "proposal", "open_data")


def parse_links(section: dict, origin: str = "config.toml") -> Links:
    """Validate `[links]`. Absent section = every link absent.

    Loud like the rest of the contract: an unknown key is a typo that would
    otherwise silently drop a link, a non-http value is a mistake, and
    `open_data` must carry both a name and a URL or neither — a credit with no
    link, or a link with nothing to call it, is half a citation.
    """
    if not section:
        return Links()
    unknown = sorted(set(section) - set(_LINK_KEYS))
    if unknown:
        raise ValueError(
            f"{origin} [links] has unknown key(s) {unknown}; valid keys are "
            f"{sorted(_LINK_KEYS)}."
        )

    def _url(key: str, value) -> str:
        if value in (None, ""):
            return ""
        if not isinstance(value, str) or not value.startswith(("http://", "https://")):
            raise ValueError(
                f"{origin} [links] {key} = {value!r} is not an http(s) URL."
            )
        return value

    open_data = section.get("open_data") or {}
    if open_data and not isinstance(open_data, dict):
        raise ValueError(
            f"{origin} [links] open_data must be a table with `name` and `url` "
            'keys, e.g. open_data = { name = "Guelph Open Data", url = "https://..." }.'
        )
    od_unknown = sorted(set(open_data) - {"name", "url"})
    if od_unknown:
        raise ValueError(
            f"{origin} [links] open_data has unknown key(s) {od_unknown}; "
            "valid keys are ['name', 'url']."
        )
    od_name = str(open_data.get("name", "") or "").strip()
    od_url = _url("open_data.url", open_data.get("url"))
    if bool(od_name) != bool(od_url):
        raise ValueError(
            f"{origin} [links] open_data needs both `name` and `url`, or "
            "neither: a credit with no link, or a link with nothing to call "
            "it, is half a citation."
        )

    return Links(
        repo=_url("repo", section.get("repo")),
        discussion=_url("discussion", section.get("discussion")),
        proposal=_url("proposal", section.get("proposal")),
        open_data_name=od_name,
        open_data_url=od_url,
    )


def parse_street_overrides(section: dict, origin: str = "config.toml") -> dict[str, str]:
    """Validate this city's `[streets] overrides` — source spelling -> the
    OSM-canonical name.

    These are the names where the source and OSM disagree about the actual
    name, not about how to abbreviate it, so no normalizer can bridge them
    (`accordeur.StreetProfile`). They are a fact about one city's data, which
    is why they are declared per city rather than compiled in: Toronto needs
    thirteen, Guelph and Hamilton none. A city that declares none gets an empty
    table and every street name reaches conflation exactly as the source wrote
    it. Absent section = no overrides, so nothing is required of a new city.

    An entry that does not change the normalized form is refused: it is a no-op
    the normalizer already covers, and leaving it in the table would make it
    look like a rule that is doing work.
    """
    raw = section.get("overrides", section) if section else {}
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(
            f"{origin} [streets] overrides must be a table of "
            "\"Source Spelling\" = \"OSM Spelling\" pairs."
        )
    out: dict[str, str] = {}
    for src, dst in raw.items():
        if not isinstance(dst, str) or not dst.strip():
            raise ValueError(
                f"{origin} [streets] overrides {src!r} = {dst!r} is not a "
                "street name."
            )
        if normalize_street(src) == normalize_street(dst):
            raise ValueError(
                f"{origin} [streets] overrides {src!r} -> {dst!r} does not "
                "change the normalized form; the normalizer already covers "
                "this case, so the entry does nothing. Remove it."
            )
        out[str(src)] = dst
    return out


DERIVED_NODE_TAGS = ("addr:housenumber", "addr:street", "addr:postcode", "addr:source")


def parse_node_tags(section: dict, origin: str = "config.toml") -> dict[str, str]:
    """Validate [export] node_tags — constant tags written on every node.

    Absent key = absent capability (03): Toronto declares none and must keep
    writing none, while Guelph's published tagging plan promises
    addr:city=Guelph on every node. Values are constants, not templates —
    anything varying per address comes from the source, not from here.
    """
    tags = section.get("node_tags")
    if tags is None:
        return {}
    if not isinstance(tags, dict) or not tags:
        raise ValueError(
            f"{origin} [export] node_tags = {tags!r} is invalid; expected a "
            'non-empty table of constant tags, e.g. { "addr:city" = "Guelph" }. '
            "Omit the key entirely for a city that adds none."
        )
    bad = {k: v for k, v in tags.items() if not isinstance(v, str) or not v.strip() or not k.strip()}
    if bad:
        raise ValueError(
            f"{origin} [export] node_tags has empty or non-string entries {bad!r}; "
            "every key and value must be a non-empty string."
        )
    clash = sorted(set(tags) & set(DERIVED_NODE_TAGS))
    if clash:
        raise ValueError(
            f"{origin} [export] node_tags redefines {clash} — the engine derives "
            f"{list(DERIVED_NODE_TAGS)} per candidate. A constant here would "
            "overwrite the conflated value on every node in the city."
        )
    return {k.strip(): v.strip() for k, v in tags.items()}


def parse_source_license(section: dict, origin: str = "config.toml") -> str:
    """Validate [export] source_license — the changeset's `source:license` tag.

    Optional, and absent for Toronto: its published changeset-tag table has no
    such key and adding one would put a tag on the changeset that the proposal
    does not document. Guelph's plan names OGL-Canada-2.0. Declared-but-blank
    is a mistake, not a way to opt out — omit the key instead.
    """
    value = section.get("source_license")
    if value is None:
        return ""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{origin} [export] source_license = {value!r} is invalid; expected "
            "a licence identifier such as 'OGL-Canada-2.0'. Omit the key "
            "entirely for a city whose changeset tags name no licence."
        )
    return value.strip()


STREET_CASE_VALUES = ("preserve", "title")


def parse_street_case(section: dict, origin: str = "config.toml") -> str:
    """Validate [export] street_case — how `addr:street` is written out.

    "preserve" (the default, and every city scaffolded before 2026-08-29) writes
    the source's own spelling. "title" title-cases it on the export path only,
    for the sources that publish ALL-CAPS names: Quinte West's "ANNA COURT",
    Brant's "GRAND RIVER STREET NORTH", Oakville's "MCCRANEY ST". Conflation is
    case-insensitive either way, so this changes what is uploaded and nothing
    about what matches.

    An unknown value is refused rather than treated as "preserve": a typo here
    would silently upload shouting street names to a live city.
    """
    value = section.get("street_case", "preserve") if section else "preserve"
    if not isinstance(value, str) or value not in STREET_CASE_VALUES:
        raise ValueError(
            f"{origin} [export] street_case = {value!r} is invalid; expected "
            f"one of {STREET_CASE_VALUES}. Omit the key for a source that "
            "already publishes mixed-case street names."
        )
    return value


_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

# The wrap-up page's three accents, in the order it uses them: the headline
# accent, a bright highlight for peaks and hero numbers, and a positive/complete
# tone. The defaults are the operator animation's own legend colours (in
# progress amber, uploaded green, control blue), so a city that declares no
# palette still gets two artifacts that look like they belong together.
# Toronto's config overrides them with the TTC subway colours its published
# one-pager was built in.
STATS_DEFAULT_ACCENT = "#3057D4"
STATS_DEFAULT_ACCENT_2 = "#F5A623"
STATS_DEFAULT_ACCENT_3 = "#2ECC71"


@dataclass(frozen=True)
class StatsTheme:
    """Presentation-only settings for the wrap-up page (`[stats]`).

    Every key is optional: a city that declares no [stats] block gets the
    neutral engine look and the documented session threshold. Nothing here
    changes a number except session_gap_minutes, which is a measurement choice
    rather than a style one and lives here because it is the wrap-up's alone.
    """

    accent: str = STATS_DEFAULT_ACCENT
    accent_2: str = STATS_DEFAULT_ACCENT_2
    accent_3: str = STATS_DEFAULT_ACCENT_3
    # Small uppercase line above the title. Empty renders "<city> - Open Data - OSM".
    badge: str = ""
    session_gap_minutes: int = 30


def parse_stats(section: dict, origin: str = "config.toml") -> StatsTheme:
    """Validate the optional [stats] section."""
    known = {"accent", "accent_2", "accent_3", "badge", "session_gap_minutes"}
    unknown = sorted(set(section) - known)
    if unknown:
        raise ValueError(
            f"{origin} [stats] has unknown key(s) {unknown}; valid keys are "
            f"{sorted(known)}."
        )
    colours = {}
    for key in ("accent", "accent_2", "accent_3"):
        if key not in section:
            continue
        value = section[key]
        if not isinstance(value, str) or not _HEX_RE.match(value):
            raise ValueError(
                f"{origin} [stats] {key} = {value!r} is invalid; expected a "
                "six-digit hex colour such as '#DA291C'. The value is "
                "interpolated into the page's CSS, so the charset is "
                "restricted rather than passed through."
            )
        colours[key] = value
    gap = section.get("session_gap_minutes", 30)
    if not isinstance(gap, int) or isinstance(gap, bool) or not 1 <= gap <= 720:
        raise ValueError(
            f"{origin} [stats] session_gap_minutes = {gap!r} is invalid; expected "
            "a whole number of minutes between 1 and 720. It is the gap after "
            "which the wrap-up decides the operator got up from the desk."
        )
    badge = section.get("badge", "")
    if not isinstance(badge, str):
        raise ValueError(f"{origin} [stats] badge = {badge!r} must be a string.")
    return StatsTheme(badge=badge.strip(), session_gap_minutes=gap, **colours)


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
    # None (no unit field), "collapse-to-civic" (one candidate per
    # (number, street, municipality), unit-less row elected representative) or
    # "per-door-or-collapse" (per-door nodes where the source shows doors, one
    # addr:flats node where it shows stacked suites). See UNIT_POLICIES.
    units_policy: str | None
    # None (no status field) or the tuple of status values whose rows are
    # importable reality; everything else is filtered from every source query.
    status_active_values: tuple[str, ...] | None
    # Source spelling -> OSM-canonical name, for the handful of streets
    # where this city's source and OSM disagree about the actual name.
    # Empty for a city that declares none.
    street_overrides: dict[str, str]
    # Operator-facing chrome: this city's repo, OSM thread, proposal and
    # open-data credit. Empty for a city that declares none.
    links: Links
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
    # Constant tags on every created node. Empty for a city that adds none;
    # {"addr:city": "Guelph"} where the published tagging plan promises one.
    export_node_tags: dict[str, str]
    # Changeset `source:license`. Empty where the city's published changeset
    # tag table names no licence (Toronto).
    export_source_license: str
    # "preserve" | "title". How addr:street is cased on the way out; only the
    # ALL-CAPS sources need "title" (see parse_street_case).
    export_street_case: str

    # Wrap-up page presentation + its one measurement knob. Always present;
    # a city with no [stats] block gets StatsTheme's defaults.
    stats: StatsTheme

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
        status_active_values=parse_status_policy(
            cfg.get("status", {}), source_fields, str(toml_path)
        ),
        street_overrides=parse_street_overrides(cfg.get("streets", {}), str(toml_path)),
        links=parse_links(cfg.get("links", {}), str(toml_path)),
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
        export_node_tags=parse_node_tags(export_section, str(toml_path)),
        export_source_license=parse_source_license(export_section, str(toml_path)),
        export_street_case=parse_street_case(export_section, str(toml_path)),
        stats=parse_stats(cfg.get("stats", {}), str(toml_path)),
        osm_api_base=env.get("OSM_API_BASE") or default_api,
        osm_client_id=env.get("OSM_CLIENT_ID", ""),
        osm_client_secret=env.get("OSM_CLIENT_SECRET", ""),
        osm_redirect_uri=env.get("OSM_REDIRECT_URI") or "http://127.0.0.1:5000/oauth/callback",
        flask_secret_key=env.get("FLASK_SECRET_KEY") or "dev-secret",
        fernet_key=env.get("FERNET_KEY", ""),
        data_dir=data_dir,
        tool_db_path=data_dir / "tool.db",
    )
