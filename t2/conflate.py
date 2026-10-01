"""Stage 3: conflate candidates against cached OSM snapshot, write verdicts to DB.

GridIndex and haversine are preserved from the sibling project's
src/conflate.py — the algorithmic contract there is proven. Street
normalization moved out to `accordeur` on 2026-08-28 and is re-exported below.
"""
import json
import math
from collections import defaultdict
from datetime import datetime, timezone

from accordeur import (  # noqa: F401 -- re-exported; see the note below
    DIRS,
    DIRS_EXPAND,
    STREET_SUFFIX_EXPAND,
    STREET_SUFFIXES,
    StreetProfile,
    expand_street_name,
    normalize_street,
)

from . import audit, config as _config, db as _db, osm_export, osm_fetch, units
from .geo import haversine  # noqa: F401 -- re-exported; callers import it from here

# Street normalization lives in `accordeur`, the family's shared conflation
# core: one answer to "are these the same street" for this engine and for
# address-beholder, instead of a copy each that drifted apart (see that repo's
# README, and future-work/multi-city/01-core-library.md). The names are
# re-exported here because they were this module's for their whole life and
# nine modules plus the review UI import them from it.
#
# The per-city half is the override table. It is a fact about one city's data
# -- the handful of names where that source and OSM disagree about the actual
# name -- so it is declared in the city checkout's `[streets] overrides`, not
# hardcoded here. Toronto declares thirteen; Guelph and Hamilton declare none.
_STREET_PROFILE = StreetProfile(_config.load().street_overrides)

# Unit-aware matching is opt-in per city, because turning it on changes what
# an existing city's candidates match. Under collapse-to-civic a bare civic
# candidate deliberately MATCHes an OSM node that carries addr:unit — that is
# what stops Toronto proposing a second node at an address already mapped as a
# suite. Under per-door-or-collapse the same leniency would be wrong: the
# whole point is that the building's civic node and its units are different
# objects. So the strict rule lands only where the policy asks for it.
_UNIT_AWARE = _config.load().units_policy == "per-door-or-collapse"

#: This city's declared overrides, source spelling -> OSM-canonical spelling.
STREET_NAME_OVERRIDES: dict[str, str] = dict(_STREET_PROFILE.overrides)


def apply_street_override(name: str | None) -> str | None:
    """Return the OSM-canonical street name when `name` is a spelling variant
    this city declares in `[streets] overrides`; otherwise return `name`
    unchanged. Empty/None passes through. Lookup is case-insensitive on the
    whitespace-collapsed input.

    Applied at ingest, so the candidate's street_raw and street_norm -- and
    therefore both conflation matching and the uploaded addr:street tag --
    carry the OSM name local mappers already know. Each entry is a candidate
    for retirement once the source and OSM converge; the
    `nearby_street_mismatch` review check surfaces fresh candidates.
    """
    return _STREET_PROFILE.apply_override(name)


class GridIndex:
    def __init__(self, cell_size_deg: float = 0.002):
        self.grid: dict[tuple[int, int], list[tuple[float, float, dict]]] = defaultdict(list)
        self.cell_size = cell_size_deg

    def _key(self, lat: float, lon: float) -> tuple[int, int]:
        return (int(lat / self.cell_size), int(lon / self.cell_size))

    def add(self, item: dict, lat: float, lon: float) -> None:
        self.grid[self._key(lat, lon)].append((lat, lon, item))

    def query(self, lat: float, lon: float) -> list[tuple[float, float, dict]]:
        ck = self._key(lat, lon)
        out: list[tuple[float, float, dict]] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                out.extend(self.grid[(ck[0] + dx, ck[1] + dy)])
        return out




POI_TAG_KEYS = frozenset((
    "amenity", "shop", "office", "tourism", "leisure", "craft", "healthcare", "building",
))

# OSM lifecycle qualifiers. A POI key wrapped in one of these — as a prefix
# (`disused:amenity`, the documented form) or the rarer suffix form
# (`amenity:disused`) — still designates a POI: a closed, demolished, or
# planned shop is not a canonical address. See
# https://wiki.openstreetmap.org/wiki/Lifecycle_prefix
LIFECYCLE_QUALIFIERS = frozenset((
    "disused", "abandoned", "ruins", "demolished", "razed", "removed",
    "destroyed", "construction", "proposed", "planned", "was",
))


def _is_poi_key(key: str) -> bool:
    """True when `key` is a POI tag, bare or wrapped in a lifecycle qualifier."""
    if key in POI_TAG_KEYS:
        return True
    head, sep, tail = key.partition(":")
    if not sep:
        return False
    return (
        (head in LIFECYCLE_QUALIFIERS and tail in POI_TAG_KEYS)
        or (head in POI_TAG_KEYS and tail in LIFECYCLE_QUALIFIERS)
    )


def _is_poi_node(el: dict) -> bool:
    """A POI node is a node that carries shop/amenity/etc. tags — its address is
    a courtesy annotation, not the canonical address feature. Polygons are never
    POI-filtered: a hospital or building polygon with addr:* is a valid match.

    Lifecycle-qualified POI keys count too: `disused:amenity`, `was:shop`, and
    the rarer suffix form `amenity:disused` all mark POIs, not addresses (see
    LIFECYCLE_QUALIFIERS).

    `entrance=*` is intentionally NOT a POI key: an entrance node with
    addr:* is a canonical address (just door-level rather than parcel-level)
    and must remain a valid match target. See IMPORT_PROPOSAL.mediawiki § Conflation.
    """
    if el.get("type") != "node":
        return False
    tags = el.get("tags") or {}
    return any(_is_poi_key(k) for k in tags)


def build_osm_index(elements: list[dict]) -> tuple[GridIndex, GridIndex]:
    """Return (match_idx, poi_idx).

    match_idx holds pure-address nodes (including entrance=* nodes that carry
    addr:*) and polygons — valid conflation targets. poi_idx holds
    amenity/shop/etc. nodes, acknowledged but ignored for matching.
    Nodes that are members of an addr:interpolation way are dropped entirely:
    they're endpoints of an interpolated range, not standalone addresses.
    """
    interp_node_ids: set[int] = set()
    for el in elements:
        if el.get("type") != "way":
            continue
        if "addr:interpolation" not in (el.get("tags") or {}):
            continue
        for nid in el.get("nodes") or ():
            interp_node_ids.add(nid)

    match_idx = GridIndex()
    poi_idx = GridIndex()
    for el in elements:
        tags = el.get("tags") or {}
        if "addr:housenumber" not in tags:
            continue
        if el.get("type") == "node":
            if el.get("id") in interp_node_ids:
                continue
            lat, lon = el.get("lat"), el.get("lon")
        elif "center" in el:
            lat = el["center"].get("lat")
            lon = el["center"].get("lon")
        else:
            lat = lon = None
        if lat is None or lon is None:
            continue
        el["_norm_street"] = normalize_street(tags.get("addr:street", ""))
        el["_norm_number"] = str(tags.get("addr:housenumber", "")).upper()
        el["_norm_unit"] = str(tags.get("addr:unit", "")).strip().upper()
        if _UNIT_AWARE:
            _index_listing(el, tags)
        target = poi_idx if _is_poi_node(el) else match_idx
        target.add(el, float(lat), float(lon))
    return match_idx, poi_idx


def _index_listing(el: dict, tags: dict) -> None:
    """Mark an element that *lists* units as the building it is.

    Two encodings count, because Guelph has both: `addr:flats`, the key that
    means containment, and a multi-valued `addr:unit` (`101-116;201-215;...`),
    which is how 453 of the city's buildings were mapped before mechanical
    edit #3. Either way the element is the building, not a unit, so its
    `_norm_unit` becomes "" and the designators it names go on
    `_listed_units` for the containment match in `_match_kind`. The raw tags
    are left alone for the diff.
    """
    listed: set[str] = set()
    flats = tags.get("addr:flats")
    if flats:
        listed |= units.expand_listing(flats)
    unit = tags.get("addr:unit")
    if unit and units.UNIT_LISTING.search(str(unit).strip()):
        listed |= units.expand_listing(unit)
    if listed:
        el["_listed_units"] = listed
        el["_norm_unit"] = ""


def _match_kind(el: dict, c_num: str, c_street_norm: str, c_unit: str) -> str | None:
    """How this OSM element answers to the candidate: "exact" or None.

    "exact" is the compare `_same_address` always made. Until 2026-10-01 there
    was also "listed": a door candidate whose designator appeared in a
    building's unit listing read MATCH_LISTED and was skipped as present. That
    is withdrawn. A listing says the building *contains* unit 30; a door node
    says *this is* unit 30, at its door. Where the group's shape is doors -- a
    townhouse complex whose buildings list their units -- the listing does not
    stand in for the doors, and they are proposed beside it. Whether a group is
    doors at all is the shape decision's job (`units.resolve` and the
    operator's verdicts), not the matcher's. `_listed_units` is still indexed:
    it is what makes a listing element the building for a collapsed candidate.
    """
    if el["_norm_number"] != c_num or el["_norm_street"] != c_street_norm:
        return None
    if not _UNIT_AWARE:
        return "exact"
    if el.get("_norm_unit", "") == c_unit:
        return "exact"
    return None


def _inside_bounds(el: dict, lat: float, lon: float) -> bool:
    """Is the candidate point inside the element's bounding box? A civic point
    inside a building's footprint is not "far" from it however big the
    building is; distance to the centre measures the footprint, not the
    error. Nodes have no bounds and are always False."""
    b = el.get("bounds")
    return bool(
        b and b["minlat"] <= lat <= b["maxlat"] and b["minlon"] <= lon <= b["maxlon"]
    )


def _same_address(el: dict, c_num: str, c_street_norm: str, c_unit: str) -> bool:
    """Is this OSM element the same address as the candidate?

    Housenumber and street always have to agree. The unit only participates
    under per-door-or-collapse, and then it has to agree *exactly*, empty
    included: a candidate for the building itself matches only an element that
    is also the building, and a candidate for unit 30 matches only unit 30.

    That exactness is what makes the Guelph cleanup campaigns order-independent.
    Splitting `714-30` into `714` + `addr:unit=30` leaves a node that no longer
    answers to a bare `714`, so gap-fill still proposes the civic node it
    should, whether the split has run yet or not.
    """
    return _match_kind(el, c_num, c_street_norm, c_unit) is not None


def _classify(
    cand_row: dict,
    match_idx: GridIndex,
    poi_idx: GridIndex,
    match_radius_m: float,
    match_near_m: float,
):
    """Return (verdict, osm_id, osm_type, dist_m, matched_osm_el, poi_el).

    Scans match_idx within match_radius_m for an OSM address with the same
    normalized housenumber + street. Nearest match within match_near_m = MATCH;
    beyond that = MATCH_FAR (operator review). No match → MISSING, plus a
    same-address POI node from poi_idx (if any) attached as acknowledgment.

    Under per-door-or-collapse, for any polygon match, a candidate inside the
    element's bounds is MATCH however far the centre is: the distance to a
    building's centre is its footprint, not an error. (MATCH_LISTED, a door
    satisfied by a building's listing, was withdrawn 2026-10-01; see
    `_match_kind`. Rows from earlier runs still carry it.)
    """
    c_lat, c_lon = cand_row["lat"], cand_row["lon"]
    if c_lat is None or c_lon is None:
        return "MISSING", None, None, None, None, None

    c_num = (cand_row.get("housenumber") or "").upper()
    c_street_norm = cand_row.get("street_norm") or ""
    c_unit = (cand_row.get("unit") or "").strip().upper()

    # Tiebreak on osm_id when distances are equal so equidistant candidates
    # pick deterministically — GridIndex.query order depends on dict insertion
    # and isn't stable across refactors.
    best_match: tuple[float, int, dict] | None = None
    for o_lat, o_lon, osm in match_idx.query(c_lat, c_lon):
        dist = haversine(c_lat, c_lon, o_lat, o_lon)
        if dist > match_radius_m:
            continue
        if _match_kind(osm, c_num, c_street_norm, c_unit) is None:
            continue
        key = (dist, osm.get("id") or 0)
        if best_match is None or key < best_match[:2]:
            best_match = (*key, osm)

    if best_match is not None:
        dist, _oid, el = best_match
        if dist <= match_near_m or _inside_bounds(el, c_lat, c_lon):
            verdict = "MATCH"
        else:
            verdict = "MATCH_FAR"
        return verdict, el.get("id"), el.get("type"), dist, el, None

    best_poi: tuple[float, int, dict] | None = None
    for o_lat, o_lon, poi in poi_idx.query(c_lat, c_lon):
        dist = haversine(c_lat, c_lon, o_lat, o_lon)
        if dist > match_radius_m:
            continue
        if not _same_address(poi, c_num, c_street_norm, c_unit):
            continue
        pid = poi.get("id") or 0
        if best_poi is None or (dist, pid) < (best_poi[0], best_poi[1]):
            best_poi = (dist, pid, poi)

    poi_el = best_poi[2] if best_poi else None
    return "MISSING", None, None, None, None, poi_el


def _proposed_tags(cand_row: dict, poi_tags: dict | None = None) -> dict[str, str]:
    """Build the tag dict we would propose for this candidate.

    Output does not merely match what osm_export writes — it *is* what
    osm_export writes: this delegates to `build_tags`, and adds only the one
    thing review knows that the upload path does not, a postcode read off a
    matched POI when the source row carries none.
    """
    tags = osm_export.build_tags(cand_row)
    if "addr:postcode" not in tags and poi_tags:
        postcode = (poi_tags.get("addr:postcode") or "").strip()
        if postcode:
            tags["addr:postcode"] = postcode
    return tags


def _matched_latlon(el: dict | None) -> tuple[float | None, float | None]:
    """Point location of the matched OSM element for map rendering.

    For nodes that's lat/lon; for ways/relations we fall back to Overpass's
    `center` output (build_osm_index already required one of the two).
    """
    if el is None:
        return None, None
    if el.get("type") == "node":
        return el.get("lat"), el.get("lon")
    c = el.get("center") or {}
    return c.get("lat"), c.get("lon")


def _is_range(row: dict) -> bool:
    """Return True when the candidate represents an address range (lo_num != hi_num)."""
    lo = row.get("lo_num")
    hi = row.get("hi_num")
    return lo is not None and hi is not None and lo != hi


# A non-Land candidate that shares (address_full, municipality_name) with
# any Land row in the same run is auto-skipped — the Land row is the
# canonical record. The lookup keys on municipality_name because the same
# address string recurs across former municipalities post-amalgamation
# (see SOURCE_DATA.md "Municipality trap" — e.g. "66 George St" exists in
# three of them); within one municipality the source treats one
# address_full as one civic address.

# Two Land rows at the same (address_full, municipality_name) within this
# distance are treated as a single logical record: conflation silently skips
# the non-canonical one. Beyond this threshold both rows proceed through
# conflation and the intra_source_duplicate check flags them for review.
_INTRA_DUP_AUTO_SKIP_M = 5.0


def _colocated_land_sibling(
    cand: dict, land_keys: set[tuple[str, str | None]]
) -> bool:
    if cand.get("address_class") == "Land":
        return False
    addr = cand.get("address_full")
    if not addr:
        return False
    return (addr, cand.get("municipality_name")) in land_keys


def _build_land_groups(
    conn, run_id: int
) -> dict[tuple[str, str | None], list[tuple[int, float, float]]]:
    """(address_full, municipality_name) -> [(candidate_id, lat, lon), ...].

    Ordered by candidate_id so the first entry of every group is the canonical
    (lowest-id) row. Carries candidate_id so the sibling link can be persisted
    on the conflation row.
    """
    groups: dict[tuple[str, str | None], list[tuple[int, float, float]]] = defaultdict(list)
    for r in conn.execute(
        "SELECT candidate_id, address_full, municipality_name, lat, lon "
        "FROM candidates WHERE run_id = ? AND address_class = 'Land' "
        "  AND address_full IS NOT NULL AND lat IS NOT NULL AND lon IS NOT NULL "
        "ORDER BY candidate_id",
        (run_id,),
    ):
        groups[(r["address_full"], r["municipality_name"])].append(
            (r["candidate_id"], r["lat"], r["lon"])
        )
    return groups


def _intra_dup_status(
    cand: dict,
    land_groups: dict[tuple[str, str | None], list[tuple[int, float, float]]],
) -> tuple[int, float, bool] | None:
    """Return (nearest_sibling_cid, dist_m, is_canonical) for a Land candidate
    that shares (address_full, municipality_name) with another Land row; None
    otherwise. is_canonical is True when this row's candidate_id is the
    lowest in the group (the keep-one tiebreak).
    """
    if cand.get("address_class") != "Land":
        return None
    addr, lat, lon = cand.get("address_full"), cand.get("lat"), cand.get("lon")
    if not addr or lat is None or lon is None:
        return None
    group = land_groups.get((addr, cand.get("municipality_name")), ())
    if len(group) < 2:
        return None
    siblings = [s for s in group if s[0] != cand["candidate_id"]]
    if not siblings:
        return None
    sib_cid, _, sib_dist = min(
        ((s[0], s, haversine(lat, lon, s[1], s[2])) for s in siblings),
        key=lambda t: t[2],
    )
    canonical_cid = min(s[0] for s in group)
    return sib_cid, sib_dist, cand["candidate_id"] == canonical_cid


def run(run_id: int, osm_snapshot_hash: str, match_radius_m: float, match_near_m: float) -> dict[str, int]:
    """Iterate candidates at stage INGESTED, write conflation row, advance to CONFLATED."""
    from . import tag_diff  # local import avoids an import cycle at module load

    elements = osm_fetch.load_cached(run_id)
    match_idx, poi_idx = build_osm_index(elements)
    now = datetime.now(timezone.utc).isoformat()

    counts = {"MATCH": 0, "MATCH_FAR": 0, "MATCH_LISTED": 0, "MISSING": 0, "SKIPPED": 0}
    verdict_by_cid: dict[int, str] = {}
    conn = _db.connect()
    try:
        land_groups = _build_land_groups(conn, run_id)
        land_keys = set(land_groups.keys())

        rows = conn.execute(
            # unit and flats are what per-door-or-collapse made of the row;
            # without them here every door compared as the bare civic point,
            # MATCHed the building's node and was SKIPPED as already in OSM.
            "SELECT candidate_id, address_full, housenumber, street_raw, street_norm, lat, lon, "
            "       lo_num, hi_num, address_class, municipality_name, unit, flats, civic_key "
            "FROM candidates WHERE run_id = ? AND stage = 'INGESTED'",
            (run_id,),
        ).fetchall()

        conn.execute("BEGIN IMMEDIATE")
        for r in rows:
            cand = dict(r)

            # Same-address Land sibling detection: <5 m auto-skips the non-canonical
            # row; wider pairs persist the link for the intra_source_duplicate check.
            dup = _intra_dup_status(cand, land_groups)
            auto_skip_dup = dup is not None and dup[1] <= _INTRA_DUP_AUTO_SKIP_M and not dup[2]

            # Address ranges are skipped during conflation (kept for reference only).
            # Non-Land rows that share an address with a Land sibling are also skipped —
            # the Land row is the canonical record (see SOURCE_DATA.md).
            if _is_range(cand) or _colocated_land_sibling(cand, land_keys) or auto_skip_dup:
                verdict, osm_id, osm_type, dist, matched, poi = "SKIPPED", None, None, None, None, None
            else:
                verdict, osm_id, osm_type, dist, matched, poi = _classify(
                    cand, match_idx, poi_idx, match_radius_m, match_near_m
                )
            counts[verdict] += 1
            verdict_by_cid[cand["candidate_id"]] = verdict

            osm_tags = (matched.get("tags") if matched else None) or None
            geom = tag_diff.geom_hint(matched) if matched else None
            m_lat, m_lon = _matched_latlon(matched)

            poi_tags = (poi.get("tags") if poi else None) or None
            poi_postcode = (poi_tags.get("addr:postcode").strip() if poi_tags and poi_tags.get("addr:postcode") else None)

            dup_sib_cid, dup_sib_dist = (dup[0], dup[1]) if dup else (None, None)

            conn.execute(
                """
                INSERT OR REPLACE INTO conflation
                  (run_id, candidate_id, verdict, nearest_osm_id, nearest_osm_type,
                   nearest_dist_m, osm_snapshot_hash, computed_at,
                   matched_osm_tags_json, matched_osm_geom_hint,
                   matched_osm_lat, matched_osm_lon,
                   poi_osm_id, poi_osm_type, poi_tags_json, proposed_postcode,
                   dup_sibling_candidate_id, dup_sibling_dist_m)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id, cand["candidate_id"], verdict, osm_id, osm_type, dist,
                    osm_snapshot_hash, now,
                    json.dumps(osm_tags) if osm_tags else None,
                    geom, m_lat, m_lon,
                    (poi.get("id") if poi else None),
                    (poi.get("type") if poi else None),
                    json.dumps(poi_tags) if poi_tags else None,
                    poi_postcode,
                    dup_sib_cid, dup_sib_dist,
                ),
            )
            if auto_skip_dup:
                audit.log(
                    actor="pipeline", event_type="INTRA_DUP_SKIPPED",
                    run_id=run_id, candidate_id=cand["candidate_id"],
                    payload={
                        "sibling_candidate_id": dup_sib_cid,
                        "dist_m": round(dup_sib_dist, 2),
                        "canonical_candidate_id": min(
                            s[0] for s in land_groups[
                                (cand["address_full"], cand["municipality_name"])
                            ]
                        ),
                    },
                    conn=conn,
                )
            conn.execute(
                "UPDATE candidates SET stage = 'CONFLATED', stage_updated_at = ? "
                "WHERE run_id = ? AND candidate_id = ?",
                (now, run_id, cand["candidate_id"]),
            )

            cand_for_proposal = dict(cand, proposed_postcode=poi_postcode)
            proposed = _proposed_tags(cand_for_proposal)
            diff_rows = tag_diff.compare_tags(proposed, osm_tags)
            has_diff = any(row["status"] != "SAME" for row in diff_rows)
            if has_diff and verdict != "SKIPPED":
                audit.log(
                    actor="pipeline",
                    event_type="CONFLATE_CANDIDATE",
                    run_id=run_id,
                    candidate_id=cand["candidate_id"],
                    payload={
                        "verdict": verdict,
                        "osm_id": osm_id,
                        "osm_type": osm_type,
                        "geom_hint": geom,
                        "dist_m": dist,
                        "diff": diff_rows,
                    },
                    conn=conn,
                )
        # Suppress the intra_source_duplicate flag for Land groups whose every
        # row already MATCHed OSM: the duplicate is then pure source noise with
        # nothing importable, so these rows auto-SKIP instead of entering the
        # operator queue. Any non-MATCH sibling (notably a MISSING one — the
        # real duplicate-upload risk) leaves the whole group flagged. Members
        # not processed this run are absent from verdict_by_cid and so read as
        # non-MATCH, keeping the conservative (flag) behaviour.
        for members in land_groups.values():
            if len(members) < 2:
                continue
            if all(verdict_by_cid.get(cid) in ("MATCH", "MATCH_LISTED") for cid, _lat, _lon in members):
                for cid, _lat, _lon in members:
                    conn.execute(
                        "UPDATE conflation SET dup_group_all_match = 1 "
                        "WHERE run_id = ? AND candidate_id = ?",
                        (run_id, cid),
                    )

        audit.log(
            actor="pipeline",
            event_type="CONFLATE_DONE",
            run_id=run_id,
            payload={"counts": counts, "osm_snapshot_hash": osm_snapshot_hash},
            conn=conn,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    return counts
