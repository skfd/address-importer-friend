"""Read-only access to the sibling addresses.db."""
import sqlite3
from datetime import datetime, timezone

from . import config as _config

_CONFIG = _config.load()


def connect_readonly() -> sqlite3.Connection:
    uri = f"file:{_CONFIG.source_sqlite_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def latest_snapshot_id(conn: sqlite3.Connection | None = None) -> int:
    own = conn is None
    if own:
        conn = connect_readonly()
    try:
        row = conn.execute("SELECT MAX(id) AS m FROM snapshots WHERE skipped = 0").fetchone()
        if not row or row["m"] is None:
            raise RuntimeError("Source DB has no non-skipped snapshots.")
        return int(row["m"])
    finally:
        if own:
            conn.close()


def latest_snapshot_info(stale_after_days: int = 14) -> dict | None:
    """Return {id, downloaded, age_days, is_stale} for the newest non-skipped
    snapshot, or None if the source DB is unavailable or empty.

    Used by the run-create UI to warn when the upstream source hasn't been
    refreshed recently. The upstream publishes daily, so >14d stale means
    we're building candidates against outdated address data.
    """
    try:
        conn = connect_readonly()
    except sqlite3.Error:
        return None
    try:
        row = conn.execute(
            "SELECT id, downloaded FROM snapshots WHERE skipped = 0 ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    ts = row["downloaded"]
    age_days: float | None = None
    if ts:
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400
        except (ValueError, TypeError):
            age_days = None
    return {
        "id": int(row["id"]),
        "downloaded": ts,
        "age_days": age_days,
        "is_stale": age_days is not None and age_days > stale_after_days,
    }


def snapshot_date(snapshot_id: int, conn: sqlite3.Connection | None = None) -> str | None:
    """The `downloaded` timestamp of a single snapshot, or None if unknown.
    Used by the maintenance history to date each delta window."""
    own = conn is None
    if own:
        conn = connect_readonly()
    try:
        row = conn.execute(
            "SELECT downloaded FROM snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()
        return row["downloaded"] if row else None
    finally:
        if own:
            conn.close()


# Qualified with the `a.` alias so the SELECT list is unambiguous when the
# delta queries below join `addresses a` against a per-point aggregate.
_ADDRESS_COLS = (
    "a.address_point_id, a.address_full, a.address_number, "
    "a.lo_num, a.lo_num_suf, a.hi_num, a.hi_num_suf, "
    "a.linear_name_full, a.linear_name, a.linear_name_type, a.linear_name_dir, "
    "a.municipality_name, a.ward_name, a.longitude, a.latitude, a.extra"
)


def iter_active_addresses_in_bbox(bbox: tuple[float, float, float, float], snapshot_id: int):
    """Yield rows from the source addresses table active at snapshot_id and inside bbox."""
    min_lat, min_lon, max_lat, max_lon = bbox
    conn = connect_readonly()
    try:
        q = f"""
            SELECT {_ADDRESS_COLS}
            FROM addresses a
            WHERE max_snapshot_id = ?
              AND latitude BETWEEN ? AND ?
              AND longitude BETWEEN ? AND ?
        """
        for row in conn.execute(q, (snapshot_id, min_lat, max_lat, min_lon, max_lon)):
            yield dict(row)
    finally:
        conn.close()


def iter_new_since(watermark_snapshot_id: int, snapshot_id: int | None = None):
    """Yield the current active row for every address_point that first appeared
    after ``watermark_snapshot_id``.

    "First appeared" is the minimum ``min_snapshot_id`` across all of a point's
    row-ranges — so an attribute edit (which retires one range and opens a new
    one for the same point) is NOT counted as new. Only a genuinely new civic
    point clears the watermark. The row returned is the one active at
    ``snapshot_id`` (defaults to the latest non-skipped snapshot)."""
    if snapshot_id is None:
        snapshot_id = latest_snapshot_id()
    conn = connect_readonly()
    try:
        q = f"""
            SELECT {_ADDRESS_COLS}
            FROM addresses a
            JOIN (
                SELECT address_point_id, MIN(min_snapshot_id) AS first_snap
                FROM addresses
                GROUP BY address_point_id
                HAVING first_snap > ?
            ) n ON n.address_point_id = a.address_point_id
            WHERE a.max_snapshot_id = ?
        """
        for row in conn.execute(q, (watermark_snapshot_id, snapshot_id)):
            yield dict(row)
    finally:
        conn.close()


def iter_retired_since(watermark_snapshot_id: int, snapshot_id: int | None = None):
    """Yield the last-known row for every address_point that dropped out of the
    feed after ``watermark_snapshot_id`` and is absent from ``snapshot_id``.

    "Dropped out" means the maximum ``max_snapshot_id`` across a point's
    row-ranges is in [watermark, snapshot_id) — i.e. it was last seen at or
    after the watermark but is no longer active. The row returned is that
    last-seen range, so its coordinates/class reflect the point as it was when
    the City last published it."""
    if snapshot_id is None:
        snapshot_id = latest_snapshot_id()
    conn = connect_readonly()
    try:
        q = f"""
            SELECT {_ADDRESS_COLS}, r.last_snap AS last_snapshot_id
            FROM addresses a
            JOIN (
                SELECT address_point_id, MAX(max_snapshot_id) AS last_snap
                FROM addresses
                GROUP BY address_point_id
                HAVING last_snap >= ? AND last_snap < ?
            ) r ON r.address_point_id = a.address_point_id
               AND r.last_snap = a.max_snapshot_id
        """
        for row in conn.execute(q, (watermark_snapshot_id, snapshot_id)):
            yield dict(row)
    finally:
        conn.close()
