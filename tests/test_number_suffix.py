"""number_suffix = "props:<KEY>" (Guelph, 2026-10-03).

Guelph publishes 155A Bristol Street as STREETNO "155" + QUALIFIER "A". With
the number taken from the integer-ish column alone, 155A read as 155: its
points carried the wrong addr:housenumber and its civic group merged with
155's, so two buildings' units were judged as one. The suffix is appended to
whatever number_from projects, upper-cased, no space.
"""
import sqlite3

import pytest

from t2 import config as _config, source_db

GUELPH = _config.parse_source_fields(
    {"street_from": "street", "full_from": "number+street",
     "municipality": "props:PLACE", "unit": "unit",
     "number_suffix": "props:QUALIFIER"},
)


def _db(rows):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE addresses (min_snapshot_id, max_snapshot_id, identity_key, "
        "number, street, unit, full, longitude, latitude, props, payload_hash)"
    )
    conn.executemany(
        "INSERT INTO addresses VALUES (1, 5, ?, ?, 'Bristol Street', ?, NULL, "
        "-80.2, 43.5, ?, NULL)",
        rows,
    )
    return conn


def _props(q):
    return '{"PLACE": "Guelph"}' if q is ... else (
        '{"PLACE": "Guelph", "QUALIFIER": %s}' % ("null" if q is None else f'"{q}"')
    )


@pytest.mark.parametrize("qualifier, expected", [
    (..., "155"),        # key absent
    (None, "155"),       # JSON null — Guelph's 53,641 unqualified rows
    ("", "155"),
    ("None", "155"),     # the tracker's literal for an empty prop
    ("A", "155A"),
    ("a", "155A"),
    (" B1 ", "155B1"),
])
def test_suffix_is_appended_upper_cased(qualifier, expected):
    conn = _db([("k", "155", None, _props(qualifier))])
    q = source_db.build_active_bbox_query(GUELPH, False)
    row = conn.execute(q, (5, 43.0, 44.0, -81.0, -80.0)).fetchone()
    assert row["address_number"] == expected
    assert row["address_full"] == f"{expected} Bristol Street"


def test_missing_number_stays_missing():
    conn = _db([("k", None, None, _props("A"))])
    q = source_db.build_active_bbox_query(GUELPH, False)
    row = conn.execute(q, (5, 43.0, 44.0, -81.0, -80.0)).fetchone()
    assert row["address_number"] is None


def test_qualified_civic_is_its_own_group():
    # 155 and 155A each publish a plain point and units B, C. Keyed on the
    # bare number they were one group with every unit twice.
    conn = _db([
        ("k1", "155", None, _props(None)),
        ("k2", "155", "B", _props(None)),
        ("k3", "155", "C", _props(None)),
        ("k4", "155", None, _props("A")),
        ("k5", "155", "B", _props("A")),
        ("k6", "155", "C", _props("A")),
    ])
    groups = {}
    for r in conn.execute(source_db.build_civic_group_query(GUELPH), {"snap": 5}):
        groups.setdefault(source_db.civic_key(dict(r)), []).append(r["unit_name"])
    assert {k: sorted(u or "" for u in v) for k, v in groups.items()} == {
        ("155", "Bristol Street", "Guelph"): ["", "B", "C"],
        ("155A", "Bristol Street", "Guelph"): ["", "B", "C"],
    }

    q = source_db.build_active_bbox_query(GUELPH, True)
    got = sorted(r["address_number"] for r in conn.execute(q, (5, 43.0, 44.0, -81.0, -80.0)))
    assert got == ["155", "155A"]


def test_undeclared_suffix_leaves_number_untouched():
    sf = _config.parse_source_fields({"street_from": "street", "full_from": "full"})
    assert sf.number_suffix is None
    assert source_db.field_sql(sf, "number") == "a.number"


def test_suffix_must_be_a_props_key():
    with pytest.raises(ValueError, match="number_suffix"):
        _config.parse_source_fields(
            {"street_from": "street", "full_from": "full", "number_suffix": "unit"},
        )
