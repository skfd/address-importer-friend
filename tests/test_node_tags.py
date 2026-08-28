"""`[export] node_tags` — the city's constant tags on every created node.

Guelph's published tagging plan promises addr:city=Guelph on every node;
Toronto's promises no addr:city and must keep writing none. So the key is
optional, absent means absent (03), and it feeds the one tag builder that both
the review preview and the changeset read.

The refusal matters as much as the feature: a constant that redefines a derived
tag would overwrite the conflated street or housenumber on every node in the
city, and would look like a conflation bug rather than a config typo.
"""
import pytest
import xml.etree.ElementTree as ET

from t2 import osm_export
from t2.config import parse_node_tags
from t2.conflate import _proposed_tags

ITEM = {
    "candidate_id": 1,
    "local_node_id": -1,
    "housenumber": "123",
    "street_raw": "Main Street",
    "lat": 43.5,
    "lon": -80.2,
}


def test_absent_key_writes_no_extra_tags():
    assert parse_node_tags({}) == {}
    assert parse_node_tags({"attribution": "x"}) == {}


def test_declared_tags_reach_the_node_and_the_preview(monkeypatch):
    monkeypatch.setattr(osm_export._CONFIG, "export_node_tags", {"addr:city": "Guelph"})
    assert osm_export.build_tags(ITEM)["addr:city"] == "Guelph"
    assert _proposed_tags(ITEM)["addr:city"] == "Guelph"

    root = ET.fromstring(osm_export._osm_change_xml([ITEM]))
    tags = {t.attrib["k"]: t.attrib["v"] for t in root.findall("./node/tag")}
    assert tags["addr:city"] == "Guelph"
    assert tags["addr:street"] == "Main Street"


def test_toronto_still_writes_no_addr_city():
    """The engine default and Toronto's checkout both declare nothing."""
    assert osm_export._CONFIG.export_node_tags == {}
    assert "addr:city" not in osm_export.build_tags(ITEM)


@pytest.mark.parametrize("derived", ["addr:housenumber", "addr:street", "addr:postcode", "addr:source"])
def test_redefining_a_derived_tag_is_refused(derived):
    with pytest.raises(ValueError, match="redefines"):
        parse_node_tags({"node_tags": {derived: "whatever"}})


@pytest.mark.parametrize("bad", [{"node_tags": []}, {"node_tags": {}}, {"node_tags": "addr:city=Guelph"}])
def test_a_malformed_table_is_refused(bad):
    with pytest.raises(ValueError):
        parse_node_tags(bad)


def test_empty_values_are_refused():
    with pytest.raises(ValueError, match="empty or non-string"):
        parse_node_tags({"node_tags": {"addr:city": "  "}})
