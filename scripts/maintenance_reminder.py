"""File the monthly maintenance reminder on a city repo.

Run by `.github/workflows/maintenance-reminder.yml`, which every city checkout
calls from a small workflow of its own (scheduled for the 1st of the month).
It is a reminder, not a delta: the real numbers need the checkout's local
tool.db and the tracker DB, so they stay on `/maintenance`. What the issue adds
is what a runner can see from outside — the city's page on the public
ontario-address-changes site, and the city repo's last published DB snapshot,
which is the last month that was closed.

A city is in maintenance once its config.toml carries

    [maintenance]
    since = "2026-06-05"   # the day the initial import finished

and gets no reminder before that, so the workflow can be scaffolded with every
new city and stay quiet until its import is done. The engine does not read this
section; only this script does.

Stdlib only, so the workflow needs no install step.

    python scripts/maintenance_reminder.py --city-dir ../toronto-2-address-import --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
import urllib.request
from datetime import date, timedelta
from pathlib import Path

LABEL = "address-maintenance"
SITE = "https://skfd.github.io/ontario-address-changes"
# A closed month publishes a DB snapshot. Longer than this without one and a
# month has probably gone by unclosed; the issue says so.
CLOSED_STALE_DAYS = 45
REPORT_CAP = 12


def _get(url: str) -> str | None:
    """Best-effort fetch: enrichment must never stop the reminder."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "maintenance-reminder"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8")
    except Exception:
        return None


def _gh(*args: str) -> str:
    out = subprocess.run(["gh", *args], capture_output=True, text=True,
                         encoding="utf-8", timeout=120)
    if out.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:2])}: {out.stderr.strip()}")
    return out.stdout


def _repo(city_dir: Path) -> str:
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    url = subprocess.run(["git", "-C", str(city_dir), "remote", "get-url", "origin"],
                         capture_output=True, text=True).stdout.strip()
    tail = url.split("github.com", 1)[-1].lstrip(":/")
    return tail[:-4] if tail.endswith(".git") else tail


def _tracker_slug(cfg: dict) -> str:
    """The ontario-address-changes dataset the city reads: the stem of
    `[source] sqlite_path` (data/<slug>/<slug>.db), else the city slug."""
    path = cfg.get("source", {}).get("sqlite_path", "")
    return Path(path).stem if path else cfg["city"]["slug"]


def feed_lines(slug: str, since: date) -> list[str]:
    """What the tracker saw of this city since `since`, from its public pages."""
    page = f"{SITE}/{slug}/"
    lines = []
    card = _get(f"{page}_card.json")
    status = _get(f"{SITE}/status.json")
    if card:
        c = json.loads(card)
        checked = (json.loads(status).get(slug, {}).get("checked") if status else None)
        lines.append(f"- {c['row_count']:,} rows in the feed"
                     + (f", last checked {checked}" if checked else "") + ".")
    index = _get(page)
    if index:
        dates = sorted({d for d in re.findall(r"report-(\d{4}-\d{2}-\d{2})\.html", index)
                        if d > since.isoformat()}, reverse=True)
        if dates:
            links = ", ".join(f"[{d}]({page}report-{d}.html)" for d in dates[:REPORT_CAP])
            more = f" and {len(dates) - REPORT_CAP} more" if len(dates) > REPORT_CAP else ""
            lines.append(f"- {len(dates)} change report{'s' if len(dates) != 1 else ''} "
                         f"since {since}: {links}{more}.")
        else:
            lines.append(f"- No change reports since {since}.")
    if card and c.get("has_changes"):
        lines.append(f"- Latest, {c['last_date']}: +{c['added']} −{c['removed']} "
                     f"~{c['modified']}" + (f" ({c['highlight']})" if c.get("highlight") else "")
                     + ".")
    prev = (date.today().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    article = f"{SITE}/articles/{slug}-{prev}.html"
    if _get(article):
        lines.append(f"- [Last month's article]({article}).")
    if lines:
        lines.insert(0, f"**The feed** ([ontario-address-changes]({page})):")
    return lines


def last_closed(repo: str) -> tuple[str, date] | None:
    """The newest `tool-db-*` release: closing a month publishes one."""
    try:
        rels = json.loads(_gh("release", "list", "--repo", repo, "--limit", "30",
                              "--json", "tagName,publishedAt"))
    except Exception:
        return None
    for r in rels:
        if r["tagName"].startswith("tool-db-"):
            return r["tagName"], date.fromisoformat(r["publishedAt"][:10])
    return None


def render(cfg: dict, city_dir: Path, since: date, closed, feed: list[str],
           superseded: list[int]) -> str:
    name = cfg["city"]["name"]
    rel = f"../{city_dir.name}"
    out = [f"Time for {name}'s monthly address maintenance "
           f"(in maintenance since {since}).", ""]
    if closed:
        tag, when = closed
        age = (date.today() - when).days
        out.append(f"**Last closed month:** `{tag}`, published {when}."
                   + (f" That is {age} days ago, so a month may have gone unclosed."
                      if age > CLOSED_STALE_DAYS else ""))
        out.append("")
    if feed:
        out += feed + [""]
    out += [
        "## Steps",
        "",
        f"- [ ] Start the engine on this checkout: "
        f"`cd address-importer-friend && python run.py --city-dir {rel} --prod`",
        "- [ ] On http://localhost:5000/maintenance, read the delta, prepare the "
        "month's `maint-snap<N>` run, review and upload it",
        "- [ ] Work the retirements from that page's JOSM / iD links. Delete only "
        "what the history supports",
        f"- [ ] Publish a DB snapshot: `/publish-db {rel}`",
        "- [ ] **Close month** on `/maintenance`",
        "- [ ] Paste `python -m t2.maintenance --report --format wiki` into the "
        "proposal's *Continuous maintenance* table and update the README total",
        "",
    ]
    plan = cfg.get("export", {}).get("import_plan")
    if plan:
        out += [f"Import plan: {plan}", ""]
    if superseded:
        out += [f"Replaces {', '.join(f'#{n}' for n in superseded)}, still open from "
                "an earlier month; one run covers everything since the watermark.", ""]
    out.append("<sub>Filed by the maintenance-reminder workflow from "
               "skfd/address-importer-friend.</sub>")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--city-dir", default=".", help="Per-city checkout (default: cwd).")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the issue instead of filing it.")
    args = p.parse_args(argv)
    # The body carries − and —; a Windows console pipe would choke on them.
    sys.stdout.reconfigure(encoding="utf-8")

    city_dir = Path(args.city_dir).resolve()
    with open(city_dir / "config.toml", "rb") as f:
        cfg = tomllib.load(f)
    name = cfg["city"]["name"]
    since = cfg.get("maintenance", {}).get("since")
    if not since:
        print(f"{name}: no [maintenance] since in config.toml, still importing; no reminder")
        return 0
    since = date.fromisoformat(str(since))

    repo = _repo(city_dir)
    title = f"Address maintenance {date.today():%Y-%m} — {name}"
    issues = json.loads(_gh("issue", "list", "--repo", repo, "--label", LABEL,
                            "--state", "all", "--limit", "100",
                            "--json", "number,title,state"))
    if any(i["title"] == title for i in issues):
        print(f"{repo}: '{title}' is already filed")
        return 0

    # Feed reports since the last closed month: that is what the run will
    # cover, however many reminders went by unworked.
    closed = last_closed(repo)
    window = max(since, closed[1]) if closed else since
    open_old = [i["number"] for i in issues if i["state"] == "OPEN"]
    body = render(cfg, city_dir, since, closed,
                  feed_lines(_tracker_slug(cfg), window), open_old)
    if args.dry_run:
        print(f"# {title}\n\n{body}")
        return 0

    _gh("label", "create", LABEL, "--repo", repo, "--color", "1D76DB", "--force",
        "--description", "Monthly address-maintenance reminder")
    url = _gh("issue", "create", "--repo", repo, "--title", title,
              "--label", LABEL, "--body", body).strip()
    print(f"{repo}: filed {url}")
    for n in open_old:
        _gh("issue", "close", str(n), "--repo", repo, "--reason", "not planned",
            "--comment", f"Superseded by {url}.")
        print(f"{repo}: closed #{n} as superseded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
