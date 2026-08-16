"""Lifecycle-status filtering (TODO §11, 2026-08-15).

Barrie publishes 3,369 Pending + 49 Temporary rows; the Niagara Region 260
Proposed. A declared [source_fields] status obliges a [status] active_values
list (the units lie-together pattern), and the source queries then exclude
every row whose status is not in the list — NULL included. No declaration =
byte-identical queries (the Toronto guardrail).
"""
import sqlite3

import pytest

from t2 import config as _config, source_db

BARRIE = _config.SourceFields(
    street_from="street", full_from="full",
    municipality=None, ward=None, lo_num=None, lo_num_suf=None,
    hi_num=None, hi_num_suf=None, address_class=None,
    unit="unit", status="props:STATUS",
)
NO_STATUS = _config.SourceFields(
    street_from="street", full_from="full",
    municipality=None, ward=None, lo_num=None, lo_num_suf=None,
    hi_num=None, hi_num_suf=None, address_class=None,
)


def test_declared_status_without_policy_is_rejected():
    with pytest.raises(ValueError, match="active_values"):
        _config.parse_status_policy({}, BARRIE)


def test_policy_without_declared_status_is_rejected():
    with pytest.raises(ValueError, match="declares no status field"):
        _config.parse_status_policy({"active_values": ["Current"]}, NO_STATUS)


def test_unknown_keys_and_bad_values_are_rejected():
    with pytest.raises(ValueError, match="unknown key"):
        _config.parse_status_policy({"values": ["Current"]}, BARRIE)
    for bad in ([], ["Current", ""], "Current", [1]):
        with pytest.raises(ValueError, match="active_values"):
            _config.parse_status_policy({"active_values": bad}, BARRIE)


def test_valid_policy_parses():
    assert _config.parse_status_policy(
        {"active_values": ["Current", "Temporary"]}, BARRIE
    ) == ("Current", "Temporary")
    assert _config.parse_status_policy({}, NO_STATUS) is None


def test_no_policy_leaves_queries_byte_identical():
    for build in (
        source_db.build_active_bbox_query,
        source_db.build_new_since_query,
        source_db.build_retired_since_query,
    ):
        assert build(BARRIE, False) == build(BARRIE, False, None)
        assert "STATUS" not in build(NO_STATUS, False, None)


def _mkdb():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE addresses (min_snapshot_id, max_snapshot_id, identity_key, "
        "number, street, unit, full, longitude, latitude, props, payload_hash)"
    )
    rows = [
        (1, 5, "k1", "10", "MAIN ST", None, "10 MAIN ST", -79.0, 44.0, '{"STATUS": "Current"}'),
        (1, 5, "k2", "12", "MAIN ST", None, "12 MAIN ST", -79.0, 44.0, '{"STATUS": "Pending"}'),
        (1, 5, "k3", "14", "MAIN ST", None, "14 MAIN ST", -79.0, 44.0, "{}"),
    ]
    conn.executemany(
        "INSERT INTO addresses VALUES (?,?,?,?,?,?,?,?,?,?,NULL)", rows
    )
    return conn


def test_active_query_filters_pending_and_null_status():
    conn = _mkdb()
    q = source_db.build_active_bbox_query(BARRIE, False, ("Current",))
    got = [r["address_number"] for r in conn.execute(q, (5, 43.0, 45.0, -80.0, -78.0))]
    assert got == ["10"]


def test_active_query_unfiltered_without_policy():
    conn = _mkdb()
    q = source_db.build_active_bbox_query(BARRIE, False, None)
    got = {r["address_number"] for r in conn.execute(q, (5, 43.0, 45.0, -80.0, -78.0))}
    assert got == {"10", "12", "14"}


def test_collapse_variant_filters_before_ranking():
    # A Pending unit-less row must not be elected representative over a
    # Current unit row at the same civic address.
    conn = _mkdb()
    conn.execute(
        "INSERT INTO addresses VALUES (1, 5, 'k4', '10', 'MAIN ST', '2', "
        "'10 MAIN ST', -79.0, 44.0, '{\"STATUS\": \"Current\"}', NULL)"
    )
    conn.execute(
        "UPDATE addresses SET props = '{\"STATUS\": \"Pending\"}' WHERE identity_key = 'k1'"
    )
    q = source_db.build_active_bbox_query(BARRIE, True, ("Current",))
    got = [
        (r["address_number"], r["extra"])
        for r in conn.execute(q, (5, 43.0, 45.0, -80.0, -78.0))
    ]
    assert [g[0] for g in got] == ["10"]
    assert "Current" in got[0][1]
