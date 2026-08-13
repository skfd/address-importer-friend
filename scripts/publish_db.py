"""Build a credential-scrubbed, compressed snapshot of the living tool.db for
publishing as a GitHub release asset.

OAuth tokens + PKCE verifiers live OUTSIDE tool.db (in data/osm_auth.json — see
t2/osm_client.py), so a snapshot should already be credential-free. This script
keeps a belt-and-suspenders scrub anyway, to catch any legacy DB that still has
credential rows in `kv`: it compacts the DB into a throwaway copy, deletes any
such rows (keeping the maintenance watermark), self-verifies none remain, then
xz-compresses it.

It does NOT upload — the `publish-db` skill runs `gh release create` on the
artifact this prints. Run with the web app stopped (VACUUM takes a read lock).

    python -m scripts.publish_db            # date = the watermark snapshot's feed date
    python -m scripts.publish_db --date 20260605
"""
from __future__ import annotations

import argparse
import lzma
import shutil
import sqlite3
import sys
from datetime import date, datetime

from t2 import config as _config

_CFG = _config.load()
LIVE = _CFG.tool_db_path            # data/<slug>/tool.db — the configured city's DB
OUT_DIR = _CFG.data_root / "release"  # shared: releases are dated, not slugged (yet)
WATERMARK_KEY = "maintenance.watermark_snapshot"
CRED_PREDICATE = "key LIKE 'osm_oauth%' OR key LIKE 'pkce:%'"


def _watermark_date() -> str:
    """Date stamp the snapshot is current through: the City-feed publication date
    of the maintenance watermark snapshot. This is the "latest maintenance we
    did" — deterministic, independent of when the snapshot is actually published.
    Falls back to today only if the watermark or its feed date can't be read."""
    try:
        conn = sqlite3.connect(f"file:{LIVE.as_posix()}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT value FROM kv WHERE key=?", (WATERMARK_KEY,)
            ).fetchone()
        finally:
            conn.close()
        if row and row[0] is not None:
            from t2 import source_db
            ds = source_db.snapshot_date(int(row[0]))
            if ds:
                return datetime.fromisoformat(ds).strftime("%Y%m%d")
    except Exception:
        pass
    return date.today().strftime("%Y%m%d")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default=None,
                    help="Override the date stamp (YYYYMMDD). Default: the feed "
                         "publication date of the maintenance watermark snapshot.")
    args = ap.parse_args(argv)
    if args.date is None:
        args.date = _watermark_date()

    if not LIVE.exists():
        sys.exit(f"living DB not found: {LIVE}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    plain = OUT_DIR / f"tool-db-{args.date}.db"
    packed = plain.with_suffix(".db.xz")
    if packed.exists():
        sys.exit(f"{packed} already exists — remove it or pass a different --date.")
    if plain.exists():
        plain.unlink()

    # 1. compact into a throwaway copy (folds WAL, reclaims free pages).
    print(f"VACUUM INTO {plain} ...")
    src = sqlite3.connect(LIVE)
    try:
        src.execute(f"VACUUM INTO '{plain.as_posix()}'")
    finally:
        src.close()

    # 2. scrub credentials (keep the watermark).
    scrub = sqlite3.connect(plain)
    try:
        scrub.execute("BEGIN")
        n = scrub.execute(f"DELETE FROM kv WHERE {CRED_PREDICATE}").rowcount
        scrub.execute("COMMIT")
        scrub.execute("VACUUM")  # don't leave deleted creds in free pages
        # 3. self-verify: no creds left, watermark intact.
        left = scrub.execute(f"SELECT COUNT(*) FROM kv WHERE {CRED_PREDICATE}").fetchone()[0]
        wm = scrub.execute("SELECT value FROM kv WHERE key=?", (WATERMARK_KEY,)).fetchone()
    finally:
        scrub.close()
    if left:
        plain.unlink(missing_ok=True)
        sys.exit(f"ABORT: {left} credential row(s) still present after scrub.")
    print(f"scrubbed {n} credential row(s); watermark="
          f"{wm[0] if wm else 'MISSING'}")

    # 4. compress with the stdlib (no dependency on an `xz` binary on Windows).
    print(f"compressing -> {packed} ...")
    with open(plain, "rb") as fin, lzma.open(packed, "wb", preset=9) as fout:
        shutil.copyfileobj(fin, fout, length=8 * 1024 * 1024)
    plain.unlink()  # keep only the compressed asset

    size_mb = packed.stat().st_size / 1e6
    print(f"\nartifact ready: {packed} ({size_mb:.0f} MB)")
    print("publish with:")
    print(f"  gh release create tool-db-{args.date} \"{packed}\" "
          f"--title \"tool.db snapshot {args.date}\" "
          f"--notes \"Credential-scrubbed living DB snapshot.\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
