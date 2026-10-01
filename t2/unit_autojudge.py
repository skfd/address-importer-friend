"""Judge a unit group by the buildings its units sit in.

`units.classify` reads the numbering, and numbering cannot tell a stacked
apartment from a townhouse complex numbered by block: 15 Carere Crescent's
`9A;9B` reads as building-coded suites and collapses, though it is 66
townhouses across 34 buildings. The OSM building outlines can. skfd's ruling,
2026-10-01: apartment buildings collapse; townhouse-looking complexes get door
nodes, even where a building already lists its units.

The judge does not change the rule. It writes verdicts, each with a note
starting `auto:` that carries its measurement, so every one shows on
/units/shapes as `auto` and is reversed by a click like any other. It never
overwrites a verdict a person made, and it only speaks to groups the rule
collapses or doubts -- a rule-`nodes` group is left alone.

Two tests and nothing else:

* **Townhouse complex -> nodes.** The units land in at least
  `MIN_BUILDINGS` buildings, a median of at most `MAX_UNITS_PER_BUILDING` to
  a building, and the source gives them distinct positions. This overrides
  coded numbering; it is the footprint guard config.toml has asked for since
  2026-09-17, applied as verdicts.
* **Apartment -> collapse**, for groups the rule only doubted: most placed
  units in one building, with less than `APARTMENT_M2_PER_UNIT` of its
  footprint each.
  Stacked floors shrink the footprint a unit gets; a row of townhouses gives
  each its whole column of ground.

Everything else stays with the rule and a human. In particular a converted
house with a handful of flats (190 Norfolk Street) has a large footprint per
unit and one building, and passes neither test -- the module's own rule is
that ambiguity resolves toward collapse, never toward nodes.
"""
from collections import Counter
from statistics import median

from . import units

MIN_BUILDINGS = 3
MAX_UNITS_PER_BUILDING = 2
ONE_BUILDING_SHARE = 0.8
APARTMENT_M2_PER_UNIT = 25.0
# Below this a small footprint per unit is a garden suite over a garage or a
# split house, not floors (155 Bristol Street: two units in a 57 m² garage).
MIN_APARTMENT_UNITS = 8
# Of the unit points, the share that must land in some building before the
# judge says anything: a complex OSM has barely drawn is not evidence. The
# apartment test asks less, because a tower's unit points are a grid the City
# lays over the lot and a third of them can fall past the walls (63 Arthur
# Street South: 92 of 132 inside); it charges the building's area to every
# unit, placed or not, which only makes the footprint per unit smaller.
PLACED_SHARE = 0.8
APARTMENT_PLACED_SHARE = 0.5

# The rule's shapes the judge may speak to. `nodes` is the rule at its most
# confident (sequential, door-width apart) and is not second-guessed here.
SCOPE = ("collapse", "review", "civic-only")

AUTO = "auto:"


def judge(rule_shape: str, points, spacing_m: float | None, at) -> tuple[str | None, str]:
    """(verdict or None, note) for one group.

    `points` is [(unit, lat, lon)]; `at(lat, lon)` returns the building a
    point sits in (`osm_buildings.Index.at`) or None. A None verdict means the
    judge has nothing to add, and the note says why.
    """
    if rule_shape not in SCOPE:
        return None, f"rule says {rule_shape}; not judged"
    if not points:
        return None, "no unit points"
    hits: dict[int, dict] = {}
    per = Counter()
    for _unit, lat, lon in points:
        b = at(lat, lon)
        if b is None:
            continue
        key = (b["type"], b["id"], round(b["area"]))
        hits[key] = b
        per[key] += 1
    placed = sum(per.values())
    n = len(points)
    if placed < APARTMENT_PLACED_SHARE * n:
        return None, f"only {placed} of {n} units fall in a mapped building"

    nb = len(per)
    med = median(per.values())
    biggest_key, biggest_n = per.most_common(1)[0]
    biggest = hits[biggest_key]
    m2_per_unit = biggest["area"] / (n if biggest_n >= ONE_BUILDING_SHARE * placed else biggest_n)
    kinds = Counter(b["building"] for b in hits.values())
    measured = (
        f"{n} units, {placed} placed in {nb} building{'s' if nb != 1 else ''}, median {med:g} per building, "
        f"largest {biggest['building']} {biggest['area']:.0f} m² holding {biggest_n} "
        f"({m2_per_unit:.0f} m² each); tags {', '.join(f'{k} {v}' for k, v in kinds.most_common(3))}"
    )

    distinct = spacing_m is not None and spacing_m >= units.NO_LOCATION_M
    if placed >= PLACED_SHARE * n and nb >= MIN_BUILDINGS and med <= MAX_UNITS_PER_BUILDING and distinct:
        return "nodes", f"{AUTO} townhouse complex — {measured}"
    if (
        rule_shape == "review"
        and n >= MIN_APARTMENT_UNITS
        and biggest_n >= ONE_BUILDING_SHARE * placed
        and m2_per_unit < APARTMENT_M2_PER_UNIT
    ):
        return "collapse", f"{AUTO} apartment building — {measured}"
    return None, f"neither test — {measured}"
