"""missing_sample must sample deterministically for both id shapes:
integer identity keys (Toronto) and the tracker's synthetic ``syn:<sha1>``
strings (Hamilton). The string form used to crash: ``str % int`` is string
formatting, not modulo.
"""
import zlib

from t2.checks.base import Candidate, CheckContext
from t2.checks.missing_sample import MissingSampleCheck, _sample_ordinal


def _cand(candidate_id):
    return Candidate(
        run_id=1, candidate_id=candidate_id, address_full="1 Test St",
        housenumber="1", street_raw="Test St", street_norm="test street",
        lat=43.0, lon=-79.9, lo_num=None, lo_num_suf=None, hi_num=None,
        hi_num_suf=None, verdict="MISSING", nearest_osm_id=None,
        nearest_osm_type=None, nearest_dist_m=None,
    )


def _ctx(every_nth=50):
    return CheckContext(
        run_id=1, osm_index=None, city_index=None,
        params={"missing_sample": {"every_nth": every_nth}},
    )


def test_integer_ids_keep_exact_prior_sampling():
    check = MissingSampleCheck()
    assert check.evaluate(_cand(100), _ctx()).status == "FLAG"
    assert check.evaluate(_cand(101), _ctx()).status == "PASS"


def test_numeric_string_id_behaves_like_its_integer():
    assert _sample_ordinal("150") == 150


def test_synthetic_string_id_does_not_crash_and_is_deterministic():
    check = MissingSampleCheck()
    cid = "syn:012bec5afd51e44f3c26ba6f51aed6275800af38"
    first = check.evaluate(_cand(cid), _ctx())
    assert first.status in ("PASS", "FLAG")
    assert check.evaluate(_cand(cid), _ctx()).status == first.status
    assert _sample_ordinal(cid) == zlib.crc32(cid.encode("utf-8"))


def test_synthetic_ids_sample_roughly_every_nth():
    check = MissingSampleCheck()
    flagged = sum(
        1
        for i in range(1000)
        if check.evaluate(_cand(f"syn:{i:040x}"), _ctx(50)).status == "FLAG"
    )
    # Binomial(1000, 1/50): ~20 expected; bounds are loose on purpose.
    assert 5 <= flagged <= 45
