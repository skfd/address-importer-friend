"""Operator verdicts on the collapse-vs-nodes decision, persisted across runs.

The classifier in `units` decides what a multi-unit civic group becomes;
`/units/shapes` shows every decision city-wide; this is where an operator who
disagrees records it, and where `candidates._emit_group` reads it back.

Three things about a verdict that are not obvious from the table:

**It applies at ingest, not export.** Every other operator decision in the
engine transforms tags late; this one changes how many candidates exist. So a
verdict saved after a group has already been ingested into a run does nothing
to that run's rows -- there is no re-ingest path, and `INSERT OR IGNORE` on
the candidate key would not replace them anyway. `ingested_runs` exists so the
page can say so rather than let the operator save a verdict and watch nothing
change.

**It is tied to the unit set it was made against.** `unit_hash` covers the
sorted designators only. A group whose designators have changed since the
verdict is *stale*: the page shows it that way with the chips still live, and
the emitter ignores it and lets the rule decide, because a decision about a
different building is not a decision about this one.

**It freezes once the group's shape is in OSM.** Freeze is a property of the
civic key, not of the verdict row: a group uploaded under the rule's own
decision is as frozen as one uploaded under an override, and a single
uploaded door freezes its whole group. After that both flips are mutations
(nodes->collapse deletes fifty-two nodes and creates one) and this import
only creates, so `save` refuses and later disagreement is a QA finding. There
is a second freeze condition -- somebody else already mapped the doors -- that
needs the OSM extract and lives on the page, not here.

`skip` produces zero candidates for the group. That was checked against the
consumers that could read "active source row with no candidate" as an error:
`city_duplicate` and `missing_sample` iterate candidates only, and
`reverse_sweep` indexes source rows independently of candidates, so a skipped
group is invisible to all three rather than a finding in any of them.
"""
from datetime import datetime, timezone

from . import db as _db, units

VERDICTS = units.OVERRIDES


def load_all() -> dict[str, dict]:
    """civic_key -> {verdict, unit_hash, note, updated_at, frozen_at}."""
    conn = _db.connect()
    try:
        rows = conn.execute(
            "SELECT civic_key, verdict, unit_hash, note, updated_at, frozen_at "
            "FROM unit_shape_verdicts"
        ).fetchall()
    finally:
        conn.close()
    return {r["civic_key"]: dict(r) for r in rows}


def effective(saved: dict | None, current_hash: str) -> str | None:
    """The override the emitter should honour for a group, or None.

    A verdict whose unit set no longer matches is stale and does not apply:
    the rule decides, and the page asks the operator again.
    """
    if saved is None or saved["unit_hash"] != current_hash:
        return None
    return saved["verdict"]


def frozen_keys() -> set[str]:
    """Civic keys whose shape has reached OSM through this tool.

    `candidates.stage = 'UPLOADED'` rather than `runs.upload_status`: a
    REJECTED candidate in an uploaded run never left the database, and its
    group is still ours to decide.
    """
    conn = _db.connect()
    try:
        rows = conn.execute(
            "SELECT DISTINCT civic_key FROM candidates "
            "WHERE civic_key IS NOT NULL AND stage = 'UPLOADED'"
        ).fetchall()
    finally:
        conn.close()
    return {r["civic_key"] for r in rows}


def ingested_runs(keys=None) -> dict[str, list[int]]:
    """civic_key -> run ids that already hold candidates for the group.

    Those rows keep the shape they were ingested with whatever is saved now;
    the page says which runs so the operator knows where a verdict will and
    will not show up.
    """
    conn = _db.connect()
    try:
        rows = conn.execute(
            "SELECT DISTINCT civic_key, run_id FROM candidates "
            "WHERE civic_key IS NOT NULL ORDER BY run_id"
        ).fetchall()
    finally:
        conn.close()
    out: dict[str, list[int]] = {}
    for r in rows:
        if keys is not None and r["civic_key"] not in keys:
            continue
        out.setdefault(r["civic_key"], []).append(int(r["run_id"]))
    return out


def group_candidates(civic_key: str) -> list[dict]:
    """Every candidate the group produced, across all runs, doors first in
    reading order. Door groups scatter across runs -- each door lands in the
    tile that contains it -- so this is the only view that shows a reviewer
    that the node in front of them is 1 of 12 doors at one address."""
    conn = _db.connect()
    try:
        rows = conn.execute(
            """SELECT c.run_id, c.candidate_id, c.unit, c.flats, c.unit_shape, c.stage,
                      c.address_full, cf.verdict
               FROM candidates c LEFT JOIN conflation cf USING (run_id, candidate_id)
               WHERE c.civic_key = ?""",
            (civic_key,),
        ).fetchall()
    finally:
        conn.close()
    out = [dict(r) for r in rows]
    out.sort(key=lambda r: (r["unit"] is not None, units.unit_sort_key(r["unit"] or ""), r["run_id"]))
    return out


class Frozen(Exception):
    """The group's shape is already in OSM; changing it would be a mutation."""


def save(civic_key: str, verdict: str, unit_hash: str, note: str | None = None) -> bool:
    """Record or replace the verdict for one group. Returns whether anything
    changed. Raises `Frozen` rather than silently keeping the old value, so
    the page can say why the click did nothing.

    `unit_hash` must be computed server-side from the group as the page
    currently sees it, never taken from the form: the hash is the statement
    "this decision is about these units", and a stale form must not be able
    to re-assert it about a building that has since changed.
    """
    if verdict not in VERDICTS:
        raise ValueError(f"unknown unit-shape verdict {verdict!r}")
    note = (note or "").strip() or None
    now = datetime.now(timezone.utc).isoformat()
    _refuse_if_frozen(civic_key, now)
    with _db.tx() as conn:
        cur = conn.execute(
            "SELECT verdict, unit_hash, note FROM unit_shape_verdicts WHERE civic_key = ?",
            (civic_key,),
        ).fetchone()
        if cur and (cur["verdict"], cur["unit_hash"], cur["note"]) == (verdict, unit_hash, note):
            return False
        conn.execute(
            "INSERT INTO unit_shape_verdicts (civic_key, verdict, unit_hash, note, updated_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(civic_key) DO UPDATE SET "
            "  verdict=excluded.verdict, unit_hash=excluded.unit_hash, "
            "  note=excluded.note, updated_at=excluded.updated_at",
            (civic_key, verdict, unit_hash, note, now),
        )
    return True


def clear(civic_key: str) -> bool:
    """Forget the verdict and let the rule decide again. Frozen groups refuse
    for the same reason `save` does: the rule's answer may not be what is in
    OSM either."""
    now = datetime.now(timezone.utc).isoformat()
    _refuse_if_frozen(civic_key, now)
    with _db.tx() as conn:
        cur = conn.execute("DELETE FROM unit_shape_verdicts WHERE civic_key = ?", (civic_key,))
        return cur.rowcount > 0


def _refuse_if_frozen(civic_key: str, now: str) -> None:
    """Stamp `frozen_at` and raise. Its own transaction, deliberately: the
    stamp has to survive the refusal, and an exception inside the write's
    transaction would roll it back along with everything else."""
    with _db.tx() as conn:
        if not _is_frozen(conn, civic_key):
            return
        _stamp_frozen(conn, civic_key, now)
    raise Frozen(civic_key)


def _is_frozen(conn, civic_key: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM candidates WHERE civic_key = ? AND stage = 'UPLOADED' LIMIT 1",
        (civic_key,),
    ).fetchone()
    if row:
        return True
    row = conn.execute(
        "SELECT frozen_at FROM unit_shape_verdicts WHERE civic_key = ?", (civic_key,)
    ).fetchone()
    return bool(row and row["frozen_at"])


def _stamp_frozen(conn, civic_key: str, now: str) -> None:
    conn.execute(
        "UPDATE unit_shape_verdicts SET frozen_at = COALESCE(frozen_at, ?) WHERE civic_key = ?",
        (now, civic_key),
    )
