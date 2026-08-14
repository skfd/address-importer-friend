"""The [source_fields] projection recipe (multi-city Tier 2).

Two things are load-bearing here:

1. The Toronto guardrail — tool.db is living, so the SQL generated from
   Toronto's declaration must be byte-identical to the projection that was
   hardcoded in source_db before Tier 2. Any drift is a behaviour change.
2. Capability gating — an undeclared field must yield SQL NULL and visibly
   disable the checks that read it, never run them silently against nothing.
"""
import sqlite3

import pytest

from t2 import source_db
from t2.config import SourceFields, parse_source_fields
from t2.pipeline import _seed_toggles, unavailable_checks

TORONTO = SourceFields(
    street_from="street",
    full_from="full",
    municipality="props:MUNICIPALITY_NAME",
    ward="props:WARD_NAME",
    lo_num="props:LO_NUM",
    lo_num_suf="props:LO_NUM_SUF",
    hi_num="props:HI_NUM",
    hi_num_suf="props:HI_NUM_SUF",
    address_class="props:ADDRESS_CLASS_DESC",
)

HAMILTON = SourceFields(
    street_from="street",          # tracker maps street = FULL_STREET_NAME
    full_from="number+street",     # Hamilton publishes no combined column
    municipality="props:COMMUNITY",
    ward=None,
    lo_num=None, lo_num_suf=None, hi_num=None, hi_num_suf=None,
    address_class=None,
)

# The projection exactly as hardcoded before Tier 2 (source_db._ADDRESS_COLS
# at commit eeab5fe). Do not "fix" this string — it is the guardrail.
LEGACY_TORONTO_COLS = (
    "a.identity_key AS address_point_id, a.full AS address_full, "
    "a.number AS address_number, "
    "CAST(json_extract(a.props,'$.LO_NUM') AS INTEGER) AS lo_num, "
    "NULLIF(json_extract(a.props,'$.LO_NUM_SUF'),'None') AS lo_num_suf, "
    "CAST(json_extract(a.props,'$.HI_NUM') AS INTEGER) AS hi_num, "
    "NULLIF(json_extract(a.props,'$.HI_NUM_SUF'),'None') AS hi_num_suf, "
    "a.street AS linear_name_full, "
    "NULL AS linear_name, NULL AS linear_name_type, NULL AS linear_name_dir, "
    "json_extract(a.props,'$.MUNICIPALITY_NAME') AS municipality_name, "
    "json_extract(a.props,'$.WARD_NAME') AS ward_name, "
    "a.longitude, a.latitude, a.props AS extra"
)


def test_toronto_projection_is_byte_identical_to_legacy():
    assert source_db.build_address_cols(TORONTO) == LEGACY_TORONTO_COLS


def test_undeclared_fields_project_null():
    cols = source_db.build_address_cols(HAMILTON)
    assert "NULL AS lo_num" in cols
    assert "NULL AS hi_num_suf" in cols
    assert "NULL AS ward_name" in cols
    assert "json_extract(a.props,'$.COMMUNITY') AS municipality_name" in cols


def _tracker_db(rows):
    """In-memory DB shaped like an ontario-address-changes tracker."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE addresses (min_snapshot_id INTEGER, max_snapshot_id INTEGER, "
        "identity_key TEXT, number TEXT, street TEXT, unit TEXT, full TEXT, "
        "longitude REAL, latitude REAL, props TEXT, payload_hash TEXT)"
    )
    conn.executemany(
        "INSERT INTO addresses (max_snapshot_id, identity_key, number, street, full, props) "
        "VALUES (1, ?, ?, ?, ?, ?)",
        rows,
    )
    return conn


def test_hamilton_projection_against_tracker_shaped_db():
    conn = _tracker_db([
        ("k1", "50", "Amore Boulevard", None,
         '{"COMMUNITY": "Hamilton", "FULL_STREET_NAME": "Amore Boulevard"}'),
        ("k2", None, "Hall Road", None, '{"COMMUNITY": "Glanbrook"}'),
    ])
    cols = source_db.build_address_cols(HAMILTON)
    rows = {r["address_point_id"]: dict(r)
            for r in conn.execute(f"SELECT {cols} FROM addresses a")}

    assert rows["k1"]["address_full"] == "50 Amore Boulevard"
    assert rows["k1"]["linear_name_full"] == "Amore Boulevard"
    assert rows["k1"]["municipality_name"] == "Hamilton"
    assert rows["k1"]["lo_num"] is None
    assert rows["k1"]["ward_name"] is None
    # Synthesis degrades cleanly when number is missing: street alone, no
    # leading space, and never the empty string (NULLIF).
    assert rows["k2"]["address_full"] == "Hall Road"


def test_parse_requires_section():
    with pytest.raises(ValueError, match=r"missing \[source_fields\]"):
        parse_source_fields({})


def test_parse_rejects_unknown_key():
    with pytest.raises(ValueError, match="unknown key"):
        parse_source_fields(
            {"street_from": "street", "full_from": "full", "streetfrom": "street"}
        )


def test_parse_rejects_bad_specs():
    with pytest.raises(ValueError, match="street_from"):
        parse_source_fields({"street_from": "number+street", "full_from": "full"})
    with pytest.raises(ValueError, match="full_from"):
        parse_source_fields({"street_from": "street", "full_from": "props:X"})
    with pytest.raises(ValueError, match="lo_num"):
        # Optional fields must be props:<KEY>, and <KEY> may not carry SQL.
        parse_source_fields(
            {"street_from": "street", "full_from": "full", "lo_num": "props:LO'NUM"}
        )


def test_parse_roundtrips_toronto_and_hamilton():
    assert parse_source_fields({
        "street_from": "street", "full_from": "full",
        "municipality": "props:MUNICIPALITY_NAME", "ward": "props:WARD_NAME",
        "lo_num": "props:LO_NUM", "lo_num_suf": "props:LO_NUM_SUF",
        "hi_num": "props:HI_NUM", "hi_num_suf": "props:HI_NUM_SUF",
        "address_class": "props:ADDRESS_CLASS_DESC",
    }) == TORONTO
    assert parse_source_fields({
        "street_from": "street", "full_from": "number+street",
        "municipality": "props:COMMUNITY",
    }) == HAMILTON


def test_unavailable_checks_per_city():
    assert unavailable_checks(TORONTO) == {}
    assert unavailable_checks(HAMILTON) == {
        "suffix_range": "lo_num, hi_num",
        "intra_source_duplicate": "address_class",
    }


def _toggle_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE check_toggles (run_id INTEGER, check_id TEXT, enabled INTEGER, "
        "PRIMARY KEY (run_id, check_id))"
    )
    return conn


def test_seed_toggles_forces_unavailable_checks_off():
    conn = _toggle_conn()
    _seed_toggles(conn, 1, {}, unavailable=unavailable_checks(HAMILTON))
    got = {r["check_id"]: r["enabled"] for r in conn.execute("SELECT * FROM check_toggles")}
    assert got["suffix_range"] == 0
    assert got["intra_source_duplicate"] == 0
    assert got["match_far"] == 1  # untouched checks keep their defaults


def test_seed_toggles_refuses_explicitly_enabled_unavailable_check():
    # A config.toml that says `suffix_range = true` for a city whose source
    # has no ranges is lying — fail the run start loudly (03: never silently
    # open, and an explicit config line must not be silently overridden).
    conn = _toggle_conn()
    with pytest.raises(ValueError, match="suffix_range"):
        _seed_toggles(conn, 1, {"suffix_range": True},
                      unavailable=unavailable_checks(HAMILTON))
