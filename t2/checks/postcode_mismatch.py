"""Flag MATCH candidates whose matched OSM object carries a different
addr:postcode from the source's.

The import never writes to an object that already exists, so the source's
postcode is not applied and OSM's is not overwritten: this check is how the
disagreement reaches a person instead of being dropped with the MATCH. It
reads only the source postcode `config.check_postcode` accepted at ingest, so
a value the city's [postcode] prefixes refused never raises a flag against a
correct OSM one.

Spacing and case are not a disagreement. Comparing Guelph's OSM address
objects with the City's rows by number and street on 2026-10-03, 114 values
differed as strings and 59 of them only by a missing space ("N1H4E2" against
"N1H 4E2"); flagging those would bury the 55 real ones.

Resolving a flag is done in OSM, not here: Reject keeps the OSM object as it
is, which is the outcome either way, and the details name both values so the
reviewer can see which one to fix. Approving would create a second node at an
address that is already mapped.
"""
from .base import Candidate, CheckContext, Verdict


def _compact(value: str) -> str:
    return "".join(value.split()).upper()


class PostcodeMismatchCheck:
    id = "postcode_mismatch"
    version = 1
    default_enabled = True
    requires = ("postcode",)
    description = (
        "Flags MATCH candidates whose matched OSM object has a different "
        "addr:postcode from the source's. Nothing is overwritten; the flag "
        "is how the disagreement reaches a reviewer."
    )

    def applies(self, cand: Candidate, ctx: CheckContext) -> bool:
        if cand.verdict not in ("MATCH", "MATCH_FAR", "MATCH_LISTED"):
            return False
        if not (cand.postcode or "").strip():
            return False
        return bool(((cand.matched_osm_tags or {}).get("addr:postcode") or "").strip())

    def evaluate(self, cand: Candidate, ctx: CheckContext) -> Verdict:
        osm = (cand.matched_osm_tags or {}).get("addr:postcode", "").strip()
        if _compact(osm) == _compact(cand.postcode):
            return Verdict(status="PASS", reason_code="postcode_agrees")
        return Verdict(
            status="FLAG",
            severity="info",
            reason_code="postcode_mismatch",
            details={
                "source_postcode": cand.postcode,
                "osm_postcode": osm,
                "osm_id": cand.nearest_osm_id,
                "osm_type": cand.nearest_osm_type,
            },
        )
