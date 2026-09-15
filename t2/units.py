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

    Every unit must carry a stem and at least two distinct stems must appear.
    One stem is not evidence: `101..124` alone is a single floor, and reads
    just as well as 24 doors numbered from 101.
    """
    stems = set()
    for unit in units:
        parsed = parse_unit(unit)
        if parsed is None:
            return False
        stem = _stem(parsed)
        if stem is None:
            return False
        stems.add(stem)
    return len(stems) >= 2


def compress_flats(units) -> str:
    """Render a set of unit designators as an `addr:flats` value: semicolon-
    separated runs, broken wherever the numbering actually skips.

    Guelph's collapsed buildings are floor-coded, so a single span would be a
    lie — 19 Woodlawn Road East runs 101..915 and holds 142 units, and only 2
    of its 46 all-numeric peers are contiguous. Per-floor runs say the same
    thing truthfully and stay far inside OSM's 255-character value ceiling
    (measured over all of Guelph's collapsed groups: median 31, max 135).

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
