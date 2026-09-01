"""JOSM fills in the changeset comment by itself, both ways into the editor.

Two mechanisms, and each one had a hole. Opening the exported file used to
prefill nothing, because the tags were written as an XML comment; JOSM only
reads them from a real `<changeset>` element. Pressing "Open in JOSM" used to
prefill everything except the comment and the source, because those went as
`changeset_comment` / `changeset_source` — parameters that `/import` does not
accept and drops with nothing but a line in JOSM's log.
"""
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlsplit

from t2 import osm_export
from t2.web.app import _josm_import_endpoint

TAGS = {
    "comment": "Toronto Open Data address import, run=maint-snap113",
    "source": "City of Toronto Open Data",
    "import": "yes",
}

ITEMS = [{"local_node_id": -1, "lat": 43.65, "lon": -79.38,
          "housenumber": "12", "street_raw": "Main St"}]


def _changeset_el(cs_tags):
    root = ET.fromstring(osm_export._osm_change_xml(ITEMS, cs_tags))
    return root.find("changeset")


def test_file_carries_the_tags_as_a_real_changeset_element():
    cs = _changeset_el(TAGS)
    assert cs is not None, "no <changeset> element — JOSM would prefill nothing"
    assert {t.get("k"): t.get("v") for t in cs.findall("tag")} == TAGS


def test_changeset_element_has_no_id():
    """JOSM reads the element only when its id matches the root's
    `upload-changeset` attribute. Neither is set, and null == null is the
    branch that accepts; any id here would make JOSM skip the element."""
    assert _changeset_el(TAGS).get("id") is None


def test_no_changeset_element_when_there_are_no_tags():
    assert _changeset_el(None) is None
    root = ET.fromstring(osm_export._osm_change_xml(ITEMS, None))
    assert root.find("node") is not None


def _params(url):
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def test_comment_and_source_ride_in_changeset_tags():
    p = _params(_josm_import_endpoint(7, TAGS))
    pairs = dict(kv.split("=", 1) for kv in p["changeset_tags"].split("|"))
    assert pairs == TAGS


def test_import_never_gets_the_load_and_zoom_only_params():
    """The regression that left the comment blank: /import silently ignores
    these two, so nothing may be routed to them."""
    p = _params(_josm_import_endpoint(7, TAGS))
    assert "changeset_comment" not in p
    assert "changeset_source" not in p


def test_url_is_not_baked_in():
    """The page appends `&url=` at click time, resolved against its own
    location so the static export works too — and it has to come last,
    because JOSM appends any trailing query text to the address it fetches."""
    url = _josm_import_endpoint(7, TAGS)
    assert "url=" not in url
    assert url.startswith("http://127.0.0.1:8111/import?")


def test_a_pipe_in_a_value_is_escaped():
    """JOSM splits the list on an *unescaped* pipe, so an unguarded one would
    tear a comment into two bogus tags."""
    p = _params(_josm_import_endpoint(7, {"comment": "a | b"}))
    assert p["changeset_tags"] == "comment=a \\| b"


def test_static_export_points_the_button_at_the_shipped_asset():
    """On the published site the Flask route is gone, so the app path has to
    become the relative path of the `.osm` copied into assets/. The page then
    resolves it against its own location before handing it to JOSM."""
    from t2.static_export import _rewrite_links

    html = '<button data-josm-osm="/runs/15/export.osm"></button>'
    out = _rewrite_links(
        html, "runs/15/index.html",
        {"/runs/15/export.osm": "assets/upload_run_15.osm"},
    )
    assert 'data-josm-osm="../../assets/upload_run_15.osm"' in out
