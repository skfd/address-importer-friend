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

One cache, at the expensive layer only. The classifier's answer for a group
depends on nothing but the source snapshot, and a full scan of the city is not
free, so that is computed once per snapshot. Everything layered on it --
verdicts, which change on every click; freeze and "already ingested", which
change on every upload and ingest -- is cheap and is recomputed per request,
because a cached overlay would keep showing live chips on a group that had
just been uploaded.
"""
import hashlib
import json
import re

from . import source_db, unit_verdicts, units

# Classifier base per snapshot: the answer cannot change without the snapshot
# changing. Holds no verdict or run state.
_BASE_CACHE: dict[int, dict] = {}

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
        # Where the City puts each unit, for the review map: the rule reads
        # the numbering, but whether a sequential group is a row of front
        # doors or a plaza's storefronts is a question the imagery answers.
        points = [
            (r.get("unit_name"), r["latitude"], r["longitude"])
            for r in group
            if (r.get("unit_name") or "").strip()
            and r.get("latitude") is not None and r.get("longitude") is not None
        ]
        points.sort(key=lambda p: units.unit_sort_key(str(p[0])))
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
                "points": points,
                # The rule's own measure, not parsed back out of the reason:
                # the widest-spaced "doors" are the likeliest plazas.
                "spacing_m": units._nearest_neighbour_spacing([(p[1], p[2]) for p in points]),
            }
        )

    # Biggest first: a rule that is wrong about a 140-unit building is wrong in
    # a way worth more of a reviewer's attention than one about a duplex.
    rows.sort(key=lambda r: (-r["unit_count"], str(r["street"]), str(r["number"])))
    data = {"snapshot_id": snapshot_id, "rows": rows, "no_unit_groups": no_units}
    _BASE_CACHE[snapshot_id] = data
    return data


# --- what OSM already holds at each address ---------------------------------
#
# The second freeze condition. ARandomThumbtack put ~5,500 hyphenated unit
# nodes into Guelph in 2025, so "somebody else already mapped these doors"
# freezes a group as surely as our own upload does: overriding one of those to
# collapse would put a civic node carrying addr:flats beside thirty existing
# unit nodes. The mirror holds too -- a node already carrying addr:flats is a
# collapsed building, and exploding it would put doors beside it.
#
# Both encodings of a door count. Before mechanical edit #2 a door sits in OSM
# as addr:housenumber=714-30; after it, as 714 + addr:unit=30. Conflation only
# recognises the second form (test_a_door_does_not_recognise_its_own_double_
# encoded_self), which is why the handoff said this column would lie until the
# split ran. It does not lie about *whether doors exist*, which is the only
# question freeze asks, so it is built to read both and to say how many of
# each it saw.
#
# And both encodings of a listing count. Guelph's towers were mapped as one
# building way carrying every unit under addr:unit -- `101-116;201-215;...` --
# rather than addr:flats. Measured 2026-09-15 against a fresh extract: 176 of
# the 409 groups have such a building, 51 of them groups the rule reads as
# doors. Read literally that is one "unit object"; read as the mapper meant it,
# it is the collapsed shape already in OSM, and that is how it is counted.

_OSM_CACHE: dict[tuple, dict] = {}
_HYPHEN_UNIT = re.compile(r"^([0-9]+[A-Z]?)-([0-9A-Z]+)$")
# The listing test is shared with conflation: `units.UNIT_LISTING`.
_UNIT_LISTING = units.UNIT_LISTING


def _osm_summaries(elements: list[dict]) -> dict[tuple[str, str], dict]:
    """(street_norm, housenumber) -> what address objects OSM has there.

    Follows conflate.build_osm_index's notion of an address object: anything
    with addr:housenumber that is not a POI node and not an endpoint of an
    addr:interpolation way. Ways and relations count through their centre.
    """
    from .conflate import _is_poi_node, normalize_street

    interp: set[int] = set()
    for el in elements:
        if el.get("type") == "way" and "addr:interpolation" in (el.get("tags") or {}):
            interp.update(el.get("nodes") or ())

    out: dict[tuple[str, str], dict] = {}

    def slot(street: str, number: str) -> dict:
        return out.setdefault(
            (street, number),
            {"civic": 0, "units": set(), "hyphenated": set(), "listings": [], "ids": [],
             "listing_ids": []},
        )

    for el in elements:
        tags = el.get("tags") or {}
        hn = str(tags.get("addr:housenumber") or "").strip().upper()
        if not hn:
            continue
        if el.get("type") == "node" and (el.get("id") in interp or _is_poi_node(el)):
            continue
        street = normalize_street(tags.get("addr:street") or "")
        if not street:
            continue
        ref = (el.get("type"), el.get("id"))
        unit = str(tags.get("addr:unit") or "").strip().upper()
        m = _HYPHEN_UNIT.match(hn)
        if m and (not unit or unit == m.group(2)):
            # 714-30: the double-encoded door. The unit is the tail whether or
            # not addr:unit repeats it. Reading the uncorroborated ones (no
            # addr:unit) is a choice: a genuine range like 380-400 would land
            # as housenumber 380 with a phantom unit. Measured 2026-09-15:
            # the extract has 17 such objects, the same 17 mechanical edit #2
            # sends to hand work, and the only group any of them touches is
            # 37 Bond Court -- twelve ways 37-1..37-12 that are exactly the
            # townhouse row the source has there. Requiring corroboration
            # would unfreeze it and let a collapse put a flats node beside
            # twelve door ways, so they stay in.
            s = slot(street, m.group(1))
            s["hyphenated"].add(m.group(2))
            s["ids"].append(ref)
            continue
        s = slot(street, hn)
        s["ids"].append(ref)
        if tags.get("addr:flats"):
            s["listings"].append(str(tags["addr:flats"]).strip())
            s["listing_ids"].append((*ref, str(tags["addr:flats"]).strip()))
        if unit and _UNIT_LISTING.search(unit):
            s["listings"].append(unit)
            s["listing_ids"].append((*ref, unit))
        elif unit:
            s["units"].add(unit)
        else:
            s["civic"] += 1
    return out


def _osm_index() -> dict | None:
    """The extract's address objects, summarised per (street, number), or None
    when no extract has been fetched. Cached on the file's identity."""
    from . import config as _config

    path = _config.load().osm_extract_json
    if not path.exists():
        return None
    st = path.stat()
    stamp = (str(path), st.st_mtime_ns, st.st_size)
    cached = _OSM_CACHE.get(stamp)
    if cached is None:
        cached = _osm_summaries(json.loads(path.read_text(encoding="utf-8")))
        _OSM_CACHE.clear()
        _OSM_CACHE[stamp] = cached
    return cached


def _osm_at(index: dict | None, base_row: dict) -> dict | None:
    """What OSM holds for one civic group, in the row's terms, or None when
    there is no extract to ask.

    `shape` is the shape OSM already asserts: "doors" (unit objects, in either
    encoding), "listing" (a building listing its units, under addr:flats or a
    multi-valued addr:unit), "civic" (a bare address object and nothing more),
    or "" for nothing at all. Only the first two freeze. A group can have both
    doors and a listing -- terrace rows mapped as a few building ways each
    listing its units, plus stray hyphenated nodes -- and reads as "doors" with
    the listings counted alongside.

    `listing_ids` is every object carrying a listing, with the listing, unlike
    `ids` which is a sample for links: the review map draws all of them, and
    941 Gordon Street has seventeen.
    """
    if index is None:
        return None
    from .conflate import apply_street_override, expand_street_name, normalize_street

    # Keyed on (street, number) only. The civic key also carries the
    # municipality because an amalgamated city reuses street names across its
    # former municipalities, but OSM has no such field to join on. Right for
    # Guelph, a single municipality; the next per-door city that is
    # amalgamated will need the OSM side keyed by proximity instead.
    street = normalize_street(expand_street_name(apply_street_override(base_row["street"])))
    number = str(base_row["number"] or "").strip().upper()
    s = index.get((street, number))
    if s is None:
        return {"shape": "", "civic": 0, "units": 0, "hyphenated": 0, "doors": 0, "listings": [],
                "ids": [], "listing_ids": []}
    doors = len(s["units"] | s["hyphenated"])
    if doors:
        shape = "doors"
    elif s["listings"]:
        shape = "listing"
    elif s["civic"]:
        shape = "civic"
    else:
        shape = ""
    return {
        "shape": shape,
        "civic": s["civic"],
        "units": len(s["units"]),
        "hyphenated": len(s["hyphenated"]),
        "doors": doors,
        "listings": s["listings"],
        "ids": s["ids"][:3],
        "listing_ids": list(s.get("listing_ids", ())),
    }


def _overlay(
    base_row: dict, saved: dict | None, frozen: set[str], ingested: dict, osm_index: dict | None
) -> dict:
    """One page row: the rule's answer with the operator's verdict applied.

    A saved verdict whose unit set no longer matches is *stale*: shown, so the
    operator can see what was decided and re-decide, but not applied, because
    the emitter will not apply it either.

    `frozen` means this import uploaded the group's shape: both flips would
    then be mutations, and the chips go. `in_osm` is the weaker fact that
    somebody already mapped doors or a listing here. Until 2026-10-01 that
    froze too; it no longer does, because a verdict there only adds what OSM
    lacks -- the doors a listing does not stand in for, or the doors missing
    from a half-mapped row -- beside what is there, and creating beside is
    what this import does. The row says what is there so the operator rules
    knowing it.
    """
    override = unit_verdicts.effective(saved, base_row["unit_hash"])
    shape, reason, flats = units.resolve(
        base_row["verdict"], base_row["rule_reason"], base_row["units"], override
    )
    osm = _osm_at(osm_index, base_row)
    frozen_why = None
    if base_row["key"] in frozen or bool(saved and saved.get("frozen_at")):
        frozen_why = "uploaded by this import"
    in_osm = None
    if osm and osm["shape"] == "doors":
        in_osm = f"OSM already has {osm['doors']} of {base_row['unit_count']} units as door objects"
        if osm["listings"]:
            in_osm += ", and a building listing them"
    elif osm and osm["shape"] == "listing":
        in_osm = "OSM lists the units on a building here, with no door objects"
    return {
        **base_row,
        "shape": shape,
        "reason": reason,
        "flats": flats,
        "nodes_created": _nodes_created(shape, base_row["row_count"]),
        "saved": saved,
        "override": override,
        "stale": saved is not None and override is None,
        "frozen": frozen_why is not None,
        "frozen_why": frozen_why,
        "in_osm": in_osm,
        "auto": bool(override and saved and (saved.get("note") or "").startswith("auto:")),
        "ingested_runs": ingested.get(base_row["key"], []),
        "osm": osm,
    }


def collect(snapshot_id: int | None = None) -> dict:
    """Every unit-bearing civic group in the city, with the shape it will take
    under the rule and the operator's verdicts together."""
    if snapshot_id is None:
        snapshot_id = source_db.latest_snapshot_id()
    # No cache on the overlay, on purpose. `frozen` and `ingested_runs` come
    # from the candidates table and move on every upload and ingest, which no
    # verdict stamp would notice; a stale overlay would show live chips on a
    # group that had just been uploaded and let the click revert in silence.
    # The overlay is three small queries and a few hundred `resolve` calls,
    # and the expensive part -- the city scan -- is cached in `_base`.
    base = _base(snapshot_id)
    saved = unit_verdicts.load_all()
    frozen = unit_verdicts.frozen_keys()
    ingested = unit_verdicts.ingested_runs()
    osm_index = _osm_index()
    rows = [_overlay(r, saved.get(r["key"]), frozen, ingested, osm_index) for r in base["rows"]]

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
        "in_osm": sum(1 for r in rows if r["in_osm"] and not r["frozen"]),
        "auto": sum(1 for r in rows if r["auto"]),
        "osm_loaded": osm_index is not None,
        "osm_shapes": {
            k: sum(1 for r in rows if r["osm"] and r["osm"]["shape"] == k)
            for k in ("doors", "listing", "civic", "")
        },
        "osm_hyphenated": sum(1 for r in rows if r["osm"] and r["osm"]["hyphenated"]),
    }
    return data


# The page's narrowing, beyond the shape tiles. "listing" is any group where
# some OSM object lists units -- not only osm.shape == "listing", which a
# group with a listing *and* a stray unit node reads as "doors". Those are
# frozen either way; the filter is for seeing them, not deciding them.
OSM_FILTERS = (
    ("open", "nothing in OSM yet"),
    ("decided", "decided, by you or the auto-judge"),
    ("listing", "an OSM building lists its units"),
)
SORTS = (
    ("", "biggest first"),
    ("spacing", "widest door spacing first"),
)


def select(rows: list[dict], shape: str = "", osm: str = "", sort: str = "") -> list[dict]:
    """The rows the page shows for a shape tile, OSM filter and sort.

    Sorting by spacing puts the widest-spaced groups first because the rule
    only has a floor on door spacing, not a ceiling: 91 m between "doors" is a
    plaza's storefronts as often as it is a townhouse row. Groups with no
    spacing (a lone unit, or collapsed without points) go last.
    """
    out = [r for r in rows if not shape or r["shape"] == shape]
    if osm == "open":
        # Groups OSM has nothing for are the ones only this import will shape;
        # the rest already have doors or a listing and are most of the city.
        out = [r for r in out if not r["frozen"] and not r["in_osm"]]
    elif osm == "decided":
        out = [r for r in out if r["override"] or r["stale"]]
    elif osm == "listing":
        out = [r for r in out if r.get("osm") and r["osm"]["listings"]]
    if sort == "spacing":
        out = sorted(out, key=lambda r: (r.get("spacing_m") is None, -(r.get("spacing_m") or 0)))
    return out


def shape_counts(rows: list[dict], osm: str = "") -> dict[str, int] | None:
    """Per-shape counts under the OSM filter alone, for the tiles; None when
    no OSM filter is on and the page-wide counts already say it."""
    if not osm:
        return None
    counts = {shape: 0 for shape, _ in SHAPES}
    for r in select(rows, osm=osm):
        counts[r["shape"]] += 1
    return counts


def decide(civic_key: str, choice: str, note: str | None = None) -> dict:
    """Record the operator's choice for one group and return its fresh row.

    The unit hash is taken from the group as the page sees it now, never from
    the form. Raises `unit_verdicts.Frozen` if this import has uploaded the
    group, and KeyError if the key names no unit-bearing group. A group
    somebody else already shaped in OSM takes a verdict (see `_overlay`).
    """
    row = collect()["by_key"][civic_key]
    if row["frozen"]:
        raise unit_verdicts.Frozen(civic_key)
    if choice == "rule":
        unit_verdicts.clear(civic_key)
    else:
        unit_verdicts.save(civic_key, choice, row["unit_hash"], note)
    return collect()["by_key"][civic_key]
