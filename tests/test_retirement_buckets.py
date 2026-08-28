"""A retired address that has been deleted counts as deleted.

`already_deleted` used to fall through to the "caution" bucket, so a month's
retirement summary got *worse* as the operator worked through it: delete the 22
pristine-ours matches and they moved from "safe" to "community (review)". The
per-row pill was right all along; only the count was wrong.
"""
from t2 import maintenance


def _match(verdict, *, is_feature=False):
    return {"provenance": {"verdict": verdict, "is_feature": is_feature}}


def _bucket(matches):
    non_feature = [m for m in matches if not m["provenance"].get("is_feature")]
    verdict = maintenance._row_verdict(matches, non_feature)
    return verdict, maintenance._VERDICT_BUCKET.get(verdict, "caution")


def test_all_matches_deleted_counts_as_deleted():
    assert _bucket([_match("already_deleted")]) == ("already_deleted", "deleted")
    assert _bucket([_match("already_deleted"), _match("already_deleted")]) == (
        "already_deleted", "deleted"
    )


def test_a_surviving_match_still_needs_review():
    """One element gone, another still carrying the address — not done."""
    verdict, bucket = _bucket([_match("already_deleted"), _match("community_touched")])
    assert bucket == "caution"
    assert verdict == "community_touched"


def test_untouched_import_node_is_still_safe_to_delete():
    assert _bucket([_match("pristine_ours")]) == ("pristine_ours", "safe")


def test_an_address_riding_a_feature_is_a_question_not_a_keep():
    """The verdict names what is uncertain — the addr:* tags on the feature —
    rather than instructing a blanket KEEP. Parks and buildings turn up here
    carrying addresses that turned out to be wrong."""
    assert _bucket([_match("pristine_ours", is_feature=True)]) == (
        "address_on_feature", "feature"
    )


def test_no_match_is_unchanged():
    assert _bucket([]) == ("no_match", "no_match")
