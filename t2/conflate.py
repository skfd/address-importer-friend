"""Stage 3: conflate candidates against cached OSM snapshot, write verdicts to DB.

Core helpers (normalize_street, GridIndex, haversine) preserved from sibling
project's src/conflate.py — the algorithmic contract there is proven.
"""
import json
import math
from collections import defaultdict
from datetime import datetime, timezone

from . import audit, db as _db, osm_fetch
from .osm_export import STATIC_TAGS

STREET_SUFFIXES = {
    "STREET": "ST", "ROAD": "RD", "AVENUE": "AVE", "BOULEVARD": "BLVD",
    "DRIVE": "DR", "LANE": "LN", "COURT": "CT", "PLACE": "PL",
    "TERRACE": "TER", "CRESCENT": "CRES", "SQUARE": "SQ", "GATE": "GTE",
    "CIRCLE": "CIR", "WAY": "WAY", "TRAIL": "TRL", "PARKWAY": "PKWY",
    "HIGHWAY": "HWY", "EXPRESSWAY": "EXPY",
    "CRT": "CT", "CRCL": "CIR", "GT": "GTE",
    "GARDENS": "GDNS", "GROVE": "GRV", "HEIGHTS": "HTS",
    "PATHWAY": "PTWY", "CIRCUIT": "CRCT", "BRIDGE": "BDGE", "LAWN": "LWN",
    "PARK": "PK", "ROADWAY": "RDWY", "CLOSE": "CS", "WOODS": "WDS",
    "GREEN": "GRN",
}
DIRS = {"NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W"}

# Short → full mapping for upload. The City source emits short suffix and
# direction tokens ("Foo Ave W"), but OSM Toronto convention is the full
# form ("Foo Avenue West"). expand_street_name() applies this at ingest so
# both the review-page display and the uploaded addr:street tag carry the
# full form. Multiple shorts pointing to the same long form (CRT and CT both
# → Court) are listed because the City source actually emits both spellings.
STREET_SUFFIX_EXPAND: dict[str, str] = {
    "ST": "Street", "RD": "Road", "AVE": "Avenue", "BLVD": "Boulevard",
    "DR": "Drive", "LN": "Lane", "CT": "Court", "CRT": "Court",
    "PL": "Place", "TER": "Terrace", "CRES": "Crescent", "SQ": "Square",
    "GTE": "Gate", "GT": "Gate", "CIR": "Circle", "CRCL": "Circle",
    "TRL": "Trail", "PKWY": "Parkway", "HWY": "Highway", "EXPY": "Expressway",
    "GDNS": "Gardens", "GRV": "Grove", "HTS": "Heights",
    "PTWY": "Pathway", "CRCT": "Circuit", "BDGE": "Bridge", "LWN": "Lawn",
    "PK": "Park", "RDWY": "Roadway", "CS": "Close", "WDS": "Woods",
    "GRN": "Green",
}

DIRS_EXPAND: dict[str, str] = {"N": "North", "S": "South", "E": "East", "W": "West"}


def expand_street_name(name: str | None) -> str | None:
    """Rewrite the trailing direction and suffix tokens of `name` from the
    City source's short form to the OSM full form ("Foo Ave W" → "Foo Avenue
    West"). Only the last token (direction) and the token immediately before
    it (suffix) are touched. Earlier tokens — including a leading "St "
    standing for "Saint" in names like "St Clair Ave E" — are preserved
    verbatim. A standalone "Mc" token followed by an alphabetic word is
    glued back into a single surname token ("Mc Caul St" → "McCaul St"),
    matching OSM Toronto's convention. Empty/None passes through.
    """
    if not name:
        return name
    parts = _glue_mc_prefix(name.split())
    if not parts:
        return name
    i = len(parts) - 1
    last_key = parts[i].upper().replace(".", "")
    if last_key in DIRS_EXPAND:
        parts[i] = DIRS_EXPAND[last_key]
        i -= 1
    if i >= 0:
        sfx_key = parts[i].upper().replace(".", "")
        if sfx_key in STREET_SUFFIX_EXPAND:
            parts[i] = STREET_SUFFIX_EXPAND[sfx_key]
    return " ".join(parts)


def _glue_mc_prefix(parts: list[str]) -> list[str]:
    """Collapse `["Mc", "Caul"]` → `["McCaul"]` for surname-prefix tokens.
    Only fires when the next token is alphabetic and not a known
    suffix/direction, so names like "Mc Way" (hypothetical) or "Mc West"
    are left alone. The next token's case is preserved, so "Mc caul" stays
    "Mccaul" and "Mc Caul" becomes "McCaul" — we don't re-case the
    surname.
    """
    out: list[str] = []
    i = 0
    while i < len(parts):
        tok = parts[i]
        key = tok.upper().replace(".", "")
        if (
            key == "MC"
            and i + 1 < len(parts)
            and parts[i + 1].isalpha()
        ):
            nxt_key = parts[i + 1].upper()
            if (
                nxt_key not in STREET_SUFFIXES
                and nxt_key not in STREET_SUFFIX_EXPAND
                and nxt_key not in DIRS
                and nxt_key not in DIRS_EXPAND
            ):
                out.append("Mc" + parts[i + 1])
                i += 2
                continue
        out.append(tok)
        i += 1
    return out

# Hardcoded source-name -> OSM-canonical-name overrides for known street
# names where the City source and OSM disagree on the actual name. Two
# shapes show up in practice:
#   - proper-noun spacing differences the normalizer can't bridge
#     (source "Deane Field Cres" vs OSM "Deanefield Crescent"), and
#   - outright suffix corrections where the source has the street type
#     wrong (source "Kathleen Ave" sits on what OSM and signage call
#     "Kathleen Crescent").
# Applied at ingest, so the candidate's street_raw and street_norm — and
# therefore both conflation matching and the uploaded addr:street tag —
# carry the OSM name local mappers already know. Override values keep the
# source's short suffixes (Rd / Cres / …) so the lookup matches the source
# spelling; expand_street_name() runs after the override and rewrites those
# shorts to the OSM full form. Lookup is case- and whitespace-insensitive on
# the source's `linear_name_full` value. Each entry is a candidate for
# retirement once the source and OSM converge; the `nearby_street_mismatch`
# review check surfaces fresh candidates for inclusion.
STREET_NAME_OVERRIDES: dict[str, str] = {
    "Deane Field Cres": "Deanefield Cres",
    "Golfcrest Rd": "Golf Crest Rd",
    "Forest View Rd": "Forestview Rd",
    "Greenhouse Rd": "Green House Rd",
    "Kathleen Ave": "Kathleen Cres",
    "Posthorn Grv": "Post Horn Grv",
}

_STREET_NAME_OVERRIDES_LOOKUP: dict[str, str] = {
    " ".join(k.upper().split()): v for k, v in STREET_NAME_OVERRIDES.items()
}


def apply_street_override(name: str | None) -> str | None:
    """Return the OSM-canonical street name when `name` is a known source
    spelling variant from `STREET_NAME_OVERRIDES`; otherwise return `name`
    unchanged. Empty/None passes through. Lookup is case-insensitive on
    the whitespace-collapsed input."""
    if not name:
        return name
    key = " ".join(name.upper().split())
    return _STREET_NAME_OVERRIDES_LOOKUP.get(key, name)


def normalize_street(name: str | None) -> str:
    if not name:
        return ""
    out = []
    for p in name.upper().replace(".", "").split():
        if p in STREET_SUFFIXES:
            out.append(STREET_SUFFIXES[p])
        elif p in DIRS:
            out.append(DIRS[p])
        else:
            out.append(p)
    return " ".join(out)


class GridIndex:
    def __init__(self, cell_size_deg: float = 0.002):
        self.grid: dict[tuple[int, int], list[tuple[float, float, dict]]] = defaultdict(list)
        self.cell_size = cell_size_deg

    def _key(self, lat: float, lon: float) -> tuple[int, int]:
        return (int(lat / self.cell_size), int(lon / self.cell_size))

    def add(self, item: dict, lat: float, lon: float) -> None:
        self.grid[self._key(lat, lon)].append((lat, lon, item))

    def query(self, lat: float, lon: float) -> list[tuple[float, float, dict]]:
        ck = self._key(lat, lon)
        out: list[tuple[float, float, dict]] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                out.extend(self.grid[(ck[0] + dx, ck[1] + dy)])
        return out


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


POI_TAG_KEYS = (
    "amenity", "shop", "office", "tourism", "leisure", "craft", "healthcare", "building",
    "disused:shop", "disused:amenity", "disused:office", "was:amenity",
)


def _is_poi_node(el: dict) -> bool:
    """A POI node is a node that carries shop/amenity/etc. tags — its address is
    a courtesy annotation, not the canonical address feature. Polygons are never
    POI-filtered: a hospital or building polygon with addr:* is a valid match.

    `entrance=*` is intentionally NOT in POI_TAG_KEYS: an entrance node with
    addr:* is a canonical address (just door-level rather than parcel-level)
    and must remain a valid match target. See IMPORT_PROPOSAL.md §6.
    """
    if el.get("type") != "node":
        return False
    tags = el.get("tags") or {}
    return any(k in tags for k in POI_TAG_KEYS)


def build_osm_index(elements: list[dict]) -> tuple[GridIndex, GridIndex]:
    """Return (match_idx, poi_idx).

    match_idx holds pure-address nodes (including entrance=* nodes that carry
    addr:*) and polygons — valid conflation targets. poi_idx holds
    amenity/shop/etc. nodes, acknowledged but ignored for matching.
    Nodes that are members of an addr:interpolation way are dropped entirely:
    they're endpoints of an interpolated range, not standalone addresses.
    """
    interp_node_ids: set[int] = set()
    for el in elements:
        if el.get("type") != "way":
            continue
        if "addr:interpolation" not in (el.get("tags") or {}):
            continue
        for nid in el.get("nodes") or ():
            interp_node_ids.add(nid)

    match_idx = GridIndex()
    poi_idx = GridIndex()
    for el in elements:
        tags = el.get("tags") or {}
        if "addr:housenumber" not in tags:
            continue
        if el.get("type") == "node":
            if el.get("id") in interp_node_ids:
                continue
            lat, lon = el.get("lat"), el.get("lon")
        elif "center" in el:
            lat = el["center"].get("lat")
            lon = el["center"].get("lon")
        else:
            lat = lon = None
        if lat is None or lon is None:
            continue
        el["_norm_street"] = normalize_street(tags.get("addr:street", ""))
        el["_norm_number"] = str(tags.get("addr:housenumber", "")).upper()
        target = poi_idx if _is_poi_node(el) else match_idx
        target.add(el, float(lat), float(lon))
    return match_idx, poi_idx


def _classify(
    cand_row: dict,
    match_idx: GridIndex,
    poi_idx: GridIndex,
    match_radius_m: float,
    match_near_m: float,
):
    """Return (verdict, osm_id, osm_type, dist_m, matched_osm_el, poi_el).

    Scans match_idx within match_radius_m for an OSM address with the same
    normalized housenumber + street. Nearest match within match_near_m = MATCH;
    beyond that = MATCH_FAR (operator review). No match → MISSING, plus a
    same-address POI node from poi_idx (if any) attached as acknowledgment.
    """
    c_lat, c_lon = cand_row["lat"], cand_row["lon"]
    if c_lat is None or c_lon is None:
        return "MISSING", None, None, None, None, None

    c_num = (cand_row.get("housenumber") or "").upper()
    c_street_norm = cand_row.get("street_norm") or ""

    # Tiebreak on osm_id when distances are equal so equidistant candidates
    # pick deterministically — GridIndex.query order depends on dict insertion
    # and isn't stable across refactors.
    best_match: tuple[float, int, dict] | None = None
    for o_lat, o_lon, osm in match_idx.query(c_lat, c_lon):
        dist = haversine(c_lat, c_lon, o_lat, o_lon)
        if dist > match_radius_m:
            continue
        if osm["_norm_number"] == c_num and osm["_norm_street"] == c_street_norm:
            oid = osm.get("id") or 0
            if best_match is None or (dist, oid) < (best_match[0], best_match[1]):
                best_match = (dist, oid, osm)

    if best_match is not None:
        dist, _oid, el = best_match
        verdict = "MATCH" if dist <= match_near_m else "MATCH_FAR"
        return verdict, el.get("id"), el.get("type"), dist, el, None

    best_poi: tuple[float, int, dict] | None = None
    for o_lat, o_lon, poi in poi_idx.query(c_lat, c_lon):
        dist = haversine(c_lat, c_lon, o_lat, o_lon)
        if dist > match_radius_m:
            continue
        if poi["_norm_number"] == c_num and poi["_norm_street"] == c_street_norm:
            pid = poi.get("id") or 0
            if best_poi is None or (dist, pid) < (best_poi[0], best_poi[1]):
                best_poi = (dist, pid, poi)

    poi_el = best_poi[2] if best_poi else None
    return "MISSING", None, None, None, None, poi_el


def _proposed_tags(cand_row: dict, poi_tags: dict | None = None) -> dict[str, str]:
    """Build the tag dict we would propose for this candidate.

    Adds addr:postcode when cand_row has proposed_postcode (stored during
    conflation) or when poi_tags carries one, so the OSM upload includes it.
    Output matches what osm_export writes.
    """
    tags = {
        "addr:housenumber": (cand_row.get("housenumber") or "").strip(),
        "addr:street": (cand_row.get("street_raw") or "").strip(),
        **STATIC_TAGS,
    }
    postcode = (cand_row.get("proposed_postcode") or "").strip()
    if not postcode and poi_tags:
        postcode = (poi_tags.get("addr:postcode") or "").strip()
    if postcode:
        tags["addr:postcode"] = postcode
    if cand_row.get("address_class") == "Structure Entrance":
        tags["entrance"] = "yes"
    return {k: v for k, v in tags.items() if v}


def _matched_latlon(el: dict | None) -> tuple[float | None, float | None]:
    """Point location of the matched OSM element for map rendering.

    For nodes that's lat/lon; for ways/relations we fall back to Overpass's
    `center` output (build_osm_index already required one of the two).
    """
    if el is None:
        return None, None
    if el.get("type") == "node":
        return el.get("lat"), el.get("lon")
    c = el.get("center") or {}
    return c.get("lat"), c.get("lon")


def _is_range(row: dict) -> bool:
    """Return True when the candidate represents an address range (lo_num != hi_num)."""
    lo = row.get("lo_num")
    hi = row.get("hi_num")
    return lo is not None and hi is not None and lo != hi


# A non-Land candidate that shares (address_full, municipality_name) with
# any Land row in the same run is auto-skipped — the Land row is the
# canonical record. The lookup keys on municipality_name because the same
# address string recurs across former municipalities post-amalgamation
# (see SOURCE_DATA.md "Municipality trap" — e.g. "66 George St" exists in
# three of them); within one municipality the source treats one
# address_full as one civic address.

# Two Land rows at the same (address_full, municipality_name) within this
# distance are treated as a single logical record: conflation silently skips
# the non-canonical one. Beyond this threshold both rows proceed through
# conflation and the intra_source_duplicate check flags them for review.
_INTRA_DUP_AUTO_SKIP_M = 5.0


def _colocated_land_sibling(
    cand: dict, land_keys: set[tuple[str, str | None]]
) -> bool:
    if cand.get("address_class") == "Land":
        return False
    addr = cand.get("address_full")
    if not addr:
        return False
    return (addr, cand.get("municipality_name")) in land_keys


def _build_land_groups(
    conn, run_id: int
) -> dict[tuple[str, str | None], list[tuple[int, float, float]]]:
    """(address_full, municipality_name) -> [(candidate_id, lat, lon), ...].

    Ordered by candidate_id so the first entry of every group is the canonical
    (lowest-id) row. Carries candidate_id so the sibling link can be persisted
    on the conflation row.
    """
    groups: dict[tuple[str, str | None], list[tuple[int, float, float]]] = defaultdict(list)
    for r in conn.execute(
        "SELECT candidate_id, address_full, municipality_name, lat, lon "
        "FROM candidates WHERE run_id = ? AND address_class = 'Land' "
        "  AND address_full IS NOT NULL AND lat IS NOT NULL AND lon IS NOT NULL "
        "ORDER BY candidate_id",
        (run_id,),
    ):
        groups[(r["address_full"], r["municipality_name"])].append(
            (r["candidate_id"], r["lat"], r["lon"])
        )
    return groups


def _intra_dup_status(
    cand: dict,
    land_groups: dict[tuple[str, str | None], list[tuple[int, float, float]]],
) -> tuple[int, float, bool] | None:
    """Return (nearest_sibling_cid, dist_m, is_canonical) for a Land candidate
    that shares (address_full, municipality_name) with another Land row; None
    otherwise. is_canonical is True when this row's candidate_id is the
    lowest in the group (the keep-one tiebreak).
    """
    if cand.get("address_class") != "Land":
        return None
    addr, lat, lon = cand.get("address_full"), cand.get("lat"), cand.get("lon")
    if not addr or lat is None or lon is None:
        return None
    group = land_groups.get((addr, cand.get("municipality_name")), ())
    if len(group) < 2:
        return None
    siblings = [s for s in group if s[0] != cand["candidate_id"]]
    if not siblings:
        return None
    sib_cid, _, sib_dist = min(
        ((s[0], s, haversine(lat, lon, s[1], s[2])) for s in siblings),
        key=lambda t: t[2],
    )
    canonical_cid = min(s[0] for s in group)
    return sib_cid, sib_dist, cand["candidate_id"] == canonical_cid


def run(run_id: int, osm_snapshot_hash: str, match_radius_m: float, match_near_m: float) -> dict[str, int]:
    """Iterate candidates at stage INGESTED, write conflation row, advance to CONFLATED."""
    from . import tag_diff  # local import avoids an import cycle at module load

    elements = osm_fetch.load_cached(run_id)
    match_idx, poi_idx = build_osm_index(elements)
    now = datetime.now(timezone.utc).isoformat()

    counts = {"MATCH": 0, "MATCH_FAR": 0, "MISSING": 0, "SKIPPED": 0}
    conn = _db.connect()
    try:
        land_groups = _build_land_groups(conn, run_id)
        land_keys = set(land_groups.keys())

        rows = conn.execute(
            "SELECT candidate_id, address_full, housenumber, street_raw, street_norm, lat, lon, "
            "       lo_num, hi_num, address_class, municipality_name "
            "FROM candidates WHERE run_id = ? AND stage = 'INGESTED'",
            (run_id,),
        ).fetchall()

        conn.execute("BEGIN IMMEDIATE")
        for r in rows:
            cand = dict(r)

            # Same-address Land sibling detection: <5 m auto-skips the non-canonical
            # row; wider pairs persist the link for the intra_source_duplicate check.
            dup = _intra_dup_status(cand, land_groups)
            auto_skip_dup = dup is not None and dup[1] <= _INTRA_DUP_AUTO_SKIP_M and not dup[2]

            # Address ranges are skipped during conflation (kept for reference only).
            # Non-Land rows that share an address with a Land sibling are also skipped —
            # the Land row is the canonical record (see SOURCE_DATA.md).
            if _is_range(cand) or _colocated_land_sibling(cand, land_keys) or auto_skip_dup:
                verdict, osm_id, osm_type, dist, matched, poi = "SKIPPED", None, None, None, None, None
            else:
                verdict, osm_id, osm_type, dist, matched, poi = _classify(
                    cand, match_idx, poi_idx, match_radius_m, match_near_m
                )
            counts[verdict] += 1

            osm_tags = (matched.get("tags") if matched else None) or None
            geom = tag_diff.geom_hint(matched) if matched else None
            m_lat, m_lon = _matched_latlon(matched)

            poi_tags = (poi.get("tags") if poi else None) or None
            poi_postcode = (poi_tags.get("addr:postcode").strip() if poi_tags and poi_tags.get("addr:postcode") else None)

            dup_sib_cid, dup_sib_dist = (dup[0], dup[1]) if dup else (None, None)

            conn.execute(
                """
                INSERT OR REPLACE INTO conflation
                  (run_id, candidate_id, verdict, nearest_osm_id, nearest_osm_type,
                   nearest_dist_m, osm_snapshot_hash, computed_at,
                   matched_osm_tags_json, matched_osm_geom_hint,
                   matched_osm_lat, matched_osm_lon,
                   poi_osm_id, poi_osm_type, poi_tags_json, proposed_postcode,
                   dup_sibling_candidate_id, dup_sibling_dist_m)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id, cand["candidate_id"], verdict, osm_id, osm_type, dist,
                    osm_snapshot_hash, now,
                    json.dumps(osm_tags) if osm_tags else None,
                    geom, m_lat, m_lon,
                    (poi.get("id") if poi else None),
                    (poi.get("type") if poi else None),
                    json.dumps(poi_tags) if poi_tags else None,
                    poi_postcode,
                    dup_sib_cid, dup_sib_dist,
                ),
            )
            if auto_skip_dup:
                audit.log(
                    actor="pipeline", event_type="INTRA_DUP_SKIPPED",
                    run_id=run_id, candidate_id=cand["candidate_id"],
                    payload={
                        "sibling_candidate_id": dup_sib_cid,
                        "dist_m": round(dup_sib_dist, 2),
                        "canonical_candidate_id": min(
                            s[0] for s in land_groups[
                                (cand["address_full"], cand["municipality_name"])
                            ]
                        ),
                    },
                    conn=conn,
                )
            conn.execute(
                "UPDATE candidates SET stage = 'CONFLATED', stage_updated_at = ? "
                "WHERE run_id = ? AND candidate_id = ?",
                (now, run_id, cand["candidate_id"]),
            )

            cand_for_proposal = dict(cand, proposed_postcode=poi_postcode)
            proposed = _proposed_tags(cand_for_proposal)
            diff_rows = tag_diff.compare_tags(proposed, osm_tags)
            has_diff = any(row["status"] != "SAME" for row in diff_rows)
            if has_diff and verdict != "SKIPPED":
                audit.log(
                    actor="pipeline",
                    event_type="CONFLATE_CANDIDATE",
                    run_id=run_id,
                    candidate_id=cand["candidate_id"],
                    payload={
                        "verdict": verdict,
                        "osm_id": osm_id,
                        "osm_type": osm_type,
                        "geom_hint": geom,
                        "dist_m": dist,
                        "diff": diff_rows,
                    },
                    conn=conn,
                )
        audit.log(
            actor="pipeline",
            event_type="CONFLATE_DONE",
            run_id=run_id,
            payload={"counts": counts, "osm_snapshot_hash": osm_snapshot_hash},
            conn=conn,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    return counts
