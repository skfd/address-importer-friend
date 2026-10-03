"""Housenumbers a city declares are not addresses (`[skip] housenumbers`).

Guelph publishes 13 active placeholder points under STREETNO "0" -- two of
them bridges -- and 11 auto-approved as addr:housenumber=0. A declared number
is SKIPPED at conflation like a range, ahead of matching, and carries the
city's reason in the audit log. Pins: the parser is loud, the skip lands, it
beats a nearby OSM match, the stage ends SKIPPED, and with nothing declared
the same candidates conflate exactly as before.
"""
import json

import pytest

from t2 import config as _config, conflate, db as _db, osm_fetch, pipeline

REASON = "Placeholder point with no civic number"


def test_absent_section_skips_nothing():
    assert _config.parse_skip_housenumbers({}) == {}
    assert _config.parse_skip_housenumbers({"housenumbers": {}}) == {}


def test_valid_section_parses_and_trims_the_reason():
    assert _config.parse_skip_housenumbers(
        {"housenumbers": {"0": f"  {REASON} "}}
    ) == {"0": REASON}


def test_unknown_keys_and_bad_values_are_rejected():
    with pytest.raises(ValueError, match="unknown key"):
        _config.parse_skip_housenumbers({"numbers": {"0": REASON}})
    with pytest.raises(ValueError, match="table"):
        _config.parse_skip_housenumbers({"housenumbers": ["0"]})
    for bad in ("", "   ", 1, None):
        with pytest.raises(ValueError, match="no reason"):
            _config.parse_skip_housenumbers({"housenumbers": {"0": bad}})
    for key in ("", " 0", "0 "):
        with pytest.raises(ValueError, match="blank or padded"):
            _config.parse_skip_housenumbers({"housenumbers": {key: REASON}})


def test_the_example_config_declares_none():
    # The suite's city is config.example.toml; the section stays commented
    # out there so Toronto-shaped checkouts copied from it skip nothing.
    assert _config.load().skip_housenumbers == {}
    assert conflate._SKIP_HOUSENUMBERS == {}


# --- conflate.run ------------------------------------------------------------


@pytest.fixture
def tool_db(tmp_path, monkeypatch):
    monkeypatch.setattr(_db._CONFIG, "tool_db_path", tmp_path / "tool.db")
    monkeypatch.setattr(_db._CONFIG, "data_dir", tmp_path)
    _db.migrate()
    with _db.tx() as conn:
        conn.execute(
            "INSERT INTO runs (run_id, name, bbox_min_lat, bbox_min_lon, bbox_max_lat, "
            "bbox_max_lon, created_at, config_json) VALUES (1, 'r', 0, 0, 90, 0, 't', '{}')"
        )
        for cid, number in ((10, "0"), (11, "12"), (12, "10")):
            conn.execute(
                "INSERT INTO candidates (run_id, candidate_id, address_full, housenumber, "
                "street_raw, street_norm, lat, lon, stage, stage_updated_at) "
                "VALUES (1, ?, ?, ?, 'Norwich Street East', 'NORWICH ST E', 43.5, -80.2, "
                "'INGESTED', 't')",
                (cid, f"{number} Norwich Street East", number),
            )
    # OSM happens to carry a "0" at the bridge and a real 10; 12 is missing.
    monkeypatch.setattr(osm_fetch, "load_cached", lambda run_id: [
        {"type": "node", "id": n, "lat": 43.5, "lon": -80.2,
         "tags": {"addr:housenumber": hn, "addr:street": "Norwich Street East"}}
        for n, hn in ((1, "0"), (2, "10"))
    ])
    return tmp_path


def _rows(sql):
    conn = _db.connect()
    try:
        return [dict(r) for r in conn.execute(sql)]
    finally:
        conn.close()


def test_a_declared_number_is_skipped_with_its_reason(tool_db, monkeypatch):
    monkeypatch.setattr(conflate, "_SKIP_HOUSENUMBERS", {"0": REASON})
    counts = conflate.run(1, "hash", 100.0, 15.0)
    assert counts["SKIPPED"] == 1 and counts["MISSING"] == 1 and counts["MATCH"] == 1
    by = {r["candidate_id"]: r for r in _rows("SELECT * FROM conflation")}
    # Skipped, not MATCHed: a placeholder is never "already in OSM", and the
    # skip records no OSM element against it.
    assert by[10]["verdict"] == "SKIPPED" and by[10]["nearest_osm_id"] is None
    assert by[11]["verdict"] == "MISSING" and by[12]["verdict"] == "MATCH"
    events = _rows("SELECT candidate_id, payload_json FROM events WHERE event_type = 'HOUSENUMBER_SKIPPED'")
    assert [(e["candidate_id"], json.loads(e["payload_json"])) for e in events] == [
        (10, {"housenumber": "0", "reason": REASON})
    ]

    # run_checks does nothing without an enabled check; match_far only looks
    # at MATCH_FAR, so it routes these three by verdict alone.
    with _db.tx() as conn:
        pipeline._ensure_checks_catalog(conn)
        conn.execute("INSERT INTO check_toggles (run_id, check_id, enabled) VALUES (1, 'match_far', 1)")
    pipeline.run_checks(1)
    stages = {r["candidate_id"]: r["stage"] for r in _rows("SELECT candidate_id, stage FROM candidates")}
    assert stages == {10: "SKIPPED", 11: "APPROVED", 12: "SKIPPED"}


def test_with_nothing_declared_the_same_run_conflates_as_before(tool_db, monkeypatch):
    monkeypatch.setattr(conflate, "_SKIP_HOUSENUMBERS", {})
    conflate.run(1, "hash", 100.0, 15.0)
    by = {r["candidate_id"]: r["verdict"] for r in _rows("SELECT candidate_id, verdict FROM conflation")}
    assert by == {10: "MATCH", 11: "MISSING", 12: "MATCH"}
    assert not _rows("SELECT 1 FROM events WHERE event_type = 'HOUSENUMBER_SKIPPED'")
