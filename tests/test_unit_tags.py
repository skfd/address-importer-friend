"""addr:unit / addr:flats emission, and unit-aware matching.

The two keys differ in kind: addr:unit says this node *is* that unit,
addr:flats says it *serves* those units. A candidate is one or the other.

The matching half is gated on `[units] policy = "per-door-or-collapse"`, and
the gate is the point. Under collapse-to-civic a bare civic candidate matching
an OSM node that carries addr:unit is *correct* — it stops Toronto proposing a
second node at an address already mapped as a suite. Under the new policy that
same leniency would merge a building into one of its own units.
"""
import xml.etree.ElementTree as ET

from t2 import conflate, osm_export
from t2.conflate import _proposed_tags, _same_address

BASE = {
    "candidate_id": 1,
    "local_node_id": -1,
    "housenumber": "714",
    "street_raw": "Willow Road",
    "lat": 43.5,
    "lon": -80.2,
}


def _item(**over):
    it = dict(BASE)
    it.update(over)
    return it


def _el(number="714", street="willow road", unit=""):
    return {"_norm_number": number, "_norm_street": street, "_norm_unit": unit}


# --- tag emission -----------------------------------------------------------


def test_a_per_door_candidate_writes_addr_unit():
    assert osm_export.build_tags(_item(unit="30"))["addr:unit"] == "30"


def test_a_collapsed_candidate_writes_addr_flats():
    tags = osm_export.build_tags(_item(flats="101-110;201-212"))
    assert tags["addr:flats"] == "101-110;201-212"
    assert "addr:unit" not in tags


def test_neither_is_written_when_the_policy_sets_neither():
    tags = osm_export.build_tags(_item())
    assert "addr:unit" not in tags and "addr:flats" not in tags


def test_blank_values_are_dropped_rather_than_written_empty():
    tags = osm_export.build_tags(_item(unit="   ", flats=""))
    assert "addr:unit" not in tags and "addr:flats" not in tags


def test_the_review_preview_and_the_changeset_agree():
    item = _item(unit="30")
    assert _proposed_tags(item)["addr:unit"] == "30"
    root = ET.fromstring(osm_export._osm_change_xml([item]))
    tags = {t.attrib["k"]: t.attrib["v"] for t in root.findall("./node/tag")}
    assert tags["addr:unit"] == "30"
    assert tags["addr:housenumber"] == "714"


# --- matching, policy off (the Toronto/Hamilton contract) -------------------


def test_without_the_policy_a_civic_candidate_still_matches_a_unit_node(monkeypatch):
    monkeypatch.setattr(conflate, "_UNIT_AWARE", False)
    assert _same_address(_el(unit="30"), "714", "willow road", "") is True


def test_without_the_policy_number_and_street_still_have_to_agree(monkeypatch):
    monkeypatch.setattr(conflate, "_UNIT_AWARE", False)
    assert _same_address(_el(number="715"), "714", "willow road", "") is False
    assert _same_address(_el(street="oak road"), "714", "willow road", "") is False


# --- matching, policy on ----------------------------------------------------


def test_a_door_matches_only_its_own_unit(monkeypatch):
    monkeypatch.setattr(conflate, "_UNIT_AWARE", True)
    assert _same_address(_el(unit="30"), "714", "willow road", "30") is True
    assert _same_address(_el(unit="31"), "714", "willow road", "30") is False


def test_a_building_does_not_match_one_of_its_own_units(monkeypatch):
    monkeypatch.setattr(conflate, "_UNIT_AWARE", True)
    assert _same_address(_el(unit="30"), "714", "willow road", "") is False


def test_a_door_does_not_match_the_buildings_civic_node(monkeypatch):
    monkeypatch.setattr(conflate, "_UNIT_AWARE", True)
    assert _same_address(_el(unit=""), "714", "willow road", "30") is False


def test_the_split_campaign_no_longer_has_to_run_in_any_order(monkeypatch):
    """The 89 Guelph groups where OSM holds only the double-encoded form.

    Before the split, OSM has `714-30` and nothing answers to `714`, so the
    civic candidate is MISSING and gets created. After the split, OSM has
    `714` + addr:unit=30 — still not the building — so the civic candidate is
    *still* MISSING and still gets created. Same outcome either way, which is
    what retires the ordering constraint between gap-fill and the cleanup.
    """
    monkeypatch.setattr(conflate, "_UNIT_AWARE", True)
    before = _el(number="714-30", unit="30")
    after = _el(number="714", unit="30")
    assert _same_address(before, "714", "willow road", "") is False
    assert _same_address(after, "714", "willow road", "") is False


def test_both_sides_are_normalized_before_they_are_compared():
    """_same_address compares verbatim; the casing is settled upstream.

    The element side is normalized when the OSM index is built, the candidate
    side in _classify. Testing it here rather than inside _same_address keeps
    the helper honest about what it actually does.
    """
    idx, _poi = conflate.build_osm_index([{
        "type": "node", "id": 1, "lat": 43.5, "lon": -80.2,
        "tags": {"addr:housenumber": "714", "addr:street": "Willow Road",
                 "addr:unit": " d101 "},
    }])
    el = next(e for _lat, _lon, e in idx.query(43.5, -80.2))
    assert el["_norm_unit"] == "D101"


def test_an_element_indexed_before_this_migration_has_no_unit(monkeypatch):
    monkeypatch.setattr(conflate, "_UNIT_AWARE", True)
    assert _same_address({"_norm_number": "714", "_norm_street": "willow road"},
                         "714", "willow road", "") is True
