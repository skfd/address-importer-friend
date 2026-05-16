from t2.checks import REGISTRY, Candidate, CheckContext
from t2.conflate import GridIndex, normalize_street


def _make_ctx(osm_elements: list[dict]) -> CheckContext:
    idx = GridIndex()
    for el in osm_elements:
        el["_norm_number"] = str(el["tags"]["addr:housenumber"]).upper()
        el["_norm_street"] = normalize_street(el["tags"]["addr:street"])
        idx.add(el, el["lat"], el["lon"])
    return CheckContext(run_id=1, osm_index=idx, city_index=GridIndex(), params={})


def _candidate(**overrides) -> Candidate:
    base = dict(
        run_id=1, candidate_id=1, address_full="10 Deane Field Cres",
        housenumber="10", street_raw="Deane Field Crescent",
        street_norm=normalize_street("Deane Field Crescent"),
        lat=43.65, lon=-79.40,
        lo_num=10, lo_num_suf=None, hi_num=10, hi_num_suf=None,
        verdict="MISSING",
        nearest_osm_id=None, nearest_osm_type=None, nearest_dist_m=None,
    )
    base.update(overrides)
    return Candidate(**base)


def test_flags_when_nearby_osm_has_same_number_different_street():
    cand = _candidate()
    osm_neighbour = {
        "type": "node", "id": 42, "lat": 43.65, "lon": -79.40,
        "tags": {"addr:housenumber": "10", "addr:street": "Deanefield Crescent"},
    }
    check = REGISTRY["nearby_street_mismatch"]
    ctx = _make_ctx([osm_neighbour])
    assert check.applies(cand, ctx) is True
    v = check.evaluate(cand, ctx)
    assert v.status == "FLAG"
    assert v.reason_code == "nearby_street_mismatch"
    assert v.details["count"] == 1
    assert v.details["matches"][0]["osm_street"] == "Deanefield Crescent"
    assert v.details["matches"][0]["osm_housenumber"] == "10"


def test_passes_when_no_osm_neighbour():
    cand = _candidate()
    check = REGISTRY["nearby_street_mismatch"]
    ctx = _make_ctx([])
    v = check.evaluate(cand, ctx)
    assert v.status == "PASS"


def test_passes_when_nearby_osm_shares_street_after_normalization():
    cand = _candidate(street_raw="Main Street", street_norm=normalize_street("Main Street"))
    osm_same_street = {
        "type": "node", "id": 7, "lat": 43.65, "lon": -79.40,
        "tags": {"addr:housenumber": "10", "addr:street": "Main St"},
    }
    check = REGISTRY["nearby_street_mismatch"]
    ctx = _make_ctx([osm_same_street])
    v = check.evaluate(cand, ctx)
    assert v.status == "PASS"


def test_passes_when_nearby_osm_has_different_number():
    cand = _candidate()
    osm_different_number = {
        "type": "node", "id": 5, "lat": 43.65, "lon": -79.40,
        "tags": {"addr:housenumber": "12", "addr:street": "Deanefield Crescent"},
    }
    check = REGISTRY["nearby_street_mismatch"]
    ctx = _make_ctx([osm_different_number])
    v = check.evaluate(cand, ctx)
    assert v.status == "PASS"


def test_does_not_apply_for_match_verdict():
    cand = _candidate(verdict="MATCH")
    check = REGISTRY["nearby_street_mismatch"]
    ctx = _make_ctx([])
    assert check.applies(cand, ctx) is False


def test_passes_when_neighbour_is_outside_radius():
    cand = _candidate()
    # ~111 m north of the candidate (well outside the 20 m default).
    osm_far = {
        "type": "node", "id": 9, "lat": 43.651, "lon": -79.40,
        "tags": {"addr:housenumber": "10", "addr:street": "Deanefield Crescent"},
    }
    check = REGISTRY["nearby_street_mismatch"]
    ctx = _make_ctx([osm_far])
    v = check.evaluate(cand, ctx)
    assert v.status == "PASS"
