"""Build a credential-scrubbed, compressed snapshot of the living tool.db for
publishing as a GitHub release asset.

The living DB always holds live OSM **prod** OAuth tokens + PKCE rows in its
`kv` table. This script is the single safeguard against shipping them: it
compacts the DB into a throwaway copy, deletes the credential rows (keeping the
maintenance watermark), self-verifies that none remain, then xz-compresses it.

It does NOT upload — the `publish-db` skill runs `gh release create` on the
artifact this prints. Run with the web app stopped (VACUUM takes a read lock).

    python -m scripts.publish_db            # -> data/release/tool-db-<today>.db.xz
    python -m scripts.publish_db --date 20260608
"""
from __future__ import annotations

import argparse
import lzma
import shutil
import sqlite3
import sys
from datetime import date
from pathlib import Path

DATA = Path("data")
LIVE = DATA / "tool.db"
OUT_DIR = DATA / "release"
WATERMARK_KEY = "maintenance.watermark_snapshot"
CRED_PREDICATE = "key LIKE 'osm_oauth%' OR key LIKE 'pkce:%'"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default=date.today().strftime("%Y%m%d"),
                    help="Date stamp for the asset name (default: today, YYYYMMDD).")
    args = ap.parse_args(argv)

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
