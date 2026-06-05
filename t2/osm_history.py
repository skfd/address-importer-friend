"""Provenance insight for an OSM element, built from its live edit history.

The monthly maintenance job (``t2/maintenance.py``) uses this to decide how
safe it is to manually delete an OSM address that has dropped out of the City
feed. Discovery of the matching element happens via Overpass; this module then
pulls the element's full version history from the OSM API and distils it into a
verdict plus a human-readable timeline.

Reads are **always against production OSM** (``api.openstreetmap.org``),
independent of the tool's upload ``--env`` — provenance is about where the
import actually lives, and the dev sandbox has no real Toronto history.
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests

# Username(s) the production import uploaded under. An element whose every
# version was authored by one of these — and nobody else — is "ours, pristine".
# See README § Status: production uploads ran from the `skfd imports` account.
IMPORT_OSM_USERNAMES = frozenset({"skfd imports"})

# Tag keys whose presence means the element is a real feature (a building or a
# POI), not a plain address point. A retired *address* must never delete one of
# these — the address rides on the feature. Mirrors POI_TAG_KEYS in conflate.
_FEATURE_TAG_KEYS = frozenset((
    "building", "amenity", "shop", "office", "tourism",
    "leisure", "craft", "healthcare",
))

_API_BASE = "https://api.openstreetmap.org"
_USER_AGENT = "t2-address-import maintenance (https://github.com/skfd/toronto-2-address-import)"


def fetch_history(osm_type: str, osm_id: int, timeout: float = 30.0) -> list[dict]:
    """Return every version of an element, oldest first. Empty list on 404."""
    url = f"{_API_BASE}/api/0.6/{osm_type}/{osm_id}/history.json"
    resp = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=timeout)
    if resp.status_code == 404:
        return []
    resp.raise_for_status()
    versions = resp.json().get("elements", [])
    return sorted(versions, key=lambda v: v.get("version", 0))


def _is_import(version: dict) -> bool:
    return version.get("user") in IMPORT_OSM_USERNAMES


def _is_feature(tags: dict) -> bool:
    return any(k in _FEATURE_TAG_KEYS for k in (tags or {}))


def _geometry_changed(versions: list[dict], osm_type: str) -> bool:
    first, last = versions[0], versions[-1]
    if osm_type == "node":
        def coord(v):
            return (round(v.get("lat", 0.0), 7), round(v.get("lon", 0.0), 7))
        return coord(first) != coord(last)
    if osm_type == "way":
        return (first.get("nodes") or []) != (last.get("nodes") or [])
    # relations: compare member refs
    return (first.get("members") or []) != (last.get("members") or [])


def _community_tag_changes(versions: list[dict]) -> dict[str, str]:
    """Keys a non-import editor added or changed after creation, value = the
    current value. Lets the operator see *what* a local mapper contributed
    (e.g. addr:unit, addr:postcode) — a strong signal to keep the node."""
    changes: dict[str, str] = {}
    prev = versions[0].get("tags") or {}
    for v in versions[1:]:
        tags = v.get("tags") or {}
        if not _is_import(v):
            for k, val in tags.items():
                if prev.get(k) != val:
                    changes[k] = val
            for k in prev:
                if k not in tags:
                    changes[k] = "(removed)"
        prev = tags
    return changes


def _days_since(ts: str | None) -> int | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int((datetime.now(timezone.utc) - dt).total_seconds() // 86400)


def analyze(osm_type: str, osm_id: int) -> dict:
    """Fetch + distil an element's history into a provenance struct.

    Verdicts (strict for action, informative underneath):
      - ``already_deleted``  — element is no longer visible in OSM; nothing to do.
      - ``keep_feature``     — building/POI; the address rides it, never delete.
      - ``pristine_ours``    — created by the import, touched by nobody since. Safe.
      - ``community_touched`` — created by us but edited by a community mapper after.
      - ``community_node``   — not created by the import. Don't delete on feed-silence.
      - ``unknown``          — history unavailable (API error / redacted).
    """
    try:
        versions = fetch_history(osm_type, osm_id)
    except requests.RequestException as exc:
        return {
            "osm_type": osm_type, "osm_id": osm_id, "verdict": "unknown",
            "error": str(exc), "timeline": [], "recommendation": "History unavailable.",
        }
    if not versions:
        return {
            "osm_type": osm_type, "osm_id": osm_id, "verdict": "unknown",
            "timeline": [], "recommendation": "No history returned.",
        }

    created, current = versions[0], versions[-1]
    current_tags = current.get("tags") or {}
    editors = {v.get("user") for v in versions}
    created_by_import = _is_import(created)
    ours_only = editors <= IMPORT_OSM_USERNAMES
    community_versions = [v for v in versions[1:] if not _is_import(v)]
    community_changes = _community_tag_changes(versions)

    if current.get("visible") is False:
        verdict = "already_deleted"
        rec = "Already deleted in OSM — nothing to do."
    elif _is_feature(current_tags):
        verdict = "keep_feature"
        kind = next((k for k in _FEATURE_TAG_KEYS if k in current_tags), "feature")
        rec = f"This is a {kind} ({kind}={current_tags.get(kind)}); the address rides it. KEEP."
    elif created_by_import and ours_only:
        verdict = "pristine_ours"
        rec = "Created by the import, never edited since. Safe to delete."
    elif created_by_import:
        verdict = "community_touched"
        rec = "Created by the import but a community mapper edited it after. Review — likely KEEP."
    else:
        verdict = "community_node"
        rec = "Not created by the import. Don't delete on feed-silence alone."

    timeline = [{
        "version": v.get("version"),
        "user": v.get("user"),
        "changeset": v.get("changeset"),
        "timestamp": v.get("timestamp"),
        "date": (v.get("timestamp") or "")[:10],
        "is_import": _is_import(v),
        "visible": v.get("visible", True),
    } for v in versions]

    return {
        "osm_type": osm_type,
        "osm_id": osm_id,
        "verdict": verdict,
        "recommendation": rec,
        "created_by_import": created_by_import,
        "n_versions": len(versions),
        "n_community_edits": len(community_versions),
        "community_tag_changes": community_changes,
        "geometry_changed": _geometry_changed(versions, osm_type),
        "is_feature": _is_feature(current_tags),
        "current_tags": current_tags,
        "last_edit_user": current.get("user"),
        "last_edit_days_ago": _days_since(current.get("timestamp")),
        "timeline": timeline,
    }
