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
    "mississauga": {
        "bbox": (43.48500, -79.83000, 43.71800, -79.52500),
        # Port Credit and Streetsville were incorporated towns until the 1974
        # amalgamation; Malton is the detached north-east community by the
        # airport. Same rationale as Hamilton's Dundas / Stoney Creek.
        "samples": {
            "port-credit": (43.548, -79.589, 43.560, -79.577),
            "streetsville": (43.575, -79.716, 43.587, -79.704),
            "malton": (43.700, -79.641, 43.712, -79.629),
        },
        "wiki": ["Canada:Ontario:Mississauga", "Mississauga"],
    },
    # Guelph is not amalgamated, so the boxes sample map-fabric variety
    # instead of former municipalities: the pre-war downtown, a 2000s
    # subdivision belt (Pine Ridge / Westminster Woods), and the west-end
    # (Parkwood Gardens). Densities checked against snapshot 39 on
    # 2026-08-15: 2,053 / 2,094 / 1,220 source rows.
    "guelph": {
        "bbox": (43.4748, -80.32545, 43.58629, -80.15481),
        "samples": {
            "downtown": (43.538, -80.254, 43.550, -80.242),
            "south-end": (43.500, -80.196, 43.512, -80.184),
            "west-end": (43.524, -80.296, 43.536, -80.284),
        },
        "wiki": ["Guelph/Address_Import", "Canada:Ontario:Guelph"],
    },
    # Amalgamated 2001 (seven municipalities); one box per major community —
    # the city core, the Valley (Hanmer), and Chelmsford. Densities checked
    # against snapshot 63 on 2026-08-16: 1,292 / 632 / 957 rows.
    "greater-sudbury": {
        "bbox": (46.20034, -81.59833, 46.88171, -80.55685),
        "samples": {
            "sudbury-core": (46.476, -81.012, 46.488, -81.000),
            "hanmer": (46.644, -80.952, 46.656, -80.940),
            "chelmsford": (46.572, -81.204, 46.584, -81.192),
        },
        "wiki": ["Canada:Ontario:Greater Sudbury", "Greater Sudbury"],
    },
    # Amalgamated 1970 (Port Arthur + Fort William), so one box per former
    # city plus Westfort. Densities checked against snapshot 17 on 2026-08-16:
    # 1,267 / 1,394 / 1,220 rows.
    "thunder-bay": {
        "bbox": (48.28951, -89.42693, 48.51491, -89.15168),
        "samples": {
            "port-arthur": (48.432, -89.244, 48.444, -89.232),
            "fort-william": (48.384, -89.256, 48.396, -89.244),
            "westfort": (48.384, -89.292, 48.396, -89.280),
        },
        "wiki": ["Canada:Ontario:Thunder Bay", "Thunder Bay"],
    },
    # Amalgamated 1998 (Kingston + Kingston Twp + Pittsburgh Twp), so one box
    # per former component. Densities checked against snapshot 47 on
    # 2026-08-16: 4,626 / 2,086 / 1,027 rows.
    "kingston": {
        "bbox": (44.20843, -76.70689, 44.47077, -76.23501),
        "samples": {
            "downtown": (44.232, -76.500, 44.244, -76.488),
            "west-end": (44.232, -76.548, 44.244, -76.536),
            "pittsburgh": (44.256, -76.464, 44.268, -76.452),
        },
        "wiki": ["Canada:Ontario:Kingston", "Kingston, Ontario"],
    },
    # Not amalgamated; map-fabric variety across the central/west/northeast
    # districts. Densities checked against snapshot 1 (the only one — the
    # tracker's Waterloo pulls stopped 2026-06-27) on 2026-08-16:
    # 2,984 / 2,653 / 1,639 rows.
    "waterloo": {
        "bbox": (43.43596, -80.62121, 43.53087, -80.47520),
        "samples": {
            "central": (43.476, -80.532, 43.488, -80.520),
            "west": (43.452, -80.544, 43.464, -80.532),
            "northeast": (43.488, -80.496, 43.500, -80.484),
        },
        "wiki": ["Canada:Ontario:Waterloo", "Waterloo, Ontario"],
    },
    # Amalgamated (1973: Galt + Preston + Hespeler), so one box per former
    # municipality, the Hamilton rationale. Densities checked against
    # snapshot 26 on 2026-08-15: 1,904 / 1,806 / 1,293 rows.
    "cambridge": {
        "bbox": (43.33257, -80.40854, 43.47116, -80.25149),
        "samples": {
            "galt": (43.344, -80.304, 43.356, -80.292),
            "preston": (43.392, -80.364, 43.404, -80.352),
            "hespeler": (43.428, -80.304, 43.440, -80.292),
        },
        "wiki": ["Canada:Ontario:Cambridge", "Cambridge, Ontario"],
    },
    # Not amalgamated (separated city inside Simcoe County), so map-fabric
    # variety: downtown/north, the south-end subdivision belt, the east
    # shore. Densities checked against snapshot 24 on 2026-08-15:
    # 1,904 / 2,228 / 2,109 rows.
    "barrie": {
        "bbox": (44.29599, -79.75085, 44.44753, -79.58783),
        "samples": {
            "downtown": (44.388, -79.692, 44.400, -79.680),
            "south-end": (44.340, -79.644, 44.352, -79.632),
            "east-shore": (44.352, -79.608, 44.364, -79.596),
        },
        "wiki": ["Canada:Ontario:Barrie", "Barrie"],
    },
    # Not amalgamated (city proper only; CITY is the constant 'CORNWALL'), so
    # map-fabric variety like Guelph: downtown core, the francophone east end,
    # the west end. Densities checked against snapshot 25 on 2026-08-15:
    # 1,791 / 1,468 / 1,413 rows.
    "cornwall": {
        "bbox": (45.00815, -74.84304, 45.08509, -74.66798),
        "samples": {
            "downtown": (45.012, -74.736, 45.024, -74.724),
            "east-end": (45.024, -74.700, 45.036, -74.688),
            "west-end": (45.024, -74.748, 45.036, -74.736),
        },
        "wiki": ["Canada:Ontario:Cornwall", "Cornwall, Ontario"],
    },
    # Amalgamated (1998: Trenton + Frankford + Sidney + Murray), so the boxes
    # follow the Hamilton rationale — one per former municipality. Densities
    # checked against snapshot 25 on 2026-08-15: 1,199 / 521 / 419 rows.
    "quinte-west": {
        "bbox": (44.02011, -77.75601, 44.31391, -77.41485),
        "samples": {
            "trenton": (44.112, -77.580, 44.124, -77.568),
            "frankford": (44.196, -77.604, 44.208, -77.592),
            "sidney": (44.124, -77.508, 44.136, -77.496),
        },
        "wiki": ["Canada:Ontario:Quinte West", "Quinte West"],
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


def _get(url, data=None, tries=6):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read().decode("utf-8")
        except urllib.error.HTTPError as ex:
            if ex.code not in (429, 502, 503, 504) or i == tries - 1:
                raise
            # Overpass shedding load needs minutes, not seconds: the 20/40/60s
            # ladder ran out mid-run on the Mississauga probe (2026-08-13).
            wait = 30 * (i + 1)
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
