"""Duplicate neighbourhood names get a community prefix, unique ones don't.

Hamilton's planning-unit layer repeats names across (and within) its former
municipalities — ten distinct "Industrial" units. `build_tiles` prefixes only
the ambiguous names with the layer's COMMUNITY field; a same-name-same-community
pair still collides and falls back to the -N id dedup in `_make_tile`.
"""
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


def _feature(name, community, min_lon, min_lat):
    return {
        "properties": {"NEIGHBOURHOOD": name, "COMMUNITY": community},
        "geometry": _square(min_lon, min_lat),
    }


BBOX = (43.0, -80.0, 43.5, -79.5)


def _points_in(features, per_feature=300):
    """per_feature points inside each square — above MERGE_FLOOR so no tile
    gets absorbed into a neighbour, below SPLIT_THRESHOLD so none splits."""
    pts = []
    for f in features:
        ring = f["geometry"]["coordinates"][0]
        min_lon, min_lat = ring[0]
        for k in range(per_feature):
            frac = (k + 0.5) / per_feature
            pts.append((min_lon + 0.008 * frac + 0.001, min_lat + 0.005))
    return pts


def test_duplicate_names_get_community_prefix():
    features = [
        _feature("Industrial", "Stoney Creek", -80.0, 43.0),
        _feature("Industrial", "Hamilton", -79.9, 43.1),
        _feature("Poplar Park", "Stoney Creek", -79.8, 43.2),
    ]
    tiles, _ = tiles_build.build_tiles(features, _points_in(features), BBOX)
    names = sorted(t["name"] for t in tiles)
    assert names == ["Hamilton Industrial", "Poplar Park", "Stoney Creek Industrial"]


def test_same_community_duplicates_fall_back_to_id_dedup():
    features = [
        _feature("Industrial", "Stoney Creek", -80.0, 43.0),
        _feature("Industrial", "Stoney Creek", -79.9, 43.1),
    ]
    tiles, _ = tiles_build.build_tiles(features, _points_in(features), BBOX)
    assert sorted(t["name"] for t in tiles) == ["Stoney Creek Industrial"] * 2
    assert sorted(t["id"] for t in tiles) == [
        "stoney-creek-industrial",
        "stoney-creek-industrial-2",
    ]


def test_name_matching_its_community_is_not_prefixed():
    # "Stoney Creek Stoney Creek" would be silly.
    features = [
        _feature("Stoney Creek", "Stoney Creek", -80.0, 43.0),
        _feature("Stoney Creek", "Stoney Creek", -79.9, 43.1),
    ]
    tiles, _ = tiles_build.build_tiles(features, _points_in(features), BBOX)
    assert sorted(t["name"] for t in tiles) == ["Stoney Creek"] * 2


def test_unique_names_never_prefixed():
    features = [
        _feature("Guernsey", "Stoney Creek", -80.0, 43.0),
        _feature("Westdale North", "Hamilton", -79.9, 43.1),
    ]
    tiles, _ = tiles_build.build_tiles(features, _points_in(features), BBOX)
    assert sorted(t["name"] for t in tiles) == ["Guernsey", "Westdale North"]
