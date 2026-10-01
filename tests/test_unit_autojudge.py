"""The building-based judge: townhouse complexes get doors, apartments
collapse, and everything it cannot tell stays with the rule.

Shapes are drawn on a metric grid near Guelph and converted to lat/lon, so
each test states its buildings in metres.
"""
import math

from t2 import osm_buildings, unit_autojudge

LAT0, LON0 = 43.5, -80.25
_KX = osm_buildings._M_PER_DEG_LAT * math.cos(math.radians(LAT0))


def _ll(x, y):
    return LAT0 + y / osm_buildings._M_PER_DEG_LAT, LON0 + x / _KX


def _box(id_, x, y, w, h, kind="yes"):
    ring = [_ll(x, y), _ll(x + w, y), _ll(x + w, y + h), _ll(x, y + h), _ll(x, y)]
    return {"id": id_, "type": "way", "building": kind, "levels": None, "ring": [list(p) for p in ring]}


def _pts(coords):
    return [(str(i + 1), *_ll(x, y)) for i, (x, y) in enumerate(coords)]


def _judge(rule_shape, buildings, coords, spacing=6.0):
    idx = osm_buildings.Index(buildings)
    return unit_autojudge.judge(rule_shape, _pts(coords), spacing, idx.at)


def test_index_finds_the_containing_building_and_one_just_past_the_wall():
    idx = osm_buildings.Index([_box(1, 0, 0, 10, 10)])
    assert idx.at(*_ll(5, 5))["id"] == 1
    assert idx.at(*_ll(12, 5))["id"] == 1  # 2 m outside: the door
    assert idx.at(*_ll(20, 5)) is None
    assert round(idx.at(*_ll(5, 5))["area"]) == 100


def test_a_coded_complex_of_small_buildings_is_a_townhouse_complex():
    # 15 Carere Crescent's shape: two units to a small building, many buildings.
    buildings = [_box(i, i * 20, 0, 12, 8, "house") for i in range(6)]
    coords = [(i * 20 + dx, 4) for i in range(6) for dx in (3, 9)]
    verdict, note = _judge("collapse", buildings, coords)
    assert verdict == "nodes" and note.startswith("auto: townhouse complex")
    assert "12 units, 12 placed in 6 buildings" in note


def test_a_tower_with_points_spilling_past_its_walls_collapses():
    # 63 Arthur Street South: units on a grid over the lot, a third outside.
    buildings = [_box(1, 0, 0, 40, 40, "apartments")]
    coords = [(x, y) for x in range(2, 60, 6) for y in range(2, 40, 6)]
    verdict, note = _judge("review", buildings, coords, spacing=3.4)
    assert verdict == "collapse" and "apartment building" in note


def test_a_row_of_townhouses_in_one_outline_stays_with_the_rule():
    # One terrace way holding ten doors: a big footprint per unit, one building.
    verdict, _ = _judge("review", [_box(1, 0, 0, 60, 10, "terrace")], [(3 + 6 * i, 1) for i in range(10)], 3.3)
    assert verdict is None


def test_a_converted_house_is_left_for_a_person():
    # 190 Norfolk Street: five flats in one big old house.
    verdict, note = _judge("review", [_box(1, 0, 0, 20, 18)], [(4, 4), (8, 5), (12, 4), (6, 9), (10, 10)], 3.9)
    assert verdict is None and "neither test" in note


def test_a_garden_suite_is_not_an_apartment_building():
    # 155 Bristol Street: two units in a 57 m² garage is not floors.
    verdict, _ = _judge("review", [_box(1, 0, 0, 8, 7, "garage")], [(2, 2), (5, 5), (30, 30), (34, 34)], 2.7)
    assert verdict is None


def test_units_with_no_distinct_positions_get_no_doors():
    buildings = [_box(i, i * 20, 0, 12, 8) for i in range(4)]
    coords = [(i * 20 + 6, 4) for i in range(4) for _ in range(2)]
    verdict, _ = _judge("collapse", buildings, coords, spacing=0.0)
    assert verdict is None


def test_a_rule_nodes_group_is_not_second_guessed():
    verdict, note = _judge("nodes", [_box(1, 0, 0, 40, 40, "apartments")], [(5, 5), (6, 6)])
    assert verdict is None and "not judged" in note


def test_a_complex_osm_has_barely_drawn_says_nothing():
    buildings = [_box(0, 0, 0, 12, 8)]
    coords = [(3, 4), (9, 4)] + [(100 + 10 * i, 50) for i in range(8)]
    verdict, note = _judge("collapse", buildings, coords)
    assert verdict is None and "only 2 of 10" in note
