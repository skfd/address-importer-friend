"""Flag MATCH candidates where a different-numbered OSM address on the same
street sits closer to the candidate than the matched OSM element. The
candidate still "matches" its same-numbered OSM twin, but a whole block of
these signals positional drift in OSM (an old bulk import shifted by one or
more houses) — the matched twin is on the wrong building.

This is the MATCH-side counterpart of nearby_street_mismatch (which catches
the MISSING-side street-name variant case).
"""
from ..conflate import haversine
from .base import Candidate, CheckContext, Verdict


class MatchNumberDriftCheck:
    id = "match_number_drift"
    version = 2
    default_enabled = True
    description = (
        "Flags MATCH candidates where a different-numbered OSM address on the "
        "same street is closer than the matched element — signals OSM address "
        "positional drift (a bulk import shifted by one or more houses)."
    )

    def applies(self, cand: Candidate, ctx: CheckContext) -> bool:
        if cand.verdict not in ("MATCH", "MATCH_FAR"):
            return False
        if cand.lat is None or cand.lon is None:
            return False
        if cand.nearest_dist_m is None:
            return False
        if not (cand.street_norm or ""):
            return False
        return bool((cand.housenumber or "").strip())

    def evaluate(self, cand: Candidate, ctx: CheckContext) -> Verdict:
        slack_m = float(
            ctx.params.get("match_number_drift", {}).get("slack_m", 2.0)
        )
        c_num = (cand.housenumber or "").upper()
        c_street_norm = cand.street_norm or ""
        matched_dist = cand.nearest_dist_m
        # A different-numbered neighbour only counts as drift if it beats the
        # matched element by the full slack — closer ties are placement noise.
        cutoff = matched_dist - slack_m
        closer: list[dict] = []
        seen: set[tuple[str | None, int | None]] = set()
        for o_lat, o_lon, osm in ctx.osm_index.query(cand.lat, cand.lon):
            if osm.get("_norm_street") != c_street_norm:
                continue
            if osm.get("_norm_number") == c_num:
                continue
            dist = haversine(cand.lat, cand.lon, o_lat, o_lon)
            if dist > cutoff:
                continue
            key = (osm.get("type"), osm.get("id"))
            if key in seen:
                continue
            seen.add(key)
            tags = osm.get("tags") or {}
            closer.append({
                "osm_id": osm.get("id"),
                "osm_type": osm.get("type"),
                "osm_street": tags.get("addr:street") or "",
                "osm_housenumber": tags.get("addr:housenumber") or "",
                "dist_m": round(dist, 2),
            })
        if not closer:
            return Verdict(status="PASS", reason_code="no_number_drift")
        closer.sort(key=lambda m: m["dist_m"])
        # Surface any MISSING city candidates on the same street within the
        # matched distance — a nearby missing address (e.g. "86A") is often
        # the root cause of the surrounding drift pattern.
        missing_nearby: list[dict] = []
        seen_missing: set[int] = set()
        for m_lat, m_lon, city in ctx.city_index.query(cand.lat, cand.lon):
            if city.get("candidate_id") == cand.candidate_id:
                continue
            if city.get("verdict") != "MISSING":
                continue
            if city.get("street_norm") != c_street_norm:
                continue
            dist = haversine(cand.lat, cand.lon, m_lat, m_lon)
            if dist > matched_dist:
                continue
            cid = city["candidate_id"]
            if cid in seen_missing:
                continue
            seen_missing.add(cid)
            missing_nearby.append({
                "candidate_id": cid,
                "housenumber": city.get("housenumber") or "",
                "dist_m": round(dist, 2),
            })
        missing_nearby.sort(key=lambda m: m["dist_m"])
        return Verdict(
            status="FLAG",
            severity="warn",
            reason_code="match_number_drift",
            details={
                "matched_housenumber": c_num,
                "matched_dist_m": round(matched_dist, 2),
                "neighbors": closer[:5],
                "count": len(closer),
                "slack_m": slack_m,
                "missing_nearby": missing_nearby[:5],
            },
        )
