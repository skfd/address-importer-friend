"""Campaign-wide statistics for the end-of-import wrap-up page.

Everything the wrap-up reports is already in `tool.db` — the pipeline writes
`events`, `runs`, `changesets`, `candidates` and `conflation` as it goes — plus
`tiles.json` for the area breakdown. Nothing here needs instrumenting during an
import, so a city's page can be generated long after the last changeset closed.

The one number that is *not* self-evident is hands-on time. There is no clock
in the schema, only event timestamps, so "how long did this take" means
sessionizing those timestamps: consecutive operator actions belong to the same
sitting until a gap longer than ``session_gap_minutes`` says the operator got
up. Toronto's hand-made one-pager published "65h across 25 sessions" from a
threshold nobody wrote down (it is somewhere near 50 minutes); the engine picks
30 minutes as its documented default and lets a city override it, rather than
quietly inheriting an unrecoverable judgement call.

Scope is the *import*, not the database. Monthly maintenance runs land in the
same `tool.db` and would otherwise stretch Toronto's 16-day campaign into a
108-day one whose bar chart is mostly empty. Maintenance runs are identified by
the ``maintenance`` key the maintenance tool writes into ``runs.config_json``
(deliberately stored on the run rather than inferred from its name), and are
excluded by default; their tail is reported separately as a footnote.

Read-only throughout: no writes, no schema, no migration.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

# Events that count as an operator doing something. Deliberately narrower than
# "all events": CONFLATE_CANDIDATE and AUTO_APPROVED fire in their hundreds of
# thousands while the machine works unattended, and folding those in would time
# the pipeline rather than the person.
OPERATOR_EVENTS = (
    "REVIEW_APPROVED",
    "REVIEW_REJECTED",
    "REVIEW_OVERRIDE",
    "REVIEW_CLEARED",
    "CHANGESET_UPLOADED",
)
# What counts as a review *decision*. REVIEW_CLEARED is deliberately absent:
# clearing reverts an earlier decision, so counting it would tally the same
# candidate twice and inflate "human effort" with its own undo. It still marks
# operator presence, so it stays in OPERATOR_EVENTS for the hands-on clock.
DECISION_EVENTS = ("REVIEW_APPROVED", "REVIEW_REJECTED", "REVIEW_OVERRIDE")

# See module docstring. Overridable via [stats] session_gap_minutes.
DEFAULT_SESSION_GAP_MINUTES = 30

TOP_N = 5

# The import proper: every run the maintenance tool did not create. Kept as a
# subquery so no caller has to inline 1,300 run ids.
IMPORT_RUNS = (
    "SELECT run_id FROM runs WHERE json_extract(config_json,'$.maintenance') IS NULL"
)
MAINTENANCE_RUNS = (
    "SELECT run_id FROM runs WHERE json_extract(config_json,'$.maintenance') IS NOT NULL"
)


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _pct(n: int, total: int) -> float:
    return round(100 * n / total, 1) if total else 0.0


def sessions(
    timestamps: list[datetime], gap_minutes: int
) -> list[tuple[datetime, datetime]]:
    """Group sorted timestamps into (first, last) sittings, splitting on a gap.

    A lone action forms a zero-length session: real, but contributing no hours.
    That is the honest reading — one click tells you the operator was present,
    not for how long — and it keeps the session *count* meaningful even when
    the hours it adds round to nothing.
    """
    if not timestamps:
        return []
    gap = gap_minutes * 60
    out: list[tuple[datetime, datetime]] = []
    start = prev = timestamps[0]
    for ts in timestamps[1:]:
        if (ts - prev).total_seconds() > gap:
            out.append((start, prev))
            start = ts
        prev = ts
    out.append((start, prev))
    return out


def _tile_by_run(conn, tiles: list[dict], scope: str) -> dict[int, dict]:
    """Map run_id -> tile for in-scope runs, matching on bbox rounded to 6 dp.

    A run stores its bbox, not the tile it came from, so this is the same
    reconstruction ``/tiles/<id>`` and the map overlay already do. Runs drawn
    freehand rather than picked off the tile layer simply don't match, and drop
    out of the per-area breakdown instead of being misfiled.
    """
    if not tiles:
        return {}
    by_bbox = {tuple(round(x, 6) for x in t["bbox"]): t for t in tiles}
    out: dict[int, dict] = {}
    for r in conn.execute(
        "SELECT run_id, bbox_min_lat, bbox_min_lon, bbox_max_lat, bbox_max_lon "
        f"FROM runs WHERE run_id IN ({scope})"
    ):
        key = (
            round(r["bbox_min_lat"], 6), round(r["bbox_min_lon"], 6),
            round(r["bbox_max_lat"], 6), round(r["bbox_max_lon"], 6),
        )
        tile = by_bbox.get(key)
        if tile is not None:
            out[int(r["run_id"])] = tile
    return out


def _area_of(tile: dict) -> str:
    """The tile's parent area, falling back to the tile itself.

    ``parent`` is the neighbourhood a tile was quadtree-split out of. A city
    with no polygon layer (`[city] neighbourhoods_url` empty) gets tiles split
    straight off the bbox, where every tile shares one parent and the honest
    grouping is the tile.
    """
    return tile.get("parent") or tile.get("name") or tile["id"]


def _fill_days(days: list[str]) -> list[str]:
    """Every calendar date between the first and last, so an idle day renders
    as a gap in the bar chart instead of being silently closed up."""
    if not days:
        return []
    d, last = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
    out = []
    while d <= last:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def collect(
    conn,
    tiles: list[dict],
    *,
    session_gap_minutes: int = DEFAULT_SESSION_GAP_MINUTES,
    top_n: int = TOP_N,
    include_maintenance: bool = False,
) -> dict:
    """Everything the wrap-up template renders, in one read-only pass."""
    scope = "SELECT run_id FROM runs" if include_maintenance else IMPORT_RUNS
    IN = f"run_id IN ({scope})"

    def n(sql: str, params: tuple = ()) -> int:
        row = conn.execute(sql, params).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def stage(name: str) -> int:
        return n(f"SELECT COUNT(*) FROM candidates WHERE {IN} AND stage=?", (name,))

    ev = {
        r[0]: int(r[1])
        for r in conn.execute(
            f"SELECT event_type, COUNT(*) FROM events WHERE {IN} GROUP BY 1"
        )
    }

    ingested = n(f"SELECT COUNT(*) FROM candidates WHERE {IN}")
    uploaded = stage("UPLOADED")
    missing = n(
        f"SELECT COUNT(*) FROM conflation WHERE {IN} AND verdict='MISSING'"
    )
    matched = n(
        f"SELECT COUNT(*) FROM conflation WHERE {IN} "
        "AND verdict IN ('MATCH','MATCH_FAR','MATCH_LISTED')"
    )
    totals = {
        "ingested": ingested,
        "uploaded": uploaded,
        "skipped": stage("SKIPPED"),
        "rejected": stage("REJECTED"),
        "pending": stage("REVIEW_PENDING"),
        "missing": missing,
        "matched": matched,
        "duplicates": ev.get("SKIPPED_CROSS_RUN_DUPLICATE", 0),
        "streets": n(
            "SELECT COUNT(DISTINCT street_norm) FROM candidates "
            f"WHERE {IN} AND stage='UPLOADED'"
        ),
        "changesets": n(f"SELECT COUNT(*) FROM changesets WHERE {IN}"),
    }

    # ---- daily uploads and hands-on time --------------------------------
    daily_uploads = {
        r[0]: int(r[1])
        for r in conn.execute(
            "SELECT date(stage_updated_at), COUNT(*) FROM candidates "
            f"WHERE {IN} AND stage='UPLOADED' AND stage_updated_at IS NOT NULL "
            "GROUP BY 1"
        )
        if r[0]
    }

    marks = ",".join("?" * len(OPERATOR_EVENTS))
    stamps = [
        _parse(r[0])
        for r in conn.execute(
            f"SELECT ts FROM events WHERE {IN} AND event_type IN ({marks}) ORDER BY ts",
            OPERATOR_EVENTS,
        )
    ]
    sitting = sessions(stamps, session_gap_minutes)
    daily_hours: dict[str, float] = {}
    for start, end in sitting:
        key = start.date().isoformat()
        daily_hours[key] = daily_hours.get(key, 0.0) + (end - start).total_seconds() / 3600

    days = sorted(set(daily_uploads) | set(daily_hours))
    calendar = [
        {
            "date": d,
            "day": int(d[-2:]),
            "uploaded": daily_uploads.get(d, 0),
            "hours": round(daily_hours.get(d, 0.0), 1),
        }
        for d in _fill_days(days)
    ]

    # ---- per-area and per-run -------------------------------------------
    tile_by_run = _tile_by_run(conn, tiles, scope)
    per_area: dict[str, int] = {}
    per_run: dict[int, int] = {}
    for r in conn.execute(
        f"SELECT run_id, COUNT(*) FROM candidates WHERE {IN} AND stage='UPLOADED' "
        "GROUP BY run_id"
    ):
        run_id, count = int(r[0]), int(r[1])
        per_run[run_id] = count
        tile = tile_by_run.get(run_id)
        if tile is not None:
            area = _area_of(tile)
            per_area[area] = per_area.get(area, 0) + count

    top_streets = [
        {"name": r[0], "count": int(r[1])}
        for r in conn.execute(
            "SELECT MIN(street_raw), COUNT(*) c FROM candidates "
            f"WHERE {IN} AND stage='UPLOADED' GROUP BY street_norm "
            "ORDER BY c DESC, 1 LIMIT ?",
            (top_n,),
        )
    ]
    top_areas = [
        {"name": name, "count": c}
        for name, c in sorted(per_area.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]
    ]

    # ---- coverage --------------------------------------------------------
    done_runs = {
        int(r[0])
        for r in conn.execute(
            f"SELECT run_id FROM runs WHERE {IN} AND upload_status='uploaded'"
        )
    }
    tiles_done = {t["id"] for rid, t in tile_by_run.items() if rid in done_runs}
    areas_done = {_area_of(t) for rid, t in tile_by_run.items() if rid in done_runs}
    areas_all = {_area_of(t) for t in tiles}

    biggest_day = max(calendar, key=lambda d: d["uploaded"], default=None)
    biggest_run = max(per_run.items(), key=lambda kv: kv[1], default=None)

    auto = ev.get("AUTO_APPROVED", 0)
    manual = sum(ev.get(k, 0) for k in DECISION_EVENTS)

    return {
        "complete": bool(tiles) and len(tiles_done) >= len(tiles),
        "progress": {
            "tiles_total": len(tiles),
            "tiles_done": len(tiles_done),
            "areas_total": len(areas_all),
            "areas_done": len(areas_done),
            "tile_pct": _pct(len(tiles_done), len(tiles)),
            "area_pct": _pct(len(areas_done), len(areas_all)),
        },
        "span": {
            "first": days[0] if days else None,
            "last": days[-1] if days else None,
            "days": len(calendar),
        },
        "totals": totals,
        "funnel": [
            {"n": ingested, "label": "Ingested from source",
             "note": "source address points"},
            {"n": missing, "label": "Missing in OSM",
             "note": f"{_pct(missing, ingested)}% of source — absent from OSM"},
            {"n": uploaded, "label": "Uploaded",
             "note": f"{_pct(uploaded, missing)}% of missing"},
        ],
        "automation": {
            "auto": auto,
            "manual": manual,
            "auto_pct": _pct(auto, auto + manual),
        },
        "calendar": calendar,
        "max_uploaded": max((d["uploaded"] for d in calendar), default=0),
        "max_hours": max((d["hours"] for d in calendar), default=0.0),
        "sessions": {
            "count": len(sitting),
            "hours": round(sum((b - a).total_seconds() for a, b in sitting) / 3600, 1),
            "gap_minutes": session_gap_minutes,
        },
        "top_streets": top_streets,
        "top_areas": top_areas,
        "facts": {
            "biggest_day": biggest_day,
            "biggest_changeset": (
                {"run_id": biggest_run[0], "count": biggest_run[1],
                 # The tile's display name where the run came off the tile
                 # layer ("South Riverdale NE-NW-2-SW-SW"); the run's own name
                 # only for a freehand run that matches no tile.
                 "name": (
                     tile_by_run[biggest_run[0]]["name"]
                     if biggest_run[0] in tile_by_run
                     else _run_name(conn, biggest_run[0])
                 )}
                if biggest_run else None
            ),
            "avg_run": round(uploaded / len(per_run)) if per_run else 0,
            "runs": len(per_run),
        },
        "maintenance": None if include_maintenance else _maintenance_tail(conn),
    }


def _maintenance_tail(conn) -> dict | None:
    """What the monthly maintenance runs have added since the import closed.

    A footnote, not a headline: it is the reason the wrap-up's window stops
    where it does, so the page says so rather than leaving a reader to wonder
    why the totals disagree with the live dashboard."""
    uploaded = conn.execute(
        "SELECT COUNT(*) FROM candidates "
        f"WHERE run_id IN ({MAINTENANCE_RUNS}) AND stage='UPLOADED'"
    ).fetchone()[0]
    if not uploaded:
        return None
    row = conn.execute(
        f"SELECT COUNT(*), MAX(date(uploaded_at)) FROM runs WHERE run_id IN "
        f"({MAINTENANCE_RUNS}) AND upload_status='uploaded'"
    ).fetchone()
    return {"uploaded": int(uploaded), "runs": int(row[0] or 0), "last": row[1]}


def _run_name(conn, run_id: int) -> str:
    row = conn.execute("SELECT name FROM runs WHERE run_id=?", (run_id,)).fetchone()
    return row[0] if row else str(run_id)
