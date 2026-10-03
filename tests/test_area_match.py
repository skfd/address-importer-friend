"""An area that carries the address -- a park, a school, a big building --
is already in OSM for a candidate inside it or near its edge, however far
away its centre is. Before 2026-10-03 the distance was taken to the centre
and capped at the match radius, so a point inside a 300 m park read MISSING
and uploaded a second copy of the park's address (Guelph: 71 Lee Street,
388 Arkell Road and three more)."""
from t2.conflate import _classify, build_osm_index

M = 1 / 111320.0   # one metre of latitude


def _park(half_m, lat=43.5, lon=-80.2, number="71", street="Lee Street"):
    h = half_m * M
    return {"type": "way", "id": 9, "center": {"lat": lat, "lon": lon},
            "bounds": {"minlat": lat - h, "maxlat": lat + h, "minlon": lon - h * 1.4, "maxlon": lon + h * 1.4},
            "tags": {"addr:housenumber": number, "addr:street": street, "leisure": "park"}}


def _cand(north_m, number="71"):
    return {"candidate_id": 1, "housenumber": number, "street_norm": "LEE ST",
            "lat": 43.5 + north_m * M, "lon": -80.2, "unit": None, "flats": None}


def _classify_with(cand, elements):
    match_idx, poi_idx = build_osm_index(elements)
    return _classify(cand, match_idx, poi_idx, 100.0, 15.0)


def test_a_point_deep_inside_a_big_park_matches_it():
    verdict, osm_id, osm_type, dist, *_ = _classify_with(_cand(250), [_park(300)])
    assert (verdict, osm_id, osm_type, dist) == ("MATCH", 9, "way", 0.0)


def test_a_point_just_outside_a_big_park_is_far_not_missing():
    verdict, _, _, dist, *_ = _classify_with(_cand(340), [_park(300)])
    assert verdict == "MATCH_FAR" and 35 < dist < 45


def test_beyond_the_radius_of_the_edge_it_is_still_missing():
    assert _classify_with(_cand(420), [_park(300)])[0] == "MISSING"


def test_a_park_with_another_number_does_not_match():
    assert _classify_with(_cand(250, number="73"), [_park(300)])[0] == "MISSING"
