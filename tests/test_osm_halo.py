"""OSM fetch pads the tile bbox by HALO_MARGIN * match_radius_m.

Candidates are ingested clipped to the tile polygon, so a candidate on a tile
edge must still see OSM up to match_radius_m beyond that edge. The fetch widens
the clip rectangle to guarantee that halo.
"""
import json

import pytest

from t2 import osm_fetch


# Tight tile bbox; ~111 m per 0.001 deg latitude at Toronto.
BBOX = (43.0, -79.5, 43.01, -79.49)


def _node(nid, lat, lon):
    return {"type": "node", "id": nid, "lat": lat, "lon": lon,
            "tags": {"addr:housenumber": str(nid), "addr:street": "Test St"}}


@pytest.fixture
def local_extract(tmp_path, monkeypatch):
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    monkeypatch.setattr(osm_fetch._CONFIG, "data_dir", tmp_path)
    monkeypatch.setattr(osm_fetch._CONFIG, "osm_extract_dir", extract_dir)
    monkeypatch.setattr(osm_fetch._CONFIG, "osm_source", "local")
    monkeypatch.setattr(osm_fetch._CONFIG, "match_radius_m", 100.0)  # halo = 150 m
    osm_fetch._SHARED_EXTRACT_CACHE.clear()
    return extract_dir


def test_pad_bbox_widens_all_sides():
    padded = osm_fetch._pad_bbox(BBOX, 150.0)
    assert padded[0] < BBOX[0] and padded[1] < BBOX[1]   # min lat/lon shrink
    assert padded[2] > BBOX[2] and padded[3] > BBOX[3]   # max lat/lon grow
    # ~150 m north ~= 0.00135 deg latitude.
    assert padded[2] - BBOX[2] == pytest.approx(150.0 / 111_320.0, rel=1e-6)


def test_fetch_includes_halo_excludes_beyond(local_extract):
    inside = _node(1, lat=43.005, lon=-79.495)         # inside tight bbox
    halo = _node(2, lat=43.01 + 0.00108, lon=-79.495)  # ~120 m N -> within 150 m halo
    beyond = _node(3, lat=43.01 + 0.0030, lon=-79.495)  # ~334 m N -> outside halo
    (local_extract / osm_fetch._CONFIG.osm_extract_json.name).write_text(
        json.dumps([inside, halo, beyond]), encoding="utf-8"
    )

    path, _digest = osm_fetch.fetch(run_id=99, bbox=BBOX, force=True)
    ids = {el["id"] for el in json.loads(path.read_text(encoding="utf-8"))}

    assert ids == {1, 2}
