"""Uploaded nodes carry `addr:source`, and the preview shows what we upload.

The switch from a bare `source` to `addr:source` (c1573d7) landed on the
preview path only — `STATIC_TAGS`, which `conflate._proposed_tags` splats — and
missed `osm_export.build_tags`, which is what both the JOSM export and the API
upload actually emit. So the review UI showed `addr:source` while every
changeset still wrote `source`, for every city, with Toronto's proposal page
already stating in print that new nodes write `addr:source`.

The guard is the agreement, not the key: whatever a node is proposed with in
review is what has to leave the building.
"""
import xml.etree.ElementTree as ET

from t2 import osm_export
from t2.conflate import _proposed_tags

ITEM = {
    "candidate_id": 1,
    "local_node_id": -1,
    "housenumber": "123",
    "street_raw": "Main Street",
    "lat": 43.5,
    "lon": -80.2,
    "proposed_postcode": "N1G 1A1",
}


def test_uploaded_node_is_attributed_in_the_addr_namespace():
    tags = osm_export.build_tags(ITEM)
    assert tags["addr:source"] == osm_export._attribution()
    assert "source" not in tags


def test_preview_and_upload_propose_the_same_tags():
    assert _proposed_tags(ITEM) == osm_export.build_tags(ITEM)


def test_the_emitted_xml_carries_it():
    root = ET.fromstring(osm_export._osm_change_xml([ITEM]))
    keys = {t.attrib["k"] for t in root.findall("./node/tag")}
    assert "addr:source" in keys
    assert "source" not in keys
