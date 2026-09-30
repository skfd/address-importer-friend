"""The city-wide unit-shape audit.

`_outcome` is the part worth pinning: it has to agree with
`candidates._emit_group` about what a civic group becomes, and it is the only
place the four review outcomes are named. If the two drift, the page describes
an upload that will not happen.
"""
import pytest

from t2 import units
from t2.unit_shapes import _outcome, _unit_sort_key


def _group(units_, spacing_m=6.0, lat=43.54, lon=-80.25):
    """A civic group as the source publishes it, spread along a line."""
    m = 1.0 / 111320.0
    return [
        {"unit_name": u, "latitude": lat + i * spacing_m * m, "longitude": lon,
         "address_point_id": f"id{i}"}
        for i, u in enumerate(units_)
    ]


def _floor_coded(floors, per_floor):
    return [f"{f}{n:02d}" for f in floors for n in range(1, per_floor + 1)]


def test_a_tower_is_one_node_carrying_its_units():
    out = _outcome(_group(_floor_coded(range(1, 5), 12), spacing_m=40))
    assert out["shape"] == "collapse"
    assert out["nodes_created"] == 1
    assert out["flats"] == "101-112;201-212;301-312;401-412"


def test_a_row_of_doors_is_a_node_each():
    rows = _group([str(n) for n in range(41, 53)])
    out = _outcome(rows)
    assert out["shape"] == "nodes"
    # Every row in the group, the unit-less civic point included -- the door
    # branch of _emit_group yields rows, not just unit rows.
    assert out["nodes_created"] == len(rows)
    assert out["flats"] is None


def test_an_over_long_listing_becomes_civic_only_not_a_failed_collapse():
    # 85 Mullin Drive: 110 units as 1A;1B;2A;2B..., 421 characters. Nothing
    # range-compresses a suffixed sequence, so the listing is dropped and the
    # building is still uploaded -- correct, and less informative.
    suffixed = [f"{n}{s}" for n in range(1, 56) for s in ("A", "B")]
    out = _outcome(_group(suffixed, spacing_m=1.0))
    assert out["shape"] == "civic-only"
    assert out["nodes_created"] == 1
    assert out["flats"] is None
    assert "255" in out["reason"]


def test_an_unsure_group_still_says_what_it_would_upload():
    # 252 Stone Road West: sequential at 3.7 m, under a door's width. Emitted
    # collapsed like any other, so the listing has to be visible -- withholding
    # it would leave the reviewer nothing to judge.
    out = _outcome(_group([str(n) for n in range(1, 30)], spacing_m=3.7))
    assert out["shape"] == "review"
    assert out["verdict"] == units.REVIEW
    assert out["nodes_created"] == 1
    assert out["flats"] == "1-29"


def test_a_group_with_no_units_is_not_a_unit_question():
    # Several rows on one civic address with no unit between them is an
    # intra-source duplicate. It takes the door branch, one node per row.
    out = _outcome(_group([None, None, None]))
    assert out["verdict"] == units.NO_UNITS
    assert out["shape"] == "nodes"


def test_unit_samples_read_in_human_order():
    # A door group's sample opened 1;10;100;101 under a string sort, which
    # reads as noise where 1;2;3 reads as a row of houses.
    assert sorted(["10", "1", "100", "2"], key=_unit_sort_key) == ["1", "2", "10", "100"]
    assert sorted(["B2", "A10", "A2"], key=_unit_sort_key) == ["A2", "A10", "B2"]
    # Unparseable designators sort last rather than interrupting a run.
    assert sorted(["REAR", "2", "1"], key=_unit_sort_key) == ["1", "2", "REAR"]


# --- the review queue: points for the map, the listing filter, the sort ------


def _fake_source(monkeypatch, rows):
    """Point `_base` at an in-memory source instead of the city's SQLite."""
    from t2 import source_db, unit_shapes

    class _Conn:
        def execute(self, q, params):
            return iter(rows)

        def close(self):
            pass

    monkeypatch.setattr(source_db, "connect_readonly", lambda: _Conn())
    monkeypatch.setattr(source_db, "build_civic_group_query", lambda *a, **k: "q")
    monkeypatch.setattr(unit_shapes, "_BASE_CACHE", {})
    return unit_shapes


def _src_row(number, unit, lat, lon, pid):
    return {"address_number": number, "linear_name_full": "Hanlon Creek Boulevard",
            "municipality_name": "Guelph", "unit_name": unit, "latitude": lat,
            "longitude": lon, "address_point_id": pid}


def test_base_rows_carry_each_units_point_for_the_map(monkeypatch):
    m = 1.0 / 111320.0
    rows = [_src_row("275", str(u), 43.5 + i * 8.4 * m, -80.2, f"p{u}")
            for i, u in enumerate((5, 1, 3, 2, 4))]
    # The unit-less civic row is part of the group but not a point on the map.
    rows.append(_src_row("275", None, 43.5, -80.2, "civic"))
    unit_shapes = _fake_source(monkeypatch, rows)
    (row,) = unit_shapes._base(1)["rows"]
    assert [p[0] for p in row["points"]] == ["1", "2", "3", "4", "5"]
    assert all(len(p) == 3 and p[1] > 43 and p[2] < -80 for p in row["points"])
    assert row["spacing_m"] == pytest.approx(8.4, abs=0.1)


def _row(key, shape, listings=(), spacing=None, osm=True):
    return {
        "key": key, "shape": shape, "spacing_m": spacing,
        "osm": {"listings": list(listings), "shape": "listing" if listings else ""} if osm else None,
    }


def test_the_listing_filter_keeps_any_group_where_osm_lists_units():
    from t2.unit_shapes import select

    rows = [
        _row("a", "nodes", ["1-5"]),
        _row("b", "nodes"),
        _row("c", "review", ["101-110"]),
        _row("d", "collapse", osm=False),  # no extract loaded
    ]
    # A group with a listing and a stray door reads osm.shape "doors"; the
    # filter is on the listing, not the shape, so it is kept.
    rows[0]["osm"]["shape"] = "doors"
    assert [r["key"] for r in select(rows, osm="listing")] == ["a", "c"]
    assert [r["key"] for r in select(rows, shape="review", osm="listing")] == ["c"]
    assert [r["key"] for r in select(rows, osm="")] == ["a", "b", "c", "d"]


def test_the_spacing_sort_puts_the_widest_doors_first_and_the_unmeasured_last():
    from t2.unit_shapes import select, shape_counts

    rows = [_row("a", "nodes", spacing=8.4), _row("b", "nodes", spacing=None),
            _row("c", "nodes", spacing=91.2), _row("d", "review", spacing=3.0)]
    assert [r["key"] for r in select(rows, sort="spacing")] == ["c", "a", "d", "b"]
    assert [r["key"] for r in select(rows, sort="")] == ["a", "b", "c", "d"]
    assert shape_counts(rows, "") is None
    rows[0]["osm"]["listings"] = ["1-5"]
    assert shape_counts(rows, "listing")["nodes"] == 1
