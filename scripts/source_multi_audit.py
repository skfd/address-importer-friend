"""Reproduce every figure cited in SOURCE_MULTI_FAQ.md.

Run from repo root: `python scripts/source_multi_audit.py`. Output is a
plain-text report ordered to mirror the FAQ; the table values printed
here should match the FAQ verbatim (snapshot-permitting).
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from t2.conflate import expand_street_name
from t2.source_db import connect_readonly, latest_snapshot_id

OSM_JSON = os.path.join(ROOT, "data", "osm", "toronto-addresses.json")


def header(title: str) -> None:
    print()
    print(f"== {title} ==")


def main() -> int:
    conn = connect_readonly()
    snap = latest_snapshot_id(conn)
    print(f"Snapshot: #{snap}")

    total_active = conn.execute(
        "SELECT COUNT(*) FROM addresses WHERE max_snapshot_id=?", (snap,)
    ).fetchone()[0]

    range_rows = list(conn.execute("""
        SELECT address_full, linear_name_full, municipality_name,
               lo_num, hi_num, lo_num_suf, hi_num_suf, extra
        FROM addresses
        WHERE max_snapshot_id=?
          AND lo_num IS NOT NULL AND hi_num IS NOT NULL
          AND lo_num != hi_num
    """, (snap,)))

    suffix_only = conn.execute("""
        SELECT COUNT(*) FROM addresses
        WHERE max_snapshot_id=? AND lo_num IS NOT NULL AND hi_num IS NOT NULL
          AND lo_num = hi_num
          AND COALESCE(lo_num_suf,'') != COALESCE(hi_num_suf,'')
    """, (snap,)).fetchone()[0]

    reversed_count = conn.execute(
        "SELECT COUNT(*) FROM addresses WHERE max_snapshot_id=? AND lo_num > hi_num",
        (snap,),
    ).fetchone()[0]

    header("Headline counts")
    print(f"  Active rows total                : {total_active:>9,}")
    print(f"  Range rows (lo_num != hi_num)    : {len(range_rows):>9,}  "
          f"({100*len(range_rows)/total_active:.3f}%)")
    print(f"  Suffix-only ranges               : {suffix_only:>9,}")
    print(f"  Reversed (lo_num > hi_num)       : {reversed_count:>9,}")

    header("Class breakdown")
    cls = Counter()
    for r in range_rows:
        cls[json.loads(r["extra"]).get("ADDRESS_CLASS_DESC", "?")] += 1
    for k in ("Land", "Structure", "Structure Entrance", "Land Entrance"):
        print(f"  {k:22s}: {cls.get(k, 0):>6,}")

    header("Form breakdown")
    pure_numeric = lettered = 0
    suffix_pairs: Counter = Counter()
    for r in range_rows:
        ls, hs = (r["lo_num_suf"] or ""), (r["hi_num_suf"] or "")
        if ls or hs:
            lettered += 1
            suffix_pairs[(ls, hs)] += 1
        else:
            pure_numeric += 1
    print(f"  Pure numeric (100-110)           : {pure_numeric:>6,}")
    print(f"  With letter suffix (100A-110A)   : {lettered:>6,}")
    print("  Top suffix pairs (lo_suf, hi_suf):")
    for k, v in suffix_pairs.most_common(10):
        print(f"    {k!r:18s}: {v}")

    header("Span histogram")
    spans = Counter()
    parity = Counter()
    widest: list[tuple[int, str, str]] = []
    for r in range_rows:
        s = r["hi_num"] - r["lo_num"]
        if s == 1: spans["1"] += 1
        elif s == 2: spans["2"] += 1
        elif s <= 10: spans["3-10"] += 1
        elif s <= 100: spans["11-100"] += 1
        else: spans[">100"] += 1
        a, b = r["lo_num"] % 2, r["hi_num"] % 2
        if a == b == 0: parity["both even"] += 1
        elif a == b == 1: parity["both odd"] += 1
        else: parity["mixed"] += 1
        widest.append((s, r["address_full"], r["municipality_name"]))
    for k in ("1", "2", "3-10", "11-100", ">100"):
        print(f"  span {k:>6s}: {spans[k]:>6,}")
    print("  Parity:")
    for k, v in parity.most_common():
        print(f"    {k:11s}: {v:>6,}")
    print("  Top 10 widest:")
    for s, full, muni in sorted(widest, key=lambda t: -t[0])[:10]:
        print(f"    span={s:>4}  {full}  ({muni})")

    header("Per-number sibling coverage")
    # Index per-number rows: (linear_name_full, municipality_name) -> set(int)
    sib_idx: dict[tuple[str, str], set[int]] = defaultdict(set)
    for r in conn.execute("""
        SELECT linear_name_full, municipality_name, lo_num
        FROM addresses
        WHERE max_snapshot_id=? AND lo_num IS NOT NULL AND lo_num = hi_num
    """, (snap,)):
        if r["linear_name_full"]:
            sib_idx[(r["linear_name_full"], r["municipality_name"])].add(r["lo_num"])

    cov = Counter()
    samples: dict[str, list] = {"zero": [], "partial": [], "full": []}
    for r in range_rows:
        lo, hi = r["lo_num"], r["hi_num"]
        step = 2 if lo % 2 == hi % 2 else 1
        expected = list(range(lo, hi + 1, step))
        sibs = sib_idx.get((r["linear_name_full"], r["municipality_name"]), set())
        present = [n for n in expected if n in sibs]
        if not present:
            cov["zero"] += 1
            if len(samples["zero"]) < 5:
                samples["zero"].append(r["address_full"])
        elif len(present) == len(expected):
            cov["full"] += 1
            if len(samples["full"]) < 5:
                samples["full"].append((r["address_full"], len(expected)))
        else:
            cov["partial"] += 1
            if len(samples["partial"]) < 5:
                samples["partial"].append(
                    (r["address_full"], f"{len(present)}/{len(expected)}"))

    print(f"  Zero siblings (range only record): {cov['zero']:>6,}")
    print(f"  Partial coverage                 : {cov['partial']:>6,}")
    print(f"  Full coverage (range redundant)  : {cov['full']:>6,}")

    # Reverse check: per-number rows inside any same-street range
    range_idx: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
    for r in range_rows:
        range_idx[(r["linear_name_full"], r["municipality_name"])].append(
            (r["lo_num"], r["hi_num"]))
    overlap = 0
    for r in conn.execute("""
        SELECT linear_name_full, municipality_name, lo_num
        FROM addresses
        WHERE max_snapshot_id=? AND lo_num IS NOT NULL AND lo_num = hi_num
    """, (snap,)):
        for lo, hi in range_idx.get((r["linear_name_full"], r["municipality_name"]), ()):
            if lo <= r["lo_num"] <= hi:
                overlap += 1
                break
    print(f"  Reverse: per-number rows inside same-street range: {overlap:,}")
    if samples["partial"]:
        print("  Partial samples:")
        for s in samples["partial"]:
            print(f"    {s}")
    if samples["full"]:
        print("  Full-coverage samples:")
        for s in samples["full"]:
            print(f"    {s}")

    header("Street concentration")
    by_street: dict[tuple[str, str], int] = Counter()
    for r in range_rows:
        by_street[(r["linear_name_full"], r["municipality_name"])] += 1
    multi_street = sum(1 for n in by_street.values() if n > 1)
    print(f"  Streets with >1 range row: {multi_street:,}")
    print("  Top 5:")
    for k, n in sorted(by_street.items(), key=lambda kv: -kv[1])[:5]:
        print(f"    {k[0]} ({k[1]}): {n}")

    header("Municipality trap")
    by_full: Counter = Counter()
    for r in range_rows:
        by_full[r["address_full"]] += 1
    cross = 0
    for full, n in by_full.items():
        munis = {r["municipality_name"] for r in range_rows if r["address_full"] == full}
        if len(munis) > 1:
            cross += 1
    print(f"  Range address_full appearing in >1 municipality: {cross}")

    header("ADDRESS_ID_LINK presence")
    have = without = 0
    for r in range_rows:
        if json.loads(r["extra"]).get("ADDRESS_ID_LINK"):
            have += 1
        else:
            without += 1
    print(f"  With ADDRESS_ID_LINK : {have:>6,}")
    print(f"  Without              : {without:>6,}")

    header("Dash characters in address_full")
    dash = Counter()
    for r in range_rows:
        for ch in r["address_full"]:
            if ch in "-‐‑‒–—―":
                dash[ch] += 1
                break
    for ch, n in dash.most_common():
        print(f"  {ch!r}: {n:,}")

    header("OSM coverage of source range numbers")
    if not os.path.exists(OSM_JSON):
        print(f"  (skipped: {OSM_JSON} not found)")
        return 0
    print(f"  Loading {OSM_JSON} ...", file=sys.stderr)
    osm_data = json.loads(open(OSM_JSON, encoding="utf-8").read())
    interp_node_ids = set()
    for el in osm_data:
        tags = el.get("tags") or {}
        if "addr:interpolation" in tags and el.get("type") == "way":
            for nid in el.get("nodes") or ():
                interp_node_ids.add(nid)
    osm_idx: dict[str, set[int]] = defaultdict(set)
    range_re = re.compile(r"^(\d+)\s*[-–]\s*(\d+)$")
    for el in osm_data:
        tags = el.get("tags") or {}
        hn = tags.get("addr:housenumber")
        st = tags.get("addr:street")
        if not hn or not st:
            continue
        if el.get("type") == "node" and el.get("id") in interp_node_ids:
            continue
        nums: set[int] = set()
        for p in re.split(r"[;,]", hn):
            p = p.strip()
            m = range_re.match(p)
            if m:
                a, b = int(m.group(1)), int(m.group(2))
                if a <= b and b - a < 200:
                    nums.update(range(a, b + 1))
                continue
            m2 = re.match(r"^(\d+)", p)
            if m2:
                nums.add(int(m2.group(1)))
        osm_idx[st].update(nums)

    osm_cov = Counter()
    osm_samples: dict[str, list] = {"none": [], "partial": [], "full": []}
    for r in range_rows:
        lo, hi = r["lo_num"], r["hi_num"]
        step = 2 if lo % 2 == hi % 2 else 1
        expected = list(range(lo, hi + 1, step))
        expanded = expand_street_name(r["linear_name_full"]) or r["linear_name_full"]
        nums = osm_idx.get(expanded) or osm_idx.get(r["linear_name_full"]) or set()
        in_osm = [n for n in expected if n in nums]
        if not in_osm:
            osm_cov["none"] += 1
            if len(osm_samples["none"]) < 5:
                osm_samples["none"].append((r["address_full"], expanded))
        elif len(in_osm) == len(expected):
            osm_cov["full"] += 1
            if len(osm_samples["full"]) < 5:
                osm_samples["full"].append(
                    (r["address_full"], expanded, len(expected)))
        else:
            osm_cov["partial"] += 1
            if len(osm_samples["partial"]) < 5:
                osm_samples["partial"].append(
                    (r["address_full"], expanded, f"{len(in_osm)}/{len(expected)}"))

    total = sum(osm_cov.values())
    for k, v in (("none", "None of the numbers in OSM"),
                 ("partial", "Some of the numbers in OSM"),
                 ("full", "All of the numbers in OSM")):
        n = osm_cov[k]
        print(f"  {v:32s}: {n:>6,}  ({100*n/total:.1f}%)")
    for label, key in (("None", "none"), ("Partial", "partial"), ("Full", "full")):
        print(f"  {label} samples:")
        for s in osm_samples[key]:
            print(f"    {s}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
