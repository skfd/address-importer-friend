"""Is the city's published import proposal the one sitting in the checkout?

A month ends in paperwork (`maintenance_report`), and the last step of that
paperwork is a human pasting `IMPORT_PROPOSAL.mediawiki` onto the city's wiki
page. Nothing enforced it, and on 2026-08-29 Toronto's page turned out to be
three revisions behind: the `maint-snap113` row, the follow-ups section that
records the `source` -> `addr:source` rewrite as dropped and repoints three
`future-work/` links that had 404'd since the repo split, and a tagging-plan
change. The links had been dead on a published import proposal for a fortnight.

**This warns; it never blocks.** `publish-db` earned a gate (2026-08-16) because
the tool owns both ends of that one — it wrote the DB and it can ask GitHub
whether the release exists. Here it owns neither the wiki nor the paste, and the
check is a network fetch of a third-party site: a gate would stop a close for a
MediaWiki outage that has nothing to do with the month. So the answer is a
standing badge on `/maintenance`, visible whether or not a month is closing,
which is also what makes it catch the two divergences that did *not* arrive with
a month.

**It compares the whole wikitext, not a marker.** `?action=raw` returns the
page's source, and against Toronto's checkout the diff came to exactly the three
pending revisions plus a trailing newline — so a full comparison is both cheaper
and sharper than hunting for the latest changeset id in the rendered page. What
it cannot tell you is whether either document is *true*: it compares two files
to each other, and on the day it was written the local one was the one carrying
a wrong claim about 49 uploaded nodes. That check is a different check.

Enabled by convention, not configuration: a city with `IMPORT_PROPOSAL.mediawiki`
at its checkout root and an `[export] import_plan` URL gets the badge, and any
city missing either gets nothing. Both already exist for their own reasons —
`import_plan` is the changeset tag, and the engine already refuses to upload
without it.
"""
from __future__ import annotations

import time
from pathlib import Path

import requests

from . import config as _config

PROPOSAL_FILENAME = "IMPORT_PROPOSAL.mediawiki"

#: The page render must stay fast (GET /maintenance is 0.28s cold and was fixed
#: at some cost to keep it there), so this is loaded async and memoized. Short
#: enough that pasting the page and reloading shows the badge flip.
CACHE_TTL_SECONDS = 300

_TIMEOUT = 15

_cache: tuple[float, dict] | None = None


def local_proposal() -> Path | None:
    """The checkout's copy of the proposal, or None where the city has none.

    Absent file = absent capability, the `03` pattern: a city being scaffolded
    has no proposal yet and must not be nagged about not having pasted one."""
    path = _config.CITY_DIR / PROPOSAL_FILENAME
    return path if path.is_file() else None


def raw_url(page_url: str) -> str:
    """The wikitext behind a MediaWiki page URL.

    `?action=raw` rather than the API: it is one request, it returns the source
    the operator pasted rather than a JSON envelope around it, and it needs no
    credentials."""
    sep = "&" if "?" in page_url else "?"
    return f"{page_url}{sep}action=raw"


def normalize(text: str) -> str:
    """Both sides, reduced to what a paste actually preserves.

    Trailing whitespace per line and at end of file survives a round trip
    through an editor and a wiki save unpredictably, and a file that differs
    only there has not diverged in any sense the operator cares about. Nothing
    else is touched: a changed word is a divergence."""
    return "\n".join(line.rstrip() for line in text.splitlines()).rstrip("\n")


def compare(local_text: str, live_text: str) -> dict:
    """Line counts for the report. Deliberately not a rendered diff — the
    operator has `git` and the file, and the badge only has to say whether to
    look."""
    local_lines = normalize(local_text).split("\n")
    live_lines = normalize(live_text).split("\n")
    if local_lines == live_lines:
        return {"state": "match", "changed_lines": 0}
    local_set, live_set = set(local_lines), set(live_lines)
    return {
        "state": "diverged",
        "changed_lines": len(local_set - live_set) + len(live_set - local_set),
        "local_only": len(local_set - live_set),
        "live_only": len(live_set - local_set),
    }


def _fetch(url: str) -> str:
    resp = requests.get(url, timeout=_TIMEOUT, headers={
        "User-Agent": "address-importer-friend wiki-sync check",
    })
    resp.raise_for_status()
    return resp.text


def status(force: bool = False) -> dict:
    """Whether the live proposal page matches the checkout's copy.

    `state` is one of:

      off       this city declares no proposal page, or has no local copy
      match     the page is the file
      diverged  the file has moved ahead (or the page has), with a line count
      unknown   the wiki could not be read — a network fact, not a paste fact,
                and reported as such rather than as a failure to paste
    """
    global _cache
    now = time.time()
    if not force and _cache and now - _cache[0] < CACHE_TTL_SECONDS:
        return _cache[1]

    page_url = (_config.load().export_import_plan or "").strip()
    local = local_proposal()
    if not page_url or local is None:
        missing = "no [export] import_plan" if not page_url else \
            f"no {PROPOSAL_FILENAME} in the checkout"
        result = {"state": "off", "reason": missing, "url": page_url or None}
    else:
        result = {"url": page_url, "raw_url": raw_url(page_url),
                  "local_path": str(local), "filename": PROPOSAL_FILENAME}
        try:
            live = _fetch(raw_url(page_url))
        except Exception as exc:                      # network, 404, redirect
            result.update({"state": "unknown", "reason": f"{type(exc).__name__}: {exc}"})
        else:
            result.update(compare(local.read_text(encoding="utf-8"), live))
    result["checked_at"] = now
    _cache = (now, result)
    return result
