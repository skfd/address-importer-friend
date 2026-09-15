"""The collapse-vs-nodes decision for every civic group in the city, at once.

`t2/units.classify` decides whether a multi-unit address becomes one node
carrying `addr:flats` or one node per front door, and until this page existed
the decision was invisible: it was made at emission time, recorded in
`candidates.unit_shape`, and surfaced only as a single `unit_shape_ambiguous`
row on whichever candidate happened to be flagged. A reviewer could see one
building at a time and never the shape of the rule.

Reviewing it as a category needs a different grain from the review queue. The
queue is per-run and per-candidate; this decision is per-civic-group and
city-wide, because `classify` has to read the whole group as the *source* has
it — a tower cut by a tile boundary shows one floor's worth of units on each
side and reads as sequential doors in both. Door groups also scatter across
runs (each door lands in the tile that contains it) while a collapsed group is
emitted once, so no per-run view can hold a group whole.

So this reads the source directly and owns no run state. It is an audit
surface: what would be created, for every group, under the current rule.

The outcome vocabulary is four, not two, because collapse-or-nodes does not
cover what actually happens:

    nodes       one node per door, each carrying addr:unit
    collapse    one node for the building, carrying addr:flats
    civic-only  one node for the building and NO listing -- the units exist
                but their addr:flats value is over OSM's 255-character limit
                and is dropped rather than truncated
    review      emitted collapsed, but the rule was not confident

`review` is deliberately not a shape. It is `collapse` plus a reason to look,
which is why its rows say what they would upload rather than withholding it.

Mirrors `candidates._emit_group` step for step. If the two ever disagree this
page is lying, so the shared parts are called rather than reimplemented.
"""
from . import source_db, units

# Keyed by snapshot: one full scan of the city is not free, and the answer
# cannot change without the snapshot changing.
_CACHE: dict[int, dict] = {}

# What each outcome creates, in the reviewer's terms rather than the rule's.
SHAPES = (
    ("nodes", "one node per door"),
    ("collapse", "one node, units listed"),
    ("civic-only", "one node, listing dropped"),
    ("review", "collapsed, but unsure"),
)


def _unit_sort_key(unit: str):
    """Order unit designators the way a person reads them, so a sample of a
    door group opens `1;2;3` rather than the `1;10;100` a string sort gives.
    Unparseable designators sort last, where they do not interrupt a run.
    """
    parsed = units.parse_unit(unit)
    if parsed is None:
        return (1, "", 0, unit)
    prefix, num, suffix = parsed
    return (0, prefix, num, suffix)


def _outcome(group: list[dict]) -> dict:
    """What `_emit_group` would do with this civic group, and why.

    The order of operations matters and mirrors the emitter: classify first,
    then render the listing, because an over-long listing downgrades a
    confident COLLAPSE to something a human has to see.
    """
    verdict, reason = units.classify(
        [
            {"unit": r.get("unit_name"), "lat": r.get("latitude"), "lon": r.get("longitude")}
            for r in group
        ]
    )
    listed = sorted(
        {str(r["unit_name"]).strip() for r in group if (r.get("unit_name") or "").strip()},
        key=_unit_sort_key,
    )
    if verdict in (units.NODES, units.NO_UNITS):
        return {
            "shape": "nodes",
            "verdict": verdict,
            "reason": reason,
            "flats": None,
            "nodes_created": len(group),
            "units": listed,
        }

    flats, too_long = units.flats_tag(listed)
    shape = "review" if verdict == units.REVIEW else "collapse"
    if too_long:
        # The node is still right; only the listing is lost. That is its own
        # outcome, not a failed collapse -- the building arrives correct and
        # less informative, and the reviewer is told which.
        shape, reason = "civic-only", too_long
    return {
        "shape": shape,
        "verdict": verdict,
        "reason": reason,
        "flats": flats,
        "nodes_created": 1,
        "units": listed,
    }


def collect(snapshot_id: int | None = None) -> dict:
    """Every unit-bearing civic group in the city, with the shape it would take.

    Groups with no unit rows are counted but not listed. Several rows sharing a
    civic address with no unit between them is an intra-source duplicate -- a
    data-quality finding that `classify` reports as NO_UNITS because it is not
    a unit question at all, and putting 40,225 of them in this table would bury
    the 409 that are.
    """
    if snapshot_id is None:
        snapshot_id = source_db.latest_snapshot_id()
    cached = _CACHE.get(snapshot_id)
    if cached is not None:
        return cached

    grouped: dict[tuple, list[dict]] = {}
    conn = source_db.connect_readonly()
    try:
        q = source_db.build_civic_group_query(
            source_db._CONFIG.source_fields, source_db._CONFIG.status_active_values
        )
        for r in conn.execute(q, {"snap": snapshot_id}):
            row = dict(r)
            grouped.setdefault(source_db.civic_key(row), []).append(row)
    finally:
        conn.close()

    rows: list[dict] = []
    no_units = 0
    for key, group in grouped.items():
        if not any((r.get("unit_name") or "").strip() for r in group):
            no_units += 1
            continue
        out = _outcome(group)
        rep = min(group, key=lambda r: str(r.get("address_point_id")))
        rows.append(
            {
                "number": key[0],
                "street": key[1],
                "municipality": key[2],
                "unit_count": len(out["units"]),
                "row_count": len(group),
                "lat": rep.get("latitude"),
                "lon": rep.get("longitude"),
                **out,
            }
        )

    # Biggest first: a rule that is wrong about a 140-unit building is wrong in
    # a way worth more of a reviewer's attention than one about a duplex.
    rows.sort(key=lambda r: (-r["unit_count"], str(r["street"]), str(r["number"])))

    counts = {shape: 0 for shape, _ in SHAPES}
    nodes_created = 0
    for r in rows:
        counts[r["shape"]] += 1
        nodes_created += r["nodes_created"]

    data = {
        "snapshot_id": snapshot_id,
        "rows": rows,
        "counts": counts,
        "group_total": len(rows),
        "unit_total": sum(r["unit_count"] for r in rows),
        "nodes_created": nodes_created,
        "no_unit_groups": no_units,
        "door_nodes": sum(r["nodes_created"] for r in rows if r["shape"] == "nodes"),
    }
    _CACHE[snapshot_id] = data
    return data
