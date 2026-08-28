"""Queries asked about a *past* snapshot must answer about that snapshot.

An SCD-2 range is `[min_snapshot_id, max_snapshot_id]` and an open range carries
the latest snapshot as its max, so "active at :snap" written as
`max_snapshot_id = :snap` is right only when :snap is the latest — at any earlier
one it matches just the ranges that closed on exactly that day. The live ingest
path only ever asks about the latest snapshot, so it never noticed; the
/maintenance page's per-run history and the closing report ask about past
windows, and got near-zero additions and inflated retirements.

See `source_db._active_at`.
"""
import sqlite3

from t2 import source_db

_ADDR_COLS = (
    "identity_key, number, street, full, longitude, latitude, props, "
    "min_snapshot_id, max_snapshot_id"
)
_LATEST = 5


def _row(pid, num, street, min_s, max_s):
    return (str(pid), num, street, f"{num} {street}", -79.4, 43.6, "{}",
            min_s, max_s)


def _build_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE snapshots (id INTEGER PRIMARY KEY, downloaded TEXT, skipped INTEGER)")
    conn.executemany(
        "INSERT INTO snapshots VALUES (?,?,?)",
        [(i, f"2026-01-0{i}", 0) for i in range(1, _LATEST + 1)],
    )
    conn.execute(f"CREATE TABLE addresses ({_ADDR_COLS})")
    conn.executemany(
        f"INSERT INTO addresses ({_ADDR_COLS}) VALUES ({','.join('?' * 9)})", rows
    )
    conn.commit()
    conn.close()


def _patch(monkeypatch, db):
    def _connect():
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(source_db, "connect_readonly", _connect)


def test_new_since_at_a_past_snapshot(tmp_path, monkeypatch):
    db = tmp_path / "addresses.db"
    _build_db(str(db), [
        _row(1, "100", "Main St", 1, _LATEST),   # predates the watermark
        _row(2, "200", "Main St", 3, _LATEST),   # new in (2, 4] and still open
        _row(3, "300", "Main St", 5, _LATEST),   # new, but only after snapshot 4
    ])
    _patch(monkeypatch, db)

    # Asked about snapshot 4, which is not the latest: the open range spanning it
    # is the live one, even though its max is 5.
    got = [r["address_full"] for r in source_db.iter_new_since(2, 4)]
    assert got == ["200 Main St"]

    # And the same question at the latest snapshot still answers as it always did.
    got_latest = sorted(r["address_full"] for r in source_db.iter_new_since(2, _LATEST))
    assert got_latest == ["200 Main St", "300 Main St"]


def test_new_since_sees_a_range_closed_after_the_asked_snapshot(tmp_path, monkeypatch):
    """An attribute edit splits a point into two ranges. Asked about a snapshot
    inside the *first* range, the point is active — the split happening later
    must not hide it."""
    db = tmp_path / "addresses.db"
    _build_db(str(db), [
        _row(1, "100", "Main St", 2, 3),         # first range, closed at 3
        _row(1, "100", "Main St", 4, _LATEST),   # reopened after an edit
    ])
    _patch(monkeypatch, db)

    assert [r["address_full"] for r in source_db.iter_new_since(1, 3)] == ["100 Main St"]
    assert [r["address_full"] for r in source_db.iter_new_since(1, 2)] == ["100 Main St"]


def test_reissue_suppression_holds_at_a_past_snapshot(tmp_path, monkeypatch):
    """The re-issue guard (same civic address under a new point_id) reads
    "still active at :snap" too — at a past snapshot it was finding nothing and
    letting false retirements through."""
    db = tmp_path / "addresses.db"
    _build_db(str(db), [
        _row(1, "100", "Main St", 1, 2),         # old id, dropped after snap 2
        _row(2, "100", "Main St", 3, _LATEST),   # re-issued, open range
        _row(3, "200", "Oak St", 1, 2),          # genuinely retired
    ])
    _patch(monkeypatch, db)

    retired = [r["address_full"] for r in source_db.iter_retired_since(1, 4)]
    assert retired == ["200 Oak St"]   # not "100 Main St" — it was re-issued


def test_active_bbox_at_a_past_snapshot(tmp_path, monkeypatch):
    db = tmp_path / "addresses.db"
    _build_db(str(db), [
        _row(1, "100", "Main St", 1, _LATEST),   # open, spans snapshot 3
        _row(2, "200", "Main St", 4, _LATEST),   # not yet there at snapshot 3
        _row(3, "300", "Main St", 1, 2),         # already gone by snapshot 3
    ])
    _patch(monkeypatch, db)

    got = [r["address_full"]
           for r in source_db.iter_active_addresses_in_bbox((43.0, -80.0, 44.0, -79.0), 3)]
    assert got == ["100 Main St"]
