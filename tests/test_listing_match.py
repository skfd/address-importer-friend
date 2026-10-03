"""A building that lists its units is the building.

Guelph's towers are in OSM as one way with `addr:unit=101-116;201-215;...`
(453 objects, 176 of the city's 409 unit groups), and until this landed the
matcher demanded unit equality, so neither the collapsed candidate nor any
door candidate ever matched them. Pins: the index recognises a listing, the
collapsed candidate matches it as the building, a door matches it by
containment no longer -- withdrawn 2026-10-01, a listing does not stand in
for a door -- an exact door node matches, and off the policy nothing changed.

Also pins the SELECT in `conflate.run`: the unit has to reach `_classify`,
or every door compares as the bare civic point, matches the building's node
and is SKIPPED as already in OSM.
"""
import pytest

from t2 import conflate, db as _db, osm_fetch, tag_diff, units
from t2.conflate import _classify, _same_address, build_osm_index


def _node(id_, number, unit=None, flats=None, street="Willow Road", lat=43.5, lon=-80.2):
    tags = {"addr:housenumber": number, "addr:street": street}
    if unit is not None:
        tags["addr:unit"] = unit
    if flats is not None:
        tags["addr:flats"] = flats
    return {"type": "node", "id": id_, "lat": lat, "lon": lon, "tags": tags}


def _way(id_, number, unit=None, flats=None, street="Willow Road", lat=43.5, lon=-80.2, half=0.0003):
    el = _node(id_, number, unit, flats, street, lat, lon)
    el.update(type="way", center={"lat": lat, "lon": lon},
              bounds={"minlat": lat - half, "maxlat": lat + half, "minlon": lon - half, "maxlon": lon + half})
    del el["lat"], el["lon"]
    el["tags"]["building"] = "apartments"
    return el


def _cand(unit=None, flats=None, lat=43.5, lon=-80.2, number="714"):
    return {"candidate_id": 1, "housenumber": number, "street_norm": "WILLOW RD",
            "lat": lat, "lon": lon, "unit": unit, "flats": flats}


@pytest.fixture
def unit_aware(monkeypatch):
    monkeypatch.setattr(conflate, "_UNIT_AWARE", True)


def _verdict(cand, elements, near=15.0, radius=100.0):
    match_idx, poi_idx = build_osm_index(elements)
    return _classify(cand, match_idx, poi_idx, radius, near)[0]


# --- the listing helpers -----------------------------------------------------


def test_a_listing_is_a_list_or_a_range_and_a_designator_is_not():
    assert units.UNIT_LISTING.search("101-116;201-215")
    assert units.UNIT_LISTING.search("1-10")
    assert units.UNIT_LISTING.search("LL1-LL4")
    assert not units.UNIT_LISTING.search("30")
    assert not units.UNIT_LISTING.search("PH-2")
    assert not units.UNIT_LISTING.search("A-1")


def test_expand_listing_walks_ranges_and_keeps_strays():
    assert units.expand_listing("101-103;201;1A") == {"101", "102", "103", "201", "1A"}
    assert units.expand_listing("LL01-LL03") == {"LL1", "LL2", "LL3"}
    # A range too wide to be a building is a literal, not an allocation.
    assert units.expand_listing("1-1000") == {"1-1000"}


def test_designators_agree_across_leading_zeros_and_case():
    assert units.norm_designator("ll01") == units.norm_designator("LL1") == "LL1"
    assert units.norm_designator("PH") == "PH"


# --- the index -----------------------------------------------------------------


def test_a_way_listing_units_is_indexed_as_the_building(unit_aware):
    idx, _ = build_osm_index([_way(1, "714", unit="101-103;201-203")])
    el = next(iter(idx.query(43.5, -80.2)))[2]
    assert el["_norm_unit"] == ""
    assert el["_listed_units"] == {"101", "102", "103", "201", "202", "203"}
    # The raw tag is left for the diff to show.
    assert el["tags"]["addr:unit"] == "101-103;201-203"


def test_addr_flats_is_a_listing_too(unit_aware):
    idx, _ = build_osm_index([_node(1, "714", flats="1-4")])
    el = next(iter(idx.query(43.5, -80.2)))[2]
    assert el["_listed_units"] == {"1", "2", "3", "4"} and el["_norm_unit"] == ""


def test_a_single_addr_unit_is_still_a_unit(unit_aware):
    idx, _ = build_osm_index([_node(1, "714", unit="30")])
    el = next(iter(idx.query(43.5, -80.2)))[2]
    assert el["_norm_unit"] == "30" and "_listed_units" not in el


def test_off_the_policy_a_listing_way_is_indexed_as_before(monkeypatch):
    monkeypatch.setattr(conflate, "_UNIT_AWARE", False)
    idx, _ = build_osm_index([_way(1, "714", unit="101-103")])
    el = next(iter(idx.query(43.5, -80.2)))[2]
    assert el["_norm_unit"] == "101-103" and "_listed_units" not in el
    assert _same_address(el, "714", "WILLOW RD", "") is True


# --- the verdicts --------------------------------------------------------------


def test_a_collapsed_candidate_matches_the_building_that_lists_its_units(unit_aware):
    assert _verdict(_cand(flats="101-103;201-203"), [_way(1, "714", unit="101-103;201-203")]) == "MATCH"


def test_a_listing_does_not_stand_in_for_a_door(unit_aware):
    # The building says it contains 30; nothing says where 30's door is. A
    # door candidate is proposed beside the listing, which stays as it is.
    assert _verdict(_cand(unit="30"), [_way(1, "714", unit="1-40")]) == "MISSING"
    assert _verdict(_cand(unit="30"), [_way(1, "714", flats="1-40")]) == "MISSING"
    assert _verdict(_cand(unit="LL01"), [_way(1, "714", flats="LL1-LL4")]) == "MISSING"


def test_an_exact_door_node_beats_a_nearer_listing(unit_aware):
    # The listing way sits on the candidate; the door node is 10 m off. The
    # door node is still the better answer: there IS a node for unit 30.
    els = [_way(1, "714", unit="1-40"), _node(2, "714", unit="30", lat=43.5 + 10 / 111320.0)]
    match_idx, poi_idx = build_osm_index(els)
    verdict, osm_id, *_ = _classify(_cand(unit="30"), match_idx, poi_idx, 100.0, 15.0)
    assert (verdict, osm_id) == ("MATCH", 2)
    # Past the near threshold the node still wins, and a human looks: a real
    # node for the unit 20 m off is a MATCH_FAR question, not a skip.
    els = [_way(1, "714", unit="1-40"), _node(2, "714", unit="30", lat=43.5 + 20 / 111320.0)]
    match_idx, poi_idx = build_osm_index(els)
    verdict, osm_id, *_ = _classify(_cand(unit="30"), match_idx, poi_idx, 100.0, 15.0)
    assert (verdict, osm_id) == ("MATCH_FAR", 2)


def test_a_civic_point_inside_the_buildings_bounds_is_not_far(unit_aware):
    # 40 m from the centre of a big footprint, inside its bounds: MATCH.
    # Outside a small one at the same distance, ~29 m past its edge: MATCH_FAR.
    inside = _verdict(_cand(flats="1-40", lat=43.5 + 40 / 111320.0), [_way(1, "714", unit="1-40", half=0.001)])
    outside = _verdict(_cand(flats="1-40", lat=43.5 + 40 / 111320.0), [_way(1, "714", unit="1-40", half=0.0001)])
    assert (inside, outside) == ("MATCH", "MATCH_FAR")


def test_the_double_encoded_door_still_does_not_match(unit_aware):
    # Mechanical edit #2 is still a prerequisite; a listing is a different thing.
    assert _verdict(_cand(unit="30"), [_node(1, "714-30", unit="30")]) == "MISSING"


# --- the diff ----------------------------------------------------------------------


def test_flats_compare_as_sets_not_strings():
    rows = tag_diff.compare_tags(
        {"addr:housenumber": "150", "addr:street": "Wellington Street East", "addr:flats": "101-104;1001-1008"},
        {"addr:housenumber": "150", "addr:street": "Wellington Street East", "addr:flats": "1001-1008;101-104"},
    )
    assert {r["tag"]: r["status"] for r in rows}["addr:flats"] == "SAME"


def test_the_diff_shows_the_retag_a_listing_way_needs():
    rows = tag_diff.compare_tags(
        {"addr:housenumber": "1878", "addr:street": "Gordon Street", "addr:flats": "101-103"},
        {"addr:housenumber": "1878", "addr:street": "Gordon Street", "addr:unit": "101-103"},
    )
    by = {r["tag"]: r["status"] for r in rows}
    assert by["addr:flats"] == "ADD" and by["addr:unit"] == "MISSING_PROPOSED"


# --- the SELECT --------------------------------------------------------------------


@pytest.fixture
def tool_db(tmp_path, monkeypatch):
    monkeypatch.setattr(_db._CONFIG, "tool_db_path", tmp_path / "tool.db")
    monkeypatch.setattr(_db._CONFIG, "data_dir", tmp_path)
    _db.migrate()
    return tmp_path


def test_run_hands_the_unit_to_the_matcher(tool_db, unit_aware, monkeypatch):
    """Without unit in the SELECT a door candidate compared as the bare civic
    point, MATCHed the building's node and was SKIPPED as already in OSM."""
    with _db.tx() as conn:
        conn.execute(
            "INSERT INTO runs (run_id, name, bbox_min_lat, bbox_min_lon, bbox_max_lat, "
            "bbox_max_lon, created_at, config_json) VALUES (1, 'r', 0, 0, 90, 0, 't', '{}')"
        )
        for cid, unit in ((10, "30"), (11, None)):
            conn.execute(
                "INSERT INTO candidates (run_id, candidate_id, address_full, housenumber, street_raw, "
                "street_norm, lat, lon, stage, stage_updated_at, unit, civic_key) "
                "VALUES (1, ?, '714 Willow Road', '714', 'Willow Road', 'WILLOW RD', 43.5, -80.2, "
                "'INGESTED', 't', ?, '714|WILLOW ROAD|GUELPH')",
                (cid, unit),
            )
    # OSM has the bare civic node only: the door is MISSING, the civic MATCHes.
    monkeypatch.setattr(osm_fetch, "load_cached", lambda run_id: [_node(1, "714")])
    counts = conflate.run(1, "hash", 100.0, 15.0)
    assert counts["MISSING"] == 1 and counts["MATCH"] == 1
    conn = _db.connect()
    try:
        by = {r["candidate_id"]: r["verdict"] for r in conn.execute("SELECT candidate_id, verdict FROM conflation")}
    finally:
        conn.close()
    assert by == {10: "MISSING", 11: "MATCH"}
