"""Intra-run upload guard: same civic address is uploaded as one node.

Spins up the schema in a temp tool.db by repointing t2.db's config, the same
way test_cross_run_duplicate.py does.
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


def _cand(conn, run_id, candidate_id, stage, address_full, municipality=None, unit=None):
    conn.execute(
        "INSERT INTO candidates (run_id, candidate_id, address_full, "
        "municipality_name, unit, stage, stage_updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, '2026-05-15T00:00:00Z')",
        (run_id, candidate_id, address_full, municipality, unit, stage),
    )


def _stage(conn, run_id, candidate_id):
    return conn.execute(
        "SELECT stage FROM candidates WHERE run_id=? AND candidate_id=?",
        (run_id, candidate_id),
    ).fetchone()["stage"]


def test_keeps_lowest_candidate_id_among_same_address(tool_db):
    from t2 import osm_export

    conn = _db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _run(conn, 25, "tile-25")
        # Two APPROVED candidates resolve to the same civic address.
        _cand(conn, 25, 900, "APPROVED", "1245 Dupont St", "Toronto")
        _cand(conn, 25, 950, "APPROVED", "1245 Dupont St", "Toronto")
        # Control: a distinct address must be untouched.
        _cand(conn, 25, 1000, "APPROVED", "1247 Dupont St", "Toronto")
        conn.execute("COMMIT")
    finally:
        conn.close()

    skipped = osm_export.skip_intra_run_duplicates(25)

    assert skipped == [950]
    conn = _db.connect()
    try:
        assert _stage(conn, 25, 900) == "APPROVED"   # canonical keeper
        assert _stage(conn, 25, 950) == "SKIPPED"
        assert _stage(conn, 25, 1000) == "APPROVED"
        ev = conn.execute(
            "SELECT run_id, candidate_id, payload_json FROM events "
            "WHERE event_type='SKIPPED_INTRA_RUN_DUPLICATE'"
        ).fetchone()
        assert ev["run_id"] == 25 and ev["candidate_id"] == 950
        assert '"kept_candidate_id": 900' in ev["payload_json"]
        assert '"1245 Dupont St"' in ev["payload_json"]
    finally:
        conn.close()

    # Idempotent: only the canonical row remains APPROVED, so a second pass
    # finds nothing and logs nothing new.
    assert osm_export.skip_intra_run_duplicates(25) == []
    conn = _db.connect()
    try:
        n = conn.execute(
            "SELECT COUNT(*) c FROM events "
            "WHERE event_type='SKIPPED_INTRA_RUN_DUPLICATE'"
        ).fetchone()["c"]
        assert n == 1
    finally:
        conn.close()


def test_same_address_different_municipality_not_deduped(tool_db):
    """Municipality trap: one address string in two former municipalities is
    two genuinely distinct addresses, so neither is skipped."""
    from t2 import osm_export

    conn = _db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _run(conn, 25, "tile-25")
        _cand(conn, 25, 10, "APPROVED", "66 George St", "Toronto")
        _cand(conn, 25, 20, "APPROVED", "66 George St", "Scarborough")
        conn.execute("COMMIT")
    finally:
        conn.close()

    assert osm_export.skip_intra_run_duplicates(25) == []
    conn = _db.connect()
    try:
        assert _stage(conn, 25, 10) == "APPROVED"
        assert _stage(conn, 25, 20) == "APPROVED"
    finally:
        conn.close()


def test_null_address_full_not_deduped(tool_db):
    """Rows without an address_full have no civic-address key, so they are
    never collapsed into each other."""
    from t2 import osm_export

    conn = _db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _run(conn, 25, "tile-25")
        _cand(conn, 25, 1, "APPROVED", None, "Toronto")
        _cand(conn, 25, 2, "APPROVED", None, "Toronto")
        conn.execute("COMMIT")
    finally:
        conn.close()

    assert osm_export.skip_intra_run_duplicates(25) == []
    conn = _db.connect()
    try:
        assert _stage(conn, 25, 1) == "APPROVED"
        assert _stage(conn, 25, 2) == "APPROVED"
    finally:
        conn.close()


def test_doors_at_one_civic_address_are_not_deduped_into_one(tool_db):
    """A townhouse row under per-door-or-collapse.

    Guelph synthesizes address_full from number+street, so all twelve doors at
    19 Burns Drive carry the same one. Without the unit in the key this guard
    would keep a single node and quietly undo the whole policy.
    """
    from t2 import osm_export

    conn = _db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _run(conn, 30, "tile-30")
        for i, unit in enumerate(range(41, 53)):
            _cand(conn, 30, 100 + i, "APPROVED", "19 Burns Drive", "Guelph", str(unit))
        conn.execute("COMMIT")
    finally:
        conn.close()

    assert osm_export.skip_intra_run_duplicates(30) == []
    conn = _db.connect()
    try:
        for i in range(12):
            assert _stage(conn, 30, 100 + i) == "APPROVED"
    finally:
        conn.close()


def test_the_same_door_twice_is_still_deduped(tool_db):
    """The guard has to keep working within a unit, or a tile overlap would
    upload one door twice."""
    from t2 import osm_export

    conn = _db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _run(conn, 31, "tile-31")
        _cand(conn, 31, 10, "APPROVED", "19 Burns Drive", "Guelph", "41")
        _cand(conn, 31, 20, "APPROVED", "19 Burns Drive", "Guelph", "41")
        conn.execute("COMMIT")
    finally:
        conn.close()

    assert osm_export.skip_intra_run_duplicates(31) == [20]


def test_a_building_and_its_own_door_are_not_deduped(tool_db):
    """The collapsed civic node carries no unit; a door at the same address
    carries one. They are different objects and both survive."""
    from t2 import osm_export

    conn = _db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _run(conn, 32, "tile-32")
        _cand(conn, 32, 10, "APPROVED", "714 Willow Road", "Guelph", None)
        _cand(conn, 32, 20, "APPROVED", "714 Willow Road", "Guelph", "30")
        conn.execute("COMMIT")
    finally:
        conn.close()

    assert osm_export.skip_intra_run_duplicates(32) == []
