"""Declared layer name fields override sniffing (multi-city Tier 4, 2026-08-15).

Quinte West's Planning Districts layer is the motivating shape: `name` holds
the parent community (TRENTON, BATAWA) and `district_n` the unit within it
("3B") — the sniff would grab `name` and mint 81 tiles all called TRENTON-N.
With the fields declared, the parent prefixes every tile ("TRENTON 3B"),
not just duplicates; a declared-but-empty name field fails loudly instead of
falling back to the sniff.
"""
import pytest

from t2 import tiles_build


def _square(min_lon, min_lat, size=0.01):
    return {
        "type": "Polygon",
        "coordinates": [[
            [min_lon, min_lat],
            [min_lon + size, min_lat],
            [min_lon + size, min_lat + size],
            [min_lon, min_lat + size],
            [min_lon, min_lat],
        ]],
    }


def _feature(props, min_lon, min_lat):
    return {"properties": props, "geometry": _square(min_lon, min_lat)}


BBOX = (43.0, -80.0, 43.5, -79.5)


def _points_in(features, per_feature=300):
    pts = []
    for f in features:
        ring = f["geometry"]["coordinates"][0]
        min_lon, min_lat = ring[0]
        for k in range(per_feature):
            frac = (k + 0.5) / per_feature
            pts.append((min_lon + 0.008 * frac + 0.001, min_lat + 0.005))
    return pts


def test_declared_parent_prefixes_every_tile_not_just_duplicates():
    features = [
        _feature({"name": "TRENTON", "district_n": "3B"}, -80.0, 43.0),
        _feature({"name": "BATAWA", "district_n": "2"}, -79.9, 43.1),
        _feature({"name": "TRENTON", "district_n": "10A"}, -79.8, 43.2),
    ]
    tiles, _ = tiles_build.build_tiles(
        features, _points_in(features), BBOX,
        name_field="district_n", parent_field="name",
    )
    assert sorted(t["name"] for t in tiles) == ["BATAWA 2", "TRENTON 10A", "TRENTON 3B"]


def test_declared_name_field_beats_sniffable_keys():
    # AREA_NAME is first in the sniff list; the declaration must win anyway.
    features = [
        _feature({"AREA_NAME": "Wrong", "district_n": "1", "name": "TRENTON"}, -80.0, 43.0),
    ]
    tiles, _ = tiles_build.build_tiles(
        features, _points_in(features), BBOX,
        name_field="district_n", parent_field="name",
    )
    assert [t["name"] for t in tiles] == ["TRENTON 1"]


def test_declared_name_field_empty_on_a_feature_fails_loudly():
    features = [
        _feature({"name": "TRENTON", "district_n": ""}, -80.0, 43.0),
    ]
    with pytest.raises(ValueError, match="neighbourhood_name_field"):
        tiles_build.build_tiles(
            features, _points_in(features), BBOX, name_field="district_n",
        )


def test_declared_parent_missing_on_a_feature_is_tolerated():
    features = [
        _feature({"district_n": "3B", "name": "TRENTON"}, -80.0, 43.0),
        _feature({"district_n": "9"}, -79.9, 43.1),  # no parent — bare name
    ]
    tiles, _ = tiles_build.build_tiles(
        features, _points_in(features), BBOX,
        name_field="district_n", parent_field="name",
    )
    assert sorted(t["name"] for t in tiles) == ["9", "TRENTON 3B"]


def test_undeclared_fields_keep_legacy_sniffing():
    # The guardrail: no declaration -> byte-identical legacy behaviour,
    # including duplicates-only prefixing (Hamilton's names must not move).
    features = [
        _feature({"NEIGHBOURHOOD": "Industrial", "COMMUNITY": "Stoney Creek"}, -80.0, 43.0),
        _feature({"NEIGHBOURHOOD": "Industrial", "COMMUNITY": "Hamilton"}, -79.9, 43.1),
        _feature({"NEIGHBOURHOOD": "Poplar Park", "COMMUNITY": "Stoney Creek"}, -79.8, 43.2),
    ]
    tiles, _ = tiles_build.build_tiles(features, _points_in(features), BBOX)
    assert sorted(t["name"] for t in tiles) == [
        "Hamilton Industrial", "Poplar Park", "Stoney Creek Industrial",
    ]
