"""Record the building-based judge's verdicts on /units/shapes.

Dry run by default: prints what it would decide and why. `--apply` saves the
verdicts (note `auto: ...`) and clears earlier auto verdicts the judge no
longer stands behind. A verdict a person made is never touched, and neither
is a group this import has uploaded. See `t2/unit_autojudge.py`.

Usage:
    python -u -m scripts.autojudge_unit_shapes [--apply] [--rebuild-buildings]
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone

from t2 import config as _config, osm_buildings, unit_autojudge, unit_shapes, unit_verdicts, units


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="save the verdicts (default: dry run)")
    ap.add_argument("--rebuild-buildings", action="store_true", help="re-read outlines from the PBF")
    args = ap.parse_args()

    cfg = _config.load()
    buildings = osm_buildings.load(cfg, rebuild=args.rebuild_buildings)
    stamp = datetime.fromtimestamp(
        osm_buildings.cache_path(cfg).stat().st_mtime, timezone.utc
    ).date().isoformat()
    index = osm_buildings.Index(buildings)
    print(f"{len(buildings)} building outlines, read {stamp}")

    tally: Counter = Counter()
    for r in unit_shapes.collect()["rows"]:
        saved = r["saved"]
        by_person = saved is not None and not (saved.get("note") or "").startswith(unit_autojudge.AUTO)
        rule_shape = units.resolve(r["verdict"], r["rule_reason"], r["units"])[0]
        verdict, note = unit_autojudge.judge(rule_shape, r.get("points") or [], r.get("spacing_m"), index.at)
        addr = f"{r['number']} {r['street']}"
        if r["frozen"] or by_person:
            if verdict:
                tally["left: decided by a person or uploaded"] += 1
                print(f"  keep    {addr:32} {rule_shape:>10} (judge would say {verdict})")
            continue
        if verdict is None:
            if saved is not None:
                tally["auto verdict withdrawn"] += 1
                print(f"  clear   {addr:32} {rule_shape:>10} -- {note}")
                if args.apply:
                    unit_verdicts.clear(r["key"])
            continue
        tally[f"{rule_shape} -> {verdict}"] += 1
        print(f"  {verdict:7} {addr:32} {rule_shape:>10} -- {note[len(unit_autojudge.AUTO):].strip()}")
        if args.apply:
            unit_verdicts.save(r["key"], verdict, r["unit_hash"], f"{note} [OSM buildings of {stamp}]")

    print()
    for k, v in sorted(tally.items()):
        print(f"{v:5}  {k}")
    if not args.apply:
        print("dry run; --apply to save")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
