"""Stage 2: fetch OSM addresses for a run's bbox. Cached per run.

Source is selected by ``config.osm.source``:

* ``local``    — clip the shared extract at ``config.osm_extract_dir/toronto-addresses.json``
                 (refreshed via ``python -m t2.osm_refresh``) to the run bbox.
                 Fast, offline, reproducible.
* ``overpass`` — POST an Overpass query for the run bbox. Network-dependent;
                 kept as a fallback for bbox experiments outside Toronto.

Both paths write the result to ``data/osm_current_run<id>.json`` so downstream
``osm_fetch.load_cached(run_id)`` and ``conflate.build_osm_index`` are unchanged.
"""
import hashlib
import json
import math
from pathlib import Path

import requests

from . import config as _config

_CONFIG = _config.load()

# Runs ingest candidates clipped to the tile polygon, but conflation must still
# find OSM matches up to match_radius_m beyond a tile edge — so the OSM fetch
# bbox is padded by HALO_MARGIN * match_radius_m. match_radius_m is the floor
# (a candidate on the bbox edge can match that far out); the >1 margin absorbs
# the metre->degree conversion and bbox rounding. Overlap of this halo between
# adjacent tiles is harmless: OSM data is read-only reference, never uploaded.
HALO_MARGIN = 1.5

# Process-local cache for the shared filtered extract used by `local` source.
# Keyed by (path_str, mtime) so a refreshed extract invalidates automatically.
# Repeated bbox clips within one process (e.g. the run-for-all worker doing
# 100+ tiles) would otherwise re-parse hundreds of MB of JSON every tile.
_SHARED_EXTRACT_CACHE: dict[tuple[str, float], list[dict]] = {}


def _load_shared_extract(path: Path) -> list[dict]:
    key = (str(path), path.stat().st_mtime)
    cached = _SHARED_EXTRACT_CACHE.get(key)
    if cached is not None:
        return cached
    elements = json.loads(path.read_text(encoding="utf-8"))
    # Drop stale entries — only the latest mtime is worth holding in memory.
    _SHARED_EXTRACT_CACHE.clear()
    _SHARED_EXTRACT_CACHE[key] = elements
    return elements


def _build_query(bbox: tuple[float, float, float, float], check_count: bool = False) -> str:
    bbox_str = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"
    timeout = 180 if not check_count else 30
    q = f"[out:json][timeout:{timeout}];("
    q += f'node["addr:housenumber"]({bbox_str});'
    q += f'way["addr:housenumber"]({bbox_str});'
    q += f'relation["addr:housenumber"]({bbox_str});'
    q += ");"
    if check_count:
        q += "out count;"
    else:
        # addr:interpolation ways pull in their member-node IDs (out body) so
        # conflation can exclude interpolation endpoints from matching.
        q += "out center;"
        q += f'way["addr:interpolation"]({bbox_str});'
        q += "out body;"
    return q


def _cache_path(run_id: int) -> Path:
    return _CONFIG.data_dir / f"osm_current_run{run_id}.json"


def _element_latlon(el: dict) -> tuple[float | None, float | None]:
    if el.get("type") == "node":
        return el.get("lat"), el.get("lon")
    c = el.get("center") or {}
    return c.get("lat"), c.get("lon")


def _in_bbox(lat: float | None, lon: float | None, bbox: tuple[float, float, float, float]) -> bool:
    if lat is None or lon is None:
        return False
    return bbox[0] <= lat <= bbox[2] and bbox[1] <= lon <= bbox[3]


def _element_in_bbox(el: dict, bbox: tuple[float, float, float, float]) -> bool:
    """Clip to run bbox using Overpass `(bbox)` semantics.

    Nodes are point-in-bbox. Ways and multipolygon relations use their stored
    ``bounds`` (from the refresh step) and pass if that rectangle intersects
    the run bbox — a feature whose center is just outside the bbox can still
    intersect it. If a cached extract predates the ``bounds`` field we fall
    back to center-in-bbox.
    """
    if el.get("type") in ("way", "relation"):
        b = el.get("bounds")
        if b:
            return (
                b["minlat"] <= bbox[2]
                and b["maxlat"] >= bbox[0]
                and b["minlon"] <= bbox[3]
                and b["maxlon"] >= bbox[1]
            )
    lat, lon = _element_latlon(el)
    return _in_bbox(lat, lon, bbox)


def _fetch_from_local(
    run_id: int, bbox: tuple[float, float, float, float], force: bool
) -> tuple[Path, str]:
    path = _cache_path(run_id)
    if path.exists() and not force:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return path, digest

    shared = _CONFIG.osm_extract_dir / "toronto-addresses.json"
    if not shared.exists():
        raise FileNotFoundError(
            f"Local OSM extract not found at {shared}. "
            "Run `python -m t2.osm_refresh` (or click Refresh at /osm) first."
        )
    all_elements = _load_shared_extract(shared)
    clipped = [el for el in all_elements if _element_in_bbox(el, bbox)]
    body = json.dumps(clipped)
    path.write_text(body, encoding="utf-8")
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return path, digest


def _fetch_from_overpass(
    run_id: int, bbox: tuple[float, float, float, float], force: bool
) -> tuple[Path, str]:
    path = _cache_path(run_id)
    if path.exists() and not force:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return path, digest

    query = _build_query(bbox)
    resp = requests.post(_CONFIG.overpass_url, data={"data": query}, timeout=200)
    resp.raise_for_status()
    data = resp.json()
    elements = data.get("elements", [])
    body = json.dumps(elements)
    path.write_text(body, encoding="utf-8")
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return path, digest


def _pad_bbox(
    bbox: tuple[float, float, float, float], meters: float
) -> tuple[float, float, float, float]:
    """Expand bbox outward by ``meters`` on every side (degrees at bbox latitude)."""
    min_lat, min_lon, max_lat, max_lon = bbox
    dlat = meters / 111_320.0
    mid_lat = (min_lat + max_lat) / 2
    dlon = meters / (111_320.0 * max(math.cos(math.radians(mid_lat)), 0.01))
    return (min_lat - dlat, min_lon - dlon, max_lat + dlat, max_lon + dlon)


def fetch(run_id: int, bbox: tuple[float, float, float, float], force: bool = False) -> tuple[Path, str]:
    """Fetch OSM elements for bbox; cached to data/osm_current_run<run>.json.

    The bbox is padded by ``HALO_MARGIN * match_radius_m`` so edge candidates
    can still match OSM just outside the tile (see HALO_MARGIN). The padded
    bbox is used only for fetching — never persisted on the run.

    Returns (path, sha256_hex). Dispatches on ``config.osm.source``.
    """
    _CONFIG.data_dir.mkdir(parents=True, exist_ok=True)
    bbox = _pad_bbox(bbox, _CONFIG.match_radius_m * HALO_MARGIN)
    if _CONFIG.osm_source == "local":
        return _fetch_from_local(run_id, bbox, force)
    return _fetch_from_overpass(run_id, bbox, force)


def _build_around_query(
    points: list[tuple[float, float]], radius_m: float
) -> str:
    """Overpass query for addr features within ``radius_m`` of ANY listed point.

    Used by the monthly maintenance job, whose working set is a scattered
    handful of delta points rather than a contiguous bbox — a single bbox over
    them would span the whole city. Overpass's ``around`` filter takes a flat
    ``lat,lon,lat,lon,...`` coordinate list, so the entire delta collapses to
    three statements. ``out meta`` is requested so the caller can read each
    element's version/changeset/user for provenance.
    """
    coords = ",".join(f"{lat:.7f},{lon:.7f}" for lat, lon in points)
    around = f"around:{radius_m:.0f},{coords}"
    q = "[out:json][timeout:120];("
    q += f'node["addr:housenumber"]({around});'
    q += f'way["addr:housenumber"]({around});'
    q += f'relation["addr:housenumber"]({around});'
    q += ");"
    q += "out meta center;"
    # addr:interpolation ways pull in their member-node IDs so conflation can
    # exclude interpolation endpoints from matching (mirrors _build_query).
    q += f'way["addr:interpolation"]({around});'
    q += "out meta body;"
    return q


def fetch_around(
    run_id: int,
    points: list[tuple[float, float]],
    radius_m: float,
    force: bool = False,
) -> tuple[Path, str]:
    """Fetch OSM addr features near a scattered point set (live Overpass) and
    cache to ``data/osm_current_run<run>.json`` — the same path the conflate
    stage reads, so ``conflate.run`` and ``osm_fetch.load_cached`` are unchanged.

    Unlike :func:`fetch`, this ignores ``config.osm.source``: maintenance always
    reads live OSM (its footprint is tiny) rather than the local extract.
    Returns (path, sha256_hex).
    """
    _CONFIG.data_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(run_id)
    if path.exists() and not force:
        return path, hashlib.sha256(path.read_bytes()).hexdigest()
    if not points:
        body = "[]"
        path.write_text(body, encoding="utf-8")
        return path, hashlib.sha256(body.encode("utf-8")).hexdigest()
    query = _build_around_query(points, radius_m)
    # overpass-api.de returns 406 for the default python-requests User-Agent.
    resp = requests.post(
        _CONFIG.overpass_url,
        data={"data": query},
        timeout=200,
        headers={"User-Agent": "t2-address-import maintenance"},
    )
    resp.raise_for_status()
    elements = resp.json().get("elements", [])
    body = json.dumps(elements)
    path.write_text(body, encoding="utf-8")
    return path, hashlib.sha256(body.encode("utf-8")).hexdigest()


def load_cached(run_id: int) -> list[dict]:
    path = _cache_path(run_id)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))
