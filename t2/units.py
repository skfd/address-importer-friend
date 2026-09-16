"""Unit-shape classification for `[units] policy = "per-door-or-collapse"`.

A unit-bearing source publishes one row per unit. `collapse-to-civic` throws
all of them away and keeps one row per civic address; this policy asks a
prior question first — *is each of these units its own front door, or are they
suites inside one building?* — and keeps them as separate nodes only in the
first case.

**The numbering decides it, not the geometry.** A suite number encodes the
floor or the building it sits in; a door number does not. Strip the last two
digits off every unit and ask whether what remains takes more than one value:

    93 Arthur Street South    101..1411, stems 1-14   -> 14 storeys  -> collapse
    150 Wellington Street E   101..1802, stems 1-18   -> 18 storeys  -> collapse
    71 Bayberry Drive         D101..D409, stems D1-D4 -> building D  -> collapse
    302 College Avenue West   1..214, no stem          -> 214 doors  -> nodes

A floor designator is not always a digit. `LL01`, `B1`, `PH2` name the lower
level, the basement and the penthouse, and where they sit alongside real
3-digit floor codes they are read as storeys rather than as doors — see
`is_coded`, which is where that exception and the two vetoes that survive it
are argued.

Guelph's numbers were measured against this on 2026-09-15 and the rule has to
catch 3-digit, 4-digit *and* letter-prefixed codes in one pass: a 3-digit-only
test reads 93 Arthur Street South as 193 front doors packed into 66 m, and so
does any test based on spacing alone. Two earlier classifiers for this were
built on geometry and both were wrong in exactly that way.

Geometry survives as the *guard* on sequential numbering, measured against a
townhouse's minimum buildable width. Below `NO_LOCATION_M` the source has not
given the units distinct positions at all, so there is nowhere to put separate
nodes; between that and `DOOR_SPACING_M` the points are distinct but too tight
to be separate ground-level entrances, and the group goes to a human.

Ambiguity resolves toward collapse, never toward nodes. A wrongly collapsed
group loses detail the source still holds and can be revisited; a wrongly
exploded one uploads dozens of invented front doors, and rejecting them one at
a time is not a review.

Pure functions over rows — no database, no config. The policy that calls this
lives in `candidates`, and the group it must be handed is the whole civic
group city-wide, not the part of it inside the current tile.
"""
import hashlib
import re
from collections import defaultdict

from .geo import haversine

# A townhouse's minimum buildable width. Sequential units spaced at least this
# far apart are separate ground-level entrances; closer than this they are not,
# whatever the numbering says.
DOOR_SPACING_M = 4.5

# Below this the source has not placed the units distinctly — they share a
# point, or differ by less than the error in placing one. There is no per-door
# location to map even if the units really are doors.
NO_LOCATION_M = 2.0

# OSM refuses a tag value longer than this, so a listing that does not fit
# cannot be uploaded at all. Guelph has three: 85 Mullin Drive (110 units
# numbered 1A;1B;2A;2B...) and two like it, where every unit carries a letter
# suffix or the numbering steps by two, and nothing range-compresses.
OSM_TAG_VALUE_MAX = 255

COLLAPSE = "collapse"
NODES = "nodes"
REVIEW = "review"
NO_UNITS = "no-units"

# What an operator may overrule the rule with, at /units/shapes. These are
# shapes, not classifier verdicts: `review` is deliberately absent because it
# is collapse plus a reason to look, and an operator who has looked has no
# reason left to record. `skip` is the one shape the rule can never reach on
# its own -- it is for 252 Stone Road West, whose 140 "units" are storefronts
# and where both a civic node and forty front doors would assert something
# false.
OVERRIDES = ("nodes", "collapse", "civic-only", "skip")

# An addr:unit value that is a *listing* rather than one designator: several
# separated by semicolons, or a numeric range. `PH-2` and `A-1` stay single.
# Guelph's towers were mapped as one building way carrying every unit this
# way -- `addr:unit=101-116;201-215;...` -- which is the collapsed shape under
# the identity key. Conflation, the shapes page and mechanical edit #3 all
# have to agree on what counts, so the test lives here once.
UNIT_LISTING = re.compile(r";|^[A-Z]*[0-9]+-[A-Z]*[0-9]+$", re.IGNORECASE)
# A range wider than this is a typo (`1-1000`), not a building; refuse to
# expand it rather than allocate a thousand designators.
MAX_RANGE_WIDTH = 500

# prefix letters, digits, suffix letters — "101", "D101", "101A", "1001".
_UNIT = re.compile(r"([A-Z]*)(\d+)([A-Z]*)")


def parse_unit(unit: str) -> tuple[str, int, str] | None:
    """Split a unit designator into (letter prefix, number, letter suffix).

    None when it does not have that shape at all, which is the signal to stop
    reasoning about it structurally and carry it through verbatim.
    """
    if not unit:
        return None
    m = _UNIT.fullmatch(str(unit).strip().upper())
    if not m:
        return None
    return m.group(1), int(m.group(2)), m.group(3)


def _stem(parsed: tuple[str, int, str]) -> str | None:
    """The floor or building a coded unit belongs to: everything left after
    the trailing two digits. `101` -> `1`, `1411` -> `14`, `D101` -> `D1`.

    None when the number is too short to carry a code — a two-digit unit is
    `41`, a door, not floor 0 unit 41.
    """
    prefix, num, _suffix = parsed
    digits = str(num)
    if len(digits) < 3:
        return None
    return prefix + digits[:-2]


def is_coded(units) -> bool:
    """True when the numbering encodes a floor or building, i.e. the units are
    stacked suites rather than doors in a row.

    At least two distinct stems must appear. One stem is not evidence:
    `101..124` alone is a single floor, and reads just as well as 24 doors
    numbered from 101.

    A unit whose number is too short to carry a stem does not automatically
    veto — a floor designator does not have to be a digit. `LL01`, `B1`, `AT1`
    and `PH2` name the lower level, the basement, the attic and the penthouse,
    which is *positive* evidence the building is stacked, and reading them as
    doors inverts the strongest signal in the data. 108 Summit Ridge Drive
    (`101-112;201-212;301-312;401-412;LL01-LL04`) is a four-storey walkup that
    the plain every-unit-needs-a-stem rule called 52 front doors.

    Two things still veto, and both are load-bearing:

    * A short number with **no letters** is a door. 302 College Avenue West
      runs `1..214`, so its first 99 units are short — absorbing those would
      collapse 214 genuine doors on the strength of the units past 99.
    * A short letter-prefixed number where **nothing else is floor-coded** is a
      building label, not a level. 12 Sunset Road (`A1..A7;B1..B5;C1..`) and
      four more Guelph groups are townhouse blocks lettered by building; only
      in the company of real 3-digit floor codes does `LL01` mean a storey.

    Deliberately still vetoing: designators that do not parse at all — `PH`,
    a bare `A;B;C`, `BHC-1`, `RR-A1`. They cannot be told apart from `REAR`,
    which is a coach house with its own front door rather than a level. All
    four Guelph groups in that shape collapse anyway on the spacing guard, so
    the blind spot costs nothing today.
    """
    parsed = []
    for unit in units:
        p = parse_unit(unit)
        if p is None:
            return False
        parsed.append(p)

    # Numbering past 99 is what a floor code looks like; without any, there is
    # no storey for a short designator to be naming.
    floor_coded = any(len(str(p[1])) >= 3 for p in parsed)

    stems = set()
    for p in parsed:
        stem = _stem(p)
        if stem is not None:
            stems.add(stem)
            continue
        prefix = p[0]
        if not prefix or not floor_coded:
            return False
        stems.add(prefix)
    return len(stems) >= 2


def compress_flats(units) -> str:
    """Render a set of unit designators as an `addr:flats` value: semicolon-
    separated runs, broken wherever the numbering actually skips.

    Guelph's collapsed buildings are mostly floor-coded, so a single span would
    be a lie — 19 Woodlawn Road East runs 101..915 and holds 142 units, and
    only 2 of its 46 all-numeric peers are contiguous. Per-floor runs say the
    same thing truthfully, and over Guelph's 167 collapsed groups they come out
    at a median of 23 characters against OSM's 255-character ceiling.

    Three do not fit, and `flats_tag` is what refuses them. Compression only
    helps where the numbering is dense and unsuffixed: 85 Mullin Drive's
    1A;1B;2A;2B... cannot form runs at all, and 176 Janefield Avenue steps by
    two, which no range syntax expresses.

    Runs only ever form within one prefix and among units with no letter
    suffix, so `101A` cannot be swallowed into `101-102`. It sorts next to its
    numeric neighbours rather than being exiled to the tail, which is where a
    naive "loose values last" pass puts it.
    """
    runs: dict[str, list[int]] = defaultdict(list)
    singles: list[tuple[str, int, str, str]] = []
    unparsed: list[str] = []
    for unit in units:
        text = str(unit).strip().upper()
        if not text:
            continue
        parsed = parse_unit(text)
        if parsed is None:
            unparsed.append(text)
            continue
        prefix, num, suffix = parsed
        if suffix:
            singles.append((prefix, num, suffix, text))
        else:
            runs[prefix].append(num)

    parts: list[tuple[str, int, str, str]] = []
    for prefix, nums in runs.items():
        ordered = sorted(set(nums))
        start = prev = ordered[0]
        for n in ordered[1:]:
            if n == prev + 1:
                prev = n
                continue
            parts.append((prefix, start, "", _run(prefix, start, prev)))
            start = prev = n
        parts.append((prefix, start, "", _run(prefix, start, prev)))
    parts.extend(singles)
    parts.sort(key=lambda p: (p[0], p[1], p[2]))
    return ";".join([p[3] for p in parts] + sorted(unparsed))


def flats_tag(units) -> tuple[str | None, str | None]:
    """The addr:flats value for a collapsed group, or (None, reason).

    A listing too long for an OSM tag is dropped rather than truncated. A
    truncated one would assert that the building stops at whatever unit the
    cut landed on, which is worse than saying nothing: the civic node is still
    correct and complete without it, just less informative. The reason travels
    with the candidate so a reviewer is told the listing was lost, rather than
    finding a building with no units and assuming it has none.
    """
    value = compress_flats(units)
    if not value:
        return None, None
    if len(value) > OSM_TAG_VALUE_MAX:
        return None, (
            f"unit listing is {len(value)} characters, over OSM's "
            f"{OSM_TAG_VALUE_MAX}-character tag limit, so it is not written"
        )
    return value, None


def _run(prefix: str, start: int, end: int) -> str:
    if start == end:
        return f"{prefix}{start}"
    return f"{prefix}{start}-{prefix}{end}"


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _nearest_neighbour_spacing(points: list[tuple[float, float]]) -> float | None:
    """Median distance from each point to its closest sibling. None when there
    is nothing to compare — a single point has no spacing."""
    if len(points) < 2:
        return None
    return _median(
        [
            min(haversine(a[0], a[1], b[0], b[1]) for j, b in enumerate(points) if j != i)
            for i, a in enumerate(points)
        ]
    )


def classify(rows) -> tuple[str, str]:
    """Decide what a whole civic group becomes. Returns (verdict, reason).

    `rows` is every active source row sharing the civic key — including the
    unit-less civic row when the source publishes one. It must be the group as
    the *source* has it, not the part of it inside the current tile: a tower
    split across a tile boundary would otherwise show one floor's worth of
    units in each half and read as sequential in both.

    Each row is a mapping with `unit`, `lat`, `lon`.
    """
    located = [r for r in rows if r.get("lat") is not None and r.get("lon") is not None]
    unit_rows = [r for r in located if (r.get("unit") or "").strip()]
    if not unit_rows:
        # Several rows, none of them a unit: an intra-source civic duplicate,
        # which is a data-quality finding and not a unit question at all.
        return NO_UNITS, "no unit rows in group"

    units = [str(r["unit"]).strip() for r in unit_rows]
    if is_coded(units):
        return COLLAPSE, "floor/building-coded suites"

    points = [(r["lat"], r["lon"]) for r in unit_rows]
    spacing = _nearest_neighbour_spacing(points)
    if spacing is None:
        # A lone unit has no siblings to be spaced from, so measure it against
        # the civic point instead. With neither, there is nothing to judge on
        # and the group goes to a human rather than defaulting to a new node.
        others = [
            (r["lat"], r["lon"])
            for r in located
            if not (r.get("unit") or "").strip()
        ]
        if not others:
            return REVIEW, "single unit, nothing to measure against"
        spacing = min(haversine(points[0][0], points[0][1], o[0], o[1]) for o in others)

    if spacing < NO_LOCATION_M:
        return COLLAPSE, f"units share a location ({spacing:.1f} m apart)"
    if spacing < DOOR_SPACING_M:
        return REVIEW, f"sequential but {spacing:.1f} m apart, under a door's width"
    return NODES, f"sequential, {spacing:.1f} m apart"


# --- the decision both the emitter and the audit page make -----------------


def unit_sort_key(unit: str):
    """Order unit designators the way a person reads them, so a door group
    lists `1;2;3` rather than the `1;10;100` a string sort gives. Unparseable
    designators sort last, where they do not interrupt a run.
    """
    parsed = parse_unit(unit)
    if parsed is None:
        return (1, "", 0, unit)
    prefix, num, suffix = parsed
    return (0, prefix, num, suffix)


def listed_units(designators) -> list[str]:
    """The distinct unit designators of a group, stripped and in reading
    order. This is the one normalized form: `flats_tag` renders it, the audit
    page shows it, and `unit_hash` covers it, so the emitter and the page must
    build it the same way or a verdict recorded on one will not be recognised
    by the other.
    """
    return sorted(
        {str(u).strip() for u in designators if (u or "").strip()},
        key=unit_sort_key,
    )


def norm_designator(unit: str) -> str:
    """One designator in the form two sides of a compare can share: upper,
    stripped, and the numeric part without leading zeros, so the City's `LL01`
    and a mapper's `LL1` are the same door. Unparseable values are compared
    as typed."""
    u = str(unit or "").strip().upper()
    parsed = parse_unit(u)
    if parsed is None:
        return u
    prefix, num, suffix = parsed
    return f"{prefix}{num}{suffix}"


def expand_listing(value: str) -> set[str]:
    """The designators a listing names, normalised with `norm_designator`.

    Per part: a numeric range whose two ends share a prefix and suffix expands
    (`101-116`, `LL1-LL4`); anything else is one value (`1A`, `PH`). A range
    wider than `MAX_RANGE_WIDTH` is left as a single literal rather than
    expanded, so a typo cannot allocate.
    """
    out: set[str] = set()
    for part in str(value or "").split(";"):
        part = part.strip()
        if not part:
            continue
        lo, sep, hi = part.partition("-")
        a, b = parse_unit(lo.strip().upper()), parse_unit(hi.strip().upper()) if sep else None
        if (
            sep and a and b and a[0] == b[0] and a[2] == b[2]
            and 0 <= b[1] - a[1] <= MAX_RANGE_WIDTH
        ):
            out.update(f"{a[0]}{n}{a[2]}" for n in range(a[1], b[1] + 1))
        else:
            out.add(norm_designator(part))
    return out


def unit_hash(listed: list[str]) -> str:
    """Fingerprint of the unit set a verdict was made against.

    Designators only -- never coordinates. Geocoding jitter between source
    snapshots would otherwise invalidate every verdict on every refresh. Its
    job is narrow: a building that gains a floor must re-surface on the audit
    page rather than silently inherit a decision made about a different
    building. Upper-cased so a source that re-cases `ll01` to `LL01` is not
    read as a new building either.
    """
    return hashlib.sha1(";".join(u.upper() for u in listed).encode("utf-8")).hexdigest()[:16]


def resolve(
    verdict: str, reason: str, listed: list[str], override: str | None = None
) -> tuple[str, str, str | None]:
    """What a civic group becomes, given the rule's verdict and any operator
    override. Returns (shape, reason, flats).

    The shape vocabulary is the audit page's, one wider than the rule's:

        nodes       one node per door, each carrying addr:unit
        collapse    one node for the building, carrying addr:flats
        civic-only  one node for the building and no listing
        review      collapsed, but the rule was not confident
        skip        nothing at all

    `candidates._emit_group` and `unit_shapes._outcome` both go through here,
    so they cannot drift: if the page says a building collapses, that is what
    ingest will do with it. The order of operations is fixed -- decide first,
    render the listing second -- because an over-long listing downgrades a
    confident collapse to something a human has to see.

    An override changes the branch, never the facts. It cannot make a
    421-character listing fit inside a 255-character tag, so `collapse` on
    such a group falls through to `civic-only` and the reason says why,
    rather than the emitter writing a truncated tag that asserts the building
    stops wherever the cut landed.
    """
    if override is None:
        if verdict in (NODES, NO_UNITS):
            return "nodes", reason, None
        flats, too_long = flats_tag(listed)
        if too_long:
            # The node is still right; only the listing is lost. That is its
            # own outcome, not a failed collapse -- the building arrives
            # correct and less informative, and the reviewer is told which.
            return "civic-only", too_long, None
        return ("review" if verdict == REVIEW else "collapse"), reason, flats

    if override not in OVERRIDES:
        raise ValueError(f"unknown unit-shape override {override!r}")
    # Keep the rule's opinion in the reason, or the audit trail is gone: a
    # candidate that says only "nodes" cannot tell a reviewer that the rule
    # wanted to collapse it and a person disagreed.
    said = f"override: rule said {verdict} ({reason})"
    if override == "collapse":
        flats, too_long = flats_tag(listed)
        if too_long:
            return "civic-only", f"override to collapse cannot fit: {too_long}", None
        return "collapse", said, flats
    return override, said, None
