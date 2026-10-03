"""The header marks the page you are on. The longest link wins, so the three
pages under /osm each light their own link and not OSM extract's."""
import pytest

from t2.web.app import nav_current


@pytest.mark.parametrize("path, link", [
    ("/", "/"),
    ("/runs/12", "/"),
    ("/runs/12/review/345", "/"),
    ("/map", "/map"),
    ("/tiles/guelph-07", "/map"),
    ("/osm", "/osm"),
    ("/osm/multi", "/osm/multi"),
    ("/osm/multi/all", "/osm/multi"),
    ("/osm/multi/corners", "/osm/multi/corners"),
    ("/osm/orphans", "/osm/orphans"),
    ("/drift/street", "/drift"),
    ("/maintenance/3/report", "/maintenance"),
    ("/units/shapes", "/units/shapes"),
])
def test_the_page_lights_the_link_it_sits_under(path, link):
    assert nav_current(path) == link


@pytest.mark.parametrize("path", ["/api/run_for_all/status", "/osmosis", "/datum"])
def test_a_page_no_link_leads_to_lights_nothing(path):
    # /osmosis is not under /osm: a bare string prefix would say it is.
    assert nav_current(path) is None
