"""Ingest clips source addresses to the tile polygon, not just its bbox.

Adjacent tiles share an overlapping bounding box but have disjoint polygons, so
a point in this tile's bbox that falls inside a neighbour's polygon must not be
ingested here. Without a polygon the ingest stays pure-bbox (back-compat).
"""
import pytest

from t2 import candidates, db as _db


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


def _src_row(point_id, lat, lon):
    return {
        "address_point_id": point_id,
        "address_full": f"{point_id} Test St",
        "address_number": str(point_id),
        "lo_num": None, "lo_num_suf": None, "hi_num": None, "hi_num_suf": None,
        "linear_name_full": "Test Street",
        "linear_name": None, "linear_name_type": None, "linear_name_dir": None,
        "municipality_name": "Toronto",
        "longitude": lon, "latitude": lat, "extra": None,
    }


def _ingested_ids(run_id):
    conn = _db.connect()
    try:
        return sorted(
            r["candidate_id"]
            for r in conn.execute(
                "SELECT candidate_id FROM candidates WHERE run_id = ?", (run_id,)
            )
        )
    finally:
        conn.close()


# Tile polygon covers the LEFT half of the bbox: lon in [0, 0.5], lat in [0, 1].
LEFT_HALF = [[[0.0, 0.0], [1.0, 0.0], [1.0, 0.5], [0.0, 0.5], [0.0, 0.0]]]
BBOX = (0.0, 0.0, 1.0, 1.0)


def test_drops_bbox_point_outside_polygon(tool_db, monkeypatch):
    conn = _db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _run(conn, 1, "tile-left")
        conn.execute("COMMIT")
    finally:
        conn.close()

    rows = [
        _src_row(100, lat=0.5, lon=0.25),  # inside polygon -> kept
        _src_row(200, lat=0.5, lon=0.75),  # in bbox, outside polygon -> dropped
    ]
    monkeypatch.setattr(
        candidates.source_db, "iter_active_addresses_in_bbox",
        lambda bbox, snap: iter(rows),
    )

    inserted = candidates.ingest(1, BBOX, 7, polygon_latlon=LEFT_HALF)

    assert inserted == 1
    assert _ingested_ids(1) == [100]


def test_no_polygon_keeps_whole_bbox(tool_db, monkeypatch):
    conn = _db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _run(conn, 2, "tile-bbox")
        conn.execute("COMMIT")
    finally:
        conn.close()

    rows = [
        _src_row(100, lat=0.5, lon=0.25),
        _src_row(200, lat=0.5, lon=0.75),
    ]
    monkeypatch.setattr(
        candidates.source_db, "iter_active_addresses_in_bbox",
        lambda bbox, snap: iter(rows),
    )

    inserted = candidates.ingest(2, BBOX, 7, polygon_latlon=None)

    assert inserted == 2
    assert _ingested_ids(2) == [100, 200]
