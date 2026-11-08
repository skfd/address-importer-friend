"""Where the watermark comes from before a city has closed a month.

Until the first close stores one, the watermark is derived from the import: the
oldest source snapshot an uploaded import run was built from. It used to be a
hard-coded Toronto snapshot id, which for Guelph counted from a date that had
nothing to do with its import.
"""
import sqlite3
from types import SimpleNamespace

import pytest

from t2 import config, maintenance


@pytest.fixture
def make_db(tmp_path, monkeypatch):
    path = tmp_path / "tool.db"

    def _make(runs=(), stored=None, override=None):
        monkeypatch.setattr(maintenance._config, "load",
                            lambda: SimpleNamespace(maintenance_import_snapshots=override))
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
    monkeypatch.setattr(maintenance.source_db, "snapshot_date",
                        lambda s, conn=None: f"2026-09-{s - 30:02d}")
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


def test_override_names_the_import_snapshots(make_db):
    """Toronto's runs carry addresses.db ids (42/45); config translates them."""
    make_db(runs=[("pilot", 42, "uploaded"), ("tile-a", 45, "uploaded")],
            override=(44, 47))
    assert maintenance.import_snapshots() == (44, 47)
    assert maintenance.get_watermark() == 44


def test_baseline_shows_the_range_the_import_used(make_db):
    make_db(runs=[("tile-a", 45, "uploaded"), ("tile-b", 47, "uploaded")], stored=60)
    b = maintenance.import_baseline()
    assert (b["snapshot"], b["date"]) == (47, "2026-09-17")
    assert (b["first_snapshot"], b["first_date"]) == (45, "2026-09-15")
    assert (b["watermark"], b["watermark_origin"]) == (60, "stored")


def test_baseline_with_one_pull_has_no_first_batches(make_db):
    make_db(runs=[("tile-a", 47, "uploaded"), ("tile-b", 47, "uploaded")])
    b = maintenance.import_baseline()
    assert b["snapshot"] == 47 and b["first_snapshot"] is None


def test_baseline_before_any_import(make_db):
    make_db()
    assert maintenance.import_baseline()["snapshot"] is None


@pytest.mark.parametrize("section, expected", [
    ({}, None),
    ({"since": "2026-06-05"}, None),
    ({"import_snapshots": [47, 44]}, (44, 47)),
    ({"import_snapshots": [47]}, (47, 47)),
])
def test_parse_maintenance(section, expected):
    assert config.parse_maintenance(section) == expected


@pytest.mark.parametrize("section", [
    {"sinse": "2026-06-05"},
    {"since": "June 5"},
    {"import_snapshots": 47},
    {"import_snapshots": [44, 45, 47]},
    {"import_snapshots": ["44"]},
])
def test_parse_maintenance_refuses(section):
    with pytest.raises(ValueError):
        config.parse_maintenance(section)
