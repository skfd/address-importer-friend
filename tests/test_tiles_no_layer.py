"""A city with no neighbourhood layer still gets a usable tile layer.

`build_tiles` with no features finds every address unassigned and takes the
orphan branch, which quadtree-splits the whole city bbox. That is the
no-neighbourhood-layer fallback (future-work/multi-city/02, Tier 4) — the
splitting and merging logic underneath is the same one the layer-backed build
uses, so this pins the fallback rather than the quadtree.
"""
from t2 import tiles_build


def _grid(bbox, n):
    """n x n evenly spaced points strictly inside bbox, as (lon, lat)."""
    min_lat, min_lon, max_lat, max_lon = bbox
    out = []
    for i in range(n):
        for j in range(n):
            lat = min_lat + (max_lat - min_lat) * (i + 0.5) / n
            lon = min_lon + (max_lon - min_lon) * (j + 0.5) / n
            out.append((lon, lat))
    return out


BBOX = (43.20, -80.00, 43.30, -79.85)


def test_no_layer_tiles_the_whole_bbox():
    points = _grid(BBOX, 40)  # 1600 points, well over SPLIT_THRESHOLD
    tiles, stats = tiles_build.build_tiles([], points, BBOX, orphan_name="Hamilton")

    assert stats["total_addresses"] == len(points)
    # Every address lands in a tile — nothing is left over when the "orphan"
    # bucket is the entire city.
    assert stats["orphan_count"] == 0
    assert tiles, "no tiles produced"
    # The point of the exercise: no tile is an unreviewable megatile.
    assert max(t["address_count"] for t in tiles) <= tiles_build.MERGE_HARD_CEILING
    assert sum(t["address_count"] for t in tiles) == len(points)


def test_no_layer_tiles_are_named_for_the_city():
    tiles, _ = tiles_build.build_tiles([], _grid(BBOX, 40), BBOX, orphan_name="Hamilton")
    # "Unassigned" would be wrong here: nothing was assigned elsewhere, so there
    # is nothing for these to be unassigned from.
    assert all("Unassigned" not in t["name"] for t in tiles)
    assert all(t["parent"] == "Hamilton" for t in tiles)


def test_orphan_name_defaults_to_unassigned():
    """The layer-backed build is unchanged: its leftovers are still 'Unassigned'."""
    tiles, _ = tiles_build.build_tiles([], _grid(BBOX, 40), BBOX)
    assert all(t["parent"] == "Unassigned" for t in tiles)
