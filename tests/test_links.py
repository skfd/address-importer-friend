"""`[links]` is the chrome contract: where the operator's header and footer point.

The pin below is the same pattern as `test_street_override`: what was hardcoded
into `base.html` must come back out of config unchanged, so moving it cannot
have altered a single link Toronto's operator sees. Everything else here is
about the city that declares *nothing* — the failure this section exists to
prevent is one city being shown another city's repo, thread and licence.
"""
import pytest

from t2.config import Links, parse_links

#: The four values `base.html` carried as literals until 2026-08-29.
TORONTO_LINKS = {
    "repo": "https://github.com/skfd/toronto-2-address-import",
    "discussion": "https://community.openstreetmap.org/t/address-import-for-toronto/119368",
    "proposal": (
        "https://github.com/skfd/toronto-2-address-import/blob/main/"
        "IMPORT_PROPOSAL.mediawiki"
    ),
    "open_data_name": "Toronto Open Data",
    "open_data_url": "https://open.toronto.ca/open-data-licence/",
}


def test_config_reproduces_the_links_the_template_hardcoded(links):
    assert {
        "repo": links.repo,
        "discussion": links.discussion,
        "proposal": links.proposal,
        "open_data_name": links.open_data_name,
        "open_data_url": links.open_data_url,
    } == TORONTO_LINKS


def test_absent_section_declares_nothing():
    # Not "falls back to Toronto" — nothing. What the templates do with an
    # empty link is their business; what config must not do is invent one.
    assert parse_links({}) == Links()
    assert parse_links({}).repo == ""


def test_unknown_key_is_refused():
    # A typo silently drops a link otherwise, and a missing footer link is
    # exactly the kind of absence nobody notices.
    with pytest.raises(ValueError, match="unknown key"):
        parse_links({"github": "https://github.com/skfd/x"})


def test_non_url_is_refused():
    with pytest.raises(ValueError, match="not an http"):
        parse_links({"repo": "skfd/toronto-2-address-import"})


def test_open_data_needs_both_halves():
    with pytest.raises(ValueError, match="half a citation"):
        parse_links({"open_data": {"name": "Guelph Open Data"}})
    with pytest.raises(ValueError, match="half a citation"):
        parse_links({"open_data": {"url": "https://guelph.ca/licence"}})


def test_open_data_both_halves_or_neither_is_fine():
    assert parse_links({"open_data": {}}).open_data_name == ""
    both = parse_links(
        {"open_data": {"name": "Guelph Open Data", "url": "https://guelph.ca/licence"}}
    )
    assert (both.open_data_name, both.open_data_url) == (
        "Guelph Open Data",
        "https://guelph.ca/licence",
    )


def test_open_data_unknown_key_is_refused():
    with pytest.raises(ValueError, match="unknown key"):
        parse_links({"open_data": {"name": "x", "url": "https://x", "licence": "y"}})


@pytest.fixture
def links():
    from t2 import config as _config

    return _config.load().links


def test_static_export_includes_the_ranges_page_for_a_city_that_has_ranges():
    from t2.static_export import _ranges_page

    assert _ranges_page() == [("/source/multi", "source/multi/index.html")]


def test_static_export_omits_the_ranges_page_for_a_rangeless_city(monkeypatch):
    # Guelph and Hamilton declare no lo_num/hi_num, so the nav hides
    # /source/multi. An export that wrote it anyway would publish an empty page
    # nothing links to (03-capability-gating.md).
    from dataclasses import replace

    from t2 import config as _config, static_export

    cfg = _config.load()
    rangeless = replace(
        cfg, source_fields=replace(cfg.source_fields, lo_num=None, hi_num=None)
    )
    assert not rangeless.source_fields.has_ranges
    monkeypatch.setattr(_config, "load", lambda: rangeless)
    assert static_export._ranges_page() == []
