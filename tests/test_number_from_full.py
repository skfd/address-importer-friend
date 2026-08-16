"""number_from = "full" + unit = "full-after-street" (Waterloo, 2026-08-16).

Waterloo publishes only CIVIC_ADDR: its tracker number column is 100% NULL
and 41.9% of rows carry a unit as the tail of the combined column
("29 BARREL YARDS BLVD 1205"). The number is the leading whitespace token;
the unit is whatever trails the street value inside full.
"""
import sqlite3

import pytest

from t2 import config as _config, source_db

WATERLOO = _config.SourceFields(
    street_from="street", full_from="full", number_from="full",
    municipality=None, ward=None, lo_num=None, lo_num_suf=None,
    hi_num=None, hi_num_suf=None, address_class=None,
    unit="full-after-street",
)


def _row(street, full):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE addresses (min_snapshot_id, max_snapshot_id, identity_key, "
        "number, street, unit, full, longitude, latitude, props, payload_hash)"
    )
    conn.execute(
        "INSERT INTO addresses VALUES (1, 5, 'k', NULL, ?, NULL, ?, -80.5, 43.5, '{}', NULL)",
        (street, full),
    )
    q = source_db.build_active_bbox_query(WATERLOO, False)
    return conn.execute(q, (5, 43.0, 44.0, -81.0, -80.0)).fetchone()


def test_number_is_leading_token():
    r = _row("PASTERN TRAIL", "213 PASTERN TRAIL")
    assert r["address_number"] == "213"
    assert r["address_full"] == "213 PASTERN TRAIL"


def test_letter_suffixed_number_survives():
    assert _row("BAIRSTOW CRES", "414B BAIRSTOW CRES")["address_number"] == "414B"


def test_unit_is_tail_after_street():
    conn_row = _row("BARREL YARDS BLVD", "29 BARREL YARDS BLVD 1205")
    assert conn_row["address_number"] == "29"
    # unit is not projected as a column; verify via the collapse partition
    # behaviour instead: two rows sharing (number, street) with different
    # tails collapse to the unit-less-looking representative.


def test_collapse_elects_no_tail_row():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE addresses (min_snapshot_id, max_snapshot_id, identity_key, "
        "number, street, unit, full, longitude, latitude, props, payload_hash)"
    )
    rows = [
        (1, 5, "k2", None, "BARREL YARDS BLVD", None, "29 BARREL YARDS BLVD 1205", -80.5, 43.5, "{}"),
        (1, 5, "k1", None, "BARREL YARDS BLVD", None, "29 BARREL YARDS BLVD", -80.5, 43.5, "{}"),
        (1, 5, "k3", None, "BARREL YARDS BLVD", None, "29 BARREL YARDS BLVD 903", -80.5, 43.5, "{}"),
    ]
    conn.executemany("INSERT INTO addresses VALUES (?,?,?,?,?,?,?,?,?,?,NULL)", rows)
    q = source_db.build_active_bbox_query(WATERLOO, True)
    got = [r["address_full"] for r in conn.execute(q, (5, 43.0, 44.0, -81.0, -80.0))]
    assert got == ["29 BARREL YARDS BLVD"]


def test_number_from_props_projects_the_declared_key():
    sf = _config.parse_source_fields(
        {"street_from": "street", "full_from": "full",
         "number_from": "props:ADDRESS"},
    )
    q = source_db.build_active_bbox_query(sf, False)
    assert "json_extract(a.props,'$.ADDRESS') AS address_number" in q

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE addresses (min_snapshot_id, max_snapshot_id, identity_key, "
        "number, street, unit, full, longitude, latitude, props, payload_hash)"
    )
    conn.execute(
        "INSERT INTO addresses VALUES (1, 5, 'k', '963', 'HOLT PL', NULL, "
        "'963 1/2 HOLT PL', -89.2, 48.4, '{\"ADDRESS\": \"963 1/2\"}', NULL)"
    )
    row = conn.execute(q, (5, 48.0, 49.0, -90.0, -89.0)).fetchone()
    assert row["address_number"] == "963 1/2"


def test_circular_number_from_full_is_rejected():
    with pytest.raises(ValueError, match="circular"):
        _config.parse_source_fields(
            {"street_from": "street", "full_from": "number+street",
             "number_from": "full"},
        )


def test_unit_tail_requires_real_full():
    with pytest.raises(ValueError, match="full-after-street"):
        _config.parse_source_fields(
            {"street_from": "street", "full_from": "number+street",
             "unit": "full-after-street", "number_from": "number"},
        )
