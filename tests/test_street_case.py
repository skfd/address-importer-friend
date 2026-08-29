"""`[export] street_case` — title-casing ALL-CAPS street names on the way out.

Three sources in the portfolio publish street names in capitals (Quinte West,
Brant, Oakville). Conflation is case-insensitive, so their baselines are
correct and only the *upload* is wrong: it would write shouting `addr:street`
values into OSM. The step therefore lives on the export path, gated on a
per-city flag, and the guardrail is that the mixed-case cities cannot move —
Toronto, Hamilton and Guelph must keep writing exactly what their sources say.

The hard cases are the ones TODO §9 named: apostrophes, "Mc", hyphens and
numbered county roads.
"""
import pytest
import xml.etree.ElementTree as ET

from t2 import osm_export
from t2.config import parse_street_case
from t2.conflate import _proposed_tags
from t2.osm_export import title_case_street


def item(street: str) -> dict:
    return {
        "candidate_id": 1,
        "local_node_id": -1,
        "housenumber": "123",
        "street_raw": street,
        "lat": 43.5,
        "lon": -80.2,
    }


@pytest.fixture
def titling(monkeypatch):
    monkeypatch.setattr(osm_export._CONFIG, "export_street_case", "title")


# --- the flag ---------------------------------------------------------------

def test_absent_key_preserves():
    assert parse_street_case({}) == "preserve"
    assert parse_street_case({"attribution": "x"}) == "preserve"
    assert parse_street_case(None) == "preserve"


def test_declared_values_round_trip():
    assert parse_street_case({"street_case": "title"}) == "title"
    assert parse_street_case({"street_case": "preserve"}) == "preserve"


@pytest.mark.parametrize("bad", ["Title", "titlecase", "upper", "", 1, True, None])
def test_an_unknown_value_is_refused(bad):
    """A typo must not fall back to preserve — that would upload capitals."""
    with pytest.raises(ValueError, match="street_case"):
        parse_street_case({"street_case": bad})


# --- the guardrail ----------------------------------------------------------

def test_the_engine_default_is_preserve():
    assert osm_export._CONFIG.export_street_case == "preserve"


def test_a_mixed_case_city_is_byte_identical():
    """Toronto/Hamilton/Guelph shapes, with the flag off: nothing is touched."""
    for street in ["Bloor Street West", "St. Andrew's Gardens", "McCaul Street",
                   "Sunny Slope", "MacGregor Avenue", "Highway 27"]:
        assert osm_export.build_tags(item(street))["addr:street"] == street


def test_titling_is_a_no_op_on_already_mixed_case(titling):
    """Even turned on, a name that arrived with case survives untouched —
    including "Mcgee", which accordeur deliberately does not fix."""
    for street in ["Bloor Street West", "McCaul Street", "Mcgee Street",
                   "MacGregor Avenue", "St. Andrew's Gardens"]:
        assert title_case_street(street) == street


# --- the real sources -------------------------------------------------------

@pytest.mark.parametrize("shouted,expected", [
    # Quinte West (2026-08-15), the source that raised §9.
    ("ANNA COURT", "Anna Court"),
    ("ANNA Court", "Anna Court"),            # after expand_street_name
    # Brant (2026-08-16), second consumer.
    ("GRAND RIVER STREET NORTH", "Grand River Street North"),
    ("GRAND RIVER Street North", "Grand River Street North"),
    # Oakville (2026-08-16) — the city whose upload this blocks.
    ("MCCRANEY Street", "McCraney Street"),
    ("MCCRANEY STREET", "McCraney Street"),
])
def test_the_portfolio_sources(shouted, expected):
    assert title_case_street(shouted) == expected


@pytest.mark.parametrize("shouted,expected", [
    ("O'NEIL CRESCENT", "O'Neil Crescent"),          # apostrophe: a real name
    ("GOVERNOR'S ROAD", "Governor's Road"),          # apostrophe: possessive s
    ("D'ARCY STREET", "D'Arcy Street"),
    ("MCGILL STREET", "McGill Street"),
    ("MCRAE DRIVE", "McRae Drive"),
    ("MACDONALD AVENUE", "Macdonald Avenue"),        # Mac is left alone
    ("MCDONALD-CARTIER LANE", "McDonald-Cartier Lane"),
    ("SAINT-LOUIS STREET", "Saint-Louis Street"),
    # Quinte West's two railway-crossing roads: a slash splits like a hyphen.
    ("CNR/WALLBRIDGE-LOYALIST ROAD", "Cnr/Wallbridge-Loyalist Road"),
    # Irreducible: an all-caps source spells an acronym like any other word.
    ("YMCA BOULEVARD", "Ymca Boulevard"),
    ("COUNTY ROAD 40", "County Road 40"),
    ("3RD LINE", "3rd Line"),
    ("ST CLAIR AVENUE EAST", "St Clair Avenue East"),
    ("THE QUEENSWAY", "The Queensway"),
    ("LA SALLE BOULEVARD", "La Salle Boulevard"),
    # Every word is capitalized, particles included. Measured against OSM
    # Toronto: these two are what a lowercasing rule would have got wrong.
    ("CHESTER LE BOULEVARD", "Chester Le Boulevard"),
    ("VITTORIO DE LUCA DRIVE", "Vittorio De Luca Drive"),
    ("ISLE OF MAN ROAD", "Isle Of Man Road"),
])
def test_the_hard_cases(shouted, expected):
    assert title_case_street(shouted) == expected


def test_it_is_idempotent():
    for shouted in ["MCCRANEY STREET", "O'NEIL CRESCENT", "ISLE OF MAN ROAD",
                    "COUNTY ROAD 40", "GRAND RIVER STREET NORTH"]:
        once = title_case_street(shouted)
        assert title_case_street(once) == once


def test_empty_passes_through():
    assert title_case_street("") == ""


# --- the one owner ----------------------------------------------------------

def test_the_flag_reaches_the_node_and_the_preview(titling):
    """build_tags is the single writer, so the review UI cannot show the
    operator a different street from the one the changeset carries."""
    it = item("MCCRANEY Street")
    assert osm_export.build_tags(it)["addr:street"] == "McCraney Street"
    assert _proposed_tags(it)["addr:street"] == "McCraney Street"

    root = ET.fromstring(osm_export._osm_change_xml([it]))
    tags = {t.attrib["k"]: t.attrib["v"] for t in root.findall("./node/tag")}
    assert tags["addr:street"] == "McCraney Street"


def test_the_housenumber_keeps_its_capital_suffix(titling):
    """Oakville's `335A` is a housenumber suffix, not shouting."""
    it = dict(item("MCCRANEY Street"), housenumber="335A")
    assert osm_export.build_tags(it)["addr:housenumber"] == "335A"
