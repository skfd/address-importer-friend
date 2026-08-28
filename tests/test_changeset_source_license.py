"""`[export] source_license` — the changeset's `source:license` tag.

Guelph's published plan puts source:license=OGL-Canada-2.0 on the changeset.
Toronto's changeset-tag table has no such key, and adding one there would put
an undocumented tag on a live import's changesets, so the key is optional and
absent means absent.
"""
import pytest

from t2 import db as _db, osm_export
from t2.config import parse_source_license


@pytest.fixture
def run_one(tmp_path, monkeypatch):
    monkeypatch.setattr(_db._CONFIG, "tool_db_path", tmp_path / "tool.db")
    monkeypatch.setattr(_db._CONFIG, "data_dir", tmp_path)
    _db.migrate()
    conn = _db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO runs (run_id, name, bbox_min_lat, bbox_min_lon, "
            "bbox_max_lat, bbox_max_lon, created_at, config_json) "
            "VALUES (1, 'tile-a', 0, 0, 1, 1, '2026-08-27T00:00:00Z', '{}')"
        )
        conn.execute("COMMIT")
    finally:
        conn.close()
    return 1


def test_absent_key_leaves_the_changeset_table_alone(run_one):
    assert osm_export._CONFIG.export_source_license == ""
    assert "source:license" not in osm_export.changeset_tags(run_one)


def test_declared_licence_reaches_the_changeset(run_one, monkeypatch):
    monkeypatch.setattr(osm_export._CONFIG, "export_source_license", "OGL-Canada-2.0")
    tags = osm_export.changeset_tags(run_one)
    assert tags["source:license"] == "OGL-Canada-2.0"
    # It is a changeset tag only — the node keeps addr:source and nothing else.
    assert "source:license" not in osm_export.build_tags(
        {"housenumber": "1", "street_raw": "Main Street"}
    )


def test_parse_accepts_absence_and_refuses_a_blank_declaration():
    assert parse_source_license({}) == ""
    assert parse_source_license({"source_license": " OGL-Canada-2.0 "}) == "OGL-Canada-2.0"
    for bad in ({"source_license": ""}, {"source_license": "   "}, {"source_license": 2}):
        with pytest.raises(ValueError):
            parse_source_license(bad)
