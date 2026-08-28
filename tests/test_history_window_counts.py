"""The /maintenance history memoizes each run's feed counts on the run.

Reconstructing (new, retired) for a run's window means two scans of the source
feed, and the retired one is the expensive query in the tool. Doing that for
every maintenance run on every page load is what made /maintenance take the
better part of a minute to open, and it got worse by two scans every month.

The counts are safe to keep because a run's window is closed: both ends are
published snapshots that are never rewritten. The cached record therefore
carries the window it was computed for — if a re-prepare or a reopen moves
`to_snapshot`, the memo simply stops matching.
"""
import json
import sqlite3

import pytest

from t2 import maintenance


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A tool.db with two maintenance runs, and counted source-feed scans."""
    path = tmp_path / "tool.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE runs (run_id INTEGER PRIMARY KEY, name TEXT, "
        "config_json TEXT, source_snapshot_id INTEGER, upload_status TEXT, "
        "changeset_id INTEGER, uploaded_at TEXT)"
    )
    for run_id, name, frm, to in (
        (1, "maint-snap90", 56, 90),
        (2, "maint-snap113", 90, 113),
    ):
        conn.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, 'uploaded', 999, NULL)",
            (run_id, name,
             json.dumps({"maintenance": {"from_snapshot": frm, "to_snapshot": to}}),
             to),
        )
    conn.commit()
    conn.close()

    def _connect():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(maintenance._db, "connect", _connect)
    monkeypatch.setattr(maintenance.source_db, "snapshot_date",
                        lambda s, conn=None: f"2026-08-{s:02d}")
    monkeypatch.setattr(maintenance.candidates, "count_by_stage",
                        lambda run_id: {"UPLOADED": 7})

    scans = {"new": 0, "retired": 0}

    def _new(frm, to):
        scans["new"] += 1
        return [{"n": i} for i in range(to - frm)]

    def _retired(frm, to):
        scans["retired"] += 1
        return [{"n": i} for i in range((to - frm) // 2)]

    monkeypatch.setattr(maintenance.source_db, "iter_new_since", _new)
    monkeypatch.setattr(maintenance.source_db, "iter_retired_since", _retired)
    return scans


def test_counts_are_computed_once_then_read_from_the_run(db):
    first = maintenance.history()
    assert [(r["run_id"], r["new_count"], r["retired_count"]) for r in first] == [
        (2, 23, 11), (1, 34, 17)
    ]
    assert db == {"new": 2, "retired": 2}  # one pair of scans per run

    second = maintenance.history()
    assert [(r["run_id"], r["new_count"], r["retired_count"]) for r in second] == [
        (2, 23, 11), (1, 34, 17)
    ]
    assert db == {"new": 2, "retired": 2}  # nothing rescanned


def test_moving_the_window_invalidates_the_memo(db):
    maintenance.history()
    assert db == {"new": 2, "retired": 2}

    # A re-prepare extends the newest run's window to a later snapshot.
    maintenance.set_run_window(2, 90, 120)

    got = maintenance.history()
    assert [(r["run_id"], r["new_count"], r["retired_count"]) for r in got] == [
        (2, 30, 15), (1, 34, 17)
    ]
    assert db == {"new": 3, "retired": 3}  # only the moved run rescanned


def test_memo_survives_alongside_the_close_record(db):
    """The counts share `config_json["maintenance"]` with the window and the
    close record, so writing them must not clobber either."""
    maintenance.history()
    conn = maintenance._db.connect()
    m = json.loads(
        conn.execute("SELECT config_json FROM runs WHERE run_id=2").fetchone()[0]
    )["maintenance"]
    conn.close()
    assert m["from_snapshot"] == 90 and m["to_snapshot"] == 113
    assert m["counts"] == {"from": 90, "to": 113, "new": 23, "retired": 11}
