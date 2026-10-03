"""A source that has not changed is current, not stale.

The tracker records a check that found nothing new as a skipped snapshot. Ageing
only the newest *non-skipped* one read Guelph as 16 days stale on 2026-10-03,
though the City had been pulled the day before, and that refused Run for All.
The age must come from the newest check; the id must stay the newest snapshot
that has address rows, because runs are keyed on it.
"""
import sqlite3
from datetime import datetime, timedelta

from t2 import source_db


def _build_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE snapshots (id INTEGER PRIMARY KEY, downloaded TEXT, skipped INTEGER)")
    conn.executemany("INSERT INTO snapshots VALUES (?,?,?)", rows)
    conn.commit()
    conn.close()


def _patch(monkeypatch, db):
    def _connect():
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(source_db, "connect_readonly", _connect)


def _ago(days):
    return (datetime.now() - timedelta(days=days)).isoformat()


def test_a_recent_unchanged_check_keeps_an_old_snapshot_current(tmp_path, monkeypatch):
    db = tmp_path / "addresses.db"
    _build_db(str(db), [(46, _ago(34), 0), (47, _ago(16), 0), (48, _ago(1), 1)])
    _patch(monkeypatch, db)

    info = source_db.latest_snapshot_info()

    assert info["id"] == 47
    assert 0.9 < info["age_days"] < 1.1
    assert not info["is_stale"]


def test_no_check_for_two_weeks_is_still_stale(tmp_path, monkeypatch):
    db = tmp_path / "addresses.db"
    _build_db(str(db), [(47, _ago(20), 0), (48, _ago(16), 1)])
    _patch(monkeypatch, db)

    info = source_db.latest_snapshot_info()

    assert info["id"] == 47
    assert info["is_stale"]
