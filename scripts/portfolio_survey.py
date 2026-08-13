"""Tier 1 portfolio survey: profile all 42 tracked datasets, offline.

Research script for future-work/multi-city/08-portfolio-survey.md. Throwaway --
it answers "which city is worth working on next" once, and its findings feed the
accordeur onboarding probe rather than becoming it.

  python scripts/portfolio_survey.py --pbf <ontario.osm.pbf> --out <dir>

One pass over the source DBs, then ONE pass over the Ontario PBF bucketing
addr:housenumber features into all 42 city extents at once. Not once per city --
the Toronto single-bbox filter alone takes ~375s.

Street resolution comes first, because the tracker's canonical `street` column
is a change-detection key, not a street name: 18 of 42 datasets store the name
component only ("Armitage"), with type and direction left in the props blob
under per-city key names. See RESOLUTION below.

Provenance by editor/changeset is deliberately absent: the Geofabrik public
extract zeroes uid/user/changeset. Only the last-touch year survives, which is
most of the import signal anyway (Guelph: 44,338 elements touched in 2025).
Editor tallies need Overpass `out meta`, per city, and belong in Tier 2 against
the handful of cities this pass flags.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
import tomllib
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from t2.conflate import DIRS, STREET_SUFFIXES, normalize_street  # noqa: E402

TRACKER = Path("C:/Users/kk/Code/ontario-address-changes")
DATASETS = TRACKER / "datasets"
DATA = TRACKER / "data"

KNOWN_SUFFIX_TOKENS = set(STREET_SUFFIXES) | set(STREET_SUFFIXES.values())
DIR_TOKENS = set(DIRS) | set(DIRS.values())

# Share of `street` values ending in a known type token above which the column
# is treated as a real street name. The measured distribution is strongly
# bimodal (Toronto 99%, Guelph 100% vs Durham 0%, Brampton 1%), so anything
# from ~40 to ~85 separates the two groups identically.
STREET_TYPED_THRESHOLD = 80.0

# Leading house number in a combined address string: "204", "61A", "1133-B".
NUMBER_RE = re.compile(r"^(\d+[A-Za-z]?(?:-\d+[A-Za-z]?)?)$")

# Props keys naming the municipality; a few sources glue it onto the combined
# address field ("3 ALLISON LINE BLENHEIM TOWN") and it must come back off.
MUNI_KEYS = (
    "MUNICIPALITY", "Municipality", "TOWN", "PLACE", "PlaceName",
    "COMMUNITY", "Community", "MUNICIPALITY_NAME", "UrbanCentre",
    "COMMUNITY_NAME", "COMMUNITY_TYPE",
)

# Per-dataset street resolution, for the cities where neither `full` nor
# `street` yields a usable name. Measured 2026-08-10; everything not listed
# resolves from `full` when populated, else from `street`.
RESOLUTION: dict[str, dict] = {
    # No canonical `full`, but props carries a complete street name.
    "hamilton": {"street_prop": "FULL_STREET_NAME"},
    "wellington": {"street_prop": "WC_FullNam"},
    # No canonical `full`; reassemble name + type + direction from props.
    "durham": {"name": "ROAD_NAME", "type": "ROAD_TYPE", "dir": "ROAD_DIR"},
    "niagara-falls": {"name": "StreetName", "type": "StreetType", "dir": "StreetDir"},
    # Corrected 2026-08-13. The first run recorded peel-region as `typeless` on
    # the strength of a 4% figure that was measured against the canonical
    # `street` column -- which maps to STREETNAME, the name component only.
    # STREETTYPE itself is populated for 98.8% of rows (Mississauga 98.2%,
    # Brampton 99.8%, Caledon 100%), so this is the same name+type split as
    # durham and niagara-falls above, not a source defect.
    "peel-region": {"name": "STREETNAME", "type": "STREETTYPE",
                    "dir": "STREETDIRECTION"},
}


def _split_full(full: str) -> tuple[str, str]:
    """Split a combined address into (number, street).

    Everything after the first comma is locality, not street: kawartha-lakes
    publishes "903 Cottingham Road, Emily Twp, Kawartha Lakes".
    """
    full = full.split(",")[0].strip()
    parts = full.split()
    if parts and NUMBER_RE.match(parts[0]):
        return parts[0], " ".join(parts[1:])
    return "", full


def _strip_muni(street: str, props: dict) -> str:
    """Drop a municipality name glued onto the end of a combined address.

    Iterative because some sources append both parts of a split name --
    chatham-kent's COMMUNITY_NAME "BLENHEIM" plus COMMUNITY_TYPE "TOWN" arrive
    as "3 ALLISON LINE BLENHEIM TOWN" and come off one token-group at a time.
    """
    for _ in range(3):
        for k in MUNI_KEYS:
            v = props.get(k)
            if not v or not isinstance(v, str):
                continue
            if street.upper().endswith(" " + v.upper()):
                street = street[: -(len(v) + 1)].strip()
                break
        else:
            break
    return street


def _resolve(row: sqlite3.Row, props: dict, recipe: dict) -> tuple[str, str]:
    """Return (number, street) for one source row, per the dataset's recipe."""
    number = (row["number"] or "").strip().upper()
    full = (row["full"] or "").strip()
    street = ""

    if recipe.get("use_street"):
        # `street` already carries its type -- prefer it over `full`, which in
        # several sources appends the unit (guelph) or the locality (kawartha).
        street = (row["street"] or "").strip()
    elif "street_prop" in recipe:
        street = str(props.get(recipe["street_prop"]) or "").strip()
    elif "name" in recipe:
        bits = [str(props.get(recipe["name"]) or "").strip(),
                str(props.get(recipe["type"]) or "").strip(),
                str(props.get(recipe["dir"]) or "").strip()]
        street = " ".join(b for b in bits if b)

    if not street and full:
        num_from_full, street = _split_full(full)
        street = _strip_muni(street, props)
    if not number and full:
        number = _split_full(full)[0].upper()
    if not street:
        street = (row["street"] or "").strip()

    return number, street


def _suffix_token(street: str) -> str:
    parts = street.upper().replace(".", "").split()
    while parts and parts[-1] in DIR_TOKENS:
        parts.pop()
    return parts[-1] if parts else ""


def _cell(lat: float, lon: float) -> tuple[int, int]:
    """~500 m grid cell. 0.0045 deg lat ~= 500 m; lon scaled by latitude."""
    return (int(lat / 0.0045), int(lon / (0.0045 / math.cos(math.radians(lat)))))


def profile_sources() -> list[dict]:
    """Read every city DB, resolve street names, return per-city profiles."""
    out = []
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
            snap = conn.execute(
                "SELECT id, downloaded FROM snapshots WHERE skipped = 0 "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
            rows = conn.execute(
                "SELECT number, street, unit, full, latitude, longitude, props "
                "FROM addresses WHERE max_snapshot_id = ?",
                (snap["id"],),
            ).fetchall()
        finally:
            conn.close()

        # Which column actually carries a street name is a property of the
        # data, not something to hardcode: measure how often `street` ends in
        # a known type token, and fall back to `full`/props only when it
        # mostly doesn't.
        sample = [r["street"] for r in rows[:4000] if (r["street"] or "").strip()]
        typed_pct = (
            100 * sum(1 for s in sample if _suffix_token(s) in KNOWN_SUFFIX_TOKENS)
            / len(sample)
        ) if sample else 0.0
        recipe = dict(RESOLUTION.get(slug, {}))
        if slug not in RESOLUTION and typed_pct >= STREET_TYPED_THRESHOLD:
            recipe["use_street"] = True

        keys: dict[str, tuple[float, float]] = {}
        unknown: Counter[str] = Counter()
        units = unresolved = 0
        lats: list[float] = []
        lons: list[float] = []

        for r in rows:
            props = {}
            if r["props"]:
                try:
                    props = json.loads(r["props"])
                except (ValueError, TypeError):
                    props = {}
            number, street = _resolve(r, props, recipe)
            if not street or not number:
                unresolved += 1
            else:
                norm = normalize_street(street)
                if norm:
                    keys[f"{number}|{norm}"] = (r["latitude"], r["longitude"])
                    tok = _suffix_token(street)
                    if tok and tok not in KNOWN_SUFFIX_TOKENS:
                        unknown[tok] += 1
            if (r["unit"] or "").strip():
                units += 1
            if r["latitude"] is not None and r["longitude"] is not None:
                lats.append(r["latitude"])
                lons.append(r["longitude"])

        total = len(rows)
        out.append({
            "slug": slug,
            "provider": cfg.get("provider", ""),
            "license_name": cfg.get("license_name", ""),
            "osm_compatible": cfg.get("osm_compatible", ""),
            "snapshot_id": snap["id"],
            "snapshot_date": (snap["downloaded"] or "")[:10],
            "active_rows": total,
            "distinct": len(keys),
            "unresolved_rows": unresolved,
            "unit_pct": round(100 * units / total, 1) if total else 0.0,
            "street_typed_pct": round(typed_pct, 1),
            "street_source": (
                "street" if recipe.get("use_street")
                else "props" if ("street_prop" in recipe or "name" in recipe)
                else "typeless" if recipe.get("typeless")
                else "full"
            ),
            "bbox": [min(lats), min(lons), max(lats), max(lons)] if lats else None,
            "unknown_suffixes": unknown.most_common(10),
            "unknown_suffix_rows": sum(unknown.values()),
            "typeless": bool(recipe.get("typeless")),
            "_keys": keys,
        })
        print(f"  {slug:<21}{total:>8,} rows  {len(keys):>8,} distinct  "
              f"{unresolved:>7,} unresolved  {sum(unknown.values()):>7,} odd-suffix")
    return out


def scan_osm(pbf: Path, cities: list[dict]) -> dict[str, dict]:
    """One PBF pass, bucketing addr:housenumber features into every city bbox."""
    import osmium

    boxes = [(c["slug"], *c["bbox"]) for c in cities if c["bbox"]]
    acc: dict[str, dict] = {
        s: {"keys": set(), "nodes": 0, "ways": 0, "years": Counter()} for s, *_ in boxes
    }

    def bucket(lat, lon, tags, kind, year):
        hn = (tags.get("addr:housenumber") or "").strip().upper()
        st = normalize_street((tags.get("addr:street") or "").strip())
        for slug, mnla, mnlo, mxla, mxlo in boxes:
            if mnla <= lat <= mxla and mnlo <= lon <= mxlo:
                a = acc[slug]
                a[kind] += 1
                a["years"][year] += 1
                if hn and st:
                    a["keys"].add(f"{hn}|{st}")

    class Handler(osmium.SimpleHandler):
        def node(self, n):
            if "addr:housenumber" not in n.tags or not n.location.valid():
                return
            bucket(n.location.lat, n.location.lon,
                   {t.k: t.v for t in n.tags}, "nodes", n.timestamp.year)

        def way(self, w):
            if "addr:housenumber" not in w.tags or "addr:interpolation" in w.tags:
                return
            lats = [wn.location.lat for wn in w.nodes if wn.location.valid()]
            lons = [wn.location.lon for wn in w.nodes if wn.location.valid()]
            if not lats:
                return
            bucket((min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2,
                   {t.k: t.v for t in w.tags}, "ways", w.timestamp.year)

    print(f"  scanning {pbf.name} against {len(boxes)} city extents ...")
    Handler().apply_file(str(pbf), locations=True)
    return acc


def compare(cities: list[dict], osm: dict[str, dict]) -> list[dict]:
    results = []
    for c in cities:
        o = osm.get(c["slug"])
        if o is None:
            continue
        src_keys = c["_keys"]
        missing = [k for k in src_keys if k not in o["keys"]]
        osm_only = len(o["keys"] - set(src_keys))

        # Does the street exist in OSM at all, just without this housenumber?
        # Separates "OSM genuinely lacks these addresses" from "the normalizer
        # failed to match a street that is present" -- the failure mode that
        # would otherwise inflate every gap in this table.
        osm_streets = {k.split("|", 1)[1] for k in o["keys"]}
        street_known = sum(1 for k in missing if k.split("|", 1)[1] in osm_streets)

        cells = Counter(_cell(*src_keys[k]) for k in missing if src_keys[k][0] is not None)
        top20 = sum(n for _, n in cells.most_common(20))
        osm_total = o["nodes"] + o["ways"]

        results.append({
            **{k: v for k, v in c.items() if k != "_keys"},
            "osm_elements": osm_total,
            "osm_nodes": o["nodes"],
            "osm_ways": o["ways"],
            "osm_way_pct": round(100 * o["ways"] / osm_total, 1) if osm_total else 0.0,
            "osm_distinct": len(o["keys"]),
            "missing": len(missing),
            "missing_pct": round(100 * len(missing) / len(src_keys), 1) if src_keys else 0.0,
            "osm_only": osm_only,
            "missing_street_known": street_known,
            "missing_street_known_pct": round(100 * street_known / len(missing), 1)
            if missing else 0.0,
            "osm_street_count": len(osm_streets),
            "missing_cells": len(cells),
            "top20_cell_share": round(100 * top20 / len(missing), 1) if missing else 0.0,
            "osm_years": dict(sorted(o["years"].most_common(6))),
            "peak_year": o["years"].most_common(1)[0] if o["years"] else None,
        })
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pbf", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    print("source pass:")
    cities = profile_sources()
    print("\nosm pass:")
    osm = scan_osm(args.pbf, cities)
    print("\ncomparing:")
    results = compare(cities, osm)
    (args.out / "survey.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"wrote {args.out / 'survey.json'} ({len(results)} datasets)")
