"""The published proposal vs the checkout's copy — a warning, never a gate.

Toronto's wiki page was three revisions behind on 2026-08-29 and nothing said
so: the month row, a follow-ups section recording a dropped campaign, and a
tagging-plan change had all queued up, and three `future-work/` links had 404'd
on a public import proposal since the repo split. The paste is the last step of
a month that nothing enforces.

What these tests pin is mostly what the check *refuses* to do. It does not
block a close; it does not report a network failure as a failure to paste; and
it does not exist at all for a city with no proposal, because a city being
scaffolded must not be nagged about not having published one.
"""
from pathlib import Path

import pytest

from t2 import config as _config, wiki_sync


@pytest.fixture(autouse=True)
def clear_cache():
    wiki_sync._cache = None
    yield
    wiki_sync._cache = None


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    """A city dir with a proposal in it, and a declared page to compare against."""
    import shutil
    shutil.copy(Path(__file__).resolve().parents[1] / "config.example.toml",
                tmp_path / "config.toml")
    monkeypatch.setattr(_config, "CITY_DIR", tmp_path)
    cfg = _config.load()
    monkeypatch.setattr(cfg, "export_import_plan", "https://wiki.example.org/wiki/City/Import")
    monkeypatch.setattr(_config, "load", lambda: cfg)
    return tmp_path


def write_proposal(path, text):
    (path / wiki_sync.PROPOSAL_FILENAME).write_text(text, encoding="utf-8")


# --- the URL and the comparison --------------------------------------------

def test_raw_url_appends_the_action():
    assert wiki_sync.raw_url("https://wiki.osm.org/wiki/X") == \
        "https://wiki.osm.org/wiki/X?action=raw"


def test_raw_url_respects_an_existing_query():
    assert wiki_sync.raw_url("https://wiki.osm.org/index.php?title=X") == \
        "https://wiki.osm.org/index.php?title=X&action=raw"


def test_trailing_whitespace_is_not_a_divergence():
    """A round trip through an editor and a wiki save moves trailing
    whitespace unpredictably. Toronto's real diff was the three pending
    revisions plus exactly one missing final newline."""
    assert wiki_sync.compare("a\nb\n", "a  \nb\n\n\n")["state"] == "match"


def test_a_changed_word_is_a_divergence():
    out = wiki_sync.compare("Last revised: 2026-08-28\n", "Last revised: 2026-08-27\n")
    assert out["state"] == "diverged"
    assert out["local_only"] == 1 and out["live_only"] == 1
    assert out["changed_lines"] == 2


def test_an_added_row_counts_only_on_the_local_side():
    local = "| row a\n| row b\n! Total 2\n"
    live = "| row a\n! Total 2\n"
    out = wiki_sync.compare(local, live)
    assert out["state"] == "diverged"
    assert out["local_only"] == 1 and out["live_only"] == 0


# --- the states ------------------------------------------------------------

def test_a_city_with_no_proposal_is_not_tracked():
    """The engine's own test checkout: a config.toml, no proposal."""
    assert wiki_sync.local_proposal() is None
    out = wiki_sync.status()
    assert out["state"] == "off"
    assert wiki_sync.PROPOSAL_FILENAME in out["reason"]


def test_a_city_with_no_import_plan_is_not_tracked(checkout, monkeypatch):
    write_proposal(checkout, "text")
    cfg = _config.load()
    monkeypatch.setattr(cfg, "export_import_plan", "")
    assert wiki_sync.status()["state"] == "off"


def test_match(checkout, monkeypatch):
    write_proposal(checkout, "one\ntwo\n")
    monkeypatch.setattr(wiki_sync, "_fetch", lambda url: "one\ntwo")
    assert wiki_sync.status()["state"] == "match"


def test_diverged_reports_the_page_it_read(checkout, monkeypatch):
    write_proposal(checkout, "one\ntwo\nthree\n")
    monkeypatch.setattr(wiki_sync, "_fetch", lambda url: "one\ntwo")
    out = wiki_sync.status()
    assert out["state"] == "diverged" and out["changed_lines"] == 1
    assert out["raw_url"].endswith("?action=raw")
    assert out["filename"] == wiki_sync.PROPOSAL_FILENAME


def test_an_unreachable_wiki_is_unknown_not_diverged(checkout, monkeypatch):
    """The distinction the operator needs: 'I could not look' is not 'you did
    not paste'. Reporting it as divergence would train them to ignore it."""
    write_proposal(checkout, "one\n")

    def boom(url):
        raise OSError("connection reset")

    monkeypatch.setattr(wiki_sync, "_fetch", boom)
    out = wiki_sync.status()
    assert out["state"] == "unknown"
    assert "connection reset" in out["reason"]


def test_the_result_is_cached(checkout, monkeypatch):
    write_proposal(checkout, "one\n")
    calls = []

    def counted(url):
        calls.append(url)
        return "one"

    monkeypatch.setattr(wiki_sync, "_fetch", counted)
    wiki_sync.status()
    wiki_sync.status()
    assert len(calls) == 1
    wiki_sync.status(force=True)
    assert len(calls) == 2


# --- what it must never do -------------------------------------------------

def test_nothing_in_the_close_path_consults_it():
    """The DB snapshot gates a close; this does not, deliberately (see
    t2/wiki_sync.py). If a close ever starts importing this module, that was a
    decision and it should break this test on the way in."""
    import inspect
    from t2 import maintenance

    assert "wiki_sync" not in inspect.getsource(maintenance)
