from t2.checks import REGISTRY, Candidate, CheckContext
from t2.conflate import GridIndex, normalize_street

# 1 degree of latitude is ~111195 m; moving a node north by d/111195 degrees
# places it d metres from the candidate so distances are easy to reason about.
_M_PER_DEG_LAT = 111195.0


def _north(lat: float, metres: float) -> float:
    return lat + metres / _M_PER_DEG_LAT


def _make_ctx(osm_elements: list[dict]) -> CheckContext:
    idx = GridIndex()
    for el in osm_elements:
        el["_norm_number"] = str(el["tags"]["addr:housenumber"]).upper()
        el["_norm_street"] = normalize_street(el["tags"]["addr:street"])
        idx.add(el, el["lat"], el["lon"])
    return CheckContext(run_id=1, osm_index=idx, city_index=GridIndex(), params={})


def _candidate(**overrides) -> Candidate:
    base = dict(
        run_id=1, candidate_id=1, address_full="164 Coleridge Ave",
        housenumber="164", street_raw="Coleridge Avenue",
        street_norm=normalize_street("Coleridge Avenue"),
        lat=43.65, lon=-79.40,
        lo_num=164, lo_num_suf=None, hi_num=164, hi_num_suf=None,
        verdict="MATCH",
        nearest_osm_id=100, nearest_osm_type="node", nearest_dist_m=6.0,
    )
    base.update(overrides)
    return Candidate(**base)


def _osm(housenumber: str, street: str, lat: float, lon: float, oid: int) -> dict:
    return {
        "type": "node", "id": oid, "lat": lat, "lon": lon,
        "tags": {"addr:housenumber": housenumber, "addr:street": street},
    }


def test_flags_when_closer_neighbour_has_different_number():
    # Matched OSM "164" is 6 m away; OSM "166" sits 1 m away -> 5 m gap.
    cand = _candidate(nearest_dist_m=6.0)
    neighbour = _osm("166", "Coleridge Avenue", _north(43.65, 1.0), -79.40, 166)
    check = REGISTRY["match_number_drift"]
    ctx = _make_ctx([neighbour])
    assert check.applies(cand, ctx) is True
    v = check.evaluate(cand, ctx)
    assert v.status == "FLAG"
    assert v.reason_code == "match_number_drift"
    assert v.details["count"] == 1
    assert v.details["neighbors"][0]["osm_housenumber"] == "166"
    assert v.details["matched_housenumber"] == "164"


def test_passes_when_matched_is_closest():
    # The only different-numbered neighbour is 10 m away, farther than the
    # 6 m matched element.
    cand = _candidate(nearest_dist_m=6.0)
    neighbour = _osm("166", "Coleridge Avenue", _north(43.65, 10.0), -79.40, 166)
    check = REGISTRY["match_number_drift"]
    ctx = _make_ctx([neighbour])
    v = check.evaluate(cand, ctx)
    assert v.status == "PASS"
    assert v.reason_code == "no_number_drift"


def test_passes_when_gap_within_slack():
    # Neighbour is only 1 m closer than the matched element (gap < 2 m slack).
    cand = _candidate(nearest_dist_m=6.0)
    neighbour = _osm("166", "Coleridge Avenue", _north(43.65, 5.0), -79.40, 166)
    check = REGISTRY["match_number_drift"]
    ctx = _make_ctx([neighbour])
    v = check.evaluate(cand, ctx)
    assert v.status == "PASS"


def test_passes_when_closer_neighbour_is_different_street():
    cand = _candidate(nearest_dist_m=6.0)
    neighbour = _osm("166", "Mortimer Avenue", _north(43.65, 1.0), -79.40, 166)
    check = REGISTRY["match_number_drift"]
    ctx = _make_ctx([neighbour])
    v = check.evaluate(cand, ctx)
    assert v.status == "PASS"


def test_does_not_apply_for_missing_verdict():
    cand = _candidate(verdict="MISSING", nearest_dist_m=None)
    check = REGISTRY["match_number_drift"]
    ctx = _make_ctx([])
    assert check.applies(cand, ctx) is False


def test_applies_and_flags_for_match_far():
    cand = _candidate(verdict="MATCH_FAR", nearest_dist_m=16.0)
    neighbour = _osm("166", "Coleridge Avenue", _north(43.65, 4.0), -79.40, 166)
    check = REGISTRY["match_number_drift"]
    ctx = _make_ctx([neighbour])
    assert check.applies(cand, ctx) is True
    v = check.evaluate(cand, ctx)
    assert v.status == "FLAG"
