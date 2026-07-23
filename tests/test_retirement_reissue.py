"""A City address re-issue (same civic address, new point_id, moved a few
metres) must NOT be reported as a retirement — the address never left, so it
would be a false deletion candidate. See `source_db.iter_retired_since`."""
import sqlite3

from t2 import source_db

# The source is ontario-address-changes' generic toronto.db schema: one row per
# SCD-2 range keyed by identity_key, with source props in a JSON blob.
_ADDR_COLS = (
    "identity_key, number, street, full, longitude, latitude, props, "
    "min_snapshot_id, max_snapshot_id"
)


def _row(pid, num, street, min_s, max_s):
    return (str(pid), num, street, f"{num} {street}", -79.4, 43.6, "{}",
            min_s, max_s)


def _build_db(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE snapshots (id INTEGER PRIMARY KEY, downloaded TEXT, skipped INTEGER)")
    conn.executemany("INSERT INTO snapshots VALUES (?,?,?)",
                     [(1, "2026-01-01", 0), (2, "2026-01-02", 0), (3, "2026-01-03", 0)])
    conn.execute(f"CREATE TABLE addresses ({_ADDR_COLS})")
    conn.executemany(
        f"INSERT INTO addresses ({_ADDR_COLS}) VALUES ({','.join('?' * 9)})",
        [
            _row(1, "100", "Main St", 1, 2),   # old id, retired at snap 2
            _row(2, "100", "Main St", 3, 3),   # re-issued same address, active at latest
            _row(3, "200", "Oak St", 1, 2),    # genuinely retired, no replacement
        ],
    )
    conn.commit()
    conn.close()


def test_reissue_excluded_genuine_retirement_kept(tmp_path, monkeypatch):
    db = tmp_path / "addresses.db"
    _build_db(str(db))

    def _connect():
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(source_db, "connect_readonly", _connect)

    retired = [r["address_full"] for r in source_db.iter_retired_since(0, 3)]

    assert "100 Main St" not in retired   # re-issued -> not a deletion candidate
    assert retired == ["200 Oak St"]      # only the genuine retirement remains
