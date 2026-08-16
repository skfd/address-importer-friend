"""Build a credential-scrubbed, compressed snapshot of the living tool.db for
publishing as a GitHub release asset.

OAuth tokens + PKCE verifiers live OUTSIDE tool.db (in data/osm_auth.json — see
t2/osm_client.py), so a snapshot should already be credential-free. This script
keeps a belt-and-suspenders scrub anyway, to catch any legacy DB that still has
credential rows in `kv`: it compacts the DB into a throwaway copy, deletes any
such rows (keeping the maintenance watermark), self-verifies none remain, then
xz-compresses it.

Any city: the `[city]` selected by T2_CITY_DIR / run.py --city-dir decides which
living DB is snapshotted and which checkout the artifact lands in. The release
itself belongs to the *city* repo, so the `gh` line printed at the end targets
that checkout's `origin` (and says so when there is no remote yet).

It does NOT upload — the `/publish-db` command runs `gh release create` on the
artifact this prints. Run with the web app stopped (VACUUM takes a read lock).

    T2_CITY_DIR=../<city>-address-import python -m scripts.publish_db
    python -m scripts.publish_db --date 20260605
"""
from __future__ import annotations

import argparse
import lzma
import shutil
import sqlite3
import subprocess
import sys
from datetime import date, datetime

from t2 import config as _config

_CFG = _config.load()
CITY_DIR = _config.CITY_DIR         # the city checkout the release belongs to
LIVE = _CFG.tool_db_path            # data/<slug>/tool.db — the configured city's DB
OUT_DIR = _CFG.data_root / "release"  # per-checkout, so cities can share a date
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


def _city_repo() -> str | None:
    """`owner/repo` of the city checkout's `origin`, or None when it has no
    remote. Most onboarded cities are local-only (gh repo create is blocked for
    the agent), and a release cannot be created for those — say so rather than
    printing a command that will fail."""
    try:
        out = subprocess.run(
            ["git", "-C", str(CITY_DIR), "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    url = out.stdout.strip()
    if not url:
        return None
    # git@github.com:owner/repo.git | https://github.com/owner/repo(.git)
    tail = url.split("github.com", 1)[-1].lstrip(":/")
    return tail[:-4] if tail.endswith(".git") else tail


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
    print(f"city: {_CFG.city_slug} ({CITY_DIR})")
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
    repo = _city_repo()
    if repo is None:
        print(f"\n{CITY_DIR.name} has no `origin` remote — the artifact is built, but "
              "there is nowhere to publish it yet.\nCreate the city repo "
              "(`gh repo create`), then run the `gh release create` below with "
              "--repo <owner/repo>.")
    print("\npublish with:")
    print(f"  gh release create tool-db-{args.date} \"{packed}\" "
          f"--title \"{_CFG.city_name} tool.db snapshot {args.date}\" "
          f"--notes \"Credential-scrubbed living DB snapshot.\""
          + (f" --repo {repo}" if repo else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
