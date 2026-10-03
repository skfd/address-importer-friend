"""Re-check not-yet-uploaded MISSING candidates against addressed areas.

Conflation before 63f641da measured an area from its centre and dropped it
past the match radius, so a point inside a park or school that carries the
address read MISSING. Conflation only processes INGESTED rows, so existing
runs keep the old verdict; this re-runs `_classify` for the candidates that
could have been affected and moves the ones that now match:

  MATCH      -> stage SKIPPED, open review item dropped (as the checks stage does)
  MATCH_FAR  -> stage REVIEW_PENDING, review item gains `match_far`

Only runs that have not uploaded, only MISSING candidates at APPROVED or
REVIEW_PENDING, and never one an operator has already decided. Dry run unless
--apply.

    python scripts/reconflate_areas.py --city-dir ../guelph-address-import [--prod] [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--city-dir", required=True)
ap.add_argument("--prod", action="store_true")
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

os.environ["T2_CITY_DIR"] = str(Path(args.city_dir).resolve())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import t2.config  # noqa: E402
if args.prod:
    t2.config.OSM_ENV = "prod"
cfg = t2.config.load()
from t2 import audit, conflate, db, osm_fetch, tag_diff  # noqa: E402

now = datetime.now(timezone.utc).isoformat()
conn = db.connect()
runs = [r["run_id"] for r in conn.execute(
    "SELECT run_id FROM runs WHERE upload_status IS NULL OR upload_status = '' ORDER BY run_id")]
moved = {"MATCH": [], "MATCH_FAR": []}
for run_id in runs:
    rows = conn.execute(
        """
        SELECT c.candidate_id, c.housenumber, c.street_norm, c.street_raw, c.lat, c.lon,
               c.unit, c.flats, c.stage, r.status AS review_status, r.reason_code
          FROM candidates c
          JOIN conflation f USING (run_id, candidate_id)
          LEFT JOIN review_items r USING (run_id, candidate_id)
         WHERE c.run_id = ? AND f.verdict = 'MISSING'
           AND c.stage IN ('APPROVED', 'REVIEW_PENDING')
           AND (r.status IS NULL OR r.status = 'OPEN')
        """, (run_id,)).fetchall()
    if not rows:
        continue
    match_idx, poi_idx = conflate.build_osm_index(osm_fetch.load_cached(run_id))
    for r in rows:
        cand = dict(r)
        verdict, osm_id, osm_type, dist, el, _poi = conflate._classify(
            cand, match_idx, poi_idx, cfg.match_radius_m, cfg.match_near_m)
        if verdict not in moved:
            continue
        name = (el.get("tags") or {}).get("name") or ""
        moved[verdict].append((run_id, cand["candidate_id"], cand["housenumber"], cand["street_raw"],
                               cand["stage"], f"{osm_type}/{osm_id}", round(dist), name))
        if not args.apply:
            continue
        m_lat, m_lon = conflate._matched_latlon(el)
        with db.tx(conn):
            conn.execute(
                """UPDATE conflation SET verdict=?, nearest_osm_id=?, nearest_osm_type=?, nearest_dist_m=?,
                          matched_osm_tags_json=?, matched_osm_geom_hint=?, matched_osm_lat=?, matched_osm_lon=?,
                          computed_at=?
                    WHERE run_id=? AND candidate_id=?""",
                (verdict, osm_id, osm_type, dist, json.dumps(el.get("tags") or {}),
                 tag_diff.geom_hint(el), m_lat, m_lon, now, run_id, cand["candidate_id"]))
            if verdict == "MATCH":
                conn.execute("UPDATE candidates SET stage='SKIPPED', stage_updated_at=? "
                             "WHERE run_id=? AND candidate_id=?", (now, run_id, cand["candidate_id"]))
                conn.execute("DELETE FROM review_items WHERE run_id=? AND candidate_id=? AND status='OPEN'",
                             (run_id, cand["candidate_id"]))
            else:
                reasons = sorted(set(filter(None, (cand["reason_code"] or "").split(","))) | {"match_far"})
                conn.execute(
                    """INSERT INTO review_items (run_id, candidate_id, reason_code, status, opened_at)
                       VALUES (?, ?, ?, 'OPEN', ?)
                       ON CONFLICT(run_id, candidate_id) DO UPDATE SET reason_code = excluded.reason_code""",
                    (run_id, cand["candidate_id"], ",".join(reasons), now))
                conn.execute("UPDATE candidates SET stage='REVIEW_PENDING', stage_updated_at=? "
                             "WHERE run_id=? AND candidate_id=?", (now, run_id, cand["candidate_id"]))
            audit.log(actor="pipeline", event_type="RECONFLATED_AREA", run_id=run_id,
                      candidate_id=cand["candidate_id"],
                      payload={"verdict": verdict, "osm": f"{osm_type}/{osm_id}", "dist_m": dist},
                      conn=conn)

for verdict, items in moved.items():
    print(f"{verdict}: {len(items)}" + ("" if args.apply else " (dry run)"))
    for it in items:
        print("  ", it)
