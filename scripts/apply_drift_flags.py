"""Back-fill the match_number_drift check into runs that were conflated and
checked before the check existed.

It evaluates ONLY match_number_drift on each MATCH/MATCH_FAR candidate and
writes a check_results row. For a FLAG:

  - if the run is already uploaded, or the candidate is already decided
    (stage APPROVED/REJECTED/UPLOADED, or a review_item with status
    APPROVED/REJECTED), the result is recorded but the decision and stage
    are left untouched;
  - otherwise a review_item is opened (or its reason_code merged if one
    already exists) and the candidate is moved to stage REVIEW_PENDING so the
    drift flag shows in the queue.

By default only non-uploaded runs are scanned. Pass --include-uploaded to
also record results for uploaded runs (recorded-only — see above), which is
what the /drift dashboard needs to show drift across every run.

It does not re-conflate, does not touch MISSING candidates, and writes
nothing for checks other than match_number_drift. It is idempotent: a
candidate that already has a match_number_drift result is skipped, so
re-running is a fast no-op. Each run commits in its own transaction.

The check's slack_m is read from config.toml.

Usage:
    python -m scripts.apply_drift_flags --dry-run            # preview
    python -m scripts.apply_drift_flags                      # non-uploaded runs
    python -m scripts.apply_drift_flags --include-uploaded   # every run
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from t2 import audit, conflate, config as _config, db as _db, osm_fetch
from t2.checks import Candidate, CheckContext
from t2.checks.match_number_drift import MatchNumberDriftCheck

DECIDED_STAGES = ("APPROVED", "REJECTED", "UPLOADED")
DECIDED_REVIEW = ("APPROVED", "REJECTED")


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _merge_reasons(existing: str | None, new: str) -> str:
    """Comma-joined sorted unique reason codes, matching run_checks' format."""
    parts = {p for p in (existing or "").split(",") if p}
    parts.add(new)
    return ",".join(sorted(parts))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m scripts.apply_drift_flags",
        description="Back-fill match_number_drift into non-uploaded runs.",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="evaluate and report, but write nothing to tool.db",
    )
    ap.add_argument(
        "--include-uploaded", action="store_true",
        help="also scan uploaded runs (results recorded only, no review items)",
    )
    args = ap.parse_args(argv)

    cfg = _config.load()
    check = MatchNumberDriftCheck()
    cv = check.version

    conn = _db.connect()
    if args.include_uploaded:
        runs = conn.execute(
            "SELECT run_id, name, upload_status FROM runs ORDER BY run_id"
        ).fetchall()
        scope = "all"
    else:
        runs = conn.execute(
            "SELECT run_id, name, upload_status FROM runs "
            "WHERE COALESCE(upload_status, '') != 'uploaded' ORDER BY run_id"
        ).fetchall()
        scope = "non-uploaded"
    print(f"{'DRY RUN - ' if args.dry_run else ''}"
          f"{len(runs)} {scope} runs to scan\n", file=sys.stderr)

    tot = dict(runs_done=0, runs_no_cache=0, evaluated=0, already=0,
               pass_=0, flag=0, new_review=0, merged=0, recorded_only=0)

    for run in runs:
        run_id = run["run_id"]
        is_uploaded = run["upload_status"] == "uploaded"
        try:
            elements = osm_fetch.load_cached(run_id)
        except Exception as e:
            print(f"  run {run_id}: skipped — no OSM cache ({e})", file=sys.stderr)
            tot["runs_no_cache"] += 1
            continue
        osm_idx, _poi = conflate.build_osm_index(elements)
        ctx = CheckContext(run_id=run_id, osm_index=osm_idx, city_index=None,
                            params=cfg.checks_params)

        done = {
            r["candidate_id"] for r in conn.execute(
                "SELECT candidate_id FROM check_results "
                "WHERE run_id=? AND check_id=? AND check_version=?",
                (run_id, check.id, cv),
            )
        }
        cands = conn.execute(
            """SELECT c.run_id, c.candidate_id, c.address_full, c.housenumber,
                      c.street_raw, c.street_norm, c.lat, c.lon, c.stage,
                      cf.verdict, cf.nearest_osm_id, cf.nearest_osm_type,
                      cf.nearest_dist_m,
                      ri.status AS review_status, ri.reason_code AS review_reason
               FROM candidates c
               JOIN conflation cf USING (run_id, candidate_id)
               LEFT JOIN review_items ri USING (run_id, candidate_id)
               WHERE c.run_id = ? AND cf.verdict IN ('MATCH', 'MATCH_FAR')""",
            (run_id,),
        ).fetchall()

        now = _iso()
        conn.execute("BEGIN IMMEDIATE")
        try:
            for r in cands:
                if r["candidate_id"] in done:
                    tot["already"] += 1
                    continue
                cand = Candidate(
                    run_id=r["run_id"], candidate_id=r["candidate_id"],
                    address_full=r["address_full"], housenumber=r["housenumber"],
                    street_raw=r["street_raw"], street_norm=r["street_norm"],
                    lat=r["lat"], lon=r["lon"],
                    lo_num=None, lo_num_suf=None, hi_num=None, hi_num_suf=None,
                    verdict=r["verdict"], nearest_osm_id=r["nearest_osm_id"],
                    nearest_osm_type=r["nearest_osm_type"],
                    nearest_dist_m=r["nearest_dist_m"],
                )
                if not check.applies(cand, ctx):
                    continue  # missing nearest_dist_m etc. — not evaluable
                v = check.evaluate(cand, ctx)
                tot["evaluated"] += 1

                conn.execute(
                    """INSERT INTO check_results
                         (run_id, candidate_id, check_id, check_version,
                          verdict, severity, reason_code, details_json, computed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (run_id, cand.candidate_id, check.id, cv, v.status,
                     v.severity, v.reason_code,
                     json.dumps(v.details, default=str), now),
                )
                if v.status != "FLAG":
                    tot["pass_"] += 1
                    continue

                tot["flag"] += 1
                audit.log(actor="apply_drift_flags", event_type="CHECK_FLAGGED",
                          run_id=run_id, candidate_id=cand.candidate_id,
                          payload={"check_id": check.id, "reason": v.reason_code,
                                   "severity": v.severity}, conn=conn)

                decided = (is_uploaded
                           or r["stage"] in DECIDED_STAGES
                           or r["review_status"] in DECIDED_REVIEW)
                if decided:
                    tot["recorded_only"] += 1
                    continue

                if r["review_status"] is None:
                    conn.execute(
                        """INSERT INTO review_items
                             (run_id, candidate_id, reason_code, status, opened_at)
                           VALUES (?, ?, ?, 'OPEN', ?)""",
                        (run_id, cand.candidate_id, check.id, now),
                    )
                    tot["new_review"] += 1
                else:
                    conn.execute(
                        "UPDATE review_items SET reason_code=? "
                        "WHERE run_id=? AND candidate_id=?",
                        (_merge_reasons(r["review_reason"], check.id),
                         run_id, cand.candidate_id),
                    )
                    tot["merged"] += 1

                if r["stage"] != "REVIEW_PENDING":
                    conn.execute(
                        "UPDATE candidates SET stage='REVIEW_PENDING', "
                        "stage_updated_at=? WHERE run_id=? AND candidate_id=?",
                        (now, run_id, cand.candidate_id),
                    )
            if args.dry_run:
                conn.execute("ROLLBACK")
            else:
                conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        tot["runs_done"] += 1

    conn.close()

    print(f"\n{'DRY RUN - nothing written' if args.dry_run else 'DONE'}")
    print(f"  runs scanned        : {tot['runs_done']}")
    print(f"  runs without cache  : {tot['runs_no_cache']}")
    print(f"  already had result  : {tot['already']}")
    print(f"  candidates evaluated: {tot['evaluated']}  "
          f"(PASS {tot['pass_']}, FLAG {tot['flag']})")
    print(f"  new review items    : {tot['new_review']}  (SKIPPED -> REVIEW_PENDING)")
    print(f"  reason merged       : {tot['merged']}  (already REVIEW_PENDING)")
    print(f"  recorded only       : {tot['recorded_only']}  (already decided)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
