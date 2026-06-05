"""Monthly maintenance: import addresses the City feed has gained, and surface
ones it has lost as editor deep-links for a human to delete.

The City of Toronto address feed updates ~daily, but the genuinely new/retired
civic points are a handful per day citywide (the rest of the daily row churn is
internal centreline metadata that never reaches OSM). So instead of re-running
the whole tile pipeline, this tool tracks a **watermark snapshot** and, each
month, processes only what changed since:

  * **Additions** — points whose first appearance is after the watermark. These
    ride the existing conflate → checks → review → upload pipeline, conflated
    against *live* Overpass (the working set is tiny, so no local extract is
    needed). Conflation auto-dedups anything already in OSM.

  * **Retirements** — points that dropped out of the feed. These are NOT
    auto-deleted (feed silence is weak evidence — see README "Out of scope").
    Each is matched to the live OSM element carrying that address, its edit
    history is pulled for provenance, and the operator gets JOSM/iD/OSM links
    to delete it by hand if warranted.

The watermark only advances when the operator confirms it (after uploading the
month's additions), so a skipped or aborted month loses nothing.
"""
from __future__ import annotations

import argparse
import json
import sys

from . import (
    candidates,
    conflate as _conflate,
    config as _config,
    db as _db,
    osm_fetch,
    osm_history,
    pipeline,
    source_db,
)

WATERMARK_KEY = "maintenance.watermark_snapshot"
# Snapshot the citywide import (Phases 1-3) finished against, 2026-05-28.
# The first maintenance run reaches back to here; anything already in OSM is
# auto-skipped by conflation, so an over-broad initial watermark is harmless.
DEFAULT_WATERMARK = 52

_OSM_WEB = "https://www.openstreetmap.org"
_JOSM_RC = "http://127.0.0.1:8111"
_TYPE_PREFIX = {"node": "n", "way": "w", "relation": "r"}

# Per-process cache of the retirement analysis (keyed by run_id + cache mtime)
# so repeated page loads don't re-hit the OSM history API.
_RETIRE_CACHE: dict[int, tuple[float, dict]] = {}


# ---- watermark (stored in tool.db kv) -------------------------------------

def get_watermark() -> int:
    conn = _db.connect()
    try:
        row = conn.execute("SELECT value FROM kv WHERE key = ?", (WATERMARK_KEY,)).fetchone()
    finally:
        conn.close()
    if row and row["value"] is not None:
        try:
            return int(row["value"])
        except (ValueError, TypeError):
            pass
    return DEFAULT_WATERMARK


def set_watermark(snapshot_id: int) -> None:
    conn = _db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (WATERMARK_KEY, str(snapshot_id)),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _around_radius() -> float:
    """Overpass `around` radius for the delta query. Must cover the conflation
    match radius so additions can still match an OSM neighbour just outside the
    point, with the same halo margin the bbox fetch uses."""
    cfg = _config.load()
    return max(cfg.match_radius_m * osm_fetch.HALO_MARGIN, 150.0)


# ---- delta (source-only, cheap) -------------------------------------------

def _address_class(row: dict) -> str | None:
    try:
        return (json.loads(row["extra"]) if row.get("extra") else {}).get("ADDRESS_CLASS_DESC")
    except (ValueError, TypeError):
        return None


def compute_delta(watermark: int | None = None) -> dict:
    """Source-side counts/lists of what changed since the watermark. No network."""
    if watermark is None:
        watermark = get_watermark()
    latest = source_db.latest_snapshot_id()
    new_rows = list(source_db.iter_new_since(watermark, latest))
    retired_rows = list(source_db.iter_retired_since(watermark, latest))
    return {
        "watermark": watermark,
        "latest_snapshot": latest,
        "new_rows": new_rows,
        "retired_rows": retired_rows,
        "new_count": len(new_rows),
        "retired_count": len(retired_rows),
    }


def run_name_for(latest_snapshot: int) -> str:
    return f"maint-snap{latest_snapshot}"


def find_run(latest_snapshot: int | None = None) -> dict | None:
    """The maintenance run for the given (default latest) snapshot, if prepared."""
    if latest_snapshot is None:
        latest_snapshot = source_db.latest_snapshot_id()
    name = run_name_for(latest_snapshot)
    conn = _db.connect()
    try:
        row = conn.execute("SELECT * FROM runs WHERE name = ?", (name,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


# ---- prepare (additions through the pipeline) -----------------------------

def prepare(watermark: int | None = None) -> dict:
    """Ingest additions since the watermark and run them through conflate +
    checks against live OSM. Idempotent: re-running resumes the same run."""
    delta = compute_delta(watermark)
    latest = delta["latest_snapshot"]
    cfg = _config.load()

    run_id = pipeline.start_run(run_name_for(latest), cfg.osm_toronto_bbox)
    inserted = candidates.ingest_rows(run_id, delta["new_rows"])

    # One live Overpass query covers additions (to conflate) and retirements
    # (to locate the OSM element). conflate only looks near the new points;
    # extra elements around retired points are harmless.
    points = [
        (r["latitude"], r["longitude"])
        for r in (delta["new_rows"] + delta["retired_rows"])
        if r.get("latitude") is not None and r.get("longitude") is not None
    ]
    _path, digest = osm_fetch.fetch_around(run_id, points, _around_radius(), force=True)
    _conflate.run(run_id, digest, cfg.match_radius_m, cfg.match_near_m)
    pipeline.run_checks(run_id)

    _RETIRE_CACHE.pop(run_id, None)
    counts = candidates.count_by_stage(run_id)
    return {
        "run_id": run_id,
        "run_name": run_name_for(latest),
        "watermark": delta["watermark"],
        "latest_snapshot": latest,
        "inserted": inserted,
        "stage_counts": counts,
        "retired_count": delta["retired_count"],
    }


# ---- retirements (provenance + editor links) ------------------------------

def _josm_zoom_url(osm_type: str, osm_id: int, lat: float, lon: float) -> str:
    d = 0.0008  # ~90 m half-box so the element sits comfortably in view
    sel = f"{osm_type}{osm_id}"
    return (
        f"{_JOSM_RC}/load_and_zoom?left={lon - d:.6f}&right={lon + d:.6f}"
        f"&top={lat + d:.6f}&bottom={lat - d:.6f}&select={sel}"
    )


def _links(osm_type: str, osm_id: int, lat: float | None, lon: float | None) -> dict:
    out = {
        "id": f"{_OSM_WEB}/edit?editor=id&{osm_type}={osm_id}",
        "browse": f"{_OSM_WEB}/{osm_type}/{osm_id}",
    }
    if lat is not None and lon is not None:
        out["josm"] = _josm_zoom_url(osm_type, osm_id, lat, lon)
    return out


def _retire_street_norm(row: dict) -> str:
    from .conflate import apply_street_override, expand_street_name, normalize_street
    raw = expand_street_name(apply_street_override(candidates._street_from_row(row)))
    return normalize_street(raw)


def _match_osm_elements(row: dict, match_idx, poi_idx, radius_m: float) -> list[dict]:
    """OSM elements at the retired address (same normalized number + street,
    within radius). Returns lightweight descriptors; provenance is fetched by
    the caller so it can be cached/limited."""
    lat, lon = row.get("latitude"), row.get("longitude")
    if lat is None or lon is None:
        return []
    num = (row.get("address_number") or "").strip().upper()
    street = _retire_street_norm(row)
    if not num or not street:
        return []
    out: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for idx in (match_idx, poi_idx):
        for o_lat, o_lon, el in idx.query(lat, lon):
            if _conflate.haversine(lat, lon, o_lat, o_lon) > radius_m:
                continue
            if el.get("_norm_number") != num or el.get("_norm_street") != street:
                continue
            key = (el.get("type"), el.get("id"))
            if key in seen:
                continue
            seen.add(key)
            out.append({"type": el["type"], "id": el["id"], "lat": o_lat, "lon": o_lon})
    return out


# Most-cautious-first ranking; the retirement row's badge takes the max over
# its non-feature matches (an address node we'd actually consider deleting).
_VERDICT_RANK = {
    "already_deleted": 0,
    "pristine_ours": 1,
    "community_touched": 2,
    "community_node": 3,
    "unknown": 4,
}


def retirements(run_id: int) -> dict:
    """Match each retired point to live OSM, attach provenance, build links.

    Cached per (run_id, OSM-cache mtime). Reads the run's cached Overpass
    elements — so call after :func:`prepare`."""
    cfg = _config.load()
    path = cfg.data_dir / f"osm_current_run{run_id}.json"
    mtime = path.stat().st_mtime if path.exists() else 0.0
    cached = _RETIRE_CACHE.get(run_id)
    if cached and cached[0] == mtime:
        return cached[1]

    watermark = get_watermark()
    retired_rows = list(source_db.iter_retired_since(watermark))
    elements = osm_fetch.load_cached(run_id)
    match_idx, poi_idx = _conflate.build_osm_index(elements)
    radius = cfg.match_radius_m

    rows: list[dict] = []
    summary = {"safe": 0, "caution": 0, "feature": 0, "no_match": 0}
    safe_objects: list[str] = []
    for r in retired_rows:
        descriptors = _match_osm_elements(r, match_idx, poi_idx, radius)
        matches = []
        for d in descriptors:
            prov = osm_history.analyze(d["type"], d["id"])
            matches.append({
                **d,
                "provenance": prov,
                "links": _links(d["type"], d["id"], d["lat"], d["lon"]),
            })

        non_feature = [m for m in matches if not m["provenance"].get("is_feature")]
        if not matches:
            row_verdict = "no_match"
            summary["no_match"] += 1
        elif non_feature:
            row_verdict = max(
                (m["provenance"]["verdict"] for m in non_feature),
                key=lambda v: _VERDICT_RANK.get(v, 4),
            )
            if row_verdict == "pristine_ours":
                summary["safe"] += 1
                safe_objects += [
                    f"{_TYPE_PREFIX[m['type']]}{m['id']}"
                    for m in non_feature
                    if m["provenance"]["verdict"] == "pristine_ours"
                ]
            else:
                summary["caution"] += 1
        else:
            row_verdict = "keep_feature"
            summary["feature"] += 1

        rows.append({
            "address_full": r.get("address_full"),
            "address_class": _address_class(r),
            "last_snapshot_id": r.get("last_snapshot_id"),
            "lat": r.get("latitude"),
            "lon": r.get("longitude"),
            "verdict": row_verdict,
            "matches": matches,
        })

    josm_all = (
        f"{_JOSM_RC}/load_object?objects=" + ",".join(safe_objects)
        if safe_objects else None
    )
    result = {
        "rows": rows,
        "summary": summary,
        "total": len(rows),
        "josm_open_all_safe": josm_all,
        "safe_object_count": len(safe_objects),
    }
    _RETIRE_CACHE[run_id] = (mtime, result)
    return result


def advance_watermark(latest_snapshot: int | None = None) -> int:
    """Move the watermark forward to the processed snapshot. Call after the
    month's additions are uploaded. Returns the new watermark."""
    if latest_snapshot is None:
        latest_snapshot = source_db.latest_snapshot_id()
    set_watermark(latest_snapshot)
    return latest_snapshot


# ---- CLI ------------------------------------------------------------------

def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Monthly Toronto address maintenance delta.")
    p.add_argument("--prepare", action="store_true",
                   help="Ingest + conflate additions (default: just print the delta).")
    p.add_argument("--watermark", type=int, default=None,
                   help="Override the watermark snapshot for this invocation.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    delta = compute_delta(args.watermark)
    print(f"watermark snapshot: {delta['watermark']}")
    print(f"latest snapshot:    {delta['latest_snapshot']}")
    print(f"new since watermark:     {delta['new_count']}")
    print(f"retired since watermark: {delta['retired_count']}")
    for r in delta["new_rows"]:
        print(f"  + {r['address_full']}")
    for r in delta["retired_rows"]:
        print(f"  - {r['address_full']} (last seen snap {r['last_snapshot_id']})")
    if args.prepare:
        print("\npreparing additions run...")
        res = prepare(args.watermark)
        print(f"run #{res['run_id']} ({res['run_name']}): inserted {res['inserted']}")
        print(f"stage counts: {res['stage_counts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
