"""Entry-state probe for a candidate city (multi-city `05`, Tier 2).

The Geofabrik public extract zeroes `uid`/`user`/`changeset`, so provenance
cannot come from the PBF the portfolio survey uses. This fills that gap with a
handful of small Overpass `out meta` samples plus changeset-API lookups.

Deliberately small and few: the public Overpass is volunteer-run, and `08`'s
rule is "do not issue full-city queries against it". Three ~0.012 deg boxes
answer the provenance question that 42 full-city queries would.

    python scripts/entry_state_probe.py hamilton [--out DIR]

Research script, kept for re-runs, not a library -- same standing as
`portfolio_survey.py`.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

UA = "toronto-2-address-import/entry-state-probe (toronto@comentality.com)"
OVERPASS = "https://overpass-api.de/api/interpreter"
OSM_API = "https://api.openstreetmap.org/api/0.6"

# Sample boxes are chosen by hand per city: pick built-up areas in distinct
# former municipalities, because amalgamated cities carry different histories
# per component (Hamilton's downtown reads nothing like Dundas).
CITIES = {
    "hamilton": {
        "bbox": (43.05106, -80.24389, 43.46763, -79.625),
        "samples": {
            "downtown": (43.250, -79.876, 43.262, -79.864),
            "dundas": (43.264, -79.956, 43.276, -79.944),
            "stoney-creek": (43.214, -79.766, 43.226, -79.754),
        },
        "wiki": ["Canada:Ontario:Hamilton", "Hamilton, Ontario"],
    },
    # Wellington boxes are untested approximations for the 2025-spike question
    # (TODO #3) -- sanity-check the element counts before trusting a run.
    "wellington": {
        "bbox": (43.51, -80.60, 44.03, -79.98),
        "samples": {
            "fergus": (43.700, -80.383, 43.712, -80.371),
            "mount-forest": (43.980, -80.740, 43.992, -80.728),
            "erin": (43.766, -80.073, 43.778, -80.061),
        },
        "wiki": ["Canada:Ontario:Wellington"],
    },
}


def _get(url, data=None, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read().decode("utf-8")
        except urllib.error.HTTPError as ex:
            if ex.code not in (429, 502, 503, 504) or i == tries - 1:
                raise
            wait = 20 * (i + 1)
            print(f"    [{ex.code}] retrying in {wait}s ...", flush=True)
            time.sleep(wait)


def _overpass(box, verbosity):
    s, w, n, e = box
    q = (f"[out:json][timeout:90];"
         f'(node["addr:housenumber"]({s},{w},{n},{e});'
         f'way["addr:housenumber"]({s},{w},{n},{e}););out {verbosity};')
    body = urllib.parse.urlencode({"data": q}).encode()
    return json.loads(_get(OVERPASS, body))["elements"]


def provenance(samples):
    """Step 3 of `05`: who edited, when, in which changesets."""
    users, years, changesets, kinds = Counter(), Counter(), Counter(), Counter()
    per_box = {}
    for name, box in samples.items():
        els = _overpass(box, "meta")
        u, y = Counter(), Counter()
        for el in els:
            u[el.get("user", "?")] += 1
            y[(el.get("timestamp") or "????")[:4]] += 1
            changesets[el.get("changeset")] += 1
            kinds[el["type"]] += 1
        users += u
        years += y
        per_box[name] = {"elements": len(els), "users": u.most_common(8),
                         "years": sorted(y.items())}
        print(f"  {name:<14} {len(els):>5} elements   top: {u.most_common(3)}")
        time.sleep(6)
    return users, years, changesets, kinds, per_box


def conventions(samples):
    """What tags does anything we upload have to be consistent with?"""
    keys, vals, combos = Counter(), {}, Counter()
    total = 0
    for box in samples.values():
        els = _overpass(box, "tags")
        total += len(els)
        for el in els:
            t = el.get("tags", {})
            for k, v in t.items():
                keys[k] += 1
                if k.startswith("addr:") or k in ("source", "building"):
                    vals.setdefault(k, Counter())[v] += 1
            combos["+".join(sorted(k for k in t if k.startswith("addr:")))] += 1
        time.sleep(5)
    return {"sampled": total,
            "keys": keys.most_common(25),
            "values": {k: c.most_common(8) for k, c in sorted(vals.items())},
            "addr_combos": combos.most_common(8)}


def changeset_tags(cid):
    cs = json.loads(_get(f"{OSM_API}/changeset/{cid}.json"))["changeset"]
    return {"id": cid, "user": cs.get("user"), "created_at": cs.get("created_at"),
            "changes": cs.get("changes_count"), "tags": cs.get("tags", {})}


def recent_activity(bbox):
    """Is anyone importing *right now*? Cheaper than another Overpass pass."""
    s, w, n, e = bbox
    root = ET.fromstring(_get(f"{OSM_API}/changesets?bbox={w},{s},{e},{n}"))
    rows = []
    for cs in root.findall("changeset"):
        tags = {t.get("k"): t.get("v") for t in cs.findall("tag")}
        rows.append({"id": cs.get("id"), "user": cs.get("user"),
                     "created_at": cs.get("created_at"),
                     "changes": int(cs.get("changes_count", 0)),
                     "comment": tags.get("comment", ""),
                     "source": tags.get("source", ""),
                     "import": tags.get("import", ""),
                     "import_page": tags.get("import:page", "")})
    return rows


def wiki_check(titles):
    out = {}
    for t in titles:
        api = (f"https://wiki.openstreetmap.org/w/api.php?action=query&prop=revisions"
               f"&rvprop=content|timestamp&rvslots=main&titles={urllib.parse.quote(t)}"
               f"&format=json")
        for _, p in json.loads(_get(api))["query"]["pages"].items():
            if "missing" in p:
                out[t] = {"exists": False}
            else:
                body = p["revisions"][0]["slots"]["main"]["*"]
                out[t] = {"exists": True, "chars": len(body),
                          "mentions_address": body.lower().count("address"),
                          "mentions_import": body.lower().count("import"),
                          "head": body[:400]}
        time.sleep(1)
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("city", choices=sorted(CITIES))
    ap.add_argument("--out", type=Path, default=Path("."))
    args = ap.parse_args()
    cfg = CITIES[args.city]

    print(f"provenance samples ({len(cfg['samples'])} boxes):")
    users, years, changesets, kinds, per_box = provenance(cfg["samples"])
    print(f"\ncombined: {sum(kinds.values())} elements {dict(kinds)}")
    print("  users:", users.most_common(10))
    print("  years:", sorted(years.items()))

    print("\nchangeset tags (top 8 by elements sampled):")
    csets = []
    for cid, n in changesets.most_common(8):
        info = changeset_tags(cid)
        info["sampled_elements"] = n
        csets.append(info)
        t = info["tags"]
        print(f"  {cid}  {info['created_at'][:10]}  {info['changes']:>6} changes  "
              f"{info['user']}")
        print(f"    comment = {t.get('comment', '')[:78]}")
        if t.get("source"):
            print(f"    source  = {t['source'][:78]}")
        if t.get("import") or t.get("import:page"):
            print(f"    IMPORT  = {t.get('import')} {t.get('import:page', '')}")
        time.sleep(2)

    print("\ntag conventions:")
    conv = conventions(cfg["samples"])
    for k in ("addr:city", "addr:province", "source"):
        if k in conv["values"]:
            print(f"  {k}: {conv['values'][k][:5]}")
    print(f"  addr combos: {conv['addr_combos'][:3]}")

    print("\nwiki:")
    wiki = wiki_check(cfg["wiki"])
    for t, r in wiki.items():
        print(f"  {t}: {r}" if not r["exists"] else
              f"  {t}: exists, {r['chars']} chars, "
              f"address x{r['mentions_address']} import x{r['mentions_import']}")

    print("\nrecent activity (100 latest changesets over full extent):")
    recent = recent_activity(cfg["bbox"])
    flagged = [r for r in recent if r["import"] or r["import_page"]]
    print(f"  import-tagged: {[r['id'] for r in flagged] or 'none'}")
    for r in recent:
        if "addr" in (r["comment"] + r["source"]).lower():
            print(f"  {r['created_at'][:10]} {r['changes']:>5} {r['user']:<20} "
                  f"{r['comment'][:60]}")

    args.out.mkdir(parents=True, exist_ok=True)
    dest = args.out / f"entry-state-{args.city}.json"
    dest.write_text(json.dumps(
        {"city": args.city, "bbox": cfg["bbox"], "per_box": per_box,
         "users": users.most_common(), "years": sorted(years.items()),
         "kinds": dict(kinds), "changesets": csets, "conventions": conv,
         "wiki": wiki, "recent_changesets": recent}, indent=2), encoding="utf-8")
    print(f"\nwrote {dest}")
