"""Where the watermark comes from before a city has closed a month.

Until the first close stores one, the watermark is derived from the import: the
oldest source snapshot an uploaded import run was built from. It used to be a
hard-coded Toronto snapshot id, which for Guelph counted from a date that had
nothing to do with its import.
"""
import sqlite3

import pytest

from t2 import maintenance


@pytest.fixture
def make_db(tmp_path, monkeypatch):
    path = tmp_path / "tool.db"

    def _make(runs=(), stored=None):
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE runs (run_id INTEGER PRIMARY KEY, name TEXT, "
            "source_snapshot_id INTEGER, upload_status TEXT)"
        )
        conn.execute("CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT)")
        conn.executemany("INSERT INTO runs (name, source_snapshot_id, upload_status) "
                         "VALUES (?, ?, ?)", runs)
        if stored is not None:
            conn.execute("INSERT INTO kv VALUES ('maintenance.watermark_snapshot', ?)",
                         (str(stored),))
        conn.commit()
        conn.close()

    def _connect():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(maintenance._db, "connect", _connect)
    monkeypatch.setattr(maintenance.source_db, "latest_snapshot_id", lambda: 78)
    return _make


def test_stored_watermark_wins(make_db):
    make_db(runs=[("tile-a", 47, "uploaded")], stored=113)
    assert maintenance.watermark_origin() == {"snapshot": 113, "origin": "stored"}


def test_derived_from_the_oldest_uploaded_import_run(make_db):
    """Batches built from different pulls: start at the oldest, or the
    addresses that appeared between the pulls are missed by both."""
    make_db(runs=[("tile-a", 49, "uploaded"), ("tile-b", 47, "uploaded"),
                  ("tile-c", 48, "uploaded")])
    assert maintenance.watermark_origin() == {"snapshot": 47, "origin": "import"}
    assert maintenance.get_watermark() == 47


def test_unuploaded_and_maintenance_runs_do_not_count(make_db):
    make_db(runs=[("tile-a", 40, "pending"), ("maint-snap30", 30, "uploaded"),
                  ("tile-b", 47, "uploaded")])
    assert maintenance.get_watermark() == 47


def test_nothing_imported_means_an_empty_delta(make_db):
    """No uploads: the latest snapshot, so nothing is counted, rather than a
    number from some other city."""
    make_db(runs=[("tile-a", 40, "pending")])
    assert maintenance.watermark_origin() == {"snapshot": 78, "origin": "none"}
