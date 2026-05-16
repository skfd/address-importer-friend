"""Flag Land candidates that share (address_full, municipality_name) with
another active Land row. Non-canonical rows within 5 m are silently deduped
by the conflate stage; this check surfaces the canonical row in those pairs
(so the operator sees the dedup happened) and both rows in wider pairs
(where neither can be safely auto-dropped).

Exception: when *every* row in the same-address Land group already MATCHed
OSM (conflate sets dup_group_all_match=1), the duplicate is pure source
noise — nothing is importable, so there is no duplicate-upload risk. Those
rows fall through to the verdict-based routing (MATCH -> SKIPPED) instead of
the review queue. A group with any non-MATCH sibling (notably a MISSING one,
which would auto-approve into a duplicate node) stays flagged.
"""
from .base import Candidate, CheckContext, Verdict


class IntraSourceDuplicateCheck:
    id = "intra_source_duplicate"
    version = 2
    default_enabled = True
    description = (
        "Flags Land candidates that share (address_full, municipality) with "
        "another active Land row in the same run, unless every row in that "
        "group already matched OSM (nothing importable)."
    )

    def applies(self, cand: Candidate, ctx: CheckContext) -> bool:
        if cand.dup_sibling_candidate_id is None:
            return False
        # Whole same-address Land group already matched OSM: nothing to import,
        # so the in-source duplicate is noise — let the row auto-SKIP.
        if cand.dup_group_all_match:
            return False
        return True

    def evaluate(self, cand: Candidate, ctx: CheckContext) -> Verdict:
        return Verdict(
            status="FLAG",
            severity="info",
            reason_code="intra_source_duplicate",
            details={
                "sibling_candidate_id": cand.dup_sibling_candidate_id,
                "dist_m": round(cand.dup_sibling_dist_m, 2)
                if cand.dup_sibling_dist_m is not None
                else None,
            },
        )
