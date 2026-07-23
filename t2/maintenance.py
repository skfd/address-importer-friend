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
from concurrent.futures import ThreadPoolExecutor

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
WATERMARK_DATE_KEY = "maintenance.watermark_date"
# Snapshot the citywide import had *finished uploading* against (2026-05-28).
# NOTE: this is the upload-completion snapshot, NOT the snapshot the import data
# was pulled from (that was IMPORT_SOURCE_SNAPSHOT=45, 2026-05-15). Defaulting
# the watermark here instead of 45 left additions that first appeared in (45,52]
# unprocessed by both the import and maintenance — 31 of them, swept up by a
# one-off `maint-catchup-snap45-56` run (2026-06-06). Conflation auto-skips
# anything already in OSM, so the safe choice for an initial watermark is the
# import *source* snapshot, not where uploads happened to finish.
# Snapshot IDs are per-database. When the source moved from the retired
# addresses.db to ontario-address-changes' toronto.db, 2026-05-28 went from id 52
# to id 54 — translated by date, never carried across as a number.
DEFAULT_WATERMARK = 54

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
    # Persist the watermark's feed date alongside the id. Snapshot ids are
    # per-database, so a future source swap must re-resolve the id by this date
    # rather than carry the integer across (see the addresses.db -> toronto.db
    # move, where the same date shifted id).
    wm_date = source_db.snapshot_date(snapshot_id)
    conn = _db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (WATERMARK_KEY, str(snapshot_id)),
        )
        if wm_date is not None:
            conn.execute(
                "INSERT INTO kv (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (WATERMARK_DATE_KEY, wm_date),
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


# Monthly runs are named `maint-snap{N}`; one-off catch-ups use other `maint-*`
# names (e.g. `maint-catchup-snap45-56`). Both are maintenance runs — the
# interface lists every `maint-*` run, not just the monthly ones.
_RUN_PREFIX = "maint-snap"
_MAINT_NAME_LIKE = "maint-%"


def run_name_for(latest_snapshot: int) -> str:
    return f"{_RUN_PREFIX}{latest_snapshot}"


# ---- maintenance-run window (persisted in runs.config_json) ----------------
# A maintenance run covers the snapshot window (from_snapshot, to_snapshot]. We
# store it on the run rather than infer it from the name, so a back-dated
# catch-up window survives and retirements can be scoped to exactly what the run
# processed. config_json otherwise only holds checks params, so adding a key is
# safe (readers use .get).

def set_run_window(run_id: int, from_snapshot: int, to_snapshot: int) -> None:
    conn = _db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT config_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
        cfg_obj = json.loads(row["config_json"]) if row and row["config_json"] else {}
        cfg_obj["maintenance"] = {"from_snapshot": from_snapshot, "to_snapshot": to_snapshot}
        conn.execute("UPDATE runs SET config_json=? WHERE run_id=?", (json.dumps(cfg_obj), run_id))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def get_run_window(run_id: int) -> dict | None:
    """The (from_snapshot, to_snapshot] this maintenance run processed, or None
    if not a window-tagged run."""
    conn = _db.connect()
    try:
        row = conn.execute(
            "SELECT config_json, source_snapshot_id FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    cfg_obj = json.loads(row["config_json"]) if row["config_json"] else {}
    m = cfg_obj.get("maintenance")
    if m and m.get("from_snapshot") is not None and m.get("to_snapshot") is not None:
        return {"from_snapshot": int(m["from_snapshot"]), "to_snapshot": int(m["to_snapshot"])}
    # Fallback for any maintenance run created before windows were persisted.
    return {"from_snapshot": DEFAULT_WATERMARK, "to_snapshot": int(row["source_snapshot_id"])}


# Source snapshots the one-time citywide import was actually built from: the
# pilot tile on 2026-05-12, then the 1,297 citywide runs on 2026-05-15. OSM
# uploads ran 2026-05-13..2026-05-28 at human review cadence. Distinct from
# DEFAULT_WATERMARK (2026-05-28) above, which is only where maintenance starts
# looking for deltas — not the date the import data was pulled.
# IDs are toronto.db's (2026-05-12=44, 2026-05-15=47); they were 42/45 in the
# retired addresses.db — translated by date on the source swap.
IMPORT_SOURCE_SNAPSHOT = 47
IMPORT_PILOT_SNAPSHOT = 44


def import_baseline() -> dict:
    """The source snapshots the one-time citywide import was built from (the
    pilot, then the citywide pass) and the maintenance watermark, each with its
    feed-publication date. Drives the "Original import" rows on the page."""
    wm = get_watermark()
    return {
        "snapshot": IMPORT_SOURCE_SNAPSHOT,
        "date": source_db.snapshot_date(IMPORT_SOURCE_SNAPSHOT),
        "pilot_snapshot": IMPORT_PILOT_SNAPSHOT,
        "pilot_date": source_db.snapshot_date(IMPORT_PILOT_SNAPSHOT),
        "watermark": wm,
        "watermark_date": source_db.snapshot_date(wm),
    }


def history() -> list[dict]:
    """One summary row per maintenance run (monthly + catch-up), newest first.

    Each run carries its processed window (from_snapshot, to_snapshot]; new/
    retired counts are reconstructed from the source feed for that window, and
    `uploaded` is the run's candidates that actually reached OSM. The window is
    read from the run (see :func:`get_run_window`), so a back-dated catch-up
    sorts and dates correctly alongside the monthly runs."""
    conn = _db.connect()
    try:
        rows = conn.execute(
            "SELECT run_id, name, source_snapshot_id, config_json, "
            "upload_status, changeset_id, uploaded_at "
            "FROM runs WHERE name LIKE ?",
            (_MAINT_NAME_LIKE,),
        ).fetchall()
    finally:
        conn.close()

    out: list[dict] = []
    for row in rows:
        r = dict(row)
        cfg_obj = json.loads(r["config_json"]) if r["config_json"] else {}
        m = cfg_obj.get("maintenance") or {}
        frm = int(m.get("from_snapshot", DEFAULT_WATERMARK))
        to = int(m.get("to_snapshot", r["source_snapshot_id"]))
        r.update(
            from_snapshot=frm,
            to_snapshot=to,
            from_date=source_db.snapshot_date(frm),
            to_date=source_db.snapshot_date(to),
            new_count=sum(1 for _ in source_db.iter_new_since(frm, to)),
            retired_count=sum(1 for _ in source_db.iter_retired_since(frm, to)),
            uploaded_count=candidates.count_by_stage(r["run_id"]).get("UPLOADED", 0),
            is_catchup=not r["name"].startswith(_RUN_PREFIX),
        )
        out.append(r)
    out.sort(key=lambda r: (r["to_snapshot"], r["run_id"]), reverse=True)  # newest first
    return out


def get_run(run_id: int) -> dict | None:
    """Full run row for a maintenance run_id, or None."""
    conn = _db.connect()
    try:
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def find_run(latest_snapshot: int | None = None) -> dict | None:
    """The monthly maintenance run for the given (default latest) snapshot, if
    prepared. Used to gate the "prepare monthly run" button — catch-ups don't
    count."""
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

def prepare(watermark: int | None = None, run_name: str | None = None) -> dict:
    """Ingest additions since the watermark and run them through conflate +
    checks against live OSM. Idempotent: re-running resumes the same run.

    ``run_name`` overrides the default ``maint-snap{latest}`` name — used for a
    one-off catch-up over a back-dated watermark so it doesn't reopen the normal
    monthly run for the current snapshot."""
    delta = compute_delta(watermark)
    latest = delta["latest_snapshot"]
    cfg = _config.load()
    name = run_name or run_name_for(latest)

    run_id = pipeline.start_run(name, cfg.osm_toronto_bbox)
    set_run_window(run_id, delta["watermark"], latest)
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
        "run_name": name,
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

    Scoped to the run's own window (see :func:`get_run_window`) so a back-dated
    catch-up surfaces the retirements it actually covered, not the live one.
    Cached per (run_id, OSM-cache mtime). Reads the run's cached Overpass
    elements — so call after :func:`prepare`."""
    cfg = _config.load()
    path = cfg.data_dir / f"osm_current_run{run_id}.json"
    mtime = path.stat().st_mtime if path.exists() else 0.0
    cached = _RETIRE_CACHE.get(run_id)
    if cached and cached[0] == mtime:
        return cached[1]

    window = get_run_window(run_id) or {"from_snapshot": get_watermark(), "to_snapshot": None}
    retired_rows = list(source_db.iter_retired_since(window["from_snapshot"], window["to_snapshot"]))
    elements = osm_fetch.load_cached(run_id)
    match_idx, poi_idx = _conflate.build_osm_index(elements)
    radius = cfg.match_radius_m

    # Match each retired row to OSM elements first (local, cheap), then fetch
    # every element's history concurrently — analyze() is one serial HTTP round
    # trip to the live OSM API each, so a serial loop is what made the page slow.
    row_descriptors = [(r, _match_osm_elements(r, match_idx, poi_idx, radius)) for r in retired_rows]
    unique: dict[tuple[str, int], dict] = {}
    for _r, descs in row_descriptors:
        for d in descs:
            unique[(d["type"], d["id"])] = d
    prov_by_key: dict[tuple[str, int], dict] = {}
    if unique:
        keys = list(unique)
        with ThreadPoolExecutor(max_workers=min(8, len(keys))) as ex:
            prov_by_key = dict(zip(keys, ex.map(lambda k: osm_history.analyze(*k), keys)))

    rows: list[dict] = []
    summary = {"safe": 0, "caution": 0, "feature": 0, "no_match": 0}
    safe_objects: list[str] = []
    for r, descriptors in row_descriptors:
        matches = [{
            **d,
            "provenance": prov_by_key[(d["type"], d["id"])],
            "links": _links(d["type"], d["id"], d["lat"], d["lon"]),
        } for d in descriptors]

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
