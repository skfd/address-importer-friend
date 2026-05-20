"""Back-scan past runs for OSM address positional drift.

Re-evaluates the `match_number_drift` check against runs that were already
conflated (and, by default, already uploaded) to find MATCH/MATCH_FAR
candidates that the check would now flag — i.e. drift that operators never
saw because the check did not exist when those runs were processed.

It is read-only: it never writes to tool.db and never creates review items.
It reimplements the pipeline's candidate-loading loop instead of calling
`pipeline.run_checks`, because that would run *all* checks and persist them.

The check's `slack_m` is read from config.toml so the scan matches what the
pipeline would produce for a fresh run.

Output:
  - a CSV (one row per flagged candidate) with the matched OSM element, the
    closer different-numbered OSM element, and both distances;
  - a console summary of "systemic" runs (>= --min-flags) and their streets.

Usage:
    python -m scripts.drift_backscan
    python -m scripts.drift_backscan --status all --min-flags 3
    python -m scripts.drift_backscan --out C:/tmp/drift.csv
"""
from __future__ import annotations

import argparse
import csv
import sys

from t2 import conflate, config as _config, db as _db, osm_fetch
from t2.checks import Candidate, CheckContext
from t2.checks.match_number_drift import MatchNumberDriftCheck


def _candidate(row) -> Candidate:
    """Build a Candidate from a candidates+conflation join row.

    Mirrors the loader in pipeline.run_checks; only the fields
    match_number_drift reads are populated (range fields are left None).
    """
    return Candidate(
        run_id=row["run_id"], candidate_id=row["candidate_id"],
        address_full=row["address_full"], housenumber=row["housenumber"],
        street_raw=row["street_raw"], street_norm=row["street_norm"],
        lat=row["lat"], lon=row["lon"],
        lo_num=None, lo_num_suf=None, hi_num=None, hi_num_suf=None,
        verdict=row["verdict"],
        nearest_osm_id=row["nearest_osm_id"],
        nearest_osm_type=row["nearest_osm_type"],
        nearest_dist_m=row["nearest_dist_m"],
    )


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m scripts.drift_backscan",
        description="Back-scan past runs for OSM address positional drift.",
    )
    ap.add_argument(
        "--status", choices=("uploaded", "all"), default="uploaded",
        help="which runs to scan (default: uploaded only)",
    )
    ap.add_argument(
        "--out", default=None,
        help="CSV output path (default: <data_dir>/drift_backscan.csv)",
    )
    ap.add_argument(
        "--min-flags", type=int, default=5,
        help="minimum flags for a run to appear in the systemic summary (default: 5)",
    )
    args = ap.parse_args(argv)

    cfg = _config.load()
    out_path = args.out or str(cfg.data_dir / "drift_backscan.csv")
    check = MatchNumberDriftCheck()

    conn = _db.connect()
    try:
        if args.status == "uploaded":
            run_sql = ("SELECT run_id, name FROM runs "
                       "WHERE upload_status = 'uploaded' ORDER BY run_id")
        else:
            run_sql = "SELECT run_id, name FROM runs ORDER BY run_id"
        runs = conn.execute(run_sql).fetchall()
        print(f"scanning {len(runs)} {args.status} runs", file=sys.stderr)

        rows_out: list[dict] = []
        per_run: dict[int, dict[str, int]] = {}
        run_name: dict[int, str] = {}
        scanned = 0

        for run in runs:
            run_id, name = run["run_id"], run["name"]
            run_name[run_id] = name
            try:
                elements = osm_fetch.load_cached(run_id)
            except Exception as e:
                print(f"  run {run_id}: skipped — no OSM cache ({e})", file=sys.stderr)
                continue
            osm_idx, _poi = conflate.build_osm_index(elements)
            ctx = CheckContext(
                run_id=run_id, osm_index=osm_idx, city_index=None,
                params=cfg.checks_params,
            )
            scanned += 1

            cands = conn.execute(
                """SELECT c.run_id, c.candidate_id, c.address_full, c.housenumber,
                          c.street_raw, c.street_norm, c.lat, c.lon,
                          cf.verdict, cf.nearest_osm_id, cf.nearest_osm_type,
                          cf.nearest_dist_m
                   FROM candidates c JOIN conflation cf USING (run_id, candidate_id)
                   WHERE c.run_id = ? AND cf.verdict IN ('MATCH', 'MATCH_FAR')""",
                (run_id,),
            ).fetchall()

            for r in cands:
                cand = _candidate(r)
                if not check.applies(cand, ctx):
                    continue
                v = check.evaluate(cand, ctx)
                if v.status != "FLAG":
                    continue
                nb = v.details["neighbors"][0]
                rows_out.append({
                    "run_id": run_id, "run_name": name,
                    "street": r["street_raw"], "city_housenumber": r["housenumber"],
                    "candidate_id": r["candidate_id"],
                    "verdict": r["verdict"],
                    "matched_osm": f'{r["nearest_osm_type"]}/{r["nearest_osm_id"]}',
                    "matched_dist_m": v.details["matched_dist_m"],
                    "closest_osm": f'{nb["osm_type"]}/{nb["osm_id"]}',
                    "closest_osm_housenumber": nb["osm_housenumber"],
                    "closest_dist_m": nb["dist_m"],
                })
                per_run.setdefault(run_id, {})
                per_run[run_id][r["street_raw"]] = (
                    per_run[run_id].get(r["street_raw"], 0) + 1
                )
    finally:
        conn.close()

    if not rows_out:
        print("no drift flags found.")
        return 0

    fieldnames = list(rows_out[0].keys())
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows_out)

    print(f"\n{len(rows_out)} drift flags across {len(per_run)} runs "
          f"(scanned {scanned} runs) - detail: {out_path}\n")
    systemic = sorted(
        ((rid, sum(st.values()), st) for rid, st in per_run.items()),
        key=lambda x: -x[1],
    )
    print(f"SYSTEMIC RUNS (>= {args.min_flags} drift flags):")
    print("=" * 70)
    shown = 0
    for rid, total, st in systemic:
        if total < args.min_flags:
            continue
        shown += 1
        print(f"\nrun {rid}  ({total} flags)  {run_name[rid]}")
        for street, n in sorted(st.items(), key=lambda x: -x[1]):
            print(f"    {n:>3}  {street}")
    if not shown:
        print("  (none)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
