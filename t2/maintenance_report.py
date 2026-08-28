"""Closing report for a finished maintenance run.

A maintenance month ends in paperwork, not in code: a row in the proposal's
*Continuous maintenance* table, the running total in the city README, and — when
the month is unusual enough to deserve one — a post on the city's forum thread.
All of it is already in `tool.db` (the run's window, its stage counts, the
changeset it uploaded), so the operator should not be retyping it out of the
web UI and getting the totals wrong.

This module reads a run and renders it in the shapes those destinations want:

  ``text``       terminal summary, including what still blocks the close
  ``wiki``       one mediawiki row for the § Continuous maintenance table
  ``wikitable``  that whole table regenerated, Total row included
  ``markdown``   a forum-ready post
  ``json``       the same numbers, for anything else

Nothing here edits the proposal, the README or the wiki. It emits text; a human
pastes it, because every one of those destinations also wants a changelog entry
that only a human can write.

City-generic by construction: the city's name and wiki page come from
`config.toml`, and nothing about the render is Toronto-specific.
"""
from __future__ import annotations

import json

from . import candidates, config as _config, maintenance as _m

_OSM_WEB = "https://www.openstreetmap.org"

# Stages a candidate can end a maintenance run in. Anything else means the run
# is still mid-flight, which is what `blockers` reports on.
_TERMINAL = ("UPLOADED", "REJECTED", "SKIPPED")


def _changeset_url(changeset_id: int | None) -> str | None:
    return f"{_OSM_WEB}/changeset/{changeset_id}" if changeset_id else None


def _date_of(ts: str | None) -> str | None:
    """The date part of an ISO timestamp — the table columns are days, not
    instants."""
    return ts.split("T")[0] if ts else None


def _run_report(row: dict, *, conn_counts: dict | None = None) -> dict:
    """Per-run numbers shared by the single-run report and the table render."""
    counts = conn_counts if conn_counts is not None else candidates.count_by_stage(row["run_id"])
    window = _m.get_run_window(row["run_id"]) or {}
    frm, to = window.get("from_snapshot"), window.get("to_snapshot")
    return {
        "run_id": row["run_id"],
        "run_name": row["name"],
        "is_catchup": not row["name"].startswith(_m._RUN_PREFIX),
        "from_snapshot": frm,
        "to_snapshot": to,
        "from_date": _m.source_db.snapshot_date(frm) if frm is not None else None,
        "to_date": _m.source_db.snapshot_date(to) if to is not None else None,
        "upload_status": row["upload_status"],
        "changeset_id": row["changeset_id"],
        "changeset_url": _changeset_url(row["changeset_id"]),
        "uploaded_at": row["uploaded_at"],
        "upload_date": _date_of(row["uploaded_at"]),
        "stage_counts": counts,
        "uploaded": counts.get("UPLOADED", 0),
        "rejected": counts.get("REJECTED", 0),
        "skipped": counts.get("SKIPPED", 0),
        "candidates": sum(counts.values()),
        "open": sum(n for stage, n in counts.items() if stage not in _TERMINAL),
    }


def latest_run_id() -> int | None:
    """The newest maintenance run, monthly or catch-up — the one `--report`
    means when given no id."""
    hist = _m.history()
    return hist[0]["run_id"] if hist else None


def blockers(rep: dict) -> list[str]:
    """What still stands between this run and a closed month. Reported rather
    than enforced: a report on an in-flight run is a legitimate thing to want,
    it just must not read as if the month were finished."""
    out = []
    if rep["open"]:
        open_stages = ", ".join(
            f"{n} {stage}" for stage, n in sorted(rep["stage_counts"].items())
            if stage not in _TERMINAL
        )
        out.append(f"{rep['open']} candidate(s) not yet resolved ({open_stages})")
    if rep["upload_status"] != "uploaded":
        out.append(f"run not uploaded (upload_status={rep['upload_status'] or 'none'})")
    snap = rep.get("snapshot") or {}
    if snap.get("lagging"):
        out.append(f"DB snapshot not published ({snap.get('reason')}) — /publish-db")
    if not rep.get("watermark_advanced"):
        out.append(
            f"watermark still at #{rep.get('watermark')} — advance it to "
            f"#{rep['to_snapshot']} to declare the month closed"
        )
    return out


def report(run_id: int | None = None, *, include_retirements: bool = True) -> dict:
    """Everything the closing paperwork for one maintenance run needs.

    `include_retirements` drives one OSM-history round trip per retired
    element's match, so the CLI can turn it off (and does, automatically, if the
    call fails — a report is worth having without the provenance breakdown)."""
    if run_id is None:
        run_id = latest_run_id()
        if run_id is None:
            raise ValueError("no maintenance runs in this database")
    row = _m.get_run(run_id)
    if not row:
        raise ValueError(f"no run {run_id}")

    rep = _run_report(row)
    frm, to = rep["from_snapshot"], rep["to_snapshot"]
    # Recomputed from the feed *now*, not the numbers the run saw. The source DB
    # is a living SCD-2 store: re-asking about a closed window can return more
    # points than the run ingested, because the publisher has since revised what
    # that window contained. So these are context, never the run's record — the
    # candidates table is the record, and it is what every count below uses.
    rep["feed_new_now"] = sum(1 for _ in _m.source_db.iter_new_since(frm, to))
    rep["feed_retired_now"] = sum(1 for _ in _m.source_db.iter_retired_since(frm, to))

    cfg = _config.load()
    rep["city"] = cfg.city_name
    rep["import_plan"] = cfg.export_import_plan

    watermark = _m.get_watermark()
    rep["watermark"] = watermark
    rep["watermark_advanced"] = to is not None and watermark >= to
    try:
        rep["snapshot"] = _m.snapshot_status()
    except Exception as exc:  # a source without snapshot bookkeeping still reports
        rep["snapshot"] = {"error": str(exc)}

    rep["retirements"] = None
    if include_retirements:
        try:
            rep["retirements"] = _m.retirements(run_id)["summary"]
        except Exception as exc:
            rep["retirements_error"] = str(exc)

    rep["totals"] = totals()
    rep["blockers"] = blockers(rep)
    return rep


def totals() -> dict:
    """Running totals across every uploaded maintenance run — the figures the
    proposal's Total row and the README's "N changesets, M addresses" line
    quote. Only uploaded runs count: an in-flight run has pushed nothing."""
    rows = uploaded_runs()
    return {
        "runs": len(rows),
        "changesets": sum(1 for r in rows if r["changeset_id"]),
        "uploaded": sum(r["uploaded"] for r in rows),
        "rejected": sum(r["rejected"] for r in rows),
        "skipped": sum(r["skipped"] for r in rows),
        "first_date": rows[0]["upload_date"] if rows else None,
        "last_date": rows[-1]["upload_date"] if rows else None,
    }


def uploaded_runs() -> list[dict]:
    """Every uploaded maintenance run, oldest first — table order."""
    rows = [
        _run_report(_m.get_run(h["run_id"]))
        for h in _m.history()
        if h["upload_status"] == "uploaded"
    ]
    rows.sort(key=lambda r: (r["upload_date"] or "", r["run_id"]))
    return rows


# ---- renderers ------------------------------------------------------------

def _wiki_row(r: dict) -> str:
    cs = (
        f"[{r['changeset_url']} {r['changeset_id']}]"
        if r["changeset_id"] else "''(no changeset)''"
    )
    return (
        f"|-\n| {cs} || <code>{r['run_name']}</code> || {r['upload_date'] or ''} "
        f"|| {r['uploaded']} || {r['rejected']} || {r['skipped']}"
    )


def render_wiki(rep: dict) -> str:
    """One row for the proposal's § Continuous maintenance table."""
    return _wiki_row(rep)


def render_wikitable(rep: dict) -> str:
    """The whole § Continuous maintenance table, Total row recomputed.

    Regenerating the table beats appending a row: the Total line is the part
    that silently goes stale, and it is the part a reader checks."""
    t = rep["totals"]
    lines = [
        '{| class="wikitable"',
        "! Changeset !! Run !! Date !! Uploaded !! Rejected !! Skipped",
    ]
    for r in uploaded_runs():
        lines.append(_wiki_row(r))
    lines += [
        "|-",
        f"! Total !! !! !! {t['uploaded']} !! {t['rejected']} !! {t['skipped']}",
        "|}",
    ]
    return "\n".join(lines)


def render_markdown(rep: dict) -> str:
    """A forum-ready post for a month worth announcing.

    Deliberately states the window, the numbers and the changeset and stops:
    the rules of the import are on the wiki page, and repeating them per month
    is how a thread becomes noise."""
    city = rep["city"]
    window = f"{rep['from_date']} → {rep['to_date']}"
    cs = (
        f"[changeset {rep['changeset_id']}]({rep['changeset_url']})"
        if rep["changeset_id"] else "no changeset (nothing uploaded)"
    )
    lines = [
        f"**{city} address import — maintenance run `{rep['run_name']}` "
        f"({window})**",
        "",
        f"Source snapshots #{rep['from_snapshot']} → #{rep['to_snapshot']}. The "
        f"run took {rep['candidates']} candidate(s) from the City feed's "
        f"additions over that window, each reviewed by hand:",
        "",
        f"- **Uploaded:** {rep['uploaded']} — {cs}",
        f"- **Rejected in review:** {rep['rejected']}",
        f"- **Skipped (already in OSM):** {rep['skipped']}",
    ]
    ret = rep.get("retirements")
    if ret:
        lines.append(
            f"- **Retirements surfaced:** {sum(ret.values())} "
            f"({ret.get('safe', 0)} import-created and untouched, "
            f"{ret.get('caution', 0)} community-touched, "
            f"{ret.get('feature', 0)} on a feature, "
            f"{ret.get('no_match', 0)} with no OSM match). "
            "Nothing is auto-deleted; these are reviewed by hand."
        )
    elif rep["feed_retired_now"]:
        lines.append(
            f"- **Retirements surfaced:** {rep['feed_retired_now']} — reviewed by "
            "hand, nothing auto-deleted."
        )
    t = rep["totals"]
    lines += [
        "",
        f"Running total since maintenance began: {t['changesets']} changesets, "
        f"{t['uploaded']} addresses ({t['first_date']} → {t['last_date']}).",
        "",
        f"Same rules as the rollout — every candidate human-reviewed, create-only, "
        f"`import=yes` / `bot=no`, plan at {rep['import_plan']}.",
    ]
    return "\n".join(lines)


def render_text(rep: dict) -> str:
    """Terminal summary — the numbers plus what still blocks the close."""
    lines = [
        f"maintenance run {rep['run_name']} (#{rep['run_id']})"
        + ("  [catch-up]" if rep["is_catchup"] else ""),
        f"  window:     #{rep['from_snapshot']} ({rep['from_date']}) -> "
        f"#{rep['to_snapshot']} ({rep['to_date']})",
        f"  feed now:   {rep['feed_new_now']} new, {rep['feed_retired_now']} "
        f"retired (recomputed today, not the run's record)",
        f"  candidates: {rep['candidates']}  "
        f"({rep['uploaded']} uploaded / {rep['rejected']} rejected / "
        f"{rep['skipped']} skipped"
        + (f" / {rep['open']} open" if rep["open"] else "") + ")",
        f"  changeset:  {rep['changeset_url'] or '(none)'}"
        + (f"  {rep['upload_date']}" if rep["upload_date"] else ""),
    ]
    ret = rep.get("retirements")
    if ret:
        lines.append(
            f"  retired:    {ret.get('safe', 0)} safe / {ret.get('caution', 0)} "
            f"caution / {ret.get('feature', 0)} feature / "
            f"{ret.get('no_match', 0)} no match"
        )
    elif rep.get("retirements_error"):
        lines.append(f"  retired:    (provenance unavailable: {rep['retirements_error']})")
    t = rep["totals"]
    lines.append(
        f"  totals:     {t['changesets']} changesets, {t['uploaded']} addresses "
        f"({t['first_date']} -> {t['last_date']})"
    )
    if rep["blockers"]:
        lines.append("  not closed yet:")
        lines += [f"    - {b}" for b in rep["blockers"]]
    else:
        lines.append("  month is closed (uploaded, published, watermark advanced)")
    return "\n".join(lines)


_RENDERERS = {
    "text": render_text,
    "wiki": render_wiki,
    "wikitable": render_wikitable,
    "markdown": render_markdown,
    "json": lambda rep: json.dumps(rep, indent=2, sort_keys=True, default=str),
}

FORMATS = tuple(_RENDERERS)


def render(rep: dict, fmt: str = "text") -> str:
    try:
        return _RENDERERS[fmt](rep)
    except KeyError:
        raise ValueError(f"unknown format {fmt!r} (want one of {', '.join(FORMATS)})")
