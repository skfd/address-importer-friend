"""Osmose's view of this city's street names: item 2060 issues on the streets the import writes.

Osmose (osmose.openstreetmap.fr) re-analyses Ontario daily. Item 2060 class 19,
"addr:street not matching a street name around", is what caught Guelph's
mechanically title-cased Mc/O' names (769 addresses, fixed 2026-11-17). Conflation
can't catch that, because it compares street names upper-cased.

Read-only. It needs no OSM extract and doesn't touch tool.db: it reads the
city's `[osm] city_bbox` and the source street vocabulary in `data/streets.json`
(`python -m t2.streets`). It keeps an issue when the element's addr:street
normalizes to a street the source publishes. It does not filter on Osmose's
`usernames`, which is each element's last editor: retagged objects stop
carrying the import account's name.

Each spelling it reports is one of:
  - a casing or name the source and OSM disagree on: add a `[streets]
    overrides` entry, after checking the road name (docs/knowledge/street-overrides.md);
  - a road that is unnamed or misnamed in OSM: fix the road, not the addresses;
  - a genuine dispute: an OSM note asking for a sign check.

Usage (from the engine):
    python -m scripts.osmose_check --city-dir ../guelph-address-import
    python -m scripts.osmose_check --city-dir ../guelph-address-import --json
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import urllib.request
from pathlib import Path

OSMOSE = "https://osmose.openstreetmap.fr/api/0.3/issues"
UA = {"User-Agent": "address-importer-friend osmose_check"}


def fetch_issues(bbox: tuple[float, float, float, float], item: int = 2060) -> list[dict]:
    """Open Osmose issues of `item` inside (min_lat, min_lon, max_lat, max_lon)."""
    s, w, n, e = bbox
    url = f"{OSMOSE}?bbox={w},{s},{e},{n}&item={item}&status=open&limit=10000&full=true"
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        return json.load(r).get("issues", [])


def summarize(issues: list[dict], source_norms: set[str], normalize) -> dict:
    """Group the issues whose addr:street is a source street by class and spelling."""
    by_class: collections.Counter = collections.Counter()
    spellings: dict[tuple[int, str], int] = collections.Counter()
    for issue in issues:
        streets = {(el.get("tags") or {}).get("addr:street") for el in issue.get("elems") or ()}
        streets.discard(None)
        ours = sorted(s for s in streets if normalize(s) in source_norms)
        if not ours:
            continue
        by_class[issue.get("class")] += 1
        for s in ours:
            spellings[(issue.get("class"), s)] += 1
    return {
        "total_2060": len(issues),
        "on_source_streets": sum(by_class.values()),
        "by_class": dict(by_class),
        "spellings": [
            {"class": c, "addr:street": s, "issues": n}
            for (c, s), n in sorted(spellings.items(), key=lambda kv: (-kv[1], kv[0][1]))
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--city-dir", required=True, help="the thin city checkout")
    ap.add_argument("--json", action="store_true", help="print the summary as JSON")
    ap.add_argument("--top", type=int, default=25, help="spellings to list (text mode)")
    args = ap.parse_args(argv)

    os.environ["T2_CITY_DIR"] = str(Path(args.city_dir).resolve())
    from t2 import config as _config, streets  # noqa: E402  (needs T2_CITY_DIR first)
    from t2.conflate import normalize_street  # noqa: E402

    cfg = _config.load()
    vocab = streets.read(cfg)
    if not vocab:
        print(f"No {streets.output_path(cfg)}; run python -m t2.streets first.", file=sys.stderr)
        return 2
    source_norms = {r["street_norm"] for k in ("matched", "missing") for r in vocab.get(k, ())}

    rep = summarize(fetch_issues(cfg.osm_city_bbox), source_norms, normalize_street)
    s, w, n, e = cfg.osm_city_bbox
    rep["map"] = (f"https://osmose.openstreetmap.fr/en/map/#item=2060&zoom=13"
                  f"&lat={(s + n) / 2:.4f}&lon={(w + e) / 2:.4f}")
    if args.json:
        print(json.dumps(rep, indent=1))
        return 0
    print(f"Osmose item 2060 in the city bbox: {rep['total_2060']} open; "
          f"{rep['on_source_streets']} on streets the source publishes "
          f"(by class: {rep['by_class']}).")
    for row in rep["spellings"][: args.top]:
        print(f"  {row['issues']:5}  class {row['class']:<4} {row['addr:street']}")
    print(rep["map"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
