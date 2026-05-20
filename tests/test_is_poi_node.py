from t2.conflate import _is_poi_node


def _node(tags: dict) -> dict:
    return {"type": "node", "id": 1, "tags": tags}


def test_pure_address_node_is_not_poi():
    assert _is_poi_node(_node({"addr:housenumber": "10", "addr:street": "Bloor St"})) is False


def test_bare_poi_key_is_poi():
    assert _is_poi_node(_node({"addr:housenumber": "10", "amenity": "cafe"})) is True
    assert _is_poi_node(_node({"addr:housenumber": "10", "shop": "bakery"})) is True


def test_lifecycle_prefix_is_poi():
    # The documented OSM form: `disused:amenity`, `was:shop`, etc.
    assert _is_poi_node(_node({"addr:housenumber": "10", "disused:amenity": "restaurant"})) is True
    assert _is_poi_node(_node({"addr:housenumber": "10", "disused:tourism": "hotel"})) is True
    assert _is_poi_node(_node({"addr:housenumber": "10", "abandoned:shop": "yes"})) is True
    assert _is_poi_node(_node({"addr:housenumber": "10", "construction:amenity": "school"})) is True
    assert _is_poi_node(_node({"addr:housenumber": "10", "was:office": "company"})) is True


def test_lifecycle_suffix_is_poi():
    # The rarer suffix form: `amenity:disused`.
    assert _is_poi_node(_node({"addr:housenumber": "10", "amenity:disused": "cafe"})) is True
    assert _is_poi_node(_node({"addr:housenumber": "10", "shop:abandoned": "yes"})) is True


def test_non_lifecycle_qualified_key_is_not_poi():
    # `building:part` shares a base key with a POI tag but `part` is not a
    # lifecycle word, so it must not flip the node to POI on its own.
    assert _is_poi_node(_node({"addr:housenumber": "10", "building:part": "yes"})) is False


def test_entrance_node_is_not_poi():
    # An entrance node carrying addr:* is a canonical (door-level) address.
    assert _is_poi_node(_node({"addr:housenumber": "10", "entrance": "yes"})) is False


def test_polygons_are_never_poi_filtered():
    # A way/relation with POI tags is still a valid match target.
    way = {"type": "way", "id": 1, "tags": {"addr:housenumber": "10", "amenity": "hospital"}}
    assert _is_poi_node(way) is False
