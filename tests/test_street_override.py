from t2.conflate import (
    STREET_NAME_OVERRIDES,
    apply_street_override,
    normalize_street,
)


def test_pass_through_when_no_override():
    assert apply_street_override("Main St") == "Main St"


def test_returns_input_unchanged_on_empty_input():
    assert apply_street_override("") == ""
    assert apply_street_override(None) is None


def test_known_overrides_use_osm_canonical_name():
    assert apply_street_override("Deane Field Cres") == "Deanefield Cres"
    assert apply_street_override("Golfcrest Rd") == "Golf Crest Rd"
    assert apply_street_override("Forest View Rd") == "Forestview Rd"
    assert apply_street_override("Greenhouse Rd") == "Green House Rd"
    assert apply_street_override("Kathleen Ave") == "Kathleen Cres"
    assert apply_street_override("Meadow Crest Rd") == "Meadowcrest Rd"
    assert apply_street_override("Posthorn Grv") == "Post Horn Grv"
    assert apply_street_override("Scenic Millway") == "Scenic Mill Way"
    assert apply_street_override("Mac Gregor Ave") == "MacGregor Ave"
    assert apply_street_override("Governor's Rd") == "Governors Road"
    assert apply_street_override("St Andrews Gdns") == "St. Andrew's Gardens"
    assert apply_street_override("Sunnyslope Ave") == "Sunny Slope"


def test_suffixless_override_survives_expand_street_name():
    # "Sunny Slope" is the OSM canonical name and has no street-type
    # suffix; expand_street_name must not invent one or otherwise alter it,
    # otherwise the uploaded addr:street wouldn't match OSM's existing
    # addr:street="Sunny Slope" on the building.
    from t2.conflate import expand_street_name

    assert expand_street_name(apply_street_override("Sunnyslope Ave")) == "Sunny Slope"


def test_override_can_change_street_suffix():
    # Kathleen Ave -> Kathleen Cres is a genuine suffix correction (the
    # source has the street type wrong). Confirm the normalized forms
    # differ before and after the override, otherwise matching would not
    # actually move from the wrong street to the right one.
    src_norm = normalize_street("Kathleen Ave")
    dst_norm = normalize_street(apply_street_override("Kathleen Ave"))
    assert src_norm != dst_norm
    assert dst_norm == normalize_street("Kathleen Crescent")


def test_lookup_is_case_insensitive():
    assert apply_street_override("deane field cres") == "Deanefield Cres"
    assert apply_street_override("GOLFCREST RD") == "Golf Crest Rd"


def test_lookup_collapses_whitespace():
    assert apply_street_override("  Forest   View   Rd  ") == "Forestview Rd"


def test_overridden_name_normalizes_to_osm_form():
    # Source "Forest View Rd" -> override -> normalize matches OSM
    # "Forestview Road" (which itself normalizes to "FORESTVIEW RD").
    overridden = apply_street_override("Forest View Rd")
    assert normalize_street(overridden) == normalize_street("Forestview Road")


def test_override_table_entries_are_self_consistent():
    # Every override must change the normalized form, otherwise it's a
    # no-op the normalizer should already handle on its own.
    for src, dst in STREET_NAME_OVERRIDES.items():
        assert normalize_street(src) != normalize_street(dst), (
            f"override {src!r} -> {dst!r} doesn't change the normalized "
            "form; the normalizer already covers this case"
        )
