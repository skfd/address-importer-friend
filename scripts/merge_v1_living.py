"""One-shot merge: fold the post-reset maintenance runs back into the frozen v1
archive, making v1 the single living `data/tool.db` again.

Background: on 2026-06-03 the ~2 GiB v1 tool.db was frozen/archived and the live
DB reset to empty. Two maintenance runs were then created in the fresh DB. This
script promotes the archive back to `data/tool.db` and merges those two runs in.

Run with the web app STOPPED. Safe to abort and re-run: it backs everything up
first and refuses to merge twice (it aborts if the renumbered runs already exist
in the target).

Steps:
  1. Checkpoint the current live (maint) DB's WAL, then copy it aside as
     `data/maint-live-premerge.db` (the only copy of the 2 prod runs).
  2. Copy the archive over `data/tool.db` (removing any stale WAL/SHM first).
  3. Apply migration 016 to bring the archive from schema 15 -> 16.
  4. Renumber the maint runs by +offset (offset = archive MAX(run_id)) in the
     premerge copy, then INSERT them into the live DB.
  5. Carry only the maintenance watermark from kv (no OAuth/PKCE creds).
  6. Fix sqlite_sequence and rename the maint OSM cache files.
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

DATA = Path("data")
ARCHIVE = DATA / "archive" / "tool-v1-20260603.db"
LIVE = DATA / "tool.db"
PREMERGE = DATA / "maint-live-premerge.db"

# Tables whose `run_id` column must be offset before merging. `events` is in the
# list for the renumber pass but is inserted separately (its event_id collides).
RUN_ID_TABLES = [
    "runs", "candidates", "conflation", "check_toggles",
    "check_results", "review_items", "changesets", "events",
]
# Inserted with `SELECT *` (column order is identical: both DBs went through the
# same migration sequence). `events` excluded — handled explicitly below.
INSERT_STAR_TABLES = [
    "runs", "candidates", "conflation", "check_toggles",
    "check_results", "review_items", "changesets",
]
WATERMARK_KEY = "maintenance.watermark_snapshot"


def _checkpoint(db: Path) -> None:
    conn = sqlite3.connect(db)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def _rm_wal_shm(db: Path) -> None:
    for suffix in ("-wal", "-shm"):
        p = db.with_name(db.name + suffix)
        if p.exists():
            p.unlink()


def main() -> int:
    if not ARCHIVE.exists():
        sys.exit(f"archive not found: {ARCHIVE}")
    if not LIVE.exists():
        sys.exit(f"live DB not found: {LIVE}")

    # --- 1. back up the maint DB (fold its WAL first so nothing is lost) ------
    _checkpoint(LIVE)
    if PREMERGE.exists():
        sys.exit(f"{PREMERGE} already exists — refusing to overwrite a backup. "
                 "Remove it manually if you really mean to re-run.")
    shutil.copy2(LIVE, PREMERGE)
    print(f"backed up maint DB -> {PREMERGE}")

    # Read the maint run_ids from the backup before we overwrite the live file.
    pm = sqlite3.connect(PREMERGE)
    pm.row_factory = sqlite3.Row
    maint_run_ids = [r["run_id"] for r in pm.execute("SELECT run_id FROM runs ORDER BY run_id")]
    pm.close()
    print(f"maint runs to merge: {maint_run_ids}")

    # --- 2. promote the archive to the live base -----------------------------
    _rm_wal_shm(LIVE)
    print("copying archive -> data/tool.db (2 GiB, be patient)...")
    shutil.copy2(ARCHIVE, LIVE)
    _rm_wal_shm(LIVE)  # drop any -shm the copy brought along

    # --- 3. schema 15 -> 16 on the new live DB -------------------------------
    from t2 import db as _db  # imported here so config picks up the new file
    before = _schema(LIVE)
    _db.migrate()
    after = _schema(LIVE)
    print(f"schema {before} -> {after}")
    if after != 16:
        sys.exit(f"expected schema 16 after migrate, got {after}")

    live_max = _scalar(LIVE, "SELECT MAX(run_id) FROM runs")
    offset = int(live_max)
    print(f"archive MAX(run_id)={live_max}; offset=+{offset} "
          f"(maint {maint_run_ids} -> {[r + offset for r in maint_run_ids]})")

    # Idempotency guard: bail if a renumbered run already landed.
    for rid in maint_run_ids:
        if _scalar(LIVE, "SELECT 1 FROM runs WHERE run_id=?", (rid + offset,)):
            sys.exit(f"run_id {rid + offset} already present in target — merge "
                     "appears already done. Aborting to avoid double-insert.")

    # --- 4. renumber run_id in the premerge copy -----------------------------
    pm = sqlite3.connect(PREMERGE)
    try:
        pm.execute("PRAGMA foreign_keys=OFF")
        pm.execute("BEGIN")
        for t in RUN_ID_TABLES:
            pm.execute(f"UPDATE {t} SET run_id = run_id + ?", (offset,))
        pm.execute("COMMIT")
    finally:
        pm.close()
    _checkpoint(PREMERGE)
    print("renumbered run_id in premerge copy")

    # --- merge into the live DB ----------------------------------------------
    live = sqlite3.connect(LIVE)
    try:
        live.execute("PRAGMA foreign_keys=OFF")
        live.execute(f"ATTACH DATABASE '{PREMERGE.as_posix()}' AS src")
        live.execute("BEGIN")
        for t in INSERT_STAR_TABLES:
            live.execute(f"INSERT INTO main.{t} SELECT * FROM src.{t}")
        # events: let event_id auto-assign (archive seq is far above maint's).
        live.execute(
            "INSERT INTO main.events(ts, run_id, candidate_id, actor, event_type, payload_json) "
            "SELECT ts, run_id, candidate_id, actor, event_type, payload_json FROM src.events"
        )
        # 5. watermark only — never the OAuth/PKCE rows.
        live.execute(
            "INSERT OR REPLACE INTO main.kv(key, value) "
            "SELECT key, value FROM src.kv WHERE key = ?",
            (WATERMARK_KEY,),
        )
        # 6. keep the run sequence ahead of the merged ids. (SQLite already
        # bumps an AUTOINCREMENT seq on explicit-id inserts; this makes it
        # explicit and correct even if the 'runs' seq row was somehow stale.)
        live.execute(
            "UPDATE sqlite_sequence SET seq=(SELECT MAX(run_id) FROM runs) WHERE name='runs'"
        )
        live.execute("COMMIT")
        live.execute("DETACH DATABASE src")
    finally:
        live.close()
    print("merge committed")

    # --- 7. rename the maint OSM cache files ---------------------------------
    for rid in maint_run_ids:
        old = DATA / f"osm_current_run{rid}.json"
        new = DATA / f"osm_current_run{rid + offset}.json"
        if old.exists() and not new.exists():
            old.rename(new)
            print(f"renamed cache {old.name} -> {new.name}")

    print("\nDONE. Verify with scripts in the plan, then start run.py.")
    return 0


def _schema(db: Path) -> int:
    return int(_scalar(db, "SELECT MAX(version) FROM schema_version") or 0)


def _scalar(db: Path, sql: str, params: tuple = ()):  # tiny read helper
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
