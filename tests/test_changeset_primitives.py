"""Open / upload / close take plain tags and a plain body.

The engine only ever created nodes for a run. Guelph's announced mechanical
edits are written per campaign rather than built in, but they still have to go
out through this module: the OAuth token is here, encrypted, along with the
401-refresh and 429-backoff, and a campaign script must not stand up a second
place with write access to the import account.

So the primitives are generic, the run pipeline is one caller among two, and
nothing about a run leaks into them.
"""
import xml.etree.ElementTree as ET

import pytest

from t2 import osm_client


class _Resp:
    def __init__(self, text="", status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture
def sent(monkeypatch):
    calls = []

    def fake(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path.endswith("/changeset/create"):
            return _Resp("4242")
        return _Resp("<diffResult/>")

    monkeypatch.setattr(osm_client, "_request", fake)
    return calls


def test_create_sends_exactly_the_tags_given(sent):
    assert osm_client.create_changeset(
        {"comment": "Guelph addr:province removal, batch 1", "mechanical": "yes"}
    ) == 4242
    _, path, kwargs = sent[0]
    assert path.endswith("/changeset/create")
    tags = {t.attrib["k"]: t.attrib["v"]
            for t in ET.fromstring(kwargs["data"]).findall("./changeset/tag")}
    assert tags == {"comment": "Guelph addr:province removal, batch 1", "mechanical": "yes"}


def test_upload_returns_the_diffresult_body(sent):
    assert osm_client.upload_osmchange(7, b"<osmChange/>") == "<diffResult/>"
    method, path, kwargs = sent[0]
    assert (method, kwargs["data"]) == ("POST", b"<osmChange/>")
    assert path.endswith("/changeset/7/upload")


def test_a_rejected_upload_stops_rather_than_retries(monkeypatch):
    monkeypatch.setattr(osm_client, "_request",
                        lambda *a, **k: _Resp("version mismatch", 409))
    with pytest.raises(RuntimeError, match="409"):
        osm_client.upload_osmchange(7, b"<osmChange/>")


def test_close_targets_the_changeset(sent):
    osm_client.close_changeset(99)
    method, path, _ = sent[0]
    assert (method, path.endswith("/changeset/99/close")) == ("PUT", True)
