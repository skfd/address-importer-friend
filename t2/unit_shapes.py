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
surface: what would be created, for every group, under the current rule and
the operator's verdicts on it (`unit_verdicts`).

The outcome vocabulary is five, not two, because collapse-or-nodes does not
cover what actually happens:

    nodes       one node per door, each carrying addr:unit
    collapse    one node for the building, carrying addr:flats
    civic-only  one node for the building and NO listing -- the units exist
                but their addr:flats value is over OSM's 255-character limit
                and is dropped rather than truncated, or the operator chose it
    review      emitted collapsed, but the rule was not confident
    skip        nothing -- an operator decided both shapes assert something
                false (a mall whose "units" are storefronts)

`review` is deliberately not a shape. It is `collapse` plus a reason to look,
which is why its rows say what they would upload rather than withholding it.

Mirrors `candidates._emit_group` step for step. If the two ever disagree this
page is lying, so the decision is one shared function (`units.resolve`) rather
than two copies of it.

Two caches, because two things change at different rates. The classifier's
answer for a group depends only on the source snapshot, and a full scan of the
city is not free, so that is computed once per snapshot. Verdicts change on
every click, and overlaying them is cheap, so that happens per request keyed
on `unit_verdicts.version()`.
"""
import hashlib

from . import source_db, unit_verdicts, units

# Classifier base per snapshot: the answer cannot change without the snapshot
# changing. Holds no verdict state.
_BASE_CACHE: dict[int, dict] = {}
# Base + verdict overlay, keyed on (snapshot, verdict version).
_CACHE: dict[tuple, dict] = {}

# What each outcome creates, in the reviewer's terms rather than the rule's.
SHAPES = (
    ("nodes", "one node per door"),
    ("collapse", "one node, units listed"),
    ("civic-only", "one node, listing dropped"),
    ("review", "collapsed, but unsure"),
    ("skip", "nothing created"),
)

# The chips on the page, in the order they appear. "rule" is not a verdict but
# the absence of one: clear the override and let the classifier decide.
CHOICES = (
    ("rule", "let the rule decide"),
    ("nodes", "one node per door"),
    ("collapse", "one node, units listed"),
    ("civic-only", "one node, no listing"),
    ("skip", "create nothing"),
)

# Kept under the old name for callers that import it from here.
_unit_sort_key = units.unit_sort_key


def _outcome(group: list[dict], override: str | None = None) -> dict:
    """What `_emit_group` would do with this civic group, and why.

    `override` is an operator verdict already known to apply to this group
    (its unit set matches); None lets the rule decide.
    """
    verdict, reason = units.classify(
        [
            {"unit": r.get("unit_name"), "lat": r.get("latitude"), "lon": r.get("longitude")}
            for r in group
        ]
    )
    listed = units.listed_units(r.get("unit_name") for r in group)
    shape, reason, flats = units.resolve(verdict, reason, listed, override)
    return {
        "shape": shape,
        "verdict": verdict,
        "reason": reason,
        "flats": flats,
        "nodes_created": _nodes_created(shape, len(group)),
        "units": listed,
    }


def _nodes_created(shape: str, row_count: int) -> int:
    if shape == "nodes":
        return row_count
    if shape == "skip":
        return 0
    return 1


def _base(snapshot_id: int) -> dict:
    """Every unit-bearing civic group with the rule's own verdict on it.

    Groups with no unit rows are counted but not listed. Several rows sharing a
    civic address with no unit between them is an intra-source duplicate -- a
    data-quality finding that `classify` reports as NO_UNITS because it is not
    a unit question at all, and putting 40,225 of them in this table would bury
    the 409 that are.
    """
    cached = _BASE_CACHE.get(snapshot_id)
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
        verdict, reason = units.classify(
            [
                {"unit": r.get("unit_name"), "lat": r.get("latitude"), "lon": r.get("longitude")}
                for r in group
            ]
        )
        listed = units.listed_units(r.get("unit_name") for r in group)
        rep = min(group, key=lambda r: str(r.get("address_point_id")))
        key_text = source_db.civic_key_text(key)
        rows.append(
            {
                "key": key_text,
                # A DOM-safe handle for the row: the key itself has spaces and
                # pipes, and two groups can share a unit set, so neither the
                # key nor the unit hash will do as an element id.
                "dom": hashlib.sha1(key_text.encode("utf-8")).hexdigest()[:12],
                "number": key[0],
                "street": key[1],
                "municipality": key[2],
                "unit_count": len(listed),
                "row_count": len(group),
                "lat": rep.get("latitude"),
                "lon": rep.get("longitude"),
                "verdict": verdict,
                "rule_reason": reason,
                "units": listed,
                "unit_hash": units.unit_hash(listed),
            }
        )

    # Biggest first: a rule that is wrong about a 140-unit building is wrong in
    # a way worth more of a reviewer's attention than one about a duplex.
    rows.sort(key=lambda r: (-r["unit_count"], str(r["street"]), str(r["number"])))
    data = {"snapshot_id": snapshot_id, "rows": rows, "no_unit_groups": no_units}
    _BASE_CACHE[snapshot_id] = data
    return data


def _overlay(base_row: dict, saved: dict | None, frozen: set[str], ingested: dict) -> dict:
    """One page row: the rule's answer with the operator's verdict applied.

    A saved verdict whose unit set no longer matches is *stale*: shown, so the
    operator can see what was decided and re-decide, but not applied, because
    the emitter will not apply it either.
    """
    override = unit_verdicts.effective(saved, base_row["unit_hash"])
    shape, reason, flats = units.resolve(
        base_row["verdict"], base_row["rule_reason"], base_row["units"], override
    )
    return {
        **base_row,
        "shape": shape,
        "reason": reason,
        "flats": flats,
        "nodes_created": _nodes_created(shape, base_row["row_count"]),
        "saved": saved,
        "override": override,
        "stale": saved is not None and override is None,
        "frozen": base_row["key"] in frozen or bool(saved and saved.get("frozen_at")),
        "ingested_runs": ingested.get(base_row["key"], []),
    }


def collect(snapshot_id: int | None = None) -> dict:
    """Every unit-bearing civic group in the city, with the shape it will take
    under the rule and the operator's verdicts together."""
    if snapshot_id is None:
        snapshot_id = source_db.latest_snapshot_id()
    stamp = unit_verdicts.version()
    cached = _CACHE.get((snapshot_id, stamp))
    if cached is not None:
        return cached

    base = _base(snapshot_id)
    saved = unit_verdicts.load_all()
    frozen = unit_verdicts.frozen_keys()
    ingested = unit_verdicts.ingested_runs()
    rows = [_overlay(r, saved.get(r["key"]), frozen, ingested) for r in base["rows"]]

    counts = {shape: 0 for shape, _ in SHAPES}
    nodes_created = 0
    for r in rows:
        counts[r["shape"]] += 1
        nodes_created += r["nodes_created"]

    data = {
        "snapshot_id": snapshot_id,
        "rows": rows,
        "by_key": {r["key"]: r for r in rows},
        "counts": counts,
        "group_total": len(rows),
        "unit_total": sum(r["unit_count"] for r in rows),
        "nodes_created": nodes_created,
        "no_unit_groups": base["no_unit_groups"],
        "door_nodes": sum(r["nodes_created"] for r in rows if r["shape"] == "nodes"),
        "overridden": sum(1 for r in rows if r["override"]),
        "stale": sum(1 for r in rows if r["stale"]),
        "frozen": sum(1 for r in rows if r["frozen"]),
    }
    # One overlay per verdict version is enough to keep; older ones are dead.
    _CACHE.clear()
    _CACHE[(snapshot_id, stamp)] = data
    return data


def decide(civic_key: str, choice: str, note: str | None = None) -> dict:
    """Record the operator's choice for one group and return its fresh row.

    The unit hash is taken from the group as the page sees it now, never from
    the form. Raises `unit_verdicts.Frozen` if the group's shape is already in
    OSM, and KeyError if the key names no unit-bearing group.
    """
    row = collect()["by_key"][civic_key]
    if choice == "rule":
        unit_verdicts.clear(civic_key)
    else:
        unit_verdicts.save(civic_key, choice, row["unit_hash"], note)
    return collect()["by_key"][civic_key]
