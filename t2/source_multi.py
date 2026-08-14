"""Statistics about source addresses that pack list-like values.

Source addresses are one-row-per-point, so they don't use ;,/ separators
the way OSM `addr:housenumber` does. The list-like shapes the source
emits are:
  - Range addresses: lo_num != hi_num (rendered as "N-M" in address_number)
  - Half-numbers:    lo_num_suf == "1/2" (rendered as "N 1/2")

Cached by snapshot_id since the data only changes when the source DB
ingests a new snapshot. Entry point: collect() -> dict, used by the
/source/multi page.
"""
from __future__ import annotations

import json
import re

from . import config as _config, source_db
from .conflate import _is_poi_node, normalize_street


_CACHE: dict[int, dict] = {}

# (label, predicate). One pass over rows assigns each span to the first
# matching bucket, so order matters.
_SPAN_BUCKETS: list[tuple[str, callable]] = [
    ("1 (adjacent)",     lambda s: s == 1),
    ("2 (duplex pair)",  lambda s: s == 2),
    ("3-9",              lambda s: 3 <= s <= 9),
    ("10-49",            lambda s: 10 <= s <= 49),
    ("50-99",            lambda s: 50 <= s <= 99),
    ("≥100",             lambda s: s >= 100),
]


def _build_osm_housenumber_index(cfg) -> dict[tuple[str, str], tuple[str, int]]:
    """Map (normalized_street, housenumber_str) -> (osm_type, osm_id).

    Mirrors the filtering rules in t2.streets / t2.conflate: skip nodes that
    are addr:interpolation members or POI nodes. Multi-value housenumbers
    (split by ; , /) each register a separate key. First element to claim a
    key wins, so callers get a stable representative for the link.
    """
    json_path = cfg.osm_extract_json
    if not json_path.exists():
        return {}
    elements = json.loads(json_path.read_text(encoding="utf-8"))

    interp_node_ids: set[int] = set()
    for el in elements:
        if el.get("type") != "way":
            continue
        if "addr:interpolation" not in (el.get("tags") or {}):
            continue
        for nid in el.get("nodes") or ():
            interp_node_ids.add(nid)

    idx: dict[tuple[str, str], tuple[str, int]] = {}
    for el in elements:
        tags = el.get("tags") or {}
        hn_raw = tags.get("addr:housenumber")
        if not hn_raw:
            continue
        if el.get("type") == "node":
            if el.get("id") in interp_node_ids:
                continue
            if _is_poi_node(el):
                continue
        street_raw = (tags.get("addr:street") or "").strip()
        if not street_raw:
            continue
        norm = normalize_street(street_raw)
        if not norm:
            continue
        for part in re.split(r"[;,/]", hn_raw):
            part = part.strip()
            if not part:
                continue
            key = (norm, part)
            idx.setdefault(key, (el["type"], el["id"]))
    return idx


def _range_items(lo: int, hi: int, lo_p: int, hi_p: int) -> list[int]:
    if lo_p == hi_p:
        return list(range(lo, hi + 1, 2))
    return list(range(lo, hi + 1))


def collect(snapshot_id: int | None = None) -> dict:
    if snapshot_id is None:
        snapshot_id = source_db.latest_snapshot_id()
    cached = _CACHE.get(snapshot_id)
    if cached is not None:
        return cached

    cfg = _config.load()
    osm_idx = _build_osm_housenumber_index(cfg)

    conn = source_db.connect_readonly()
    try:
        total_active = conn.execute(
            "SELECT COUNT(*) FROM addresses WHERE max_snapshot_id=?",
            (snapshot_id,),
        ).fetchone()[0]

        lo_expr = source_db.expr("lo_num", "")
        hi_expr = source_db.expr("hi_num", "")
        range_rows = conn.execute(
            f"SELECT {lo_expr} AS lo_num, "
            f"       {hi_expr} AS hi_num, "
            f"       {source_db.expr('lo_num_suf', '')} AS lo_num_suf, "
            f"       {source_db.expr('hi_num_suf', '')} AS hi_num_suf, "
            f"       {source_db.expr('full', '')} AS address_full, "
            f"       {source_db.expr('street', '')} AS linear_name_full, "
            f"       {source_db.expr('municipality', '')} AS municipality_name "
            "FROM addresses "
            f"WHERE max_snapshot_id=? AND {lo_expr} IS NOT NULL "
            f"  AND {hi_expr} IS NOT NULL "
            f"  AND {lo_expr} != {hi_expr} "
            f"ORDER BY ({hi_expr} - {lo_expr}) DESC, {source_db.expr('full', '')}",
            (snapshot_id,),
        ).fetchall()
        ranges = [dict(r) for r in range_rows]

        bucket_counts = [{"label": label, "count": 0} for label, _ in _SPAN_BUCKETS]
        parity_counts = {"odd": 0, "even": 0, "mixed": 0}
        street_counts: dict[str, int] = {}
        mixed_examples: list[dict] = []

        for r in ranges:
            span = r["hi_num"] - r["lo_num"]
            r["span"] = span
            for (_, pred), bucket in zip(_SPAN_BUCKETS, bucket_counts):
                if pred(span):
                    bucket["count"] += 1
                    break
            lo_p, hi_p = r["lo_num"] % 2, r["hi_num"] % 2
            if lo_p == 0 and hi_p == 0:
                parity_counts["even"] += 1
            elif lo_p == 1 and hi_p == 1:
                parity_counts["odd"] += 1
            else:
                parity_counts["mixed"] += 1
                if len(mixed_examples) < 12:
                    mixed_examples.append({**r})
            street = r["linear_name_full"] or "(no street)"
            street_counts[street] = street_counts.get(street, 0) + 1

            items = _range_items(r["lo_num"], r["hi_num"], lo_p, hi_p)
            r["items_total"] = len(items)
            norm_street = normalize_street(r["linear_name_full"])
            osm_hits = 0
            missing: list[int] = []
            osm_link_target: tuple[str, int] | None = None
            if norm_street:
                for n in items:
                    hit = osm_idx.get((norm_street, str(n)))
                    if hit is not None:
                        osm_hits += 1
                        if osm_link_target is None:
                            osm_link_target = hit
                    else:
                        missing.append(n)
            else:
                missing = list(items)
            r["osm_hits"] = osm_hits
            r["missing_numbers"] = missing
            r["missing_count"] = len(missing)
            if osm_link_target is not None:
                kind, oid = osm_link_target
                r["osm_url"] = f"https://www.openstreetmap.org/{kind}/{oid}"
            else:
                r["osm_url"] = None

        top_streets = sorted(street_counts.items(), key=lambda kv: -kv[1])[:12]
        top_streets = [{"street": s, "count": c} for s, c in top_streets]

        half_rows = conn.execute(
            f"SELECT {source_db.expr('full', '')} AS address_full, "
            f"       {source_db.expr('lo_num', '')} AS lo_num, "
            f"       {source_db.expr('lo_num_suf', '')} AS lo_num_suf, "
            f"       {source_db.expr('street', '')} AS linear_name_full, "
            f"       {source_db.expr('municipality', '')} AS municipality_name "
            "FROM addresses "
            f"WHERE max_snapshot_id=? AND {source_db.expr('lo_num_suf', '')}='1/2' "
            f"ORDER BY {source_db.expr('street', '')}, {source_db.expr('lo_num', '')}",
            (snapshot_id,),
        ).fetchall()
        halves = [dict(h) for h in half_rows]

        snap_row = conn.execute(
            "SELECT id, downloaded, row_count, filename FROM snapshots WHERE id=?",
            (snapshot_id,),
        ).fetchone()
    finally:
        conn.close()

    ranges_with_osm_hit = sum(1 for r in ranges if r["osm_hits"] > 0)

    result = {
        "snapshot_id": snapshot_id,
        "snapshot_downloaded": snap_row["downloaded"] if snap_row else None,
        "snapshot_filename": snap_row["filename"] if snap_row else None,
        "total_active": total_active,
        "ranges_total": len(ranges),
        "ranges_with_osm_hit": ranges_with_osm_hit,
        "halves_total": len(halves),
        "span_buckets": bucket_counts,
        "parity_counts": parity_counts,
        "top_streets": top_streets,
        "ranges": ranges,
        "mixed_parity_examples": mixed_examples,
        "halves": halves,
    }
    _CACHE[snapshot_id] = result
    return result
