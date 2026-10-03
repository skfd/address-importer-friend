"""[source_fields] postcode: the source's own postal code on created nodes.

Guelph's layer carries POSTCODE on 48,957 of 53,847 active rows (snapshot 47),
and its 2025 import wrote it; until 2026-10-03 the engine wrote addr:postcode
only from a same-address POI. The source value now leads, the POI stays the
fallback, and a value that is not a postal code or not in the city's declared
forward sortation areas is omitted and audited — never repaired.

A city that declares no postcode (Toronto, the suite's config) must be
byte-identical: no column value, no audit key, the POI fallback as before.
"""
import json
import xml.etree.ElementTree as ET

import pytest

from t2 import candidates, config as _config, db as _db, osm_export
from t2.checks.base import Candidate
from t2.checks.postcode_mismatch import PostcodeMismatchCheck
from t2.conflate import _proposed_tags
from t2.pipeline import unavailable_checks

GUELPH_FSAS = ("N1C", "N1E", "N1G", "N1H", "N1K", "N1L")


def _sf(**kw):
    return _config.SourceFields(
        street_from="street", full_from="number+street",
        municipality=None, ward=None, lo_num=None, lo_num_suf=None,
        hi_num=None, hi_num_suf=None, address_class=None, **kw,
    )


WITH_POSTCODE = _sf(postcode="props:POSTCODE")
WITHOUT = _sf()


# ------------------------------------------------------------------ config

def test_the_field_is_declared_like_any_other_optional_prop():
    sf = _config.parse_source_fields(
        {"street_from": "street", "full_from": "number+street",
         "postcode": "props:POSTCODE"}
    )
    assert sf.postcode_key == "POSTCODE"
    assert _config.parse_source_fields(
        {"street_from": "street", "full_from": "full"}
    ).postcode_key is None


def test_declaring_postcode_without_prefixes_is_refused():
    with pytest.raises(ValueError, match="no \\[postcode\\] prefixes"):
        _config.parse_postcode_policy({}, WITH_POSTCODE)


def test_prefixes_without_a_declared_postcode_are_refused():
    with pytest.raises(ValueError, match="declares no postcode field"):
        _config.parse_postcode_policy({"prefixes": ["N1E"]}, WITHOUT)


@pytest.mark.parametrize("bad", [[], "N1E", ["n1e"], ["N1"], ["N1E 1A1"], ["D1E"]])
def test_malformed_prefixes_are_refused(bad):
    with pytest.raises(ValueError, match="invalid"):
        _config.parse_postcode_policy({"prefixes": bad}, WITH_POSTCODE)


def test_unknown_keys_are_refused():
    with pytest.raises(ValueError, match="unknown key"):
        _config.parse_postcode_policy({"fsas": ["N1E"]}, WITH_POSTCODE)


def test_no_declaration_is_no_policy():
    assert _config.parse_postcode_policy({}, WITHOUT) is None
    assert _config.parse_postcode_policy(
        {"prefixes": list(GUELPH_FSAS)}, WITH_POSTCODE
    ) == GUELPH_FSAS


# --------------------------------------------------------------- the check

@pytest.mark.parametrize("raw, want", [
    ("N1H 4E2", "N1H 4E2"),
    ("N1H4E2", "N1H 4E2"),      # the one way a value is repaired: its space
    ("  n1g 2w1 ", "N1G 2W1"),
    ("N1K 1A1", "N1K 1A1"),     # 595 Governors Road, the one Eramosa row with one
])
def test_good_values_are_normalized(raw, want):
    assert _config.check_postcode(raw, GUELPH_FSAS) == (want, None)


# Every bad value in Guelph's layer at snapshot 47, by ADDID.
@pytest.mark.parametrize("raw, why", [
    ("K8V 5P4", "prefix"),   # 9539, 254 Colonial Drive (Peterborough area)
    ("M6N 2N8", "prefix"),   # 48658, 91 Poppy Drive East unit 14 (Toronto)
    ("L7P 0N4", "prefix"),   # 51877, 88 Decorso Drive (Burlington)
    ("N0L 0H1", "prefix"),   # 30480 and 55312, Lambeth Way
    ("N0B 1C0", "prefix"),   # 18992, 1 Cox Court
    ("N1B 0B8", "prefix"),   # 43586, 1423 Gordon Street
    ("0", "format"),         # 53855, 82 Farquhar Street
    ("N1H 4E", "format"),
    ("N1H 4E22", "format"),
    ("NIH 4E2", "format"),   # letter I for digit 1
    ("D1H 4E2", "format"),   # D never appears
])
def test_bad_values_are_omitted_not_guessed(raw, why):
    assert _config.check_postcode(raw, GUELPH_FSAS) == (None, why)


@pytest.mark.parametrize("raw", [None, "", "   ", "None"])
def test_absence_is_not_a_rejection(raw):
    assert _config.check_postcode(raw, GUELPH_FSAS) == (None, "empty")


# ---------------------------------------------------------------- ingest

def _row(postcode=None, **props):
    if postcode is not None:
        props["POSTCODE"] = postcode
    return {"address_point_id": 9539, "address_full": "254 Colonial Drive",
            "address_number": "254", "linear_name_full": "Colonial Drive",
            "latitude": 43.5, "longitude": -80.2, "extra": json.dumps(props)}


def _ingested_postcode(row):
    values = candidates._candidate_values(1, row, "2026-10-03T00:00:00Z")
    return values[candidates._INSERT_SQL.split("(", 1)[1].split(")")[0]
                  .replace("\n", "").replace(" ", "").split(",").index("postcode")]


def test_toronto_ingests_no_postcode_even_when_its_props_carry_one():
    assert candidates._SOURCE_FIELDS.postcode_key is None
    assert _ingested_postcode(_row("N1H 4E2")) is None
    assert candidates._postcode_tally(3) == {}


@pytest.fixture
def guelph(monkeypatch):
    monkeypatch.setattr(candidates, "_SOURCE_FIELDS", WITH_POSTCODE)
    monkeypatch.setattr(candidates, "_POSTCODE_PREFIXES", GUELPH_FSAS)


def test_a_declared_city_ingests_the_normalized_value(guelph):
    assert _ingested_postcode(_row("N1H4E2")) == "N1H 4E2"
    assert _ingested_postcode(_row("K8V 5P4")) is None
    assert _ingested_postcode(_row()) is None
    assert candidates._postcode_tally(0) == {"postcode_rejected": 0}


@pytest.fixture
def tool_db(tmp_path, monkeypatch):
    monkeypatch.setattr(_db._CONFIG, "tool_db_path", tmp_path / "tool.db")
    monkeypatch.setattr(_db._CONFIG, "data_dir", tmp_path)
    _db.migrate()
    return tmp_path


def test_a_rejection_is_audited_with_its_value(guelph, tool_db):
    conn = _db.connect()
    try:
        assert candidates._log_postcode_rejection(conn, 1, _row("K8V 5P4"))
        assert not candidates._log_postcode_rejection(conn, 1, _row("N1H 4E2"))
        assert not candidates._log_postcode_rejection(conn, 1, _row())
        rows = conn.execute(
            "SELECT event_type, payload_json FROM events "
            "WHERE event_type = 'POSTCODE_REJECTED'"
        ).fetchall()
    finally:
        conn.close()
    assert [json.loads(r["payload_json"]) for r in rows] == [
        {"value": "K8V 5P4", "reason": "prefix"}
    ]


# ------------------------------------------------------------------ tags

ITEM = {"candidate_id": 1, "local_node_id": -1, "housenumber": "254",
        "street_raw": "Colonial Drive", "lat": 43.5, "lon": -80.2}


def test_the_source_postcode_outranks_the_poi():
    it = dict(ITEM, postcode="N1H 4E2", proposed_postcode="N1G 1A1")
    assert osm_export.build_tags(it)["addr:postcode"] == "N1H 4E2"
    assert _proposed_tags(it)["addr:postcode"] == "N1H 4E2"


def test_the_poi_still_fills_a_row_with_none():
    it = dict(ITEM, postcode=None, proposed_postcode="N1G 1A1")
    assert osm_export.build_tags(it)["addr:postcode"] == "N1G 1A1"


def test_neither_means_no_tag():
    assert "addr:postcode" not in osm_export.build_tags(dict(ITEM, postcode=None))


def test_the_upload_query_carries_the_column(tool_db):
    """Through the real SELECT, the way test_upload_items pins unit and flats."""
    conn = _db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO runs (run_id, name, bbox_min_lat, bbox_min_lon, "
            "bbox_max_lat, bbox_max_lon, created_at, config_json) "
            "VALUES (7, 'tile-7', 0, 0, 1, 1, '2026-10-03T00:00:00Z', '{}')"
        )
        conn.execute(
            "INSERT INTO candidates (run_id, candidate_id, housenumber, street_raw, "
            "lat, lon, postcode, stage, stage_updated_at) VALUES "
            "(7, 5, '254', 'Colonial Drive', 43.5, -80.2, 'N1H 4E2', 'APPROVED', 'x')"
        )
        conn.execute("COMMIT")
    finally:
        conn.close()
    items = osm_export._assign_local_node_ids(7, osm_export._load_upload_items(7))
    root = ET.fromstring(osm_export._osm_change_xml(items))
    tags = {t.attrib["k"]: t.attrib["v"] for t in root.findall("./node/tag")}
    assert tags["addr:postcode"] == "N1H 4E2"


# ------------------------------------------------------- postcode_mismatch

def _cand(postcode, osm_postcode, verdict="MATCH"):
    tags = {"addr:housenumber": "1", "addr:street": "Wyndham Street North"}
    if osm_postcode is not None:
        tags["addr:postcode"] = osm_postcode
    return Candidate(
        run_id=1, candidate_id=1, address_full=None, housenumber="1",
        street_raw="Wyndham Street North", street_norm=None, lat=43.5, lon=-80.2,
        lo_num=None, lo_num_suf=None, hi_num=None, hi_num_suf=None,
        verdict=verdict, nearest_osm_id=42, nearest_osm_type="node",
        nearest_dist_m=3.0, matched_osm_tags=tags, postcode=postcode,
    )


CHECK = PostcodeMismatchCheck()


def test_a_different_postcode_on_the_matched_object_is_flagged():
    v = CHECK.evaluate(_cand("N1L 0A6", "N1L 0Z6"), None)
    assert (v.status, v.reason_code) == ("FLAG", "postcode_mismatch")
    assert v.details["source_postcode"] == "N1L 0A6"
    assert v.details["osm_postcode"] == "N1L 0Z6"


def test_spacing_and_case_are_not_a_disagreement():
    assert CHECK.evaluate(_cand("N1H 4E2", "n1h4e2"), None).status == "PASS"


@pytest.mark.parametrize("cand", [
    _cand("N1H 4E2", "N1G 1A1", verdict="MISSING"),   # nothing matched
    _cand(None, "N1G 1A1"),                           # source has none usable
    _cand("N1H 4E2", None),                           # OSM has none: beholder's
])
def test_it_applies_only_where_both_sides_have_one(cand):
    assert not CHECK.applies(cand, None)


def test_a_city_without_postcode_cannot_run_it():
    assert unavailable_checks(WITHOUT)["postcode_mismatch"] == "postcode"
    assert "postcode_mismatch" not in unavailable_checks(WITH_POSTCODE)


# ------------------------------------------------- collapsed buildings

def _member(aid, postcode, unit=None):
    row = _row(postcode)
    return dict(row, address_point_id=aid, unit_name=unit)


def test_a_building_takes_the_one_postcode_its_rows_agree_on(guelph):
    # The elected row has none; its units do, and they agree.
    group = [_member(1, None), _member(2, "N1H 7J7", "101"), _member(3, "N1H7J7", "102")]
    rep = candidates._with_group_postcodes(candidates._elect(group), group)
    assert rep["address_point_id"] == 1
    assert candidates._source_postcode(rep) == ("N1H 7J7", "N1H 7J7", None)


def test_a_building_whose_rows_disagree_gets_none(guelph, tool_db):
    # 180 Marksam Road: four valid postcodes across one civic group.
    group = [_member(1, "N1H 8G4"), _member(2, "N1H 8G6", "2"), _member(3, "K8V 5P4", "3")]
    rep = candidates._with_group_postcodes(candidates._elect(group), group)
    assert candidates._source_postcode(rep) == (None, ["N1H 8G4", "N1H 8G6"], "ambiguous")
    conn = _db.connect()
    try:
        assert candidates._log_postcode_rejection(conn, 1, rep)
        payload = conn.execute(
            "SELECT payload_json FROM events WHERE event_type = 'POSTCODE_REJECTED'"
        ).fetchone()["payload_json"]
    finally:
        conn.close()
    assert json.loads(payload) == {"value": ["N1H 8G4", "N1H 8G6"], "reason": "ambiguous"}


def test_the_collapse_branch_of_emit_group_decides_for_the_group(guelph):
    tower = [_member(i, "N1H 8G4" if i % 2 else "N1H 8G6", f"{100 + i}") for i in range(1, 30)]
    for i, r in enumerate(tower):  # stacked on one point: a tower, collapsed
        r["latitude"], r["longitude"] = 43.5, -80.2
    emitted = list(candidates._emit_group(tower, lambda r: True))
    assert len(emitted) == 1
    assert candidates._source_postcode(emitted[0][0])[2] == "ambiguous"


def test_toronto_emissions_are_untouched():
    row = _member(1, "N1H 8G4")
    assert candidates._with_group_postcodes(row, [row]) is row
