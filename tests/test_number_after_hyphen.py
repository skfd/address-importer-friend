"""`unit = "number-after-hyphen"`: Thunder Bay's "270-1" is civic 270, unit 1.

Three Caribou Crescent townhouse blocks (270-1..5, 274-1..5, 276-1..4) carry
the unit after a hyphen in ADDRESS, the column number_from reads, and nothing
else does (2026-11-08). The split must touch exactly that shape: a qualified
number, a lettered one, a double hyphen or a trailing hyphen stays whole.
"""
import sqlite3

import pytest

from t2 import config as _config, source_db

SF = _config.parse_source_fields({
    "street_from": "props:ROOT", "full_from": "full",
    "number_from": "props:ADDRESS", "unit": "number-after-hyphen",
})


@pytest.mark.parametrize("address, number, unit", [
    ("270-1", "270", "1"),
    ("276-4", "276", "4"),
    ("963 1/2", "963 1/2", None),
    ("688B", "688B", None),
    ("12A-3", "12A-3", None),
    ("1-2-3", "1-2-3", None),
    ("12-", "12-", None),
    ("1943", "1943", None),
    (None, None, None),
])
def test_split(address, number, unit):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE addresses (props TEXT)")
    props = "{}" if address is None else '{"ADDRESS": "%s"}' % address
    conn.execute("INSERT INTO addresses VALUES (?)", (props,))
    got = conn.execute(
        f"SELECT {source_db.field_sql(SF, 'number', '')}, "
        f"{source_db.field_sql(SF, 'unit', '')} FROM addresses"
    ).fetchone()
    assert got == (number, unit)


def test_refused_with_street_from_full():
    with pytest.raises(ValueError, match="number-after-hyphen"):
        _config.parse_source_fields({
            "street_from": "full", "full_from": "full",
            "number_from": "full", "unit": "number-after-hyphen",
        })
