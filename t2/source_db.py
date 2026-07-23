"""Read-only access to the sibling change-tracker DB (ontario-address-changes'
toronto.db)."""
import re
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
    """The City-feed date (`YYYY-MM-DD`) of a single snapshot, or None if unknown.
    Used by the maintenance history to date each delta window.

    Taken from the snapshot filename, not `downloaded`: in toronto.db the
    historical snapshots were bulk-imported on one day, so `downloaded` is that
    import timestamp, not the feed date. The filename carries the true feed date
    (`…-2026-06-05.geojson`). Falls back to `downloaded` if the name has none."""
    own = conn is None
    if own:
        conn = connect_readonly()
    try:
        row = conn.execute(
            "SELECT filename, downloaded FROM snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()
        if not row:
            return None
        m = re.search(r"\d{4}-\d{2}-\d{2}", row["filename"] or "")
        return m.group() if m else row["downloaded"]
    finally:
        if own:
            conn.close()


# The source is now ontario-address-changes' generic `toronto.db` (SCD-2, one
# `props` JSON blob per row) instead of the retired per-city `addresses.db` with
# flat Toronto columns. This projection maps the generic schema back to the row
# contract the rest of t2 already consumes, so callers are unchanged:
#   identity_key -> address_point_id, full/number -> address_full/address_number,
#   street -> linear_name_full, LO_NUM/HI_NUM(+suf), MUNICIPALITY_NAME, WARD_NAME
#   and ADDRESS_CLASS_DESC pulled out of `props` (kept there via toronto.toml
#   keep_fields). `props` is exposed as `extra` because t2 only reads
#   ADDRESS_CLASS_DESC from it.
# `props` stores the source's literal string 'None' for empty suffixes; NULLIF
# restores the SQL NULL the old columns had, so `(r["lo_num_suf"] or "")` logic
# in ranges/reverse_sweep keeps working. linear_name/_type/_dir are dropped by
# the tracker (ignore_fields) and were dead fallbacks here (linear_name_full is
# always present), so they project as NULL.
# Qualified with the `a.` alias so the SELECT list is unambiguous when the
# delta queries below join `addresses a` against a per-point aggregate.
_ADDRESS_COLS = (
    "a.identity_key AS address_point_id, a.full AS address_full, "
    "a.number AS address_number, "
    "CAST(json_extract(a.props,'$.LO_NUM') AS INTEGER) AS lo_num, "
    "NULLIF(json_extract(a.props,'$.LO_NUM_SUF'),'None') AS lo_num_suf, "
    "CAST(json_extract(a.props,'$.HI_NUM') AS INTEGER) AS hi_num, "
    "NULLIF(json_extract(a.props,'$.HI_NUM_SUF'),'None') AS hi_num_suf, "
    "a.street AS linear_name_full, "
    "NULL AS linear_name, NULL AS linear_name_type, NULL AS linear_name_dir, "
    "json_extract(a.props,'$.MUNICIPALITY_NAME') AS municipality_name, "
    "json_extract(a.props,'$.WARD_NAME') AS ward_name, "
    "a.longitude, a.latitude, a.props AS extra"
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
                SELECT identity_key, MIN(min_snapshot_id) AS first_snap
                FROM addresses
                GROUP BY identity_key
                HAVING first_snap > ?
            ) n ON n.identity_key = a.identity_key
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
    the City last published it.

    **Re-issues are excluded.** The City sometimes retires a point_id and emits
    a new one for the *same civic address* (same number + street, moved a few
    metres). The address never left, so it must not be flagged for deletion — it
    rides the additions path instead. We drop any retired point whose
    (address_number, linear_name_full) is still active at ``snapshot_id`` under a
    different point_id."""
    if snapshot_id is None:
        snapshot_id = latest_snapshot_id()
    conn = connect_readonly()
    try:
        q = f"""
            SELECT {_ADDRESS_COLS}, r.last_snap AS last_snapshot_id
            FROM addresses a
            JOIN (
                SELECT identity_key, MAX(max_snapshot_id) AS last_snap
                FROM addresses
                GROUP BY identity_key
                HAVING last_snap >= ? AND last_snap < ?
            ) r ON r.identity_key = a.identity_key
               AND r.last_snap = a.max_snapshot_id
            WHERE NOT EXISTS (
                SELECT 1 FROM addresses b
                WHERE b.number   = a.number
                  AND b.street   = a.street
                  AND b.identity_key <> a.identity_key
                  AND b.max_snapshot_id   = ?
            )
        """
        for row in conn.execute(q, (watermark_snapshot_id, snapshot_id, snapshot_id)):
            yield dict(row)
    finally:
        conn.close()
