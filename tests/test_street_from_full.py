"""street_from = "full" derives the street by stripping the number prefix.

Never exercised before Barrie (2026-08-15): the branch projected the raw
combined column — housenumber included — which would mis-street every city
declaring it. Length-based stripping is deliberate: Barrie's dirty rows
("32PENNELL DR" without its space; KIRKWOOD WAY rows whose number disagrees
with full) all strip correctly by number length where token-splitting fails.
"""
import sqlite3

from t2 import config as _config, source_db

BARRIE = _config.SourceFields(
    street_from="full", full_from="full",
    municipality=None, ward=None, lo_num=None, lo_num_suf=None,
    hi_num=None, hi_num_suf=None, address_class=None,
)


def _street_of(number, full):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE addresses (min_snapshot_id, max_snapshot_id, identity_key, "
        "number, street, unit, full, longitude, latitude, props, payload_hash)"
    )
    conn.execute(
        "INSERT INTO addresses VALUES (1, 5, 'k', ?, NULL, NULL, ?, -79.0, 44.0, '{}', NULL)",
        (number, full),
    )
    q = source_db.build_active_bbox_query(BARRIE, False)
    return conn.execute(q, (5, 43.0, 45.0, -80.0, -78.0)).fetchone()["linear_name_full"]


def test_strips_number_prefix():
    assert _street_of("204", "204 ALVA ST") == "ALVA ST"
    assert _street_of("236A", "236A BAYFIELD ST") == "BAYFIELD ST"


def test_dirty_rows_strip_by_length_not_prefix():
    assert _street_of("32", "32PENNELL DR") == "PENNELL DR"
    assert _street_of("114", "110 KIRKWOOD WAY") == "KIRKWOOD WAY"


def test_full_column_itself_is_untouched():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE addresses (min_snapshot_id, max_snapshot_id, identity_key, "
        "number, street, unit, full, longitude, latitude, props, payload_hash)"
    )
    conn.execute(
        "INSERT INTO addresses VALUES (1, 5, 'k', '204', NULL, NULL, "
        "'204 ALVA ST', -79.0, 44.0, '{}', NULL)"
    )
    q = source_db.build_active_bbox_query(BARRIE, False)
    row = conn.execute(q, (5, 43.0, 45.0, -80.0, -78.0)).fetchone()
    assert row["address_full"] == "204 ALVA ST"
