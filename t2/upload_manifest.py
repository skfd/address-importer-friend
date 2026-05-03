"""Public traceability dump: per uploaded candidate, emit
(address_point_id, address_full, osm_node_id, changeset_id) as CSV.

Used by static_export and static_export_all so the OSM wiki page can link
to a public file listing every node we created and the changeset that
produced it. Per-tile files plus a cumulative file across all tiles.
"""
from __future__ import annotations

import csv
from pathlib import Path

from . import db as _db


HEADER = ("address_point_id", "address_full", "osm_node_id", "changeset_id")

Row = tuple[int, str, int, int]


def fetch_for_run(run_id: int) -> list[Row]:
    conn = _db.connect()
    try:
        rows = conn.execute(
            """
            SELECT c.candidate_id, c.address_full, c.osm_node_id, r.changeset_id
            FROM candidates c
            JOIN runs r ON r.run_id = c.run_id
            WHERE c.run_id = ?
              AND c.stage = 'UPLOADED'
              AND c.osm_node_id IS NOT NULL
              AND r.changeset_id IS NOT NULL
            ORDER BY c.candidate_id
            """,
            (run_id,),
        ).fetchall()
    finally:
        conn.close()
    return [
        (int(r["candidate_id"]), r["address_full"] or "",
         int(r["osm_node_id"]), int(r["changeset_id"]))
        for r in rows
    ]


def write_csv(path: Path, rows: list[Row]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows)
