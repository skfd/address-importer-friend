import zlib

from .base import Candidate, CheckContext, Verdict


def _sample_ordinal(candidate_id: int | str) -> int:
    """Deterministic ordinal for every-Nth sampling. Numeric ids keep their
    value, so cities with integer identity keys (Toronto) sample the exact
    same candidates as before. Synthetic string ids (the tracker's
    ``syn:<sha1>`` fallback, e.g. Hamilton) hash via crc32 — stable across
    processes, unlike ``hash()``."""
    if isinstance(candidate_id, int):
        return candidate_id
    s = str(candidate_id)
    if s.isdigit():
        return int(s)
    return zlib.crc32(s.encode("utf-8"))


class MissingSampleCheck:
    id = "missing_sample"
    version = 1
    default_enabled = True
    description = "Flags every Nth MISSING candidate for spot-check review."

    def applies(self, cand: Candidate, ctx: CheckContext) -> bool:
        return cand.verdict == "MISSING"

    def evaluate(self, cand: Candidate, ctx: CheckContext) -> Verdict:
        every_nth = int(ctx.params.get("missing_sample", {}).get("every_nth", 50))
        if every_nth <= 0 or _sample_ordinal(cand.candidate_id) % every_nth != 0:
            return Verdict(status="PASS", reason_code="not_sampled")
        return Verdict(
            status="FLAG",
            severity="info",
            reason_code="spot_check",
            details={"every_nth": every_nth},
        )
