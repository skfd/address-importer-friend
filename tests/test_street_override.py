"""The overrides are per-city config now, not a compiled-in table.

The mechanism — case-insensitive lookup, whitespace collapsing, empty
pass-through — is `accordeur.StreetProfile`'s and is tested there. What this
file pins is the wiring and the city's own table: that `[streets] overrides`
reaches `apply_street_override` intact, and that Toronto's thirteen still
produce exactly the mappings the module constant produced before the move
(2026-08-28). config.example.toml is Toronto's worked example and is the
synthetic city the suite runs against, so it carries the same thirteen.
"""
import pytest

from t2.conflate import (
    STREET_NAME_OVERRIDES,
    apply_street_override,
    expand_street_name,
    normalize_street,
)

#: What `t2.conflate.STREET_NAME_OVERRIDES` held while it was a module
#: constant. Kept verbatim so the config round-trip is checked against the old
#: behaviour rather than against itself.
TORONTO_THIRTEEN = {
    "Deane Field Cres": "Deanefield Cres",
    "Golfcrest Rd": "Golf Crest Rd",
    "Forest View Rd": "Forestview Rd",
    "Greenhouse Rd": "Green House Rd",
    "Kathleen Ave": "Kathleen Cres",
    "Meadow Crest Rd": "Meadowcrest Rd",
    "Posthorn Grv": "Post Horn Grv",
    "Scenic Millway": "Scenic Mill Way",
    "Mac Gregor Ave": "MacGregor Ave",
    "Governor's Rd": "Governors Road",
    "St Andrews Gdns": "St. Andrew's Gardens",
    "St Leonard's Ave": "Saint Leonard's Avenue",
    "Sunnyslope Ave": "Sunny Slope",
}


def test_config_reproduces_the_table_the_constant_held():
    # The Tier 2 pattern: the parsed config must generate exactly what was
    # compiled in, so the move cannot have changed a single candidate's
    # street_raw.
    assert STREET_NAME_OVERRIDES == TORONTO_THIRTEEN


@pytest.mark.parametrize("src,dst", sorted(TORONTO_THIRTEEN.items()))
def test_known_overrides_use_osm_canonical_name(src, dst):
    assert apply_street_override(src) == dst


def test_pass_through_when_no_override():
    assert apply_street_override("Main St") == "Main St"
    assert apply_street_override("") == ""
    assert apply_street_override(None) is None


def test_suffixless_override_survives_expand_street_name():
    # "Sunny Slope" is the OSM canonical name and has no street-type suffix;
    # expand_street_name must not invent one or otherwise alter it, otherwise
    # the uploaded addr:street would not match OSM's existing
    # addr:street="Sunny Slope" on the building.
    assert expand_street_name(apply_street_override("Sunnyslope Ave")) == "Sunny Slope"


def test_override_can_change_street_suffix():
    # Kathleen Ave -> Kathleen Cres is a genuine suffix correction (the source
    # has the street type wrong). Confirm the normalized forms differ before
    # and after the override, otherwise matching would not actually move from
    # the wrong street to the right one.
    src_norm = normalize_street("Kathleen Ave")
    dst_norm = normalize_street(apply_street_override("Kathleen Ave"))
    assert src_norm != dst_norm
    assert dst_norm == normalize_street("Kathleen Crescent")


def test_a_city_that_declares_none_leaves_every_name_alone():
    # Guelph and Hamilton declare no [streets] section at all. Their engine
    # must then be a pure pass-through — the failure this move prevents is
    # Toronto's curated table silently rewriting another city's street names.
    from accordeur import NO_OVERRIDES

    for name in TORONTO_THIRTEEN:
        assert NO_OVERRIDES.apply_override(name) == name


def test_no_op_entries_are_refused_at_load():
    # An override that does not change the normalized form is a rule that does
    # nothing while looking like it does. The old suite asserted this over the
    # constant; now the config loader enforces it for every city.
    from t2.config import parse_street_overrides

    with pytest.raises(ValueError, match="does not change the normalized form"):
        parse_street_overrides({"overrides": {"Bloor St W": "Bloor Street West"}})
