"""Closing a maintenance month.

The close advances the watermark, so the thing it must never do is advance it
too far. The City publishes daily; a month closed a day after its run would push
the watermark past snapshots the run never looked at, and `first_snap > :wm`
then hides those addresses from every later month. That is the #45-vs-#52 gap
that cost 31 addresses once already, and the bare "advance watermark" button
this close replaced had exactly that shape — it advanced to whatever was latest
at click time.
"""
import json
import sqlite3

import pytest

from t2 import maintenance


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A tool.db with one uploaded maintenance run over the window (90, 113]."""
    path = tmp_path / "tool.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE runs (run_id INTEGER PRIMARY KEY, name TEXT, "
        "config_json TEXT, source_snapshot_id INTEGER, upload_status TEXT, "
        "changeset_id INTEGER, uploaded_at TEXT)"
    )
    conn.execute("CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "INSERT INTO runs VALUES (1, 'maint-snap113', ?, 113, 'uploaded', 999, "
        "'2026-08-28T00:55:13+00:00')",
        (json.dumps({"maintenance": {"from_snapshot": 90, "to_snapshot": 113}}),),
    )
    conn.execute("INSERT INTO kv VALUES ('maintenance.watermark_snapshot', '90')")
    conn.commit()
    conn.close()

    def _connect():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(maintenance._db, "connect", _connect)
    # The source feed has moved on since the run: two more snapshots have landed.
    monkeypatch.setattr(maintenance.source_db, "latest_snapshot_id", lambda: 115)
    monkeypatch.setattr(maintenance.source_db, "snapshot_date",
                        lambda s, conn=None: f"2026-08-{s:02d}")
    monkeypatch.setattr(maintenance, "snapshot_status",
                        lambda: {"lagging": False, "watermark": 90})
    monkeypatch.setattr(maintenance.candidates, "count_by_stage",
                        lambda run_id: {"UPLOADED": 49, "REJECTED": 10, "SKIPPED": 18})
    return path


def test_close_advances_to_the_runs_snapshot_not_the_latest(db):
    """The whole point. Latest is 115; the run processed up to 113."""
    res = maintenance.close_month(1, retirements_note="22 deleted, 3 left")

    assert res["advanced_to"] == 113
    assert maintenance.get_watermark() == 113, (
        "watermark must land on the run's snapshot — advancing to the live "
        "latest would skip everything that appeared in (113, 115]"
    )


def test_close_records_the_retirement_account(db):
    maintenance.close_month(1, retirements_note="22 deleted, 3 left alone")

    closed = maintenance.get_close(1)
    assert closed["retirements_note"] == "22 deleted, 3 left alone"
    assert closed["closed_at"]

    # ...and the window it was closed over survives alongside it.
    assert maintenance.get_run_window(1) == {"from_snapshot": 90, "to_snapshot": 113}


def test_close_is_idempotent_over_an_advanced_watermark(db):
    maintenance.close_month(1, retirements_note="first pass")
    again = maintenance.close_month(1, retirements_note="second pass")

    assert again["already_advanced"] is True
    assert again["advanced_to"] is None
    assert maintenance.get_watermark() == 113
    assert maintenance.get_close(1)["retirements_note"] == "second pass"


def test_close_refuses_while_candidates_are_unresolved(db, monkeypatch):
    monkeypatch.setattr(maintenance.candidates, "count_by_stage",
                        lambda run_id: {"APPROVED": 5, "UPLOADED": 44})

    with pytest.raises(maintenance.MonthNotFinished, match="5 APPROVED"):
        maintenance.close_month(1)

    assert maintenance.get_watermark() == 90   # nothing moved
    assert maintenance.get_close(1) is None

    # force is the operator's override, and it works.
    maintenance.close_month(1, force=True)
    assert maintenance.get_watermark() == 113


def test_reprepare_does_not_drop_the_close(db):
    """`prepare()` re-calls set_run_window on a resumed run. Both live under the
    same config_json key, so a window write must merge rather than replace."""
    maintenance.close_month(1, retirements_note="handled")
    maintenance.set_run_window(1, 90, 113)

    assert maintenance.get_close(1)["retirements_note"] == "handled"


def test_close_is_blocked_by_the_unpublished_snapshot_gate(db, monkeypatch):
    monkeypatch.setattr(maintenance, "snapshot_status",
                        lambda: {"lagging": True, "watermark": 90,
                                 "watermark_date": "2026-07-22",
                                 "reason": "no release recorded"})

    with pytest.raises(maintenance.SnapshotUnpublished):
        maintenance.close_month(1)

    assert maintenance.get_watermark() == 90
    assert maintenance.get_close(1) is None, (
        "a refused close must not leave a close record behind"
    )
