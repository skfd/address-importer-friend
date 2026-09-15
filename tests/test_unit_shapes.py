"""The city-wide unit-shape audit.

`_outcome` is the part worth pinning: it has to agree with
`candidates._emit_group` about what a civic group becomes, and it is the only
place the four review outcomes are named. If the two drift, the page describes
an upload that will not happen.
"""
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
