"""Unit-shape classification.

Every fixture here is a real City of Guelph civic group, measured from source
snapshot 46 on 2026-09-15. They are the cases the rule was derived from and
the ones that broke the two classifiers before it, so they are worth carrying
verbatim rather than paraphrasing into tidy synthetic numbers.

Coordinates are synthesized, because what they need to express is one scalar —
the spacing between units — and a row of real lat/lons buries that.
"""
from t2.units import (
    COLLAPSE,
    flats_tag,
    NO_UNITS,
    NODES,
    REVIEW,
    classify,
    compress_flats,
    is_coded,
    parse_unit,
)

# metres -> degrees of latitude, near enough at Guelph's 43.5 N.
_M = 1.0 / 111320.0


def _row(unit, index=0, spacing_m=6.0, lat=43.54, lon=-80.25):
    """One source row, placed `index` steps of `spacing_m` along a line."""
    return {"unit": unit, "lat": lat + index * spacing_m * _M, "lon": lon}


def _row_line(units, spacing_m=6.0):
    return [_row(u, i, spacing_m) for i, u in enumerate(units)]


def _floor_coded(floors, per_floor, prefix=""):
    return [f"{prefix}{f}{n:02d}" for f in floors for n in range(1, per_floor + 1)]


# --- parse_unit -------------------------------------------------------------


def test_parse_unit_splits_prefix_number_suffix():
    assert parse_unit("101") == ("", 101, "")
    assert parse_unit("D101") == ("D", 101, "")
    assert parse_unit("101A") == ("", 101, "A")


def test_parse_unit_is_case_and_space_insensitive():
    assert parse_unit(" d101 ") == ("D", 101, "")


def test_parse_unit_rejects_what_has_no_number():
    assert parse_unit("REAR") is None
    assert parse_unit("") is None


# --- is_coded ---------------------------------------------------------------


def test_93_arthur_street_south_is_a_14_storey_building():
    # 101..1411 over stems 1-14. The case that broke the 3-digit-only rule:
    # read as doors it claims 193 front entrances inside 66 metres.
    units = _floor_coded(range(1, 15), 13)
    assert is_coded(units) is True


def test_letter_prefix_is_a_building_code():
    # 71 Bayberry Drive: D101..D409, four floors of building D.
    assert is_coded(_floor_coded(range(1, 5), 12, prefix="D")) is True


def test_sequential_numbering_is_not_coded():
    # 302 College Avenue West, 1..214 — genuinely 214 doors.
    assert is_coded([str(n) for n in range(1, 215)]) is False


def test_two_digit_units_are_doors_not_floor_zero():
    # 19 Burns Drive, units 41..52. Stripping two digits off "41" would leave
    # nothing; a short number carries no code.
    assert is_coded([str(n) for n in range(41, 53)]) is False


def test_one_stem_alone_is_not_evidence_of_coding():
    # A single floor's worth, 101..124, reads just as well as 24 doors
    # numbered from 101 — so it is not called coded on its own.
    assert is_coded([f"1{n:02d}" for n in range(1, 25)]) is False


def test_a_unit_that_does_not_parse_blocks_coding():
    assert is_coded(["101", "201", "REAR"]) is False


# --- compress_flats ---------------------------------------------------------


def test_23_woodlawn_road_east_keeps_its_gaps():
    # 103 units. 706 and 910 genuinely do not exist, and the runs break there.
    units = (
        _floor_coded([1], 10) + _floor_coded([2, 3, 4, 5, 6], 12)
        + [f"7{n:02d}" for n in list(range(1, 6)) + list(range(7, 13))]
        + _floor_coded([8], 12)
        + [f"9{n:02d}" for n in list(range(1, 10)) + [11]]
    )
    assert compress_flats(units) == (
        "101-110;201-212;301-312;401-412;501-512;601-612;"
        "701-705;707-712;801-812;901-909;911"
    )


def test_letter_prefixed_runs_stay_within_their_building():
    assert compress_flats(_floor_coded(range(1, 4), 12, prefix="D")) == (
        "D101-D112;D201-D212;D301-D312"
    )


def test_a_letter_suffixed_stray_sorts_beside_its_neighbours():
    # 511 Edinburgh Road South. 101A cannot join the 101-102 run, and must not
    # be exiled to the tail either.
    assert compress_flats(["101", "101A", "102", "201", "202"]) == "101-102;101A;201-202"


def test_single_units_are_emitted_bare():
    assert compress_flats(["100", "105", "106", "107"]) == "100;105-107"


def test_unparseable_designators_are_carried_through_last():
    assert compress_flats(["101", "102", "REAR"]) == "101-102;REAR"


def test_duplicate_units_collapse():
    assert compress_flats(["101", "101", "102"]) == "101-102"


def test_guelphs_largest_group_stays_inside_the_osm_tag_limit():
    # The ceiling that ruled out an explicit list: 19 Woodlawn Road East holds
    # 142 units, which as raw values would run past 255 characters.
    assert len(compress_flats(_floor_coded(range(1, 10), 16))) <= 255


# --- classify ---------------------------------------------------------------


def test_coded_numbering_collapses_however_far_apart_the_points_are():
    # The whole point of numbering-over-geometry: 93 Arthur Street South's
    # units spread widely, and it is still one building.
    verdict, reason = classify(_row_line(_floor_coded(range(1, 15), 13), spacing_m=40))
    assert verdict == COLLAPSE
    assert "coded" in reason


def test_sequential_and_door_width_apart_becomes_nodes():
    verdict, _ = classify(_row_line([str(n) for n in range(41, 53)], spacing_m=6.0))
    assert verdict == NODES


def test_sequential_but_too_tight_goes_to_review():
    # 252 Stone Road West: a mall, 140 "units" at 3.7 m. Whether a storefront
    # is a door is not a call this rule makes quietly.
    verdict, _ = classify(_row_line([str(n) for n in range(1, 141)], spacing_m=3.7))
    assert verdict == REVIEW


def test_units_sharing_a_location_collapse():
    rows = [_row(str(n), index=0) for n in range(1, 25)]
    verdict, reason = classify(rows)
    assert verdict == COLLAPSE
    assert "share a location" in reason


def test_a_group_with_no_unit_rows_is_not_a_unit_question():
    verdict, _ = classify([_row(None, 0), _row("", 1)])
    assert verdict == NO_UNITS


def test_rows_without_coordinates_are_ignored():
    rows = _row_line(["1", "2", "3"], spacing_m=6.0)
    rows.append({"unit": "4", "lat": None, "lon": None})
    assert classify(rows)[0] == NODES


def test_a_lone_unit_is_measured_against_the_civic_point():
    rows = [_row(None, 0), _row("2", 1, spacing_m=8.0)]
    assert classify(rows)[0] == NODES


def test_a_lone_unit_on_the_civic_point_collapses():
    rows = [_row(None, 0), _row("2", 0)]
    assert classify(rows)[0] == COLLAPSE


def test_a_lone_unit_with_nothing_to_compare_against_goes_to_review():
    verdict, reason = classify([_row("2", 0)])
    assert verdict == REVIEW
    assert "nothing to measure" in reason


# --- flats_tag: what will not fit in a tag ----------------------------------


def test_a_listing_that_fits_is_returned_with_no_complaint():
    value, reason = flats_tag(["101", "102", "103"])
    assert value == "101-103"
    assert reason is None


def test_an_over_long_listing_is_dropped_rather_than_truncated():
    """85 Mullin Drive: 110 units as 1A;1B;2A;2B... — nothing compresses, and
    the result runs to 421 characters. A truncated listing would assert the
    building stops where the cut landed."""
    units = [f"{n}{s}" for n in range(1, 56) for s in ("A", "B")]
    value, reason = flats_tag(units)
    assert value is None
    assert "over OSM's 255-character tag limit" in reason


def test_a_group_with_no_units_asks_for_nothing_and_complains_about_nothing():
    assert flats_tag([]) == (None, None)
