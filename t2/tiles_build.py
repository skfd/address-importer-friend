"""Build the city's tile layer from a neighbourhood GeoJSON + source addresses.

Canonical entry point: ``python -m t2.tiles_build``.

Fetches the polygon layer named by ``[city] neighbourhoods_url`` (Toronto's is
the City's official 158-neighbourhood layer), counts active source addresses
inside each polygon, and quadtree-splits any neighbourhood with more than
``SPLIT_THRESHOLD`` addresses so each final tile is a manageable picking unit
for a run.

**Cities with no neighbourhood layer** leave ``neighbourhoods_url`` empty. The
builder then skips the download and quadtree-splits ``[osm] city_bbox``
directly, naming the tiles after ``[city] name``. This is the same code path
the layer-backed build already used for addresses falling outside every
polygon, so the splitting, merging and ≤500-per-tile logic are untouched.

Writes to ``cfg.data_dir``:

    neighbourhoods/neighbourhoods-4326.geojson    raw GeoJSON (WGS84)
    neighbourhoods/meta.json                      download sidecar
    tiles.json                                    the tile layer (read by the web app)
    tiles/meta.json                               build sidecar (counts, duration, orphans)
    tiles/build.lock                              PID of the running build
    tiles/build.log                               stdout+stderr of last build
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import requests
from shapely.geometry import MultiPolygon, Point, Polygon, box, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

from . import audit, config as _config, source_db

SPLIT_THRESHOLD = 500
# ~330 m at southern-Ontario latitude. Below this, stop subdividing even if count > threshold —
# prevents runaway recursion on high-rise clusters where all addresses share a point.
MIN_SPAN_DEG = 0.003
# Orphan pieces from a layer-backed build are force-split below this span
# (~1 km) regardless of count, so sparse orphans become small local tiles the
# merge step can absorb into bordering real tiles. Without it, a handful of
# stragglers makes one catch-all tile whose ring polygon — and therefore whose
# bbox, and therefore whose runs — spans the entire city. The no-layer path
# does not use it: there the "orphans" are the whole city and big rural tiles
# are the point.
ORPHAN_MAX_SPAN_DEG = 0.01
# After splitting, merge under-filled tiles into border-sharing neighbours so the
# operator never reviews a near-empty tile. Merges prefer same-parent partners and
# results staying ≤ soft ceiling; hard ceiling caps how big a merged tile may grow.
MERGE_FLOOR = 250
MERGE_SOFT_CEILING = 500
MERGE_HARD_CEILING = 750
SCHEMA_VERSION = 1

_CHUNK = 1 << 20
_HTTP_TIMEOUT = 60


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _paths(cfg) -> dict[str, Path]:
    data = cfg.data_dir
    tiles_dir = data / "tiles"
    hood_dir = data / "neighbourhoods"
    return {
        "data_dir": data,
        "tiles_dir": tiles_dir,
        "hood_dir": hood_dir,
        "geojson": hood_dir / "neighbourhoods-4326.geojson",
        "geojson_meta": hood_dir / "meta.json",
        "tiles_json": data / "tiles.json",
        "tiles_meta": tiles_dir / "meta.json",
        "lock": tiles_dir / "build.lock",
        "log": tiles_dir / "build.log",
    }


def read_meta(cfg=None) -> dict | None:
    cfg = cfg or _config.load()
    p = _paths(cfg)["tiles_meta"]
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def log_path(cfg=None) -> Path:
    cfg = cfg or _config.load()
    return _paths(cfg)["log"]


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
            h = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid
            )
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


def is_build_running(cfg=None) -> tuple[bool, int | None]:
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


def _acquire_lock(lock: Path) -> None:
    lock.parent.mkdir(parents=True, exist_ok=True)
    if lock.exists():
        try:
            pid = int(lock.read_text(encoding="utf-8").strip())
        except Exception:
            pid = -1
        if _pid_alive(pid):
            raise RuntimeError(
                f"build already running (pid {pid}); remove {lock} if stale"
            )
        _log(f"clearing stale lock (pid {pid} not alive)")
        lock.unlink(missing_ok=True)
    lock.write_text(str(os.getpid()), encoding="utf-8")


def _release_lock(lock: Path) -> None:
    try:
        lock.unlink(missing_ok=True)
    except Exception:
        pass


def _log(msg: str) -> None:
    print(f"[{_iso_now()}] {msg}", flush=True)


def _head(url: str) -> dict[str, str]:
    r = requests.head(url, allow_redirects=True, timeout=_HTTP_TIMEOUT)
    r.raise_for_status()
    return dict(r.headers)


def _download(url: str, dest: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    total = 0
    tmp = dest.with_suffix(dest.suffix + ".partial")
    with requests.get(url, stream=True, timeout=_HTTP_TIMEOUT) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_content(chunk_size=_CHUNK):
                if not chunk:
                    continue
                f.write(chunk)
                h.update(chunk)
                total += len(chunk)
    tmp.replace(dest)
    return h.hexdigest(), total


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "tile"


def _polygon_latlon(poly: Polygon) -> list[list[list[float]]]:
    """Return Leaflet-style rings: [[[lat, lon], ...]] (exterior ring only)."""
    coords = [[round(y, 6), round(x, 6)] for x, y in poly.exterior.coords]
    return [coords]


def _iter_polygons(geom) -> Iterator[Polygon]:
    """Yield Polygon pieces from any geometry, ignoring non-polygonal parts."""
    if geom is None or geom.is_empty:
        return
    if isinstance(geom, Polygon):
        yield geom
        return
    if isinstance(geom, MultiPolygon):
        for g in geom.geoms:
            yield from _iter_polygons(g)
        return
    geoms = getattr(geom, "geoms", None)
    if geoms is None:
        return
    for g in geoms:
        yield from _iter_polygons(g)


def _bounds_bbox(poly: Polygon) -> list[float]:
    minx, miny, maxx, maxy = poly.bounds
    return [round(miny, 6), round(minx, 6), round(maxy, 6), round(maxx, 6)]


def _count_inside(poly: Polygon, points: list[Point], tree: STRtree) -> int:
    idxs = tree.query(poly)
    count = 0
    for i in idxs:
        if poly.contains(points[int(i)]):
            count += 1
    return count


def _make_tile(
    *,
    name: str,
    parent: str,
    polygon: Polygon,
    count: int,
    depth: int,
    is_multipolygon: bool,
    is_orphan: bool,
    used_ids: set[str],
) -> dict:
    base_id = _slugify(name)
    tile_id = base_id
    i = 2
    while tile_id in used_ids:
        tile_id = f"{base_id}-{i}"
        i += 1
    used_ids.add(tile_id)
    return {
        "id": tile_id,
        "name": name,
        "parent": parent,
        "depth": depth,
        "address_count": count,
        "bbox": _bounds_bbox(polygon),
        "polygon_latlon": _polygon_latlon(polygon),
        "is_multipolygon": is_multipolygon,
        "is_orphan": is_orphan,
    }


def _split_tile(
    *,
    name: str,
    parent: str,
    polygon: Polygon,
    points: list[Point],
    tree: STRtree,
    depth: int,
    threshold: int,
    min_span: float,
    max_span: float = 0.0,
    is_multipolygon: bool,
    is_orphan: bool,
    used_ids: set[str],
) -> Iterator[tuple[dict, Polygon]]:
    count = _count_inside(polygon, points, tree)
    if count == 0:
        return
    minx, miny, maxx, maxy = polygon.bounds
    at_floor = (maxx - minx) < min_span and (maxy - miny) < min_span
    over_span = max_span > 0 and ((maxx - minx) > max_span or (maxy - miny) > max_span)
    if at_floor or (count <= threshold and not over_span):
        yield (
            _make_tile(
                name=name,
                parent=parent,
                polygon=polygon,
                count=count,
                depth=depth,
                is_multipolygon=is_multipolygon,
                is_orphan=is_orphan,
                used_ids=used_ids,
            ),
            polygon,
        )
        return
    cx = (minx + maxx) / 2
    cy = (miny + maxy) / 2
    quadrants = [
        ("SW", box(minx, miny, cx, cy)),
        ("SE", box(cx, miny, maxx, cy)),
        ("NW", box(minx, cy, cx, maxy)),
        ("NE", box(cx, cy, maxx, maxy)),
    ]
    for qname, qbox in quadrants:
        child_geom = polygon.intersection(qbox)
        pieces = list(_iter_polygons(child_geom))
        if not pieces:
            continue
        if len(pieces) == 1:
            yield from _split_tile(
                name=f"{name}-{qname}",
                parent=parent,
                polygon=pieces[0],
                points=points,
                tree=tree,
                depth=depth + 1,
                threshold=threshold,
                min_span=min_span,
                max_span=max_span,
                is_multipolygon=is_multipolygon,
                is_orphan=is_orphan,
                used_ids=used_ids,
            )
        else:
            for k, piece in enumerate(pieces, start=1):
                yield from _split_tile(
                    name=f"{name}-{qname}-{k}",
                    parent=parent,
                    polygon=piece,
                    points=points,
                    tree=tree,
                    depth=depth + 1,
                    threshold=threshold,
                    min_span=min_span,
                    max_span=max_span,
                    is_multipolygon=is_multipolygon,
                    is_orphan=is_orphan,
                    used_ids=used_ids,
                )


def _merge_underfilled(
    tiles: list[dict],
    polys: list[Polygon],
    *,
    floor: int,
    soft_ceiling: int,
    hard_ceiling: int,
) -> tuple[list[dict], list[Polygon], dict]:
    """Absorb tiles below ``floor`` into a border-sharing neighbour.

    Only legal merges produce a single connected polygon (point-only contact
    rejected) and stay within ``hard_ceiling``. Selection prefers same-parent
    partners, results within ``soft_ceiling``, longest shared border, and the
    smallest combined count among ties. The larger contributor's id/name/parent
    survive so prior runs keyed off the survivor's id remain reachable.
    """
    n = len(tiles)
    if n == 0:
        return tiles, polys, {"merges": 0, "below_floor_remaining": 0}

    tiles_w = [dict(t) for t in tiles]
    polys_w = list(polys)
    alive = set(range(n))
    skipped: set[int] = set()

    tree = STRtree(polys_w)
    neighbours: list[set[int]] = [set() for _ in range(n)]
    for i in range(n):
        for j_obj in tree.query(polys_w[i]):
            j = int(j_obj)
            if j == i or j in neighbours[i]:
                continue
            try:
                shared = polys_w[i].boundary.intersection(polys_w[j].boundary)
            except Exception:
                continue
            if not shared.is_empty and shared.length > 0:
                neighbours[i].add(j)
                neighbours[j].add(i)

    merges = 0
    while True:
        below = [
            (tiles_w[i]["address_count"], i)
            for i in alive
            if i not in skipped and tiles_w[i]["address_count"] < floor
        ]
        if not below:
            break
        below.sort()
        _, t_idx = below[0]

        scored: list[tuple] = []
        for nb_idx in neighbours[t_idx]:
            combined = tiles_w[t_idx]["address_count"] + tiles_w[nb_idx]["address_count"]
            if combined > hard_ceiling:
                continue
            union = unary_union([polys_w[t_idx], polys_w[nb_idx]])
            if not isinstance(union, Polygon):
                continue
            same_parent = tiles_w[t_idx]["parent"] == tiles_w[nb_idx]["parent"]
            within_soft = combined <= soft_ceiling
            shared = polys_w[t_idx].boundary.intersection(polys_w[nb_idx].boundary)
            border = shared.length if not shared.is_empty else 0.0
            scored.append((not same_parent, not within_soft, -border, combined, nb_idx, union))

        if not scored:
            skipped.add(t_idx)
            continue

        scored.sort()
        _, _, _, _, partner_idx, merged_poly = scored[0]
        if tiles_w[partner_idx]["address_count"] >= tiles_w[t_idx]["address_count"]:
            keep, drop = partner_idx, t_idx
        else:
            keep, drop = t_idx, partner_idx

        survivor = tiles_w[keep]
        absorbed = tiles_w[drop]
        survivor["address_count"] = survivor["address_count"] + absorbed["address_count"]
        survivor["bbox"] = _bounds_bbox(merged_poly)
        survivor["polygon_latlon"] = _polygon_latlon(merged_poly)
        survivor["is_orphan"] = bool(survivor["is_orphan"]) or bool(absorbed["is_orphan"])
        history = survivor.setdefault("merged_from", [])
        history.extend(absorbed.get("merged_from", []))
        history.append(absorbed["name"])

        polys_w[keep] = merged_poly
        new_nb = (neighbours[keep] | neighbours[drop]) - {keep, drop}
        for nb in new_nb:
            neighbours[nb].discard(drop)
            neighbours[nb].add(keep)
        neighbours[keep] = new_nb
        neighbours[drop] = set()
        alive.discard(drop)
        skipped.discard(keep)
        merges += 1

    final_tiles = [tiles_w[i] for i in sorted(alive)]
    final_polys = [polys_w[i] for i in sorted(alive)]
    below_floor_remaining = sum(1 for t in final_tiles if t["address_count"] < floor)
    return final_tiles, final_polys, {
        "merges": merges,
        "below_floor_remaining": below_floor_remaining,
    }


def _feature_name(props: dict, name_field: str = "") -> str:
    if name_field:
        v = props.get(name_field)
        if v is None or not str(v).strip():
            raise ValueError(
                f"[city] neighbourhood_name_field = {name_field!r} is declared but "
                f"empty on a feature (props keys: {sorted(props)}). A declared "
                "field is a promise about the layer — fix the declaration or the "
                "layer, don't fall back to sniffing."
            )
        return str(v).strip()
    for key in ("AREA_NAME", "area_name", "NEIGHBOURHOOD_NAME", "NEIGHBOURHOOD", "Neighbourhood", "name"):
        v = props.get(key)
        if v:
            return str(v).strip()
    aid = props.get("AREA_ID") or props.get("_id") or "?"
    return f"neighbourhood-{aid}"


def _feature_community(props: dict, parent_field: str = "") -> str:
    """The layer's parent-area field, if it has one (Hamilton's COMMUNITY holds
    the former municipality). Sniffed, it disambiguates duplicate names only;
    declared via [city] neighbourhood_parent_field, it prefixes every tile name
    (a declared parent means the name field is a unit *within* it, e.g. Quinte
    West's planning district "3B" inside "TRENTON"). Lenient about empties —
    a parentless feature simply gets no prefix."""
    if parent_field:
        v = props.get(parent_field)
        return str(v).strip() if v else ""
    for key in ("COMMUNITY", "Community", "community"):
        v = props.get(key)
        if v:
            return str(v).strip()
    return ""


def load_addresses(snap_id: int) -> list[tuple[float, float]]:
    """Return address points as (lon, lat) — shapely's Point takes x,y = lon,lat."""
    conn = source_db.connect_readonly()
    try:
        rows = conn.execute(
            "SELECT latitude, longitude FROM addresses "
            "WHERE max_snapshot_id=? AND latitude IS NOT NULL AND longitude IS NOT NULL",
            (snap_id,),
        ).fetchall()
    finally:
        conn.close()
    return [(float(r["longitude"]), float(r["latitude"])) for r in rows]


def build_tiles(
    features: list[dict],
    points_xy: list[tuple[float, float]],
    city_bbox: tuple[float, float, float, float],
    *,
    orphan_name: str = "Unassigned",
    threshold: int = SPLIT_THRESHOLD,
    min_span: float = MIN_SPAN_DEG,
    merge_floor: int = MERGE_FLOOR,
    merge_soft_ceiling: int = MERGE_SOFT_CEILING,
    merge_hard_ceiling: int = MERGE_HARD_CEILING,
    name_field: str = "",
    parent_field: str = "",
) -> tuple[list[dict], dict]:
    points = [Point(x, y) for x, y in points_xy]
    tree = STRtree(points)

    used_ids: set[str] = set()
    tiles: list[dict] = []
    polys: list[Polygon] = []
    skipped_empty: list[str] = []
    hood_geoms: list = []

    # Neighbourhood names can repeat across a layer (Hamilton has ten distinct
    # "Industrial" units). Prefix ambiguous names with the parent community so
    # the tile reads "Stoney Creek Industrial", not "Industrial-2"; same-name-
    # same-community leftovers still get the -N id dedup in _make_tile.
    base_names = [_feature_name(feat.get("properties") or {}, name_field) for feat in features]
    name_counts = Counter(base_names)

    for feat, base_name in zip(features, base_names):
        props = feat.get("properties") or {}
        name = base_name
        # A declared parent field prefixes unconditionally; the sniffed
        # COMMUNITY fallback only disambiguates duplicates (Hamilton's tile
        # names must not move — TODO §7 makes ids/names load-bearing).
        if parent_field or name_counts[base_name] > 1:
            community = _feature_community(props, parent_field)
            if community and community.lower() != base_name.lower():
                name = f"{community} {base_name}"
        geom = shape(feat["geometry"])
        hood_geoms.append(geom)
        pieces = list(_iter_polygons(geom))
        if not pieces:
            continue
        is_multi = len(pieces) > 1
        yielded_any = False
        if not is_multi:
            for t, poly in _split_tile(
                name=name,
                parent=name,
                polygon=pieces[0],
                points=points,
                tree=tree,
                depth=0,
                threshold=threshold,
                min_span=min_span,
                is_multipolygon=False,
                is_orphan=False,
                used_ids=used_ids,
            ):
                tiles.append(t)
                polys.append(poly)
                yielded_any = True
        else:
            for k, piece in enumerate(pieces, start=1):
                piece_name = f"{name}-{k}"
                for t, poly in _split_tile(
                    name=piece_name,
                    parent=name,
                    polygon=piece,
                    points=points,
                    tree=tree,
                    depth=0,
                    threshold=threshold,
                    min_span=min_span,
                    is_multipolygon=True,
                    is_orphan=False,
                    used_ids=used_ids,
                ):
                    tiles.append(t)
                    polys.append(poly)
                    yielded_any = True
        if not yielded_any:
            skipped_empty.append(name)

    total = len(points)
    assigned = sum(t["address_count"] for t in tiles)
    orphan_count = total - assigned
    orphan_pct = (orphan_count / total) if total else 0.0

    # Every orphan gets bucketed, no matter how few — an address in no tile is
    # unreachable from the picker and from Run-for-All (decision 2026-08-15;
    # Hamilton's layer strands 27). Small orphan tiles are then absorbed into
    # bordering real tiles by the merge pass below.
    if orphan_count > 0:
        _log(
            f"bucketing {orphan_count} orphans ({orphan_pct:.2%}) into {orphan_name!r}"
        )
        # With no neighbourhood layer, hood_geoms is empty, the union is empty,
        # and leftover is the whole city rectangle — so this is also the
        # no-layer path, splitting the bbox with the same quadtree.
        union = unary_union(hood_geoms)
        min_lat, min_lon, max_lat, max_lon = city_bbox
        city_rect = box(min_lon, min_lat, max_lon, max_lat)
        leftover = city_rect.difference(union)
        pieces = list(_iter_polygons(leftover))
        # Layer-backed leftovers get the span cap (see ORPHAN_MAX_SPAN_DEG);
        # the no-layer path (no features) keeps unbounded rural tiles.
        orphan_max_span = ORPHAN_MAX_SPAN_DEG if features else 0.0
        for k, piece in enumerate(pieces, start=1):
            piece_name = f"{orphan_name}-{k}" if len(pieces) > 1 else orphan_name
            for t, poly in _split_tile(
                name=piece_name,
                parent=orphan_name,
                polygon=piece,
                points=points,
                tree=tree,
                depth=0,
                threshold=threshold,
                max_span=orphan_max_span,
                min_span=min_span,
                is_multipolygon=len(pieces) > 1,
                is_orphan=True,
                used_ids=used_ids,
            ):
                tiles.append(t)
                polys.append(poly)

    assigned_after = sum(t["address_count"] for t in tiles)
    pre_merge_count = len(tiles)
    tiles, polys, merge_stats = _merge_underfilled(
        tiles,
        polys,
        floor=merge_floor,
        soft_ceiling=merge_soft_ceiling,
        hard_ceiling=merge_hard_ceiling,
    )
    stats = {
        "total_addresses": total,
        "assigned_after": assigned_after,
        "orphan_count": total - assigned_after,
        "orphan_pct": (total - assigned_after) / total if total else 0.0,
        "skipped_empty": skipped_empty,
        "tile_count": len(tiles),
        "pre_merge_tile_count": pre_merge_count,
        "merges": merge_stats["merges"],
        "below_floor_remaining": merge_stats["below_floor_remaining"],
    }
    return tiles, stats


def _run_without_layer(cfg, paths: dict[str, Path], *, dry_run: bool) -> dict:
    """Tile a city that has no neighbourhood polygon layer.

    Same builder, no features: `build_tiles` finds every address unassigned,
    takes the orphan branch, and quadtree-splits the whole `city_bbox`. Tiles
    are named after the city instead of "Unassigned" — nothing was assigned
    elsewhere, so there is nothing for them to be unassigned from.
    """
    if dry_run:
        _log("dry-run: no neighbourhoods_url configured; would split city_bbox directly")
        return {
            "source_url": "",
            "source_last_modified": "",
            "source_bytes": 0,
            "would_download": False,
        }

    _acquire_lock(paths["lock"])
    t_start = time.monotonic()
    try:
        _log(f"no [city] neighbourhoods_url; splitting city_bbox {cfg.osm_city_bbox}")
        _log("loading addresses from source DB")
        snap_id = source_db.latest_snapshot_id()
        points_xy = load_addresses(snap_id)
        _log(f"loaded {len(points_xy)} address points at snapshot {snap_id}")

        t_build = time.monotonic()
        tiles, stats = build_tiles(
            [], points_xy, cfg.osm_city_bbox, orphan_name=cfg.city_name
        )
        build_s = time.monotonic() - t_build
        _log(
            f"built {stats['tile_count']} tiles in {build_s:.1f}s; "
            f"merges={stats['merges']} (pre-merge={stats['pre_merge_tile_count']}); "
            f"below_floor_remaining={stats['below_floor_remaining']}; "
            f"orphans={stats['orphan_count']} ({stats['orphan_pct']:.2%})"
        )
        return _write_tiles(
            paths, tiles, stats, snap_id,
            neighbourhoods_sha=None, build_s=build_s, t_start=t_start,
        )
    finally:
        _release_lock(paths["lock"])


def _write_tiles(
    paths: dict[str, Path],
    tiles: list[dict],
    stats: dict,
    snap_id: int,
    *,
    neighbourhoods_sha: str | None,
    build_s: float,
    t_start: float,
) -> dict:
    """Write tiles.json + the build sidecar. Shared by both build paths so the
    on-disk shape cannot drift between them."""
    out = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso_now(),
        "source_snapshot_id": snap_id,
        "neighbourhoods_sha256": neighbourhoods_sha,
        "threshold": SPLIT_THRESHOLD,
        "tiles": tiles,
    }
    body = json.dumps(out)
    tmp = paths["tiles_json"].with_suffix(paths["tiles_json"].suffix + ".partial")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(paths["tiles_json"])
    _log(f"wrote {paths['tiles_json']} ({len(body)} bytes)")

    meta_out = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": out["generated_at"],
        "source_snapshot_id": snap_id,
        "neighbourhoods_sha256": neighbourhoods_sha,
        "threshold": SPLIT_THRESHOLD,
        "merge_floor": MERGE_FLOOR,
        "merge_soft_ceiling": MERGE_SOFT_CEILING,
        "merge_hard_ceiling": MERGE_HARD_CEILING,
        "tile_count": stats["tile_count"],
        "pre_merge_tile_count": stats["pre_merge_tile_count"],
        "merges": stats["merges"],
        "below_floor_remaining": stats["below_floor_remaining"],
        "total_addresses": stats["total_addresses"],
        "assigned_after": stats["assigned_after"],
        "orphan_count": stats["orphan_count"],
        "orphan_pct": round(stats["orphan_pct"], 6),
        "skipped_empty": stats["skipped_empty"],
        "build_duration_s": round(build_s, 2),
        "total_duration_s": round(time.monotonic() - t_start, 2),
    }
    paths["tiles_meta"].write_text(json.dumps(meta_out, indent=2), encoding="utf-8")
    audit.log(actor="tiles_build", event_type="TILES_REBUILT", payload=meta_out)
    _log("done")
    return meta_out


def run(force: bool = False, dry_run: bool = False) -> dict:
    cfg = _config.load()
    paths = _paths(cfg)
    paths["tiles_dir"].mkdir(parents=True, exist_ok=True)
    paths["hood_dir"].mkdir(parents=True, exist_ok=True)

    hoods_url = cfg.city_neighbourhoods_url
    if not hoods_url:
        return _run_without_layer(cfg, paths, dry_run=dry_run)

    _log(f"HEAD {hoods_url}")
    headers = _head(hoods_url)
    source_last_modified = headers.get("Last-Modified", "")
    content_length = int(headers.get("Content-Length") or 0)
    _log(
        f"source last-modified: {source_last_modified or '(unknown)'} "
        f"size: {content_length} bytes"
    )

    prior_meta: dict | None = None
    if paths["geojson_meta"].exists():
        try:
            prior_meta = json.loads(paths["geojson_meta"].read_text(encoding="utf-8"))
        except Exception:
            prior_meta = None
    unchanged = (
        prior_meta is not None
        and prior_meta.get("source_last_modified") == source_last_modified
        and paths["geojson"].exists()
    )

    if dry_run:
        _log(f"dry-run: would_download={(not unchanged) or force}")
        return {
            "source_url": hoods_url,
            "source_last_modified": source_last_modified,
            "source_bytes": content_length,
            "would_download": (not unchanged) or force,
        }

    _acquire_lock(paths["lock"])
    t_start = time.monotonic()
    try:
        if unchanged and not force:
            _log("source unchanged since last build; reusing existing geojson")
            geojson_sha = (prior_meta or {}).get("sha256") or _sha256_file(paths["geojson"])
        else:
            _log(f"downloading to {paths['geojson']}")
            geojson_sha, bytes_written = _download(hoods_url, paths["geojson"])
            _log(f"downloaded {bytes_written} bytes, sha256 {geojson_sha[:16]}…")
            paths["geojson_meta"].write_text(
                json.dumps(
                    {
                        "source_url": hoods_url,
                        "source_last_modified": source_last_modified,
                        "bytes": bytes_written,
                        "sha256": geojson_sha,
                        "downloaded_at": _iso_now(),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

        _log("loading addresses from source DB")
        snap_id = source_db.latest_snapshot_id()
        points_xy = load_addresses(snap_id)
        _log(f"loaded {len(points_xy)} address points at snapshot {snap_id}")

        geojson_data = json.loads(paths["geojson"].read_text(encoding="utf-8"))
        features = geojson_data.get("features", [])
        _log(f"loaded {len(features)} neighbourhood features")

        t_build = time.monotonic()
        if cfg.city_neighbourhood_name_field or cfg.city_neighbourhood_parent_field:
            _log(
                f"declared layer fields: name={cfg.city_neighbourhood_name_field!r} "
                f"parent={cfg.city_neighbourhood_parent_field!r}"
            )
        tiles, stats = build_tiles(
            features, points_xy, cfg.osm_city_bbox,
            name_field=cfg.city_neighbourhood_name_field,
            parent_field=cfg.city_neighbourhood_parent_field,
        )
        build_s = time.monotonic() - t_build
        _log(
            f"built {stats['tile_count']} tiles in {build_s:.1f}s; "
            f"merges={stats['merges']} (pre-merge={stats['pre_merge_tile_count']}); "
            f"below_floor_remaining={stats['below_floor_remaining']}; "
            f"orphans={stats['orphan_count']} ({stats['orphan_pct']:.2%}); "
            f"skipped_empty={len(stats['skipped_empty'])}"
        )

        return _write_tiles(
            paths, tiles, stats, snap_id,
            neighbourhoods_sha=geojson_sha, build_s=build_s, t_start=t_start,
        )
    finally:
        _release_lock(paths["lock"])


def _cli() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m t2.tiles_build",
        description="Download the city's neighbourhoods (if any), quadtree-split to ≤500 addrs/tile, write data/tiles.json.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-download the neighbourhoods GeoJSON even if unchanged.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Only HEAD-check the source; print what would happen.",
    )
    args = parser.parse_args()
    try:
        run(force=args.force, dry_run=args.dry_run)
        return 0
    except Exception as e:
        _log(f"ERROR: {e!r}")
        return 1


if __name__ == "__main__":
    sys.exit(_cli())
