from t2.conflate import expand_street_name, normalize_street


def test_pass_through_when_empty():
    assert expand_street_name("") == ""
    assert expand_street_name(None) is None


def test_expands_trailing_suffix_and_direction():
    assert expand_street_name("Bloor St W") == "Bloor Street West"
    assert expand_street_name("Amelia St") == "Amelia Street"


def test_leading_st_for_saint_is_preserved_verbatim():
    # The leading "St" stands for "Saint" and must NOT be rewritten as the
    # suffix "Street". Only the trailing tokens are expanded.
    assert expand_street_name("St Clair Ave E") == "St Clair Avenue East"


def test_cornwall_variant_shorts_expand_and_normalize():
    # Cornwall emits AV/CR/BV/WY (32% of its rows, added 2026-08-15).
    # Guardrail: no toronto/hamilton/guelph/quinte-west street ends in these
    # tokens, measured against all four tracker DBs the same day.
    assert expand_street_name("Larin Av") == "Larin Avenue"
    assert expand_street_name("Grant Cr") == "Grant Crescent"
    assert expand_street_name("Sunset Bv") == "Sunset Boulevard"
    assert expand_street_name("Primrose Wy") == "Primrose Way"
    assert expand_street_name("Second St W") == "Second Street West"
    # Both spellings must land on one normalized key so source matches OSM.
    assert normalize_street("Larin Av") == normalize_street("Larin Avenue")
    assert normalize_street("Grant Cr") == normalize_street("Grant Crescent")
    assert normalize_street("Sunset Bv") == normalize_street("Sunset Boulevard")
    assert normalize_street("Primrose Wy") == normalize_street("Primrose Way")


def test_glues_mc_surname_prefix():
    assert expand_street_name("Mc Caul St") == "McCaul Street"
    assert expand_street_name("Mc Gee St") == "McGee Street"
    assert expand_street_name("Mc Murray Ave") == "McMurray Avenue"
    assert expand_street_name("Mc Farland Ave") == "McFarland Avenue"
    assert expand_street_name("Mc Master Ave") == "McMaster Avenue"
    assert expand_street_name("Mc Cord Rd") == "McCord Road"
    assert expand_street_name("Mc Kenzie Ave") == "McKenzie Avenue"
    assert expand_street_name("Mc Alpine St") == "McAlpine Street"
    assert expand_street_name("Mc Connell Ave") == "McConnell Avenue"


def test_mc_glue_normalizes_to_osm_form():
    # Source "Mc Caul St" must end up matching OSM's "McCaul St" on the
    # normalized key — that's the whole point of the glue.
    assert normalize_street(expand_street_name("Mc Caul St")) == normalize_street("McCaul St")


def test_mc_glue_does_not_fire_for_already_glued_names():
    assert expand_street_name("McCaul St") == "McCaul Street"


def test_mc_glue_skips_when_next_token_is_suffix_or_direction():
    # Defensive: don't glue "Mc Way" or "Mc East" — those would be
    # nonsensical surname tokens. Leave them alone so the suffix/direction
    # expansion stays correct.
    assert expand_street_name("Mc Way") == "Mc Way"
    assert expand_street_name("Mc East") == "Mc East"


def test_mac_prefix_is_not_glued():
    # Mac is intentionally NOT glued: OSM Toronto has "Mac Frost Way"
    # spelled with a space, so blanket gluing would break that match.
    assert expand_street_name("Mac Frost Way") == "Mac Frost Way"


def test_mc_glue_is_case_insensitive_on_the_prefix():
    # The "Mc" trigger is case-insensitive, but we always emit "Mc" (the
    # OSM convention) and preserve the surname's original case.
    assert expand_street_name("MC CAUL ST") == "McCAUL Street"
    assert expand_street_name("mc caul st") == "Mccaul Street"
