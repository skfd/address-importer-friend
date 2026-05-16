from t2.checks.base import Candidate, CheckContext
from t2.checks.intra_source_duplicate import IntraSourceDuplicateCheck

CHECK = IntraSourceDuplicateCheck()
CTX = CheckContext(run_id=1, osm_index=None, city_index=None, params={})


def _cand(**over) -> Candidate:
    base = dict(
        run_id=1, candidate_id=10, address_full="100 Main St", housenumber="100",
        street_raw="Main St", street_norm="main st", lat=43.6, lon=-79.4,
        lo_num=100, lo_num_suf=None, hi_num=100, hi_num_suf=None,
        verdict="MATCH", nearest_osm_id=None, nearest_osm_type=None,
        nearest_dist_m=None,
    )
    base.update(over)
    return Candidate(**base)


def test_no_sibling_does_not_apply():
    assert CHECK.applies(_cand(dup_sibling_candidate_id=None), CTX) is False


def test_sibling_with_unknown_group_state_still_flags():
    # dup_group_all_match absent (None) -> conservative: keep flagging.
    c = _cand(dup_sibling_candidate_id=11, dup_group_all_match=None)
    assert CHECK.applies(c, CTX) is True


def test_sibling_with_non_match_in_group_flags():
    c = _cand(dup_sibling_candidate_id=11, dup_group_all_match=0)
    assert CHECK.applies(c, CTX) is True


def test_whole_group_matched_osm_is_suppressed():
    c = _cand(dup_sibling_candidate_id=11, dup_group_all_match=1)
    assert CHECK.applies(c, CTX) is False


def test_evaluate_flags_with_reason_and_details():
    c = _cand(dup_sibling_candidate_id=11, dup_sibling_dist_m=12.345)
    v = CHECK.evaluate(c, CTX)
    assert v.status == "FLAG"
    assert v.reason_code == "intra_source_duplicate"
    assert v.details == {"sibling_candidate_id": 11, "dist_m": 12.35}
