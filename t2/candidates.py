"""Stage 1: ingest active city addresses in run bbox into tool.db."""
import json
from datetime import datetime, timezone

from . import audit, config as _config, db as _db, source_db

_SOURCE_FIELDS = _config.load().source_fields


def _street_from_row(row: dict) -> str:
    s = row.get("linear_name_full")
    if s:
        return s
    parts = [row.get("linear_name") or "", row.get("linear_name_type") or "", row.get("linear_name_dir") or ""]
    return " ".join(p for p in parts if p).strip()


def _build_polygon(polygon_latlon: list):
    """Reconstruct a shapely polygon from a tile's Leaflet rings.

    ``polygon_latlon`` is [[[lat, lon], ...]] (exterior ring first); shapely
    wants (x=lon, y=lat). Tiles store a single exterior ring with no holes
    (tiles_build._polygon_latlon), so we use the first ring as the shell.
    """
    from shapely.geometry import Polygon  # local import; only tile runs need shapely

    if not polygon_latlon:
        return None
    shell = [(lon, lat) for lat, lon in polygon_latlon[0]]
    return Polygon(shell)


def _candidate_values(run_id: int, row: dict, now: str) -> tuple | None:
    """Map one source row to a candidates INSERT tuple, or None to skip it.

    Shared by the bbox/polygon ingest and the maintenance row-list ingest so
    street normalization, class extraction, and the Land Entrance skip stay
    identical across both paths.
    """
    from .conflate import apply_street_override, expand_street_name, normalize_street

    street_raw = expand_street_name(apply_street_override(_street_from_row(row)))
    housenumber = row.get("address_number") or ""
    extra_raw = row.get("extra")
    # Which props key holds the class is per-city ([source_fields]); a city
    # that declares none gets address_class NULL, which also keeps the Land
    # Entrance skip below Toronto-only by construction.
    class_key = _SOURCE_FIELDS.address_class_key
    address_class = None
    if class_key:
        try:
            address_class = (json.loads(extra_raw) if extra_raw else {}).get(class_key)
        except (ValueError, TypeError):
            address_class = None
    # Land Entrance rows model driveway/gate entry points (closest OSM concept
    # is barrier=gate, not an address) and are out of scope — see
    # IMPORT_PROPOSAL.mediawiki § Goals and non-goals.
    if address_class == "Land Entrance":
        return None
    return (
        run_id,
        row["address_point_id"],
        row.get("address_full"),
        str(housenumber).strip().upper() if housenumber else None,
        street_raw or None,
        normalize_street(street_raw),
        row.get("latitude"),
        row.get("longitude"),
        row.get("lo_num"),
        row.get("lo_num_suf"),
        row.get("hi_num"),
        row.get("hi_num_suf"),
        extra_raw,
        address_class,
        row.get("municipality_name"),
        "INGESTED",
        now,
    )


_INSERT_SQL = """
    INSERT OR IGNORE INTO candidates
      (run_id, candidate_id, address_full, housenumber, street_raw, street_norm,
       lat, lon, lo_num, lo_num_suf, hi_num, hi_num_suf, extra_json,
       address_class, municipality_name, stage, stage_updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def ingest_rows(run_id: int, rows) -> int:
    """Insert candidates from an explicit iterable of source rows (no bbox).

    The selection axis is the caller's — used by the monthly maintenance job,
    which ingests just the points that first appeared since its watermark
    rather than everything inside a tile. Returns count inserted this call.
    """
    inserted = 0
    now = datetime.now(timezone.utc).isoformat()
    conn = _db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        for row in rows:
            values = _candidate_values(run_id, row, now)
            if values is None:
                continue
            cur = conn.execute(_INSERT_SQL, values)
            if cur.rowcount > 0:
                inserted += 1
        audit.log(
            actor="pipeline",
            event_type="CANDIDATE_INGESTED",
            run_id=run_id,
            payload={"inserted": inserted, "source": "maintenance_delta"},
            conn=conn,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return inserted


def ingest(
    run_id: int,
    bbox: tuple[float, float, float, float],
    snapshot_id: int,
    polygon_latlon: list | None = None,
) -> int:
    """Insert new candidates into tool.db. Returns count inserted this call.

    When ``polygon_latlon`` is given, the bbox query is a prefilter and each
    row is kept only if the point falls inside the tile polygon — so a source
    address in this tile's bbox but inside a neighbour's polygon is not
    ingested here (and so never reviewed/uploaded twice). NULL polygon keeps
    the legacy pure-bbox behaviour. Containment is strict (matches the
    poly.contains() assignment tiles_build uses to count addresses).
    """
    polygon = _build_polygon(polygon_latlon)
    point_cls = None
    if polygon is not None:
        from shapely.geometry import Point as point_cls  # noqa: N813

    inserted = 0
    now = datetime.now(timezone.utc).isoformat()
    conn = _db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        for row in source_db.iter_active_addresses_in_bbox(bbox, snapshot_id):
            if polygon is not None:
                lat, lon = row.get("latitude"), row.get("longitude")
                if lat is None or lon is None or not polygon.contains(point_cls(lon, lat)):
                    continue
            values = _candidate_values(run_id, row, now)
            if values is None:
                continue
            cur = conn.execute(_INSERT_SQL, values)
            if cur.rowcount > 0:
                inserted += 1
        audit.log(
            actor="pipeline",
            event_type="CANDIDATE_INGESTED",
            run_id=run_id,
            payload={"inserted": inserted, "snapshot_id": snapshot_id, "bbox": list(bbox)},
            conn=conn,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return inserted


def count_by_stage(run_id: int) -> dict[str, int]:
    conn = _db.connect()
    try:
        rows = conn.execute(
            "SELECT stage, COUNT(*) AS n FROM candidates WHERE run_id = ? GROUP BY stage",
            (run_id,),
        ).fetchall()
        return {r["stage"]: r["n"] for r in rows}
    finally:
        conn.close()


def count_ranges(run_id: int) -> int:
    conn = _db.connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM candidates WHERE run_id = ?"
            " AND stage = 'SKIPPED'"
            " AND lo_num IS NOT NULL AND hi_num IS NOT NULL"
            " AND lo_num != hi_num",
            (run_id,),
        ).fetchone()
        return int(row["n"]) if row else 0
    finally:
        conn.close()
