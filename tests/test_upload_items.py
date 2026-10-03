"""The upload query carries every column build_tags reads.

`build_tags` treats a key it is not handed as empty, so a column missing from
`_load_upload_items` is not an error anywhere: the tag just never reaches the
changeset, while the review preview (its own query) keeps showing it. These
tests go through the real query against a migrated tool.db, which the dict-fed
build_tags tests cannot.
"""
import xml.etree.ElementTree as ET

import pytest

from t2 import db as _db


@pytest.fixture
def tool_db(tmp_path, monkeypatch):
    monkeypatch.setattr(_db._CONFIG, "tool_db_path", tmp_path / "tool.db")
    monkeypatch.setattr(_db._CONFIG, "data_dir", tmp_path)
    _db.migrate()
    return tmp_path


def _seed(rows):
    conn = _db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO runs (run_id, name, bbox_min_lat, bbox_min_lon, "
            "bbox_max_lat, bbox_max_lon, created_at, config_json) "
            "VALUES (7, 'tile-7', 0, 0, 1, 1, '2026-10-03T00:00:00Z', '{}')"
        )
        for cid, extra in rows:
            cols = {"run_id": 7, "candidate_id": cid, "housenumber": "19",
                    "street_raw": "Burns Drive", "lat": 43.5, "lon": -80.2,
                    "address_full": f"19 Burns Drive #{cid}",
                    "stage": "APPROVED",
                    "stage_updated_at": "2026-10-03T00:00:00Z", **extra}
            conn.execute(
                f"INSERT INTO candidates ({', '.join(cols)}) "
                f"VALUES ({', '.join('?' for _ in cols)})",
                tuple(cols.values()),
            )
        conn.execute("COMMIT")
    finally:
        conn.close()


def _node_tags(run_id):
    from t2 import osm_export

    items = osm_export._assign_local_node_ids(run_id, osm_export._load_upload_items(run_id))
    root = ET.fromstring(osm_export._osm_change_xml(items))
    return {
        int(n.attrib["id"]): {t.attrib["k"]: t.attrib["v"] for t in n.findall("tag")}
        for n in root.findall("node")
    }


def test_unit_and_flats_reach_the_changeset(tool_db):
    _seed([(1, {"unit": "12"}), (2, {"flats": "1-2;101-110"}), (3, {})])
    tags = _node_tags(7)
    assert tags[-1]["addr:unit"] == "12"
    assert tags[-2]["addr:flats"] == "1;2;101-110"
    assert "addr:unit" not in tags[-3] and "addr:flats" not in tags[-3]
