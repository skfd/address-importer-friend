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
import re
from collections import defaultdict

from .conflate import haversine

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
