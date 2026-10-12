"""Filter the shared Ontario OSM extract to the city's address features.

Canonical entry point: ``python -m t2.osm_refresh``.

The PBF itself lives in the shared store (``t2.osm_store``); a refresh asks
``osm-extracts`` to fetch it, then filters the dated file ``latest.json``
names. Writes to ``config.osm_extract_dir`` (default ``data/osm``):

    <slug>-addresses.json     filtered element list (shape matches Overpass `out center;`)
    meta.json                 source PBF (dated file + sha256) + timestamps + element counts
    refresh.lock              PID of the running refresh (present only while running)
    refresh.log               stdout+stderr of the last refresh run

Element JSON shape matches what ``osm_fetch.py`` used to write, so downstream
``conflate.build_osm_index`` and the checks need no changes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import audit, config as _config, osm_store


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _paths(cfg) -> dict[str, Path]:
    d = cfg.osm_extract_dir
    return {
        "dir": d,
        "json": cfg.osm_extract_json,
        "meta": d / "meta.json",
        "lock": d / "refresh.lock",
        "log": d / "refresh.log",
    }


def read_meta(cfg=None) -> dict | None:
    cfg = cfg or _config.load()
    p = _paths(cfg)["meta"]
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def log_path(cfg=None) -> Path:
    cfg = cfg or _config.load()
    return _paths(cfg)["log"]


def extract_dir(cfg=None) -> Path:
    cfg = cfg or _config.load()
    return _paths(cfg)["dir"]


def extract_status(cfg=None, stale_after_days: int = 14) -> str:
    """One of: 'running' | 'missing' | 'fresh' | 'stale'."""
    cfg = cfg or _config.load()
    running, _pid = is_refresh_running(cfg)
    if running:
        return "running"
    meta = read_meta(cfg)
    if not meta or not _paths(cfg)["json"].exists():
        return "missing"
    ts = meta.get("downloaded_at")
    if not ts:
        return "stale"
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return "stale"
    if dt.tzinfo is None:
        # meta written by an older refresh may lack tz info; treat as UTC.
        dt = dt.replace(tzinfo=timezone.utc)
    try:
        age_days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400
    except TypeError:
        return "stale"
    return "stale" if age_days > stale_after_days else "fresh"


def is_refresh_running(cfg=None) -> tuple[bool, int | None]:
    """Return (is_running, pid). A lock with a dead PID is treated as not running."""
    cfg = cfg or _config.load()
    lock = _paths(cfg)["lock"]
    if not lock.exists():
        return False, None
    try:
        pid = int(lock.read_text(encoding="utf-8").strip())
    except Exception:
        return False, None
    if _pid_alive(pid):
        return True, pid
    return False, pid


def tail_log(cfg=None, lines: int = 40) -> str:
    cfg = cfg or _config.load()
    p = _paths(cfg)["log"]
    if not p.exists():
        return ""
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                return False
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _log(msg: str) -> None:
    print(f"[{_iso_now()}] {msg}", flush=True)


def _in_bbox(lat: float, lon: float, bbox: tuple[float, float, float, float]) -> bool:
    return bbox[0] <= lat <= bbox[2] and bbox[1] <= lon <= bbox[3]


def _bounds_intersect_bbox(
    bounds: dict, bbox: tuple[float, float, float, float]
) -> bool:
    """True if a bounds rectangle overlaps bbox (minlat, minlon, maxlat, maxlon)."""
    return (
        bounds["minlat"] <= bbox[2]
        and bounds["maxlat"] >= bbox[0]
        and bounds["minlon"] <= bbox[3]
        and bounds["maxlon"] >= bbox[1]
    )


def _filter(pbf_path: Path, bbox: tuple[float, float, float, float]) -> tuple[list[dict], dict[str, int]]:
    """Scan the PBF and return (elements, counts) for addr:housenumber features in bbox.

    Element shape matches Overpass `out center;` for address ways and
    `out body;` for addr:interpolation ways (which carry their member node IDs
    so downstream conflation can exclude interpolation endpoints from matching).
    Multipolygon relations with addr:housenumber are emitted with a centroid
    computed from the union bbox of their member ways — close to the exact
    outer-ring centroid for typical building/co-op relations (e.g. relation
    12272741, "100 Bain Avenue"):

      node:   {"type": "node", "id": N, "lat": L, "lon": L, "tags": {...}}
      way:    {"type": "way",  "id": N, "center": {"lat": L, "lon": L},
               "bounds": {"minlat": .., "minlon": .., "maxlat": .., "maxlon": ..},
               "nodes": [n1, n2, ...], "tags": {...}}
      interp: {"type": "way",  "id": N, "bounds": {...},
               "nodes": [n1, n2, ...], "tags": {"addr:interpolation": ...}}
      rel:    {"type": "relation", "id": N, "center": {...}, "bounds": {...}, "tags": {...}}

    Two passes: pass 1 reads only relation blocks (no location cache) to
    identify target relations and their member way IDs; pass 2 is the existing
    node+way scan, which additionally caches bounds for those member ways.
    Pass 1 is ~1s on the 935 MB Ontario PBF; pass 2 is the existing cost.
    """
    import osmium  # imported lazily so the web app doesn't pay the cost

    elements: list[dict] = []
    counts = {
        "nodes": 0,
        "ways": 0,
        "interp_ways": 0,
        "relations": 0,
        "relations_no_geometry": 0,
        "outside_bbox": 0,
    }

    # Pass 1: collect addr:housenumber multipolygon relations + member way IDs.
    target_rels: dict[int, dict] = {}
    member_way_ids: set[int] = set()

    class _RelCollector(osmium.SimpleHandler):
        def relation(self, r):
            if "addr:housenumber" not in r.tags:
                return
            if r.tags.get("type") != "multipolygon":
                # Other relation types (boundary, site, …) carry addr:* less
                # often and have ill-defined centroids — skip for now.
                return
            way_refs = [m.ref for m in r.members if m.type == "w"]
            if not way_refs:
                return
            target_rels[r.id] = {
                "tags": {t.k: t.v for t in r.tags},
                "member_ways": way_refs,
            }
            member_way_ids.update(way_refs)

    _RelCollector().apply_file(str(pbf_path))

    # Pass 2: existing node+way scan, plus bounds capture for relation members.
    way_bounds_for_rels: dict[int, dict] = {}

    class Handler(osmium.SimpleHandler):
        def node(self, n):
            if "addr:housenumber" not in n.tags:
                return
            if not n.location.valid():
                return
            lat, lon = n.location.lat, n.location.lon
            if not _in_bbox(lat, lon, bbox):
                counts["outside_bbox"] += 1
                return
            elements.append({
                "type": "node",
                "id": n.id,
                "lat": lat,
                "lon": lon,
                "tags": {t.k: t.v for t in n.tags},
            })
            counts["nodes"] += 1

        def way(self, w):
            has_hn = "addr:housenumber" in w.tags
            has_interp = "addr:interpolation" in w.tags
            is_member = w.id in member_way_ids
            if not has_hn and not has_interp and not is_member:
                return
            node_ids: list[int] = []
            lats: list[float] = []
            lons: list[float] = []
            for wn in w.nodes:
                node_ids.append(wn.ref)
                if wn.location.valid():
                    lats.append(wn.location.lat)
                    lons.append(wn.location.lon)
            if not lats:
                return
            minlat, maxlat = min(lats), max(lats)
            minlon, maxlon = min(lons), max(lons)
            bounds = {"minlat": minlat, "minlon": minlon,
                      "maxlat": maxlat, "maxlon": maxlon}
            if is_member:
                way_bounds_for_rels[w.id] = bounds
            if not has_hn and not has_interp:
                return
            # Match Overpass `way(...)(bbox)` semantics: keep the way if its
            # bounding box intersects the city bbox, not just if its center
            # falls inside.
            if not _bounds_intersect_bbox(bounds, bbox):
                counts["outside_bbox"] += 1
                return
            out: dict = {
                "type": "way",
                "id": w.id,
                "bounds": bounds,
                "nodes": node_ids,
                "tags": {t.k: t.v for t in w.tags},
            }
            if has_hn:
                out["center"] = {"lat": (minlat + maxlat) / 2,
                                 "lon": (minlon + maxlon) / 2}
                counts["ways"] += 1
            else:
                counts["interp_ways"] += 1
            elements.append(out)

    Handler().apply_file(str(pbf_path), locations=True)

    # Post-pass: assemble relation entries from member-way bounds.
    for rid, info in target_rels.items():
        union: dict | None = None
        for wid in info["member_ways"]:
            wb = way_bounds_for_rels.get(wid)
            if wb is None:
                continue
            if union is None:
                union = dict(wb)
            else:
                union = {
                    "minlat": min(union["minlat"], wb["minlat"]),
                    "minlon": min(union["minlon"], wb["minlon"]),
                    "maxlat": max(union["maxlat"], wb["maxlat"]),
                    "maxlon": max(union["maxlon"], wb["maxlon"]),
                }
        if union is None:
            counts["relations_no_geometry"] += 1
            continue
        if not _bounds_intersect_bbox(union, bbox):
            counts["outside_bbox"] += 1
            continue
        elements.append({
            "type": "relation",
            "id": rid,
            "bounds": union,
            "center": {
                "lat": (union["minlat"] + union["maxlat"]) / 2,
                "lon": (union["minlon"] + union["maxlon"]) / 2,
            },
            "tags": info["tags"],
        })
        counts["relations"] += 1

    return elements, counts


def _acquire_lock(lock: Path) -> None:
    lock.parent.mkdir(parents=True, exist_ok=True)
    if lock.exists():
        try:
            pid = int(lock.read_text(encoding="utf-8").strip())
        except Exception:
            pid = -1
        if _pid_alive(pid):
            raise RuntimeError(f"refresh already running (pid {pid}); remove {lock} if stale")
        _log(f"clearing stale lock (pid {pid} not alive)")
        lock.unlink(missing_ok=True)
    lock.write_text(str(os.getpid()), encoding="utf-8")


def _release_lock(lock: Path) -> None:
    try:
        lock.unlink(missing_ok=True)
    except Exception:
        pass


def _same_pbf(prior: dict | None, latest: dict) -> bool:
    """Whether the city extract was filtered from the store's latest file."""
    if not prior:
        return False
    if prior.get("pbf_sha256") and latest.get("sha256"):
        return prior["pbf_sha256"] == latest["sha256"]
    return bool(latest.get("source_last_modified")) and (
        prior.get("source_last_modified") == latest["source_last_modified"]
    )


def _filter_and_write(cfg, paths: dict[str, Path], pbf: Path, info: dict,
                      t_start: float, **stamps: str) -> dict:
    """Filter pbf, write the city JSON + meta.json, audit. info is the store's
    meta for pbf; stamps override downloaded_at / add rebuilt_at."""
    _log(f"filtering {pbf.name} with pyosmium to bbox {cfg.osm_city_bbox}")
    t_filter = time.monotonic()
    elements, counts = _filter(pbf, cfg.osm_city_bbox)
    filter_s = time.monotonic() - t_filter
    _log(f"filter done in {filter_s:.1f}s — {counts}")

    body = json.dumps(elements)
    paths["json"].write_text(body, encoding="utf-8")
    json_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    _log(f"wrote {paths['json']} ({len(body)} bytes, sha256 {json_sha[:16]}…)")

    meta = {
        "source_url": info.get("source_url") or cfg.osm_pbf_url,
        "source_last_modified": info.get("source_last_modified") or "",
        "source_bytes": info.get("bytes") or pbf.stat().st_size,
        "pbf_file": pbf.name,
        "pbf_sha256": info.get("sha256") or "",
        "json_sha256": json_sha,
        "json_bytes": len(body),
        "element_counts": counts,
        "city_bbox": list(cfg.osm_city_bbox),
        "downloaded_at": _iso_now(),
        **stamps,
        "filter_duration_s": round(filter_s, 2),
        "total_duration_s": round(time.monotonic() - t_start, 2),
    }
    paths["meta"].write_text(json.dumps(meta, indent=2), encoding="utf-8")
    audit.log(actor="osm_refresh", event_type="OSM_EXTRACT_REFRESHED", payload=meta)
    _log("done")
    return meta


def run(force: bool = False, dry_run: bool = False, rebuild: bool = False) -> dict:
    """Do the refresh. Returns the meta dict written to disk (or would-be meta on dry_run).

    rebuild=True re-filters the PBF the extract was built from without
    fetching; useful after the filter logic changes (e.g. emitting
    multipolygon relations).
    """
    cfg = _config.load()
    paths = _paths(cfg)
    paths["dir"].mkdir(parents=True, exist_ok=True)
    prior = read_meta(cfg)

    if rebuild:
        pbf, note = osm_store.resolve_pbf(cfg, prior)
        if pbf is None:
            raise FileNotFoundError(f"--rebuild: {note}; run without --rebuild first.")
        if note:
            _log(note)
        info = osm_store.file_meta(pbf)
        if not note and prior and not info.get("sha256"):
            info = {**info, "sha256": prior.get("pbf_sha256")}
        _acquire_lock(paths["lock"])
        t_start = time.monotonic()
        try:
            _log(f"rebuild: reusing {pbf} ({pbf.stat().st_size} bytes)")
            downloaded_at = (prior or {}).get("downloaded_at") if not note else None
            return _filter_and_write(cfg, paths, pbf, info, t_start,
                                     downloaded_at=downloaded_at or _iso_now(),
                                     rebuilt_at=_iso_now())
        finally:
            _release_lock(paths["lock"])

    if dry_run:
        latest = osm_store.read_latest(cfg) or {}
        unchanged = _same_pbf(prior, latest) and paths["json"].exists()
        _log(f"dry-run: store latest {latest.get('file') or '(none)'}, "
             f"would_filter={not unchanged or force} (Geofabrik not checked)")
        return {
            "store_file": latest.get("file"),
            "source_last_modified": latest.get("source_last_modified", ""),
            "source_bytes": latest.get("bytes", 0),
            "would_filter": (not unchanged) or force,
            "prior": prior,
        }

    _acquire_lock(paths["lock"])
    t_start = time.monotonic()
    try:
        _log(f"fetching {cfg.osm_pbf_url} into {osm_store.region_dir(cfg)}")
        osm_store.fetch(cfg, force=force)
        latest = osm_store.read_latest(cfg) or {}
        pbf = osm_store.region_dir(cfg) / latest["file"] if latest.get("file") else None
        if pbf is None or not pbf.exists():
            raise FileNotFoundError(f"no latest extract in {osm_store.region_dir(cfg)} after fetch")
        _log(f"store latest: {pbf.name}, source last-modified "
             f"{latest.get('source_last_modified') or '(unknown)'}")

        if _same_pbf(prior, latest) and paths["json"].exists() and not force:
            if prior.get("pbf_file") != pbf.name:
                prior["pbf_file"] = pbf.name
                paths["meta"].write_text(json.dumps(prior, indent=2), encoding="utf-8")
                _log(f"recorded pbf_file {pbf.name} in {paths['meta']}")
            _log("extract already filtered from this PBF; skipping (pass --force to override)")
            return prior

        return _filter_and_write(cfg, paths, pbf, latest, t_start)
    finally:
        _release_lock(paths["lock"])


def _cli() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m t2.osm_refresh",
        description="Fetch the shared OSM extract and filter it to the city for stage 2.",
    )
    parser.add_argument("--force", action="store_true",
                        help="Have the store re-download even if Geofabrik Last-Modified "
                             "is unchanged, and re-filter.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Only compare the city extract with the store's latest; "
                             "fetch nothing.")
    parser.add_argument("--rebuild", action="store_true",
                        help="Re-filter the PBF the extract was built from (no fetch). "
                             "Use after the filter logic changes.")
    args = parser.parse_args()
    try:
        run(force=args.force, dry_run=args.dry_run, rebuild=args.rebuild)
        return 0
    except Exception as e:
        _log(f"ERROR: {e!r}")
        return 1


if __name__ == "__main__":
    sys.exit(_cli())
