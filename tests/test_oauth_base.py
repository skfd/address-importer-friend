from t2 import osm_client


def test_prod_oauth_goes_to_the_website(monkeypatch):
    monkeypatch.setattr(osm_client._CONFIG, "osm_api_base", "https://api.openstreetmap.org")
    assert osm_client._auth_base() == "https://www.openstreetmap.org"


def test_dev_oauth_stays_on_its_one_host(monkeypatch):
    monkeypatch.setattr(osm_client._CONFIG, "osm_api_base", "https://master.apis.dev.openstreetmap.org/")
    assert osm_client._auth_base() == "https://master.apis.dev.openstreetmap.org"
