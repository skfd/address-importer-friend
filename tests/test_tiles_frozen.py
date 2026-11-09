"""A city whose config says [tiles] frozen never gets its tile layer rebuilt.

Tile ids do not survive a rebuild (future-work/multi-city/TODO.md §7), so a
city with runs to keep freezes its tiles. The guard has to fire before
anything touches the data directory: no download, no lock, no tiles.json.
"""
from types import SimpleNamespace

import pytest

from t2 import tiles_build


def _cfg(tmp_path, frozen):
    return SimpleNamespace(
        city_name="Thunder Bay",
        tiles_frozen=frozen,
        data_dir=tmp_path,
        city_neighbourhoods_url="",
    )


def test_frozen_city_refuses_to_rebuild(tmp_path, monkeypatch):
    monkeypatch.setattr(tiles_build._config, "load", lambda: _cfg(tmp_path, "Import announced."))
    with pytest.raises(tiles_build.TilesFrozen, match="Import announced"):
        tiles_build.run()
    assert not (tmp_path / "tiles").exists()
    assert not (tmp_path / "tiles.json").exists()


def test_force_does_not_thaw(tmp_path, monkeypatch):
    monkeypatch.setattr(tiles_build._config, "load", lambda: _cfg(tmp_path, "Frozen."))
    with pytest.raises(tiles_build.TilesFrozen):
        tiles_build.run(force=True)


def test_unfrozen_city_gets_past_the_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(tiles_build._config, "load", lambda: _cfg(tmp_path, ""))
    reached = {}
    monkeypatch.setattr(
        tiles_build, "_run_without_layer",
        lambda cfg, paths, dry_run: reached.setdefault("ok", True),
    )
    assert tiles_build.run() is True
    assert reached == {"ok": True}
