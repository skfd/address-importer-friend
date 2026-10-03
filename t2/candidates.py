"""Stage 1: ingest active city addresses in run bbox into tool.db."""
import json
from datetime import datetime, timezone

from . import audit, config as _config, db as _db, source_db, unit_verdicts, units

_SOURCE_FIELDS = _config.load().source_fields
_POSTCODE_PREFIXES = _config.load().postcode_prefixes


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


def _source_postcode(extra_raw) -> tuple[str | None, str | None, str | None]:
    """(postcode, raw, why) for one source row's props.

    All three are None for a city that declares no [source_fields] postcode,
    so the column stays NULL and nothing else is read. Otherwise `postcode` is
    the normalized value config.check_postcode accepted, or None with `why`
    saying what was wrong with `raw`."""
    key = _SOURCE_FIELDS.postcode_key
    if not key:
        return None, None, None
    try:
        raw = (json.loads(extra_raw) if extra_raw else {}).get(key)
    except (ValueError, TypeError):
        raw = None
    value, why = _config.check_postcode(raw, _POSTCODE_PREFIXES)
    return value, raw, why


def _log_postcode_rejection(conn, run_id: int, row: dict) -> bool:
    """Audit a source postcode that was present but not written. True if so.

    "Omitted and counted, not guessed": the node is still created, without
    addr:postcode (or with a same-address POI's, if conflation finds one), and
    the value it did not get stays findable per candidate."""
    _value, raw, why = _source_postcode(row.get("extra"))
    if why not in ("format", "prefix"):
        return False
    audit.log(
        actor="pipeline", event_type="POSTCODE_REJECTED",
        run_id=run_id, candidate_id=row["address_point_id"],
        payload={"value": raw, "reason": why}, conn=conn,
    )
    return True


def _postcode_tally(rejected: int) -> dict:
    """The ingest audit's postcode count — absent, not zero, for a city that
    declares no postcode, so its CANDIDATE_INGESTED payload does not move."""
    return {"postcode_rejected": rejected} if _SOURCE_FIELDS.postcode_key else {}


def _candidate_values(
    run_id: int,
    row: dict,
    now: str,
    unit: str | None = None,
    flats: str | None = None,
    shape: str | None = None,
    shape_reason: str | None = None,
    civic_key: str | None = None,
) -> tuple | None:
    """Map one source row to a candidates INSERT tuple, or None to skip it.

    Shared by the bbox/polygon ingest and the maintenance row-list ingest so
    street normalization, class extraction, and the Land Entrance skip stay
    identical across both paths.

    `unit` and `flats` are what the row became under per-door-or-collapse —
    one front door, or one building standing for all of them. They are never
    both set, and both stay None under every other policy. `civic_key` is the
    group the row was decided in (source_db.civic_key_text), kept so a shape
    verdict can find the runs its group landed in; also None off the policy.
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
    postcode, _raw, _why = _source_postcode(extra_raw)
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
        unit,
        flats,
        shape,
        shape_reason,
        civic_key,
        postcode,
        "INGESTED",
        now,
    )


_INSERT_SQL = """
    INSERT OR IGNORE INTO candidates
      (run_id, candidate_id, address_full, housenumber, street_raw, street_norm,
       lat, lon, lo_num, lo_num_suf, hi_num, hi_num_suf, extra_json,
       address_class, municipality_name, unit, flats, unit_shape,
       unit_shape_reason, civic_key, postcode, stage, stage_updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _elect(group: list[dict]) -> dict:
    """The row that stands for a whole collapsed group.

    Mirrors `_unit_rank`'s ORDER BY exactly — the unit-less row first, because
    it is the parcel's own civic point, then the lowest identity_key so the
    choice is the same on every run.
    """
    return sorted(
        group,
        key=lambda r: (
            bool((r.get("unit_name") or "").strip()),
            str(r.get("address_point_id")),
        ),
    )[0]


def _emit_group(group: list[dict], in_tile, override: str | None = None):
    """Yield (source_row, unit, flats, shape, reason) for one civic group under
    per-door-or-collapse.

    `group` is the whole group city-wide; `in_tile` decides what belongs to the
    run being ingested. Doors are placed individually, so each lands in the
    tile that contains it and no tile emits a neighbour's. A collapsed group
    has exactly one representative point, so it is created once however many
    tiles its units sprawl across.

    `override` is the operator's verdict from /units/shapes, already checked
    against the group's current unit set by the caller; None lets the rule
    decide. The decision itself is `units.resolve`, shared with the page, so
    what the page says a building becomes is what this does with it.

    The `shape` yielded is what `candidates.unit_shape` records, and it is the
    page's vocabulary with one deliberate exception: a listing dropped for
    length that nobody chose is labelled `review`, not `civic-only`, because
    the label means "a human should look" and the unit_shape_ambiguous check
    keys on it. An operator who chose civic-only has looked.
    """
    verdict, reason = units.classify(
        [
            {"unit": r.get("unit_name"), "lat": r.get("latitude"), "lon": r.get("longitude")}
            for r in group
        ]
    )
    listed = units.listed_units(r.get("unit_name") for r in group)
    doors = None
    if override == "split":
        doors = units.split_doors(
            {"unit": r.get("unit_name"), "lat": r.get("latitude"), "lon": r.get("longitude")}
            for r in group
        )
    shape, reason, flats = units.resolve(verdict, reason, listed, override, doors)
    if shape == "skip":
        return
    if shape == "split":
        # The door rows as `nodes` and the building as `collapse`, so every
        # consumer of unit_shape reads each candidate as the thing it is; the
        # reason carries the split.
        door_rows = [r for r in group if (r.get("unit_name") or "").strip() in doors]
        for row in door_rows:
            if in_tile(row):
                yield row, row["unit_name"].strip(), None, "nodes", reason
        rep = _elect([r for r in group if r not in door_rows])
        if in_tile(rep):
            yield rep, None, flats, "collapse", reason
        return
    if shape == "nodes":
        # Every row is its own address, the unit-less civic row included: the
        # City publishes it as a distinct point, and under unit-aware matching
        # it is a distinct object from the doors rather than a duplicate of one.
        for row in group:
            if in_tile(row):
                yield row, (row.get("unit_name") or "").strip() or None, None, shape, reason
        return
    # COLLAPSE, REVIEW and CIVIC-ONLY alike become one node for the building.
    # Review is not a third outcome here — it is the same node plus a reason
    # for a human to look, because collapsing is right either way while
    # exploding a group the rule is unsure about uploads front doors that may
    # not exist.
    rep = _elect(group)
    if not in_tile(rep):
        return
    label = "review" if shape == "civic-only" and override != "civic-only" else shape
    yield rep, None, flats, label, reason


def _iter_emissions(bbox, snapshot_id: int, polygon, point_cls, in_tile):
    """Yield (source_row, unit, flats, shape, reason, civic_key) for what this
    run creates.

    Off the per-door policy this is the loop it replaces, unchanged: the bbox
    query already applies the city's collapse, and the polygon clips it.

    Under per-door-or-collapse the tile query stops being the thing that
    decides what to create, and only says which civic groups this tile touches.
    Each of those is then fetched whole — city-wide, not tile-clipped — because
    the classifier reads the numbering across the entire group, and a tower cut
    by a tile boundary would otherwise show one floor's worth of units on each
    side and read as a row of doors in both.
    """
    if not source_db.PER_DOOR:
        for row in source_db.iter_active_addresses_in_bbox(bbox, snapshot_id):
            if polygon is not None:
                lat, lon = row.get("latitude"), row.get("longitude")
                if lat is None or lon is None or not polygon.contains(point_cls(lon, lat)):
                    continue
            yield row, None, None, None, None, None
        return

    keys = {
        source_db.civic_key(row)
        for row in source_db.iter_active_addresses_in_bbox(bbox, snapshot_id)
        if in_tile(row)
    }
    # Operator verdicts, read once per ingest. A verdict is honoured only if
    # the group's unit set still matches the one it was made against; a stale
    # one is ignored here and re-asked on the page.
    verdicts = unit_verdicts.load_all()
    for key, group in source_db.fetch_civic_groups(keys, snapshot_id).items():
        key_text = source_db.civic_key_text(key)
        override = unit_verdicts.effective(
            verdicts.get(key_text),
            units.unit_hash(units.listed_units(r.get("unit_name") for r in group)),
        )
        for row, unit, flats, shape, reason in _emit_group(group, in_tile, override):
            yield row, unit, flats, shape, reason, key_text


def ingest_rows(run_id: int, rows) -> int:
    """Insert candidates from an explicit iterable of source rows (no bbox).

    The selection axis is the caller's — used by the monthly maintenance job,
    which ingests just the points that first appeared since its watermark
    rather than everything inside a tile. Returns count inserted this call.

    Refuses to run under per-door-or-collapse. That policy turns the SQL
    collapse off, so `iter_new_since` hands over every unit row, and this path
    has no notion of a civic group to classify them in: a tower that gained one
    unit would arrive as 142 bare civic candidates for one building. Closing it
    properly needs a mutation path — a new unit at a collapsed tower means
    editing addr:flats on a node that already exists — and this import only
    creates. Until that exists the policy runs from the tile path only.
    """
    if source_db.PER_DOOR:
        raise RuntimeError(
            "ingest_rows is not available under [units] policy = "
            '"per-door-or-collapse": the maintenance path cannot group source '
            "rows into civic addresses, and a new unit at a collapsed building "
            "needs addr:flats modified rather than a node created. Run the "
            "tile path, and route source deltas to a QA finding."
        )
    inserted = rejected = 0
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
                rejected += _log_postcode_rejection(conn, run_id, row)
        audit.log(
            actor="pipeline",
            event_type="CANDIDATE_INGESTED",
            run_id=run_id,
            payload={"inserted": inserted, "source": "maintenance_delta",
                     **_postcode_tally(rejected)},
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

    min_lat, min_lon, max_lat, max_lon = bbox

    def in_tile(row: dict) -> bool:
        lat, lon = row.get("latitude"), row.get("longitude")
        if lat is None or lon is None:
            return False
        if polygon is not None:
            return polygon.contains(point_cls(lon, lat))
        return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon

    inserted = rejected = 0
    now = datetime.now(timezone.utc).isoformat()
    conn = _db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        for row, unit, flats, shape, reason, civic_key in _iter_emissions(
            bbox, snapshot_id, polygon, point_cls, in_tile
        ):
            values = _candidate_values(run_id, row, now, unit, flats, shape, reason, civic_key)
            if values is None:
                continue
            cur = conn.execute(_INSERT_SQL, values)
            if cur.rowcount > 0:
                inserted += 1
                rejected += _log_postcode_rejection(conn, run_id, row)
        audit.log(
            actor="pipeline",
            event_type="CANDIDATE_INGESTED",
            run_id=run_id,
            payload={"inserted": inserted, "snapshot_id": snapshot_id, "bbox": list(bbox),
                     **_postcode_tally(rejected)},
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
