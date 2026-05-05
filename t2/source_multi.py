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

from . import source_db


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


def collect(snapshot_id: int | None = None) -> dict:
    if snapshot_id is None:
        snapshot_id = source_db.latest_snapshot_id()
    cached = _CACHE.get(snapshot_id)
    if cached is not None:
        return cached

    conn = source_db.connect_readonly()
    try:
        total_active = conn.execute(
            "SELECT COUNT(*) FROM addresses WHERE max_snapshot_id=?",
            (snapshot_id,),
        ).fetchone()[0]

        range_rows = conn.execute(
            "SELECT lo_num, hi_num, lo_num_suf, hi_num_suf, address_full,"
            "       linear_name_full, municipality_name "
            "FROM addresses "
            "WHERE max_snapshot_id=? AND lo_num IS NOT NULL AND hi_num IS NOT NULL "
            "  AND lo_num != hi_num "
            "ORDER BY (hi_num - lo_num) DESC, address_full",
            (snapshot_id,),
        ).fetchall()
        ranges = [dict(r) for r in range_rows]

        bucket_counts = [{"label": label, "count": 0} for label, _ in _SPAN_BUCKETS]
        parity_counts = {"odd": 0, "even": 0, "mixed": 0}
        street_counts: dict[str, int] = {}
        mixed_examples: list[dict] = []

        for r in ranges:
            span = r["hi_num"] - r["lo_num"]
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
                    mixed_examples.append({**r, "span": span})
            street = r["linear_name_full"] or "(no street)"
            street_counts[street] = street_counts.get(street, 0) + 1

        biggest = [{**r, "span": r["hi_num"] - r["lo_num"]} for r in ranges[:15]]
        top_streets = sorted(street_counts.items(), key=lambda kv: -kv[1])[:12]
        top_streets = [{"street": s, "count": c} for s, c in top_streets]

        half_rows = conn.execute(
            "SELECT address_full, lo_num, lo_num_suf,"
            "       linear_name_full, municipality_name "
            "FROM addresses "
            "WHERE max_snapshot_id=? AND lo_num_suf='1/2' "
            "ORDER BY linear_name_full, lo_num",
            (snapshot_id,),
        ).fetchall()
        halves = [dict(h) for h in half_rows]

        snap_row = conn.execute(
            "SELECT id, downloaded, row_count, filename FROM snapshots WHERE id=?",
            (snapshot_id,),
        ).fetchone()
    finally:
        conn.close()

    result = {
        "snapshot_id": snapshot_id,
        "snapshot_downloaded": snap_row["downloaded"] if snap_row else None,
        "snapshot_filename": snap_row["filename"] if snap_row else None,
        "total_active": total_active,
        "ranges_total": len(ranges),
        "halves_total": len(halves),
        "span_buckets": bucket_counts,
        "parity_counts": parity_counts,
        "top_streets": top_streets,
        "biggest_spans": biggest,
        "mixed_parity_examples": mixed_examples,
        "halves": halves,
    }
    _CACHE[snapshot_id] = result
    return result
