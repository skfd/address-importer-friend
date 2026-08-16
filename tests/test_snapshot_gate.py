"""Advancing the maintenance watermark declares a month finished, so it is
gated on that month's DB snapshot being published.

The gap this closes: Toronto finalized `maint-snap90` on 2026-07-23 and the
newest public snapshot stayed `tool-db-20260605` until 2026-08-16 — six weeks
where the only record of what the import pushed lived on one machine. The rule
was written in the README and skipped anyway, so it is a check now.
"""
import pytest

from t2 import maintenance, source_db


@pytest.fixture
def wm90(monkeypatch):
    """Watermark #90, feed date 2026-07-22 — Toronto's state on 2026-08-16.
    `set_watermark` is stubbed so the gate is tested without a real tool.db."""
    advanced = []
    monkeypatch.setattr(maintenance, "get_watermark", lambda: 90)
    monkeypatch.setattr(source_db, "snapshot_date",
                        lambda snap: "2026-07-22" if snap == 90 else "2026-08-16")
    monkeypatch.setattr(source_db, "latest_snapshot_id", lambda: 115)
    monkeypatch.setattr(maintenance, "set_watermark", lambda s: advanced.append(s))
    return advanced


def _published(monkeypatch, date, tag="tool-db-x"):
    monkeypatch.setattr(maintenance, "get_published_snapshot",
                        lambda: {"date": date, "tag": tag, "url": None})


def test_blocks_when_nothing_published(wm90, monkeypatch):
    _published(monkeypatch, None)
    assert maintenance.snapshot_status()["lagging"] is True
    with pytest.raises(maintenance.SnapshotUnpublished):
        maintenance.advance_watermark()
    assert wm90 == []  # watermark untouched


def test_blocks_when_published_snapshot_predates_watermark(wm90, monkeypatch):
    # The real regression: a June release while the watermark sits in July.
    _published(monkeypatch, "2026-06-05", "tool-db-20260605")
    status = maintenance.snapshot_status()
    assert status["lagging"] is True
    assert "2026-06-05" in status["reason"]
    with pytest.raises(maintenance.SnapshotUnpublished):
        maintenance.advance_watermark()
    assert wm90 == []


def test_allows_when_snapshot_covers_the_watermark(wm90, monkeypatch):
    _published(monkeypatch, "2026-07-22", "tool-db-20260722")
    assert maintenance.snapshot_status()["lagging"] is False
    assert maintenance.advance_watermark() == 115
    assert wm90 == [115]


def test_force_overrides_for_a_city_with_nowhere_to_publish(wm90, monkeypatch):
    _published(monkeypatch, None)
    assert maintenance.advance_watermark(force=True) == 115
    assert wm90 == [115]


def test_unknown_watermark_date_does_not_block(wm90, monkeypatch):
    # Pre-`watermark_date` DBs can't be compared; never block on a comparison
    # that cannot be made.
    monkeypatch.setattr(source_db, "snapshot_date", lambda snap: None)
    _published(monkeypatch, None)
    assert maintenance.snapshot_status()["lagging"] is False
    assert maintenance.advance_watermark() == 115
