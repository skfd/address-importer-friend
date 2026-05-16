"""Cross-run upload guard: a source point in overlapping tiles is uploaded once.

These exercise real DB state, so they spin up the schema in a temp tool.db by
repointing t2.db's config (db.connect / audit.log both read t2.db._CONFIG).
"""
import pytest

from t2 import db as _db


@pytest.fixture
def tool_db(tmp_path, monkeypatch):
    monkeypatch.setattr(_db._CONFIG, "tool_db_path", tmp_path / "tool.db")
    monkeypatch.setattr(_db._CONFIG, "data_dir", tmp_path)
    _db.migrate()
    return tmp_path


def _run(conn, run_id, name):
    conn.execute(
        "INSERT INTO runs (run_id, name, bbox_min_lat, bbox_min_lon, "
        "bbox_max_lat, bbox_max_lon, created_at, config_json) "
        "VALUES (?, ?, 0, 0, 1, 1, '2026-05-15T00:00:00Z', '{}')",
        (run_id, name),
    )


def _cand(conn, run_id, candidate_id, stage, osm_node_id=None):
    conn.execute(
        "INSERT INTO candidates (run_id, candidate_id, address_full, stage, "
        "stage_updated_at, osm_node_id) VALUES (?, ?, ?, ?, '2026-05-15T00:00:00Z', ?)",
        (run_id, candidate_id, f"{candidate_id} Test St", stage, osm_node_id),
    )


def _stage(conn, run_id, candidate_id):
    return conn.execute(
        "SELECT stage FROM candidates WHERE run_id=? AND candidate_id=?",
        (run_id, candidate_id),
    ).fetchone()["stage"]


def test_skips_candidate_already_uploaded_in_another_run(tool_db):
    from t2 import osm_export

    conn = _db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _run(conn, 1, "tile-a")
        _run(conn, 2, "tile-b")
        # Overlap point: uploaded by tile-a, still APPROVED in tile-b.
        _cand(conn, 1, 999, "UPLOADED", osm_node_id=555)
        _cand(conn, 2, 999, "APPROVED")
        # Control: a tile-b-only point must be untouched.
        _cand(conn, 2, 1000, "APPROVED")
        conn.execute("COMMIT")
    finally:
        conn.close()

    skipped = osm_export.skip_cross_run_duplicates(2)

    assert skipped == [999]
    conn = _db.connect()
    try:
        assert _stage(conn, 2, 999) == "SKIPPED"
        assert _stage(conn, 2, 1000) == "APPROVED"
        assert _stage(conn, 1, 999) == "UPLOADED"  # winner unchanged
        ev = conn.execute(
            "SELECT run_id, candidate_id, payload_json FROM events "
            "WHERE event_type='SKIPPED_CROSS_RUN_DUPLICATE'"
        ).fetchone()
        assert ev["run_id"] == 2 and ev["candidate_id"] == 999
        assert '"uploaded_in_run": 1' in ev["payload_json"]
        assert '"osm_node_id": 555' in ev["payload_json"]
    finally:
        conn.close()

    # Idempotent: a second pass finds nothing and logs nothing new.
    assert osm_export.skip_cross_run_duplicates(2) == []
    conn = _db.connect()
    try:
        n = conn.execute(
            "SELECT COUNT(*) c FROM events "
            "WHERE event_type='SKIPPED_CROSS_RUN_DUPLICATE'"
        ).fetchone()["c"]
        assert n == 1
    finally:
        conn.close()


def test_does_not_skip_when_other_run_only_approved(tool_db):
    """Both copies still APPROVED (neither uploaded) -> nothing skipped yet.
    First run to actually upload wins; the loser is skipped only then."""
    from t2 import osm_export

    conn = _db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _run(conn, 1, "tile-a")
        _run(conn, 2, "tile-b")
        _cand(conn, 1, 999, "APPROVED")
        _cand(conn, 2, 999, "APPROVED")
        conn.execute("COMMIT")
    finally:
        conn.close()

    assert osm_export.skip_cross_run_duplicates(2) == []
    conn = _db.connect()
    try:
        assert _stage(conn, 2, 999) == "APPROVED"
    finally:
        conn.close()
