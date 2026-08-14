"""Check framework: pluggable per-candidate validators whose results are cached in tool.db.

A Check maps a candidate to a Verdict (PASS / FLAG / SKIP). FLAG creates a review_item.
Bump Check.version to invalidate cached results on behavior change.
"""
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Candidate:
    run_id: int
    # The source's identity_key: an integer where the source has a stable
    # numeric id (Toronto), the tracker's synthetic "syn:<sha1>" string
    # where it does not (Hamilton).
    candidate_id: int | str
    address_full: str | None
    housenumber: str | None
    street_raw: str | None
    street_norm: str | None
    lat: float | None
    lon: float | None
    lo_num: int | None
    lo_num_suf: str | None
    hi_num: int | None
    hi_num_suf: str | None
    verdict: str  # MATCH / MATCH_FAR / MISSING / SKIPPED from conflation
    nearest_osm_id: int | None
    nearest_osm_type: str | None
    nearest_dist_m: float | None
    matched_osm_tags: dict[str, str] | None = None
    dup_sibling_candidate_id: int | str | None = None
    dup_sibling_dist_m: float | None = None
    dup_group_all_match: int | None = None  # 1 when every same-address Land sibling MATCHed OSM


@dataclass
class Verdict:
    status: str  # PASS / FLAG / SKIP
    severity: str = "info"  # info / warn / block
    reason_code: str = ""
    details: dict[str, Any] = field(default_factory=dict)


class CheckContext:
    def __init__(self, run_id: int, osm_index, city_index, params: dict[str, dict]):
        self.run_id = run_id
        self.osm_index = osm_index
        self.city_index = city_index
        self.params = params


class Check(Protocol):
    id: str
    version: int
    default_enabled: bool
    description: str
    # Optional source fields ([source_fields] keys, e.g. "lo_num") this check
    # reads. When the city's config declares none of them, the check is
    # disabled-for-cause at run start — visibly, so "could not run" is never
    # mistaken for "ran and found nothing" (03-capability-gating.md). Checks
    # with no such dependency simply omit the attribute (treated as ()).
    requires: tuple[str, ...]

    def applies(self, cand: Candidate, ctx: CheckContext) -> bool: ...
    def evaluate(self, cand: Candidate, ctx: CheckContext) -> Verdict: ...
