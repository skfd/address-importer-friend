"""Do any two tracked datasets publish the same addresses?

Research script for future-work/multi-city/10-boundary-clipping.md, same status
as portfolio_survey.py: re-runnable, not a library. Re-run it when datasets are
added to the tracker.

  python scripts/source_overlap_census.py

The question it answers is *source* overlap, which is not the same problem as
the OSM-side bbox bleed the rest of `10` is about. A rectangle around Guelph
contains a lot of Wellington County, but that says nothing about whether the two
feeds publish the same addresses -- and they do not, because a separated city is
outside its county's layer by construction.

Method: every pair whose bboxes intersect, then points of A inside B's bbox,
then shared `number|normalized street` keys, then a coordinate-proximity test.
The last step is what separates a real duplicate from "1 MAIN ST exists in
thirty Ontario towns" -- without it the shared-key column is meaningless.

Street resolution is imported from portfolio_survey rather than reimplemented:
the tracker's canonical `street` column is a change-detection key, not a street
name, and getting this wrong is what produced the peel-region misreading.
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
import tomllib
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from portfolio_survey import (  # noqa: E402
    DATA, DATASETS, KNOWN_SUFFIX_TOKENS, RESOLUTION, STREET_TYPED_THRESHOLD,
    _resolve, _suffix_token,
)
from t2.conflate import normalize_street  # noqa: E402

# Two points this close, sharing a housenumber and street, are the same address.
# Generous on purpose: the real duplicate pairs sit at 0-10 m (90.6% of
# lambton/sarnia is identical to the metre), so the threshold is nowhere near
# any decision boundary.
COLOCATED_M = 150

# Per-dataset municipality field. This is the key finding of the census: where
# two datasets do overlap, this attribute resolves ownership exactly, with no
# boundary polygon needed. Datasets absent here have no overlapping partner.
MUNI_FIELD = {
    "brampton": "CITY", "burlington": "CITY", "bruce": "Municipality",
    "chatham-kent": "COMMUNITY_NAME", "cornwall": "CITY", "durham": "MUNICIPALITY",
    "elgin": "MUNI", "frontenac": "Municipality", "guelph": "PLACE",
    "hamilton": "MUNICIPALITY", "kawartha-lakes": "PLACE", "kingston": "MUNICIPALITY",
    "lambton": "MUNICIPALITY", "muskoka": "Municipality", "niagara-falls": "Municipality",
    "peel-region": "MUNICIPALITY", "sarnia": "CITY", "thunder-bay": "CITY",
    "toronto": "MUNICIPALITY", "wellington": "Municipality", "york": "MUNICIPALITY",
}


def haversine(a: tuple, b: tuple) -> float:
    p = math.pi / 180
    x = (math.sin((b[0] - a[0]) * p / 2) ** 2
         + math.cos(a[0] * p) * math.cos(b[0] * p) * math.sin((b[1] - a[1]) * p / 2) ** 2)
    return 2 * 6371000 * math.asin(math.sqrt(x))


def bbox_overlap(a, b) -> float:
    """Intersection as a share of the smaller box. 0 when they miss."""
    if not a or not b:
        return 0.0
    la, lo = max(a[0], b[0]), max(a[1], b[1])
    ha, ho = min(a[2], b[2]), min(a[3], b[3])
    if ha <= la or ho <= lo:
        return 0.0
    return ((ha - la) * (ho - lo)
            / min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])))


def load() -> dict:
    """Resolved key -> coords, plus the municipality tally, per dataset."""
    out = {}
    for toml_path in sorted(DATASETS.glob("*.toml")):
        cfg = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        slug = cfg.get("slug", toml_path.stem)
        db = DATA / slug / f"{slug}.db"
        if not db.exists():
            print(f"  {slug}: db missing")
            continue
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            snap = conn.execute("SELECT id FROM snapshots WHERE skipped = 0 "
                                "ORDER BY id DESC LIMIT 1").fetchone()["id"]
            rows = conn.execute(
                "SELECT number, street, unit, full, latitude, longitude, props "
                "FROM addresses WHERE max_snapshot_id = ?", (snap,)).fetchall()
        finally:
            conn.close()

        sample = [r["street"] for r in rows[:4000] if (r["street"] or "").strip()]
        typed = (100 * sum(1 for s in sample if _suffix_token(s) in KNOWN_SUFFIX_TOKENS)
                 / len(sample)) if sample else 0.0
        recipe = dict(RESOLUTION.get(slug, {}))
        if slug not in RESOLUTION and typed >= STREET_TYPED_THRESHOLD:
            recipe["use_street"] = True

        mkey = MUNI_FIELD.get(slug)
        pts: dict[str, tuple] = {}
        muni_of: dict[str, str] = {}
        muni = Counter()
        for r in rows:
            props = {}
            if r["props"]:
                try:
                    props = json.loads(r["props"])
                except (ValueError, TypeError):
                    props = {}
            if mkey:
                muni[props.get(mkey)] += 1
            n, st = _resolve(r, props, recipe)
            ns = normalize_street(st)
            if n and ns and r["latitude"] is not None:
                pts[f"{n}|{ns}"] = (r["latitude"], r["longitude"])
                if mkey:
                    muni_of[f"{n}|{ns}"] = props.get(mkey)
        lats = [p[0] for p in pts.values()]
        lons = [p[1] for p in pts.values()]
        out[slug] = {
            "provider": cfg.get("provider", ""),
            "rows": len(rows), "pts": pts, "muni_of": muni_of,
            "muni_field": mkey, "muni": muni,
            "bbox": (min(lats), min(lons), max(lats), max(lons)) if lats else None,
        }
        print(f"  {slug:<21}{len(rows):>8,} rows  {len(pts):>8,} keys"
              f"{'  muni=' + mkey if mkey else ''}")
    return out


def census(d: dict) -> list[dict]:
    slugs = sorted(d)
    found = []
    for i, sa in enumerate(slugs):
        for sb in slugs[i + 1:]:
            A, B = d[sa], d[sb]
            if bbox_overlap(A["bbox"], B["bbox"]) < 0.001:
                continue
            shared = set(A["pts"]) & set(B["pts"])
            if not shared:
                continue
            coloc = [k for k in shared
                     if haversine(A["pts"][k], B["pts"][k]) < COLOCATED_M]
            if not coloc:
                continue
            # Where both datasets name a municipality for the duplicate, report
            # it: it is what decides ownership, and it is also how a genuine
            # containment (lambton/sarnia) is told apart from a boundary strip.
            labels = Counter(
                (A["muni_of"].get(k), B["muni_of"].get(k)) for k in coloc
            ).most_common(3)
            found.append({"a": sa, "b": sb, "shared": len(shared),
                          "coloc": len(coloc), "labels": labels,
                          "a_keys": len(A["pts"]), "b_keys": len(B["pts"])})
    return sorted(found, key=lambda f: -f["coloc"])


if __name__ == "__main__":
    print("loading datasets:")
    d = load()
    print(f"\n{len(d)} datasets, {len(d)*(len(d)-1)//2} pairs\n")

    print(f"pairs sharing colocated addresses (< {COLOCATED_M} m):")
    print(f"{'A':<20}{'B':<20}{'sharedKey':>10}{'colocated':>11}"
          f"{'  share of smaller layer':>10}")
    for f in census(d):
        smaller = min(f["a_keys"], f["b_keys"])
        print(f"{f['a']:<20}{f['b']:<20}{f['shared']:>10,}{f['coloc']:>11,}"
              f"{100*f['coloc']/smaller:>16.1f}%")
        for (ma, mb), n in f["labels"]:
            print(f"      {n:>7,}  {f['a']}={ma!r}  {f['b']}={mb!r}")

    print("\nReading: a pair is real duplicate coverage only when the two")
    print("municipality labels agree and the share is large. Everything in the")
    print("tens is a boundary strip. As of 2026-08-13 exactly two pairs are")
    print("real: lambton/sarnia and peel-region/brampton.")
