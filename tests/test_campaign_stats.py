"""The wrap-up page's numbers.

Three things are load-bearing here:

1. **Scope.** Maintenance runs share the city's tool.db. The wrap-up describes
   the import, so a maintenance run must not stretch the campaign window,
   inflate the totals, or appear in the per-area ranking.
2. **Sessionization.** There is no clock in the schema; hands-on time *is* the
   gap threshold, so the grouping has to be exactly what the docstring claims.
3. **Degradation.** A city with no polygon layer, and a campaign with nothing
   uploaded yet, must both render rather than divide by zero.
"""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from t2 import campaign_stats

SCHEMA = """
CREATE TABLE runs (run_id INTEGER PRIMARY KEY, name TEXT,
  bbox_min_lat REAL, bbox_min_lon REAL, bbox_max_lat REAL, bbox_max_lon REAL,
  upload_status TEXT, uploaded_at TEXT, config_json TEXT);
CREATE TABLE candidates (run_id INTEGER, candidate_id INTEGER, stage TEXT,
  stage_updated_at TEXT, street_raw TEXT, street_norm TEXT);
CREATE TABLE conflation (run_id INTEGER, candidate_id INTEGER, verdict TEXT);
CREATE TABLE changesets (changeset_id INTEGER, run_id INTEGER, status TEXT);
CREATE TABLE events (ts TEXT, run_id INTEGER, event_type TEXT);
"""

T0 = datetime(2026, 5, 13, 9, 0, tzinfo=timezone.utc)

# Two tiles in one area, one in another, so the per-area rollup has something
# to actually roll up.
TILES = [
    {"id": "downtown-nw", "name": "Downtown-NW", "parent": "Downtown",
     "bbox": [43.0, -79.5, 43.1, -79.4]},
    {"id": "downtown-se", "name": "Downtown-SE", "parent": "Downtown",
     "bbox": [43.1, -79.5, 43.2, -79.4]},
    {"id": "eastside", "name": "Eastside", "parent": "Eastside",
     "bbox": [43.2, -79.5, 43.3, -79.4]},
]


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _run(conn, run_id, tile, *, day, uploaded, maintenance=False, street="Main St"):
    """One run over `tile` that uploaded `uploaded` candidates on `day`."""
    cfg = {"maintenance": {"from_snapshot": 1, "to_snapshot": 2}} if maintenance else {}
    ts = (T0 + timedelta(days=day)).isoformat()
    b = tile["bbox"]
    conn.execute(
        "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)",
        (run_id, f"{tile['id']}-r{run_id}", b[0], b[1], b[2], b[3],
         "uploaded", ts, json.dumps(cfg)),
    )
    conn.execute("INSERT INTO changesets VALUES (?,?,?)", (run_id, run_id, "closed"))
    for i in range(uploaded):
        conn.execute(
            "INSERT INTO candidates VALUES (?,?,?,?,?,?)",
            (run_id, run_id * 1000 + i, "UPLOADED", ts, street, street.lower()),
        )
        conn.execute(
            "INSERT INTO conflation VALUES (?,?,?)",
            (run_id, run_id * 1000 + i, "MISSING"),
        )
    conn.execute("INSERT INTO events VALUES (?,?,?)", (ts, run_id, "CHANGESET_UPLOADED"))


def _fixture():
    """Two import runs (days 0 and 2) plus one maintenance run 90 days later."""
    conn = _conn()
    _run(conn, 1, TILES[0], day=0, uploaded=10, street="Main St")
    _run(conn, 2, TILES[1], day=2, uploaded=5, street="Elm Ave")
    _run(conn, 3, TILES[2], day=90, uploaded=7, maintenance=True, street="Oak Rd")
    return conn


# ---- scope -----------------------------------------------------------------

def test_maintenance_runs_are_excluded_from_the_campaign():
    s = campaign_stats.collect(_fixture(), TILES)
    assert s["totals"]["uploaded"] == 15          # not 22
    assert s["totals"]["changesets"] == 2         # not 3
    assert s["span"] == {"first": "2026-05-13", "last": "2026-05-15", "days": 3}


def test_maintenance_tail_is_reported_separately():
    s = campaign_stats.collect(_fixture(), TILES)
    assert s["maintenance"] == {"uploaded": 7, "runs": 1, "last": "2026-08-11"}


def test_including_maintenance_widens_the_window_and_drops_the_footnote():
    s = campaign_stats.collect(_fixture(), TILES, include_maintenance=True)
    assert s["totals"]["uploaded"] == 22
    assert s["span"]["last"] == "2026-08-11"
    assert s["maintenance"] is None


def test_maintenance_area_is_absent_from_the_ranking():
    s = campaign_stats.collect(_fixture(), TILES)
    assert [a["name"] for a in s["top_areas"]] == ["Downtown"]
    assert s["top_areas"][0]["count"] == 15


# ---- sessionization --------------------------------------------------------

def _stamps(*minutes):
    return [T0 + timedelta(minutes=m) for m in minutes]


def test_sessions_split_only_on_a_gap_longer_than_the_threshold():
    # 29 minutes holds the sitting together; 31 breaks it. Exactly 30 does not
    # split — the threshold is the longest gap still counted as continuous.
    assert len(campaign_stats.sessions(_stamps(0, 29), 30)) == 1
    assert len(campaign_stats.sessions(_stamps(0, 30), 30)) == 1
    assert len(campaign_stats.sessions(_stamps(0, 31), 30)) == 2


def test_a_lone_action_is_a_session_worth_no_hours():
    got = campaign_stats.sessions(_stamps(0), 30)
    assert len(got) == 1
    assert got[0][0] == got[0][1]


def test_no_events_means_no_sessions():
    assert campaign_stats.sessions([], 30) == []


def test_gap_threshold_changes_the_reported_hours():
    conn = _conn()
    conn.execute(
        "INSERT INTO runs VALUES (1,'r',43.0,-79.5,43.1,-79.4,'uploaded',?,'{}')",
        (T0.isoformat(),),
    )
    for m in (0, 45, 90):
        conn.execute(
            "INSERT INTO events VALUES (?,1,'REVIEW_APPROVED')",
            ((T0 + timedelta(minutes=m)).isoformat(),),
        )
    tight = campaign_stats.collect(conn, TILES, session_gap_minutes=30)
    loose = campaign_stats.collect(conn, TILES, session_gap_minutes=60)
    assert tight["sessions"]["count"] == 3      # every gap breaks
    assert loose["sessions"]["count"] == 1      # none do
    assert loose["sessions"]["hours"] > tight["sessions"]["hours"]


def test_clearing_a_decision_does_not_count_as_one():
    """REVIEW_CLEARED reverts a decision; counting it would tally the same
    candidate twice. It still marks presence, so it stays on the clock."""
    conn = _conn()
    ts = T0.isoformat()
    conn.execute("INSERT INTO runs VALUES (1,'r',43.0,-79.5,43.1,-79.4,'uploaded',?,'{}')", (ts,))
    for kind in ("REVIEW_APPROVED", "REVIEW_CLEARED"):
        conn.execute("INSERT INTO events VALUES (?,1,?)", (ts, kind))
    s = campaign_stats.collect(conn, TILES)
    assert s["automation"]["manual"] == 1
    assert s["sessions"]["count"] == 1


# ---- completeness and coverage ---------------------------------------------

def test_campaign_is_incomplete_until_every_tile_has_an_uploaded_run():
    s = campaign_stats.collect(_fixture(), TILES)
    assert s["complete"] is False
    assert s["progress"]["tiles_done"] == 2
    assert s["progress"]["tiles_total"] == 3


def test_campaign_is_complete_when_the_last_tile_lands():
    conn = _fixture()
    _run(conn, 4, TILES[2], day=3, uploaded=1)
    s = campaign_stats.collect(conn, TILES)
    assert s["complete"] is True
    assert s["progress"]["tile_pct"] == 100.0
    assert s["progress"]["area_pct"] == 100.0


def test_a_run_that_matches_no_tile_still_counts_in_the_totals():
    """Freehand runs have no tile, so they drop out of the per-area rollup
    rather than being misfiled — but their uploads are real."""
    conn = _fixture()
    freehand = {"id": "x", "bbox": [1.0, 2.0, 3.0, 4.0]}
    _run(conn, 5, freehand, day=1, uploaded=100, street="Nowhere St")
    s = campaign_stats.collect(conn, TILES)
    assert s["totals"]["uploaded"] == 115
    assert sum(a["count"] for a in s["top_areas"]) == 15


# ---- degradation -----------------------------------------------------------

def test_no_tile_layer_reports_no_coverage_rather_than_dividing_by_zero():
    s = campaign_stats.collect(_fixture(), [])
    assert s["complete"] is False
    assert s["progress"] == {
        "tiles_total": 0, "tiles_done": 0, "areas_total": 0, "areas_done": 0,
        "tile_pct": 0.0, "area_pct": 0.0,
    }
    assert s["top_areas"] == []
    assert s["totals"]["uploaded"] == 15


def test_a_tile_with_no_parent_groups_under_itself():
    """A city with no polygon layer gets tiles split straight off the bbox."""
    flat = [{"id": "q1", "name": "Q1", "bbox": TILES[0]["bbox"]}]
    conn = _conn()
    _run(conn, 1, flat[0], day=0, uploaded=4)
    s = campaign_stats.collect(conn, flat)
    assert s["top_areas"] == [{"name": "Q1", "count": 4}]


def test_an_empty_database_renders_zeroes():
    s = campaign_stats.collect(_conn(), TILES)
    assert s["totals"]["uploaded"] == 0
    assert s["calendar"] == []
    assert s["span"]["first"] is None
    assert s["sessions"] == {"count": 0, "hours": 0.0, "gap_minutes": 30}
    assert s["facts"]["avg_run"] == 0
    assert s["maintenance"] is None


def test_idle_days_survive_as_gaps_in_the_chart():
    """Day 1 has no uploads. It must still occupy a slot, or the bar chart
    silently closes the gap and misrepresents the pace."""
    s = campaign_stats.collect(_fixture(), TILES)
    assert [d["uploaded"] for d in s["calendar"]] == [10, 0, 5]
