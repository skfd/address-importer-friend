"""The PBF comes from the shared OSM store, and every pass reopens the one the
city extract recorded.

A tmp OSM_DATA_DIR stands in for ~/Code/.osm-data: two dated dummy files with
sidecars and a latest.json, nothing fetched.
"""
import json
from types import SimpleNamespace

import pytest

from t2 import osm_refresh, osm_store

URL = "https://download.geofabrik.de/north-america/canada/ontario-latest.osm.pbf"
OLD, NEW = "ontario-2026-08-13.osm.pbf", "ontario-2026-10-02.osm.pbf"
SHA = {OLD: "a" * 64, NEW: "b" * 64}
LM = {OLD: "Thu, 13 Aug 2026 23:37:19 GMT", NEW: "Fri, 02 Oct 2026 23:17:11 GMT"}


def _side(name):
    return {"region": "ontario", "source_url": URL, "source_last_modified": LM[name],
            "bytes": 4, "sha256": SHA[name], "data_date": name[8:18]}


@pytest.fixture
def store(tmp_path, monkeypatch):
    root = tmp_path / "osm-data"
    d = root / "ontario"
    d.mkdir(parents=True)
    for name in (OLD, NEW):
        (d / name).write_bytes(b"fake")
        (d / name.replace(".osm.pbf", ".meta.json")).write_text(json.dumps(_side(name)))
    (d / "latest.json").write_text(json.dumps({"file": NEW, **_side(NEW)}))
    monkeypatch.setenv("OSM_DATA_DIR", str(root))
    return d


@pytest.fixture
def cfg(tmp_path):
    extract = tmp_path / "city" / "data" / "osm"
    extract.mkdir(parents=True)
    return SimpleNamespace(osm_pbf_url=URL, osm_extract_dir=extract,
                           osm_extract_json=extract / "testcity-addresses.json",
                           osm_city_bbox=(43.4, -80.3, 43.6, -80.1))


def test_region_from_url():
    assert osm_store.region_from_url(URL) == "ontario"
    assert osm_store.region_from_url("https://example.org/quebec.osm.pbf") == "quebec"
    with pytest.raises(ValueError):
        osm_store.region_from_url("https://example.org/ontario.zip")


def test_recorded_file_wins_over_latest(store, cfg):
    assert osm_store.resolve_pbf(cfg, {"pbf_file": OLD}) == (store / OLD, None)


def test_old_meta_matched_by_sha(store, cfg):
    # A meta from before the store: no pbf_file, only the sha of what it read.
    assert osm_store.resolve_pbf(cfg, {"pbf_sha256": SHA[OLD]}) == (store / OLD, None)


def test_pruned_file_falls_back_to_latest_with_note(store, cfg):
    (store / OLD).unlink()
    pbf, note = osm_store.resolve_pbf(cfg, {"pbf_file": OLD, "pbf_sha256": SHA[OLD]})
    assert pbf == store / NEW
    assert OLD in note and "Refresh" in note


def test_no_meta_reads_latest(store, cfg):
    assert osm_store.resolve_pbf(cfg, None) == (store / NEW, None)


def test_empty_store(tmp_path, monkeypatch, cfg):
    monkeypatch.setenv("OSM_DATA_DIR", str(tmp_path / "nothing"))
    pbf, note = osm_store.resolve_pbf(cfg, {"pbf_file": OLD})
    assert pbf is None and "refresh" in note


def test_city_pbf_reads_city_meta(store, cfg):
    (cfg.osm_extract_dir / "meta.json").write_text(json.dumps({"pbf_sha256": SHA[OLD]}))
    assert osm_store.city_pbf(cfg) == (store / OLD, None)


def test_fetch_runs_the_tool_with_force(tmp_path, monkeypatch, cfg):
    tool = tmp_path / "osm_extracts.py"
    tool.write_text("")
    monkeypatch.setenv("OSM_EXTRACTS_TOOL", str(tool))
    calls = []
    monkeypatch.setattr(osm_store.subprocess, "run", lambda args, check: calls.append(args))
    osm_store.fetch(cfg)
    osm_store.fetch(cfg, force=True)
    assert calls[0][1:] == [str(tool), "fetch", "--url", URL]
    assert calls[1][-1] == "--force"


@pytest.fixture
def refresh(store, cfg, monkeypatch):
    """osm_refresh.run against the tmp store with fetch and the filter stubbed."""
    monkeypatch.setattr(osm_refresh._config, "load", lambda: cfg)
    fetched, filtered = [], []
    monkeypatch.setattr(osm_store, "fetch", lambda c, force=False: fetched.append(force))
    monkeypatch.setattr(osm_refresh, "_filter",
                        lambda pbf, bbox: (filtered.append(pbf.name) or [], {"nodes": 0}))
    monkeypatch.setattr(osm_refresh.audit, "log", lambda **kw: None)
    return SimpleNamespace(fetched=fetched, filtered=filtered, meta=cfg.osm_extract_dir / "meta.json")


def test_refresh_filters_latest_and_records_dated_file(refresh, cfg):
    meta = osm_refresh.run()
    assert refresh.fetched == [False] and refresh.filtered == [NEW]
    assert meta["pbf_file"] == NEW and meta["pbf_sha256"] == SHA[NEW]
    assert meta["source_last_modified"] == LM[NEW]
    assert json.loads(refresh.meta.read_text())["pbf_file"] == NEW


def test_refresh_skips_when_extract_came_from_latest(refresh, cfg):
    # An old meta built from the latest PBF: skip the filter, backfill pbf_file.
    refresh.meta.write_text(json.dumps({"pbf_sha256": SHA[NEW], "source_last_modified": LM[NEW]}))
    cfg.osm_extract_json.write_text("[]")
    osm_refresh.run()
    assert refresh.fetched == [False] and refresh.filtered == []
    assert json.loads(refresh.meta.read_text())["pbf_file"] == NEW


def test_refresh_refilters_when_store_moved_on(refresh, cfg):
    refresh.meta.write_text(json.dumps({"pbf_file": OLD, "pbf_sha256": SHA[OLD]}))
    cfg.osm_extract_json.write_text("[]")
    osm_refresh.run()
    assert refresh.filtered == [NEW]


def test_force_refetches_and_refilters(refresh, cfg):
    refresh.meta.write_text(json.dumps({"pbf_file": NEW, "pbf_sha256": SHA[NEW]}))
    cfg.osm_extract_json.write_text("[]")
    osm_refresh.run(force=True)
    assert refresh.fetched == [True] and refresh.filtered == [NEW]


def test_rebuild_rereads_the_recorded_file_without_fetching(refresh, cfg):
    refresh.meta.write_text(json.dumps({"pbf_sha256": SHA[OLD], "downloaded_at": "then"}))
    meta = osm_refresh.run(rebuild=True)
    assert refresh.fetched == [] and refresh.filtered == [OLD]
    assert meta["pbf_file"] == OLD and meta["downloaded_at"] == "then" and "rebuilt_at" in meta
