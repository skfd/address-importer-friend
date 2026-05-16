"""Flag MISSING candidates that have a nearby OSM address with the same
housenumber but a different normalized street name. Catches street-name
spelling variants between source and OSM (e.g. source "Deane Field
Crescent" vs OSM signage "Deanefield Crescent") that conflation can't
match because the normalizer can't bridge an arbitrary space change.
"""
from ..conflate import haversine
from .base import Candidate, CheckContext, Verdict


class NearbyStreetMismatchCheck:
    id = "nearby_street_mismatch"
    version = 1
    default_enabled = True
    description = (
        "Flags MISSING candidates that have a nearby OSM address with the same "
        "housenumber but a different street name (catches spelling variants "
        "like 'Deane Field' vs 'Deanefield')."
    )

    def applies(self, cand: Candidate, ctx: CheckContext) -> bool:
        if cand.verdict != "MISSING":
            return False
        if cand.lat is None or cand.lon is None:
            return False
        return bool((cand.housenumber or "").strip())

    def evaluate(self, cand: Candidate, ctx: CheckContext) -> Verdict:
        radius = float(
            ctx.params.get("nearby_street_mismatch", {}).get("radius_m", 20.0)
        )
        c_num = (cand.housenumber or "").upper()
        c_street_norm = cand.street_norm or ""
        matches: list[dict] = []
        seen: set[tuple[str | None, int | None]] = set()
        for o_lat, o_lon, osm in ctx.osm_index.query(cand.lat, cand.lon):
            if osm.get("_norm_number") != c_num:
                continue
            if osm.get("_norm_street") == c_street_norm:
                continue
            dist = haversine(cand.lat, cand.lon, o_lat, o_lon)
            if dist > radius:
                continue
            key = (osm.get("type"), osm.get("id"))
            if key in seen:
                continue
            seen.add(key)
            tags = osm.get("tags") or {}
            matches.append({
                "osm_id": osm.get("id"),
                "osm_type": osm.get("type"),
                "osm_street": tags.get("addr:street") or "",
                "osm_housenumber": tags.get("addr:housenumber") or "",
                "dist_m": round(dist, 2),
            })
        if not matches:
            return Verdict(status="PASS", reason_code="no_nearby_mismatch")
        matches.sort(key=lambda m: m["dist_m"])
        return Verdict(
            status="FLAG",
            severity="warn",
            reason_code="nearby_street_mismatch",
            details={
                "matches": matches[:5],
                "count": len(matches),
                "radius_m": radius,
            },
        )
