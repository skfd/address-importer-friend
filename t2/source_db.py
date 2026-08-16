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


# The source is ontario-address-changes' generic tracker schema (SCD-2, one
# `props` JSON blob per row). This projection maps it back to the row contract
# the rest of t2 consumes — address_point_id, address_full, linear_name_full,
# lo_num/hi_num(+suf), municipality_name, ward_name, `props` as `extra` —
# but where each value comes from is per-city config ([source_fields], see
# future-work/multi-city/02-city-config-contract.md): the canonical columns
# are not dependable across cities, and the Toronto-only props keys must not
# be baked in (03-capability-gating.md). An undeclared optional field projects
# SQL NULL, so callers keep their contract and capability gating decides what
# may run.
# Toronto's declaration generates byte-for-byte the SQL that was previously
# hardcoded here (asserted by tests/test_source_fields.py — the guardrail:
# tool.db is living, Toronto's behaviour must not move):
#   full -> address_full, street -> linear_name_full, LO_NUM/HI_NUM(+suf),
#   MUNICIPALITY_NAME, WARD_NAME and ADDRESS_CLASS_DESC out of `props` (kept
#   there via toronto.toml keep_fields).
# `props` stores the source's literal string 'None' for empty suffixes; NULLIF
# restores the SQL NULL the old columns had, so `(r["lo_num_suf"] or "")` logic
# in ranges/reverse_sweep keeps working. linear_name/_type/_dir are dropped by
# the tracker (ignore_fields) and were dead fallbacks here (linear_name_full is
# always present), so they project as NULL.
# Qualified with the `a.` alias so the SELECT list is unambiguous when the
# delta queries below join `addresses a` against a per-point aggregate.


def _spec_sql(spec: str, alias: str) -> str:
    """SQL value expression for one [source_fields] spec.

    ``alias`` prefixes column references ("a" for the delta queries' joined
    form, "" for callers selecting from a bare `addresses`)."""
    p = f"{alias}." if alias else ""
    if spec in ("street", "full", "number", "unit"):
        return f"{p}{spec}"
    key = spec.removeprefix("props:")
    return f"json_extract({p}props,'$.{key}')"


def field_sql(sf: _config.SourceFields, name: str, alias: str = "a") -> str:
    """SQL value expression (no AS) for a logical source field under recipe
    ``sf``. Undeclared optional fields project literal NULL — visible in the
    generated SQL rather than an absent key at runtime."""
    if name == "number":
        if sf.number_from.startswith("props:"):
            # e.g. Thunder Bay's ADDRESS ("963 1/2", "688B") — the combined
            # civic number with its qualifier, which the tracker's integer
            # column drops (the hastings shape, 2026-08-16).
            return _spec_sql(sf.number_from, alias)
        if sf.number_from == "full":
            # Leading whitespace token of the combined column (Waterloo's
            # CIVIC_ADDR — the tracker number column is 100% NULL there).
            # The trailing "|| ' '" makes single-token fulls terminate.
            p = f"{alias}." if alias else ""
            return (
                f"NULLIF(SUBSTR({p}full, 1, INSTR({p}full || ' ', ' ') - 1),'')"
            )
        p = f"{alias}." if alias else ""
        return f"{p}number"
    if name == "street":
        if sf.street_from == "full":
            # Derive the street by stripping the housenumber prefix from the
            # combined column. Length-based, not prefix-match: Barrie's 18
            # dirty rows (2026-08-15: "32PENNELL DR" missing its space,
            # KIRKWOOD WAY rows whose number disagrees with full) all strip
            # correctly by length where token-splitting would not. First
            # exercised by Barrie — the branch was a naive column projection
            # (including the number!) until then; declaring it obliges the
            # onboarding probe to verify number-length ≈ leading-token-length
            # on the city's rows.
            p = f"{alias}." if alias else ""
            return (
            f"NULLIF(TRIM(SUBSTR({p}full, "
            f"LENGTH(COALESCE({field_sql(sf, 'number', alias)},'')) + 1)),'')"
        )
        return _spec_sql(sf.street_from, alias)
    if name == "full":
        if sf.full_from == "full":
            return _spec_sql("full", alias)
        # "number+street": the source publishes no combined column (e.g.
        # Hamilton), so synthesize the tracker reports' own fallback form.
        p = f"{alias}." if alias else ""
        street = field_sql(sf, "street", alias)
        return (
            f"NULLIF(TRIM(COALESCE({field_sql(sf, 'number', alias)},'') || ' ' "
            f"|| COALESCE({street},'')),'')"
        )
    if name in ("lo_num", "hi_num"):
        spec = getattr(sf, name)
        return f"CAST({_spec_sql(spec, alias)} AS INTEGER)" if spec else "NULL"
    if name in ("lo_num_suf", "hi_num_suf"):
        spec = getattr(sf, name)
        return f"NULLIF({_spec_sql(spec, alias)},'None')" if spec else "NULL"
    if name in ("municipality", "ward", "status"):
        spec = getattr(sf, name)
        return _spec_sql(spec, alias) if spec else "NULL"
    if name == "unit":
        spec = sf.unit
        if spec == "full-after-street":
            # The unit is whatever trails the street inside the combined
            # column ("29 BARREL YARDS BLVD 1205" -> "1205"; 41.9% of
            # Waterloo's rows, 2026-08-16 — hidden units the tracker does not
            # map). Anchored on the street value; a full that does not
            # contain " <street>" yields NULL rather than garbage.
            p = f"{alias}." if alias else ""
            street = field_sql(sf, "street", alias)
            probe = f"INSTR({p}full, ' ' || {street})"
            tail = f"SUBSTR({p}full, {probe} + 1 + LENGTH({street}))"
            return f"CASE WHEN {probe} > 0 THEN NULLIF(TRIM({tail}),'') END"
        # Sources write '' or the literal string 'None' for "no unit";
        # both must read as SQL NULL so the collapse elects those rows.
        return f"NULLIF(NULLIF({_spec_sql(spec, alias)},''),'None')" if spec else "NULL"
    raise KeyError(f"unknown logical source field {name!r}")


def expr(name: str, alias: str = "a") -> str:
    """field_sql bound to this process's city config — for callers (ranges,
    source_multi) that build their own source-DB queries."""
    return field_sql(_CONFIG.source_fields, name, alias)


def build_address_cols(sf: _config.SourceFields) -> str:
    return (
        f"a.identity_key AS address_point_id, {field_sql(sf, 'full')} AS address_full, "
        f"{field_sql(sf, 'number')} AS address_number, "
        f"{field_sql(sf, 'lo_num')} AS lo_num, "
        f"{field_sql(sf, 'lo_num_suf')} AS lo_num_suf, "
        f"{field_sql(sf, 'hi_num')} AS hi_num, "
        f"{field_sql(sf, 'hi_num_suf')} AS hi_num_suf, "
        f"{field_sql(sf, 'street')} AS linear_name_full, "
        "NULL AS linear_name, NULL AS linear_name_type, NULL AS linear_name_dir, "
        f"{field_sql(sf, 'municipality')} AS municipality_name, "
        f"{field_sql(sf, 'ward')} AS ward_name, "
        "a.longitude, a.latitude, a.props AS extra"
    )


_ADDRESS_COLS = build_address_cols(_CONFIG.source_fields)


# --- collapse-to-civic (units_policy, 09-units.md) --------------------------
# A unit-bearing source publishes one row per unit, stacked at the parcel
# point (Hamilton: 100,587 of 273,374 rows). Under `[units] policy =
# "collapse-to-civic"` the projection yields ONE representative row per civic
# address — keyed (number, street, municipality); municipality is load-bearing,
# an amalgamated city reuses street names across former municipalities
# (Hamilton: 776 (number, street) pairs span communities) — electing the
# unit-less row when one exists (it is the parcel's own civic point), else the
# lowest identity_key, so the choice is deterministic across runs. With no
# policy the queries are exactly their pre-collapse forms — the Toronto
# guardrail extends to query shape, not just the projection.


def _status_filter(
    sf: _config.SourceFields,
    active_status: tuple[str, ...] | None,
    alias: str,
) -> str:
    """WHERE fragment excluding rows whose lifecycle status is not importable
    (TODO §11: Barrie's Pending, Niagara's Proposed). Empty when no policy is
    declared, so every query stays byte-identical for status-less cities —
    the Toronto guardrail again. NULL status fails the IN and is excluded:
    a declared status field missing on a row is not evidence of reality."""
    if not active_status:
        return ""
    quoted = ", ".join("'" + v.replace("'", "''") + "'" for v in active_status)
    return f"\n              AND {field_sql(sf, 'status', alias)} IN ({quoted})"


def _unit_rank(sf: _config.SourceFields, alias: str) -> str:
    p = f"{alias}." if alias else ""
    return (
        f"ROW_NUMBER() OVER (PARTITION BY {field_sql(sf, 'number', alias)}, "
        f"{field_sql(sf, 'street', alias)}, {field_sql(sf, 'municipality', alias)} "
        f"ORDER BY ({field_sql(sf, 'unit', alias)} IS NOT NULL), {p}identity_key"
        ") AS _unit_rn"
    )


def build_active_bbox_query(
    sf: _config.SourceFields,
    collapse: bool,
    active_status: tuple[str, ...] | None = None,
) -> str:
    """Active-rows-in-bbox query. Params: (snapshot, min_lat, max_lat,
    min_lon, max_lon) in both variants."""
    cols = build_address_cols(sf)
    where = (
        "max_snapshot_id = ?\n"
        "              AND latitude BETWEEN ? AND ?\n"
        "              AND longitude BETWEEN ? AND ?"
        + _status_filter(sf, active_status, "")
    )
    if not collapse:
        return f"""
            SELECT {cols}
            FROM addresses a
            WHERE {where}
        """
    return f"""
            SELECT {cols}
            FROM (
                SELECT *, {_unit_rank(sf, '')}
                FROM addresses
                WHERE {where}
            ) a
            WHERE a._unit_rn = 1
        """


def build_new_since_query(
    sf: _config.SourceFields,
    collapse: bool,
    active_status: tuple[str, ...] | None = None,
) -> str:
    """New-points-since-watermark query. Named params :wm and :snap.

    The collapsed form ranks over the FULL active set, then filters to new
    points — so a new unit row at a civic address whose representative already
    existed never surfaces. (A unit-only civic that later gains its unit-less
    base row re-elects the representative and surfaces once as "new"; rare —
    Hamilton has 550 unit-only groups — and it errs toward review, not
    silence.)"""
    cols = build_address_cols(sf)
    first_appeared = (
        "SELECT identity_key, MIN(min_snapshot_id) AS first_snap\n"
        "                FROM addresses\n"
        "                GROUP BY identity_key\n"
        "                HAVING first_snap > :wm"
    )
    if not collapse:
        return f"""
            SELECT {cols}
            FROM addresses a
            JOIN (
                {first_appeared}
            ) n ON n.identity_key = a.identity_key
            WHERE a.max_snapshot_id = :snap{_status_filter(sf, active_status, "a")}
        """
    return f"""
            SELECT {cols}
            FROM (
                SELECT *, {_unit_rank(sf, '')}
                FROM addresses
                WHERE max_snapshot_id = :snap{_status_filter(sf, active_status, "")}
            ) a
            JOIN (
                {first_appeared}
            ) n ON n.identity_key = a.identity_key
            WHERE a._unit_rn = 1
        """


def build_retired_since_query(
    sf: _config.SourceFields,
    collapse: bool,
    active_status: tuple[str, ...] | None = None,
) -> str:
    """Retired-points query. Named params :wm and :snap.

    The collapsed form ranks over the surviving retired rows, so a civic
    address whose whole stack retires is flagged once, not once per unit. A
    partially-retired stack is already suppressed by the re-issue NOT EXISTS
    (some same-street row is still active)."""
    cols = build_address_cols(sf)
    retired_join = (
        "JOIN (\n"
        "                SELECT identity_key, MAX(max_snapshot_id) AS last_snap\n"
        "                FROM addresses\n"
        "                GROUP BY identity_key\n"
        "                HAVING last_snap >= :wm AND last_snap < :snap\n"
        "            ) r ON r.identity_key = a.identity_key\n"
        "               AND r.last_snap = a.max_snapshot_id"
    )
    not_reissued = (
        "NOT EXISTS (\n"
        "                SELECT 1 FROM addresses b\n"
        f"                WHERE {field_sql(sf, 'number', 'b')}   = {field_sql(sf, 'number', 'a')}\n"
        f"                  AND {field_sql(sf, 'street', 'b')}   = {field_sql(sf, 'street', 'a')}\n"
        "                  AND b.identity_key <> a.identity_key\n"
        "                  AND b.max_snapshot_id   = :snap\n"
        "            )"
    )
    # The status filter applies to the retired row itself: a Pending row that
    # vanishes was never importable, so its retirement is not OSM-actionable.
    # The not_reissued EXISTS deliberately stays unfiltered — any surviving
    # same-street row suppresses the flag, importable or not, erring toward
    # silence over a false retirement.
    if not collapse:
        return f"""
            SELECT {cols}, r.last_snap AS last_snapshot_id
            FROM addresses a
            {retired_join}
            WHERE {not_reissued}{_status_filter(sf, active_status, "a")}
        """
    return f"""
            SELECT {cols}, a.last_snap AS last_snapshot_id
            FROM (
                SELECT a.*, r.last_snap, {_unit_rank(sf, 'a')}
                FROM addresses a
                {retired_join}
                WHERE {not_reissued}{_status_filter(sf, active_status, "a")}
            ) a
            WHERE a._unit_rn = 1
        """


_COLLAPSE = _CONFIG.units_policy == "collapse-to-civic"


def iter_active_addresses_in_bbox(bbox: tuple[float, float, float, float], snapshot_id: int):
    """Yield rows from the source addresses table active at snapshot_id and inside bbox."""
    min_lat, min_lon, max_lat, max_lon = bbox
    conn = connect_readonly()
    try:
        q = build_active_bbox_query(
            _CONFIG.source_fields, _COLLAPSE, _CONFIG.status_active_values
        )
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
        q = build_new_since_query(
            _CONFIG.source_fields, _COLLAPSE, _CONFIG.status_active_values
        )
        for row in conn.execute(q, {"wm": watermark_snapshot_id, "snap": snapshot_id}):
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
        q = build_retired_since_query(
            _CONFIG.source_fields, _COLLAPSE, _CONFIG.status_active_values
        )
        for row in conn.execute(q, {"wm": watermark_snapshot_id, "snap": snapshot_id}):
            yield dict(row)
    finally:
        conn.close()
