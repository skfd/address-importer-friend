"""Analytical scan: OSM addresses absent from the City source.

For each pure-address node and entrance node in the cached OSM extract,
check whether the City source has a row with the same normalized
(street, housenumber). Source range rows (`lo_num != hi_num`) are
parity-expanded into per-integer keys so an OSM "153 Foo St" matches a
source "151-155 Foo St".

Scope (matches the user's option from /osm/orphans question prompt):

  - type=node, has addr:housenumber
  - not a POI node (no amenity/shop/office/tourism/leisure/craft/healthcare/
    building/disused:*/was:* tags)
  - not an addr:interpolation way endpoint
  - bucket "entrance" if the node carries an `entrance=*` tag, else "pure"

Polygons (building/POI ways and relations) are excluded by design; their
addr is on the building feature and the city source represents the same
parcel as a point inside it.

This is analytical only. The README's "Out of scope" section explicitly
defers reverse-direction deletion of OSM addresses based on source
silence — Toronto's open-data feed has refresh lag, missing
neighborhoods, and retired-address states that are not separable from
"never existed" without further validation.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from . import config as _config, source_db
from .conflate import _is_poi_node, apply_street_override, normalize_street


_CACHE: dict[tuple[float, int], dict] = {}
_BOUNDARY_CACHE: dict[Path, tuple[float, object]] = {}

_RANGE_SIMPLE = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")
# A fractional housenumber like "11 1/2" or "1/2" — `/` is part of the number,
# not a list separator. Mirrors the pattern in multi_addresses.
_FRACTION = re.compile(r"^\s*\d+\s+\d+/\d+\s*$|^\s*\d+/\d+\s*$")


def _load_toronto_boundary(geojson_path: Path):
    """Return a Shapely (Multi)Polygon representing the City of Toronto.

    Built as the union of the 158 neighbourhood polygons in
    `data/neighbourhoods/neighbourhoods-4326.geojson`. Cached by mtime;
    the union takes ~0.5s and shouldn't run per request.
    """
    from shapely.geometry import shape
    from shapely.ops import unary_union

    mtime = geojson_path.stat().st_mtime
    cached = _BOUNDARY_CACHE.get(geojson_path)
    if cached and cached[0] == mtime:
        return cached[1]
    data = json.loads(geojson_path.read_text(encoding="utf-8"))
    polys = [shape(f["geometry"]) for f in data.get("features", [])]
    union = unary_union(polys)
    _BOUNDARY_CACHE[geojson_path] = (mtime, union)
    return union


def _osm_hn_subkeys(hn: str) -> list[str]:
    """Split an OSM addr:housenumber into the individual address tokens.

    A fractional value like `11 1/2` is treated as one token (the `/` is
    part of the number, not a list separator). Otherwise splits on `;`,
    `,`, `/`. For each part, if the part is a simple `N-M` range with
    span between 1 and 100, expands to parity-aware integer tokens
    (matches source_multi conventions). Otherwise returns the part
    uppercased and trimmed.
    """
    if _FRACTION.match(hn or ""):
        return [hn.strip().upper()]
    out: list[str] = []
    for raw in re.split(r"[;,/]", hn):
        part = raw.strip()
        if not part:
            continue
        m = _RANGE_SIMPLE.match(part)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            span = hi - lo
            if 0 < span <= 100:
                step = 2 if (lo % 2) == (hi % 2) else 1
                out.extend(str(n) for n in range(lo, hi + 1, step))
                continue
        out.append(part.upper())
    return out


def _build_source_index(snapshot_id: int) -> dict[tuple[str, str], int]:
    """(street_norm, hn_uppercase) -> count of source rows that emit that key.

    Range rows (lo_num != hi_num, no letter/half suffix) are parity-expanded
    into integer items. Range rows with letter or 1/2 suffixes are indexed
    by their rendered `address_number` only — expanding letters into a
    sequence isn't well-defined.
    """
    idx: dict[tuple[str, str], int] = {}
    conn = source_db.connect_readonly()
    try:
        rows = conn.execute(
            "SELECT lo_num, hi_num, lo_num_suf, hi_num_suf, address_number, "
            "       linear_name_full "
            "FROM addresses WHERE max_snapshot_id = ?",
            (snapshot_id,),
        )
        for r in rows:
            name = apply_street_override(r["linear_name_full"])
            name_norm = normalize_street(name)
            if not name_norm:
                continue
            lo, hi = r["lo_num"], r["hi_num"]
            lo_suf = (r["lo_num_suf"] or "").strip()
            hi_suf = (r["hi_num_suf"] or "").strip()
            rendered = (r["address_number"] or "").strip().upper()
            if lo is None or hi is None or lo == hi or lo_suf or hi_suf:
                if not rendered:
                    continue
                idx[(name_norm, rendered)] = idx.get((name_norm, rendered), 0) + 1
                # Single-number rows with a non-letter/half value: also index
                # by lo_num so an OSM "153" matches a source row whose
                # rendered number is "153" (which is the same string anyway,
                # but doing this explicitly keeps the contract obvious).
                if lo is not None and lo == hi and not lo_suf:
                    key = (name_norm, str(lo))
                    idx[key] = idx.get(key, 0) + 1
                continue
            step = 2 if (lo % 2) == (hi % 2) else 1
            for n in range(lo, hi + 1, step):
                key = (name_norm, str(n))
                idx[key] = idx.get(key, 0) + 1
    finally:
        conn.close()
    return idx


def _classify_osm_nodes(
    json_path: Path, boundary=None
) -> tuple[list[dict], list[dict], int]:
    """Return (pure_address_nodes, entrance_nodes, outside_boundary_count).

    Filters: type=node, has addr:housenumber, not POI, not an
    addr:interpolation way endpoint, and (when `boundary` is provided)
    inside the City of Toronto polygon. Split by presence of `entrance` tag.
    """
    from shapely.geometry import Point
    from shapely.prepared import prep

    data = json.loads(json_path.read_text(encoding="utf-8"))

    interp: set[int] = set()
    for el in data:
        if el.get("type") != "way":
            continue
        if "addr:interpolation" not in (el.get("tags") or {}):
            continue
        for nid in el.get("nodes") or ():
            interp.add(nid)

    prepared = prep(boundary) if boundary is not None else None

    pure: list[dict] = []
    entrance: list[dict] = []
    outside = 0
    for el in data:
        if el.get("type") != "node":
            continue
        tags = el.get("tags") or {}
        if "addr:housenumber" not in tags:
            continue
        if el.get("id") in interp:
            continue
        if _is_poi_node(el):
            continue
        if prepared is not None:
            lat, lon = el.get("lat"), el.get("lon")
            if lat is None or lon is None or not prepared.contains(Point(lon, lat)):
                outside += 1
                continue
        target = entrance if "entrance" in tags else pure
        target.append(el)
    return pure, entrance, outside


def _classify_buildings_no_street(
    json_path: Path, boundary=None
) -> tuple[list[dict], int]:
    """Return (rows, outside_count) for ways/relations that carry
    `addr:housenumber` but no `addr:street`.

    Boundary-clipped on the element's center (Overpass-style). Excludes
    addr:interpolation ways. These elements have no street name to key
    against, so this bucket is a tagging-quality signal — not a
    missing-from-source claim.
    """
    from shapely.geometry import Point
    from shapely.prepared import prep

    data = json.loads(json_path.read_text(encoding="utf-8"))
    prepared = prep(boundary) if boundary is not None else None

    rows: list[dict] = []
    outside = 0
    for el in data:
        t = el.get("type")
        if t not in ("way", "relation"):
            continue
        tags = el.get("tags") or {}
        if "addr:housenumber" not in tags:
            continue
        if (tags.get("addr:street") or "").strip():
            continue
        if "addr:interpolation" in tags:
            continue
        center = el.get("center") or {}
        lat, lon = center.get("lat"), center.get("lon")
        if prepared is not None:
            if lat is None or lon is None or not prepared.contains(Point(lon, lat)):
                outside += 1
                continue
        rows.append({
            "type": t,
            "id": el.get("id"),
            "lat": lat,
            "lon": lon,
            "hn": tags.get("addr:housenumber") or "",
            "building": tags.get("building") or "",
            "name": tags.get("name") or "",
            "addr_place": tags.get("addr:place") or "",
            "addr_hamlet": tags.get("addr:hamlet") or "",
        })
    return rows, outside


def _building_stats(rows: list[dict], table_cap: int = 500) -> dict:
    from collections import Counter

    by_building = Counter(r["building"] or "(no building tag)" for r in rows)
    by_type = Counter(r["type"] for r in rows)
    rows_sorted = sorted(rows, key=lambda r: (_hn_sort_key(r["hn"]), r["hn"] or "", r["id"]))
    return {
        "total": len(rows),
        "by_building": [
            {"label": k, "count": v} for k, v in
            sorted(by_building.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "by_type": dict(by_type),
        "rows": rows_sorted,
        "rows_table": rows_sorted[:table_cap],
        "table_cap": table_cap,
    }


def _node_row(el: dict, source_idx: dict[tuple[str, str], int]) -> dict:
    tags = el.get("tags") or {}
    hn = tags.get("addr:housenumber") or ""
    street = tags.get("addr:street") or ""
    street_norm = normalize_street(street)
    parts = _osm_hn_subkeys(hn) if hn else []
    missing_parts: list[str] = []
    matched_parts: list[str] = []
    if street_norm and parts:
        for p in parts:
            if (street_norm, p) in source_idx:
                matched_parts.append(p)
            else:
                missing_parts.append(p)
    in_source = bool(parts) and not missing_parts and bool(street_norm)
    return {
        "id": el.get("id"),
        "lat": el.get("lat"),
        "lon": el.get("lon"),
        "hn": hn,
        "street": street,
        "street_norm": street_norm,
        "entrance": tags.get("entrance") or "",
        "name": tags.get("name") or "",
        "in_source": in_source,
        "no_street": not bool(street_norm),
        "missing_parts": missing_parts,
        "matched_parts": matched_parts,
    }


def _split_results(
    nodes: list[dict],
    source_idx: dict[tuple[str, str], int],
    table_cap: int = 500,
) -> dict[str, Any]:
    rows = [_node_row(el, source_idx) for el in nodes]
    matched = [r for r in rows if r["in_source"]]
    no_street = [r for r in rows if r["no_street"]]
    missing = [r for r in rows if not r["in_source"] and not r["no_street"]]

    def _sort_key(r: dict) -> tuple:
        return ((r["street_norm"] or ""), _hn_sort_key(r["hn"]), r["hn"] or "")

    missing.sort(key=_sort_key)
    no_street.sort(key=_sort_key)
    return {
        "total": len(rows),
        "matched_count": len(matched),
        "missing_count": len(missing),
        "no_street_count": len(no_street),
        "missing": missing,
        "missing_table": missing[:table_cap],
        "no_street": no_street,
        "no_street_table": no_street[:table_cap],
        "table_cap": table_cap,
    }


def _hn_sort_key(hn: str) -> int:
    m = re.search(r"\d+", hn or "")
    return int(m.group(0)) if m else 0


def collect(snapshot_id: int | None = None) -> dict:
    """Run the reverse sweep, cached by (json_mtime, snapshot_id)."""
    cfg = _config.load()
    json_path = cfg.osm_extract_dir / "toronto-addresses.json"
    if not json_path.exists():
        return {"missing_extract": True, "json_path": str(json_path)}
    if snapshot_id is None:
        snapshot_id = source_db.latest_snapshot_id()
    mtime = json_path.stat().st_mtime
    cached = _CACHE.get((mtime, snapshot_id))
    if cached is not None:
        return cached

    boundary_path = cfg.data_dir / "neighbourhoods" / "neighbourhoods-4326.geojson"
    boundary = _load_toronto_boundary(boundary_path) if boundary_path.exists() else None
    pure, entrance, outside_count = _classify_osm_nodes(json_path, boundary=boundary)
    source_idx = _build_source_index(snapshot_id)
    pure_stats = _split_results(pure, source_idx)
    entrance_stats = _split_results(entrance, source_idx)
    buildings, buildings_outside = _classify_buildings_no_street(json_path, boundary=boundary)
    buildings_stats = _building_stats(buildings)

    snap_info: dict | None = None
    try:
        conn = source_db.connect_readonly()
        try:
            row = conn.execute(
                "SELECT id, downloaded, filename FROM snapshots WHERE id = ?",
                (snapshot_id,),
            ).fetchone()
            if row:
                snap_info = dict(row)
        finally:
            conn.close()
    except Exception:
        snap_info = None

    result = {
        "json_path": str(json_path),
        "json_mtime": mtime,
        "snapshot_id": snapshot_id,
        "snapshot": snap_info,
        "source_index_size": len(source_idx),
        "bbox": list(cfg.osm_toronto_bbox),
        "boundary_applied": boundary is not None,
        "boundary_path": str(boundary_path) if boundary is not None else None,
        "outside_boundary_count": outside_count,
        "buildings_outside_boundary": buildings_outside,
        "pure": pure_stats,
        "entrance": entrance_stats,
        "buildings_no_street": buildings_stats,
    }
    _CACHE[(mtime, snapshot_id)] = result
    return result


def write_csv(dest: Path, payload: dict) -> int:
    """Write the full missing + no-street rows for both buckets to CSV.
    Returns the number of data rows written.
    """
    n = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "bucket", "reason", "osm_type", "osm_id",
            "addr_housenumber", "addr_street", "entrance", "name",
            "building", "lat", "lon", "missing_parts", "matched_parts",
        ])
        for bucket_key in ("pure", "entrance"):
            bucket = payload.get(bucket_key) or {}
            for r in bucket.get("missing", []):
                w.writerow([
                    bucket_key, "missing_in_source", "node", r["id"],
                    r["hn"], r["street"], r["entrance"], r["name"], "",
                    r["lat"], r["lon"],
                    ";".join(r["missing_parts"]),
                    ";".join(r["matched_parts"]),
                ])
                n += 1
            for r in bucket.get("no_street", []):
                w.writerow([
                    bucket_key, "no_addr_street", "node", r["id"],
                    r["hn"], r["street"], r["entrance"], r["name"], "",
                    r["lat"], r["lon"], "", "",
                ])
                n += 1
        buildings = (payload.get("buildings_no_street") or {}).get("rows", [])
        for r in buildings:
            w.writerow([
                "buildings_no_street", "no_addr_street_polygon", r["type"], r["id"],
                r["hn"], "", "", r["name"], r["building"],
                r["lat"], r["lon"], "", "",
            ])
            n += 1
    return n
