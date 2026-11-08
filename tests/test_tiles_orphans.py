"""Layer-backed builds bucket every orphan, without creating megatiles.

Decision 2026-08-15 (Hamilton, 27 stranded addresses): an address outside every
neighbourhood polygon must still land in a tile — an address in no tile is
unreachable from the picker and from Run-for-All. The old >=1% gate dropped
small orphan sets silently. The other half of the decision is the span cap:
without it, a sparse orphan set makes one catch-all tile whose ring polygon —
and therefore whose bbox, and therefore whose runs — spans the entire city.
"""
from t2 import tiles_build


BBOX = (43.0, -80.0, 43.5, -79.5)


def _square(min_lon, min_lat, size):
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


def _grid_in(min_lon, min_lat, size, n):
    return [
        (min_lon + size * (j + 0.5) / n, min_lat + size * (i + 0.5) / n)
        for i in range(n)
        for j in range(n)
    ]


def _spans(tile):
    min_lat, min_lon, max_lat, max_lon = tile["bbox"]
    return max_lat - min_lat, max_lon - min_lon


def test_sub_percent_orphans_still_get_tiles():
    hood = {
        "properties": {"NEIGHBOURHOOD": "Guernsey"},
        "geometry": _square(-79.90, 43.10, 0.01),
    }
    inside = _grid_in(-79.90, 43.10, 0.01, 18)  # 324 points, > MERGE_FLOOR
    strays = [(-79.8880 + k * 0.0004, 43.1050) for k in range(5)]  # ~0.4% orphans
    tiles, stats = tiles_build.build_tiles([hood], inside + strays, BBOX)

    # The old behaviour: 5/329 < 1% meant no bucket, orphan_count == 5.
    assert stats["orphan_count"] == 0
    assert sum(t["address_count"] for t in tiles) == len(inside) + len(strays)


def test_orphan_bucketing_never_yields_a_megatile():
    hood = {
        "properties": {"NEIGHBOURHOOD": "Guernsey"},
        "geometry": _square(-79.90, 43.10, 0.01),
    }
    inside = _grid_in(-79.90, 43.10, 0.01, 18)
    strays = [(-79.8880 + k * 0.0004, 43.1050) for k in range(5)]
    tiles, _ = tiles_build.build_tiles([hood], inside + strays, BBOX)

    # The catch-all is the city rect minus the hood — a ring spanning the whole
    # bbox. The span cap must have cut it down to pieces near the strays.
    for t in tiles:
        dlat, dlon = _spans(t)
        assert dlat < 0.05 and dlon < 0.05, f"megatile {t['id']}: {t['bbox']}"


def test_no_layer_path_keeps_unbounded_tiles():
    # Sparse no-layer city: one big tile is correct there, the span cap must
    # not apply (rural Hamilton squares were ~10 km on purpose).
    points = _grid_in(-79.95, 43.05, 0.4, 10)  # 100 points spread wide
    tiles, stats = tiles_build.build_tiles([], points, BBOX, orphan_name="X")

    assert stats["orphan_count"] == 0
    assert len(tiles) == 1
    dlat, dlon = _spans(tiles[0])
    assert dlat > 0.3 and dlon > 0.3


def test_small_orphans_merge_into_the_layer_by_default():
    """The old behaviour, kept for cities that don't name their orphans:
    Hamilton's and Toronto's tile ids must not move."""
    hood = {"properties": {"NEIGHBOURHOOD": "Guernsey"},
            "geometry": _square(-79.90, 43.10, 0.01)}
    inside = _grid_in(-79.90, 43.10, 0.01, 18)
    strays = [(-79.8995 + k * 0.0004, 43.1102) for k in range(5)]  # just north
    tiles, _ = tiles_build.build_tiles([hood], inside + strays, BBOX)
    guernsey = [t for t in tiles if t["name"].startswith("Guernsey")]
    assert sum(t["address_count"] for t in guernsey) == len(inside) + len(strays)

def test_named_orphans_never_merge_into_the_layer():
    """Thunder Bay: the orphans are Fort William First Nation, another
    jurisdiction. They must stay in tiles of their own, however small."""
    hood = {"properties": {"NEIGHBOURHOOD": "Guernsey"},
            "geometry": _square(-79.90, 43.10, 0.01)}
    inside = _grid_in(-79.90, 43.10, 0.01, 18)
    strays = [(-79.8995 + k * 0.0004, 43.1102) for k in range(5)]
    tiles, _ = tiles_build.build_tiles([hood], inside + strays, BBOX,
                                       orphan_name="Fort William First Nation",
                                       keep_orphans_apart=True)
    layer = [t for t in tiles if not t["is_orphan"]]
    orphans = [t for t in tiles if t["is_orphan"]]
    assert sum(t["address_count"] for t in layer) == len(inside)
    assert sum(t["address_count"] for t in orphans) == len(strays)
    assert all(t["name"].startswith("Fort William First Nation") for t in orphans)


def test_a_ward_with_an_enclave_keeps_its_hole():
    """Thunder Bay's Westfort ward wraps Fort William First Nation land. The
    stored tile polygon must keep the hole, or a run on the ward tile ingests
    the enclave's addresses (candidates._build_polygon reads it back)."""
    from shapely.geometry import Point, Polygon
    from t2 import candidates

    ward = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], [[(4, 4), (6, 4), (6, 6), (4, 6)]])
    stored = tiles_build._polygon_latlon(ward)
    assert len(stored) == 2
    back = candidates._build_polygon(stored)
    assert not back.covers(Point(5, 5))
    assert back.covers(Point(1, 1))


def test_old_single_ring_polygons_still_read():
    from shapely.geometry import Point
    from t2 import candidates

    back = candidates._build_polygon([[[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]])
    assert back.covers(Point(5, 5))
