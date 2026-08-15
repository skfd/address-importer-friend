"""collapse-to-civic (multi-city 09-units.md, option 2 — taken for Hamilton
2026-08-14).

What is load-bearing:

1. The collapse key is (number, street, MUNICIPALITY) — an amalgamated city
   reuses street names across former municipalities (Hamilton: 776
   (number, street) pairs span communities), so a bare (number, street) key
   would merge genuinely distinct civic addresses.
2. Representative election is deterministic: the unit-less row when one
   exists, else the lowest identity_key — candidate ids must be stable
   across runs.
3. No policy → the exact pre-collapse behaviour (the Toronto guardrail).
"""
import sqlite3

import pytest

from t2 import source_db
from t2.config import SourceFields, parse_source_fields, parse_units_policy

HAMILTON = SourceFields(
    street_from="street",
    full_from="number+street",
    municipality="props:COMMUNITY",
    ward=None,
    lo_num=None, lo_num_suf=None, hi_num=None, hi_num_suf=None,
    address_class=None,
    unit="props:UNIT_NUMBER_COMPLETE",
)

BBOX_PARAMS = (1, 43.0, 44.0, -80.0, -79.0)  # snapshot 1, lat/lon bands


def _db(rows):
    """Tracker-shaped DB. rows: (min_snap, max_snap, identity_key, number,
    street, community, unit_or_None)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE addresses (min_snapshot_id INTEGER, max_snapshot_id INTEGER, "
        "identity_key TEXT, number TEXT, street TEXT, unit TEXT, full TEXT, "
        "longitude REAL, latitude REAL, props TEXT, payload_hash TEXT)"
    )
    import json
    for mn, mx, key, number, street, community, unit in rows:
        props = {"COMMUNITY": community}
        if unit is not None:
            props["UNIT_NUMBER_COMPLETE"] = unit
        conn.execute(
            "INSERT INTO addresses (min_snapshot_id, max_snapshot_id, identity_key, "
            "number, street, longitude, latitude, props) VALUES (?,?,?,?,?,?,?,?)",
            (mn, mx, key, number, street, -79.5, 43.5, json.dumps(props)),
        )
    return conn


def _active(conn, collapse=True):
    q = source_db.build_active_bbox_query(HAMILTON, collapse)
    return [dict(r) for r in conn.execute(q, BBOX_PARAMS)]


def test_stack_collapses_to_unitless_representative():
    conn = _db([
        (1, 1, "syn:b", "75", "James Street South", "Hamilton", "101"),
        (1, 1, "syn:a", "75", "James Street South", "Hamilton", None),
        (1, 1, "syn:c", "75", "James Street South", "Hamilton", "102"),
    ])
    rows = _active(conn)
    assert [r["address_point_id"] for r in rows] == ["syn:a"]


def test_unit_only_stack_keeps_lowest_identity_key():
    conn = _db([
        (1, 1, "syn:x2", "30", "Times Square Boulevard", "Stoney Creek", "5"),
        (1, 1, "syn:x1", "30", "Times Square Boulevard", "Stoney Creek", "7"),
    ])
    rows = _active(conn)
    assert [r["address_point_id"] for r in rows] == ["syn:x1"]


def test_same_street_different_community_not_merged():
    # King Street exists in Hamilton, Dundas and Stoney Creek — same civic
    # number in two former municipalities is two addresses, not a stack.
    conn = _db([
        (1, 1, "syn:h", "1", "King Street East", "Hamilton", None),
        (1, 1, "syn:d", "1", "King Street East", "Dundas", None),
    ])
    assert len(_active(conn)) == 2


def test_empty_and_literal_none_units_count_as_unitless():
    # '' and the literal string 'None' both mean "no unit"; a row carrying
    # them must beat a real unit row in the election.
    conn = _db([
        (1, 1, "syn:z9", "10", "Hall Road", "Glanbrook", "4"),
        (1, 1, "syn:zz", "10", "Hall Road", "Glanbrook", "None"),
        (1, 1, "syn:za", "11", "Hall Road", "Glanbrook", "2"),
        (1, 1, "syn:zb", "11", "Hall Road", "Glanbrook", ""),
    ])
    got = {r["address_point_id"] for r in _active(conn)}
    assert got == {"syn:zz", "syn:zb"}


def test_no_policy_keeps_every_row():
    conn = _db([
        (1, 1, "syn:b", "75", "James Street South", "Hamilton", "101"),
        (1, 1, "syn:a", "75", "James Street South", "Hamilton", None),
    ])
    assert len(_active(conn, collapse=False)) == 2


def test_new_unit_row_at_existing_civic_is_not_new():
    # Snapshot 2 adds a unit row to a civic address whose base row predates
    # the watermark: nothing genuinely new happened at street level.
    conn = _db([
        (1, 2, "syn:a", "75", "James Street South", "Hamilton", None),
        (2, 2, "syn:b", "75", "James Street South", "Hamilton", "101"),
        (2, 2, "syn:n", "9", "New Street", "Hamilton", None),
    ])
    q = source_db.build_new_since_query(HAMILTON, collapse=True)
    got = [r["address_point_id"] for r in conn.execute(q, {"wm": 1, "snap": 2})]
    assert got == ["syn:n"]


def test_wholly_retired_stack_flags_one_deletion():
    # All rows of one civic retire at snapshot 1 (active set is snapshot 2):
    # one deletion candidate, and the unit-less representative carries it.
    conn = _db([
        (1, 1, "syn:b", "75", "James Street South", "Hamilton", "101"),
        (1, 1, "syn:a", "75", "James Street South", "Hamilton", None),
        (1, 2, "syn:k", "1", "King Street East", "Hamilton", None),
    ])
    q = source_db.build_retired_since_query(HAMILTON, collapse=True)
    got = [r["address_point_id"] for r in conn.execute(q, {"wm": 1, "snap": 2})]
    assert got == ["syn:a"]


def test_partially_retired_stack_flags_nothing():
    # Unit rows retire but the civic's base row is still active: the re-issue
    # exclusion suppresses them (same number+street alive under another key).
    conn = _db([
        (1, 2, "syn:a", "75", "James Street South", "Hamilton", None),
        (1, 1, "syn:b", "75", "James Street South", "Hamilton", "101"),
    ])
    q = source_db.build_retired_since_query(HAMILTON, collapse=True)
    assert list(conn.execute(q, {"wm": 1, "snap": 2})) == []


# --- config contract ---------------------------------------------------------

BASE = {"street_from": "street", "full_from": "full"}


def test_declared_unit_without_policy_raises():
    sf = parse_source_fields({**BASE, "unit": "props:UNIT_NUMBER_COMPLETE"})
    with pytest.raises(ValueError, match=r"no \[units\] policy"):
        parse_units_policy({}, sf)


def test_policy_without_declared_unit_raises():
    sf = parse_source_fields(BASE)
    with pytest.raises(ValueError, match="no unit field"):
        parse_units_policy({"policy": "collapse-to-civic"}, sf)


def test_unknown_policy_raises():
    sf = parse_source_fields({**BASE, "unit": "unit"})
    with pytest.raises(ValueError, match="invalid"):
        parse_units_policy({"policy": "keep-units"}, sf)


def test_unknown_units_key_raises():
    sf = parse_source_fields(BASE)
    with pytest.raises(ValueError, match="unknown key"):
        parse_units_policy({"polcy": "collapse-to-civic"}, sf)


def test_valid_pair_parses():
    sf = parse_source_fields({**BASE, "unit": "props:UNIT_NO"})
    assert parse_units_policy({"policy": "collapse-to-civic"}, sf) == "collapse-to-civic"
    assert parse_units_policy({}, parse_source_fields(BASE)) is None


def test_unit_spec_accepts_canonical_column_and_props():
    assert parse_source_fields({**BASE, "unit": "unit"}).unit == "unit"
    with pytest.raises(ValueError, match="unit"):
        parse_source_fields({**BASE, "unit": "street"})
