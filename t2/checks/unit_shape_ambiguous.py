"""Flag a collapsed candidate whose civic group the unit rule was unsure about.

Under per-door-or-collapse most civic groups decide themselves: the unit
numbering says floor-coded suites, or it says sequential doors and the spacing
agrees. A minority say sequential and then sit closer together than a townhouse
can be built — Guelph has 58 of these against 349 that decide themselves.

Those are emitted *collapsed*, which is the safe upload: one node carrying
addr:flats is right whether the units turn out to be suites or doors, whereas
exploding a group the rule doubts uploads front doors that may not exist. But
safe is not the same as certain, and without this check the reviewer cannot
tell 252 Stone Road West — a mall, 140 storefronts, 3.7 m apart — from a
14-storey tower. Both arrive as one node with a long addr:flats.

Informational, not blocking: the candidate is uploadable as proposed. What it
buys is that somebody looked.
"""
from .base import Candidate, CheckContext, Verdict


class UnitShapeAmbiguousCheck:
    id = "unit_shape_ambiguous"
    version = 1
    default_enabled = True
    description = (
        "Flags a collapsed candidate whose units are numbered sequentially "
        "but sit too close together to be separate front doors, so the "
        "collapse was the safe choice rather than a confident one."
    )
    # Without a declared unit field there are no civic groups to classify and
    # unit_shape is NULL on every row, so the check would silently pass
    # everything. Gating it makes "could not run" visible instead.
    requires = ("unit",)

    def applies(self, cand: Candidate, ctx: CheckContext) -> bool:
        return cand.unit_shape == "review"

    def evaluate(self, cand: Candidate, ctx: CheckContext) -> Verdict:
        return Verdict(
            status="FLAG",
            severity="info",
            reason_code="unit_shape_ambiguous",
            details={
                "reason": cand.unit_shape_reason,
                "flats": cand.flats,
            },
        )
