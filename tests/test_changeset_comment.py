"""The changeset comment renders from one place.

`[upload] changeset_comment_template` gained a `{city}` placeholder when the
tool went multi-city. Two call sites rendered it and drifted: `changeset_tags`
passed both keys, while the upload path in `osm_client` passed only `run_name`
and raised `KeyError: 'city'` — mid-upload, after a run had been reviewed and
approved. Both now go through `osm_export.changeset_comment`.
"""
import inspect

from t2 import osm_client, osm_export


def test_comment_fills_every_placeholder(monkeypatch):
    cfg = osm_export._CONFIG
    monkeypatch.setattr(
        cfg, "changeset_comment_template",
        "{city} Open Data address import, run={run_name}", raising=False,
    )
    monkeypatch.setattr(cfg, "city_name", "Toronto", raising=False)

    assert osm_export.changeset_comment("maint-snap113") == (
        "Toronto Open Data address import, run=maint-snap113"
    )


def test_upload_path_does_not_render_the_template_itself():
    """The bug was a second renderer, so the regression to guard is a second
    `.format(` on the template anywhere outside the one owner."""
    for mod in (osm_client, osm_export):
        src = inspect.getsource(mod)
        renders = src.count("changeset_comment_template.format(")
        expected = 1 if mod is osm_export else 0
        assert renders == expected, (
            f"{mod.__name__} renders the comment template {renders} time(s); "
            "it should go through osm_export.changeset_comment"
        )
