# Beholders for feature types other than addresses — Guelph first

Status: **planned 2026-09-12**, following the Guelph open-data audit in
`C:/Users/kk/Code/guelph-osm-import-audit`. Doc `11` named the second axis and
deliberately declined to schedule it ("not a mandate to build hydrant
support"). This document schedules it, because the audit produced concrete
datasets rather than a hypothetical one.

Reads on top of `07` (beholder generalization, implemented) and `11` (feature
types as the second axis). Doc `11`'s guidance stands: L1 stays address-only —
`ontario-address-changes` does not learn about pitches — and feature-type
genericity is a property of L2–L4.

## Why a beholder rather than an import

The audit's finding was that **Guelph OSM is not a blank map**. OSM has more
buildings than the City publishes, 88% of the trees, more road kilometres, more
trails, more pitches. Of 46 catalogued layers, none justified a bulk import.

But a third of them scored **tier 3 `reference`** — useful for validating OSM,
not for loading into it. A tier 3 verdict is a beholder's job description. The
data is authoritative and refreshed, the gap is real but small, and the work is
perpetual rather than a one-time upload. That is exactly the product
`address-beholder` already is for Guelph addresses, pointed at a different
layer.

So: no new imports out of this audit. Watchers.

## The shortlist

A beholder earns its keep when **four** things hold: the source is
**automatable** (a live endpoint, not a zip), an **identity predicate** exists
that is not the thing being audited, the gap **recurs** (new stops, renamed
parks, drifting classification) rather than being a one-shot backlog, and —
added after review — **the diff is bounded**.

Bounded means OSM coverage is already high enough that a run surfaces a queue a
person could actually work through. A watcher that opens with 35,000 unclearable
findings does not get used; it gets closed. This is the precondition that
excludes trees, and it is the one most likely to be forgotten, because a large
gap looks like a strong reason to build a watcher when it is the opposite.

| dataset | source | identity predicate | what it watches |
|---|---|---|---|
| **transit** | GTFS + `OD1/33` | `ref` = GTFS `stop_id` | 80 stops with nothing within 100 m; route relations; stale names |
| **pitches** | `OD1/22` + `OD1/23` | proximity + compatible `sport` | `name` on 15/303, `surface` 86/303, `lit` 51/303 |
| **swm ponds** | `OD2/10` | polygon overlap | 36 absent; bare water to classify. **Guelph tags basins `natural=water`+`water=basin` (10 today), not `landuse=basin`** — a predicate built on the wrong scheme reports correct ponds as failures |
| **parks** | `OD1/5` | name + overlap | official names and renamings |
| **gardens** | `OD1/28` | `CommGardenID` + proximity | small, keyed, stable |

**Second wave.** AEDs are valuable (1 in OSM vs 173) but every row is an
address-point geocode, so their identity predicate is *"resolve `ADDID` to the
address, then to the building"* — it reuses the address identity rather than
having its own, and should wait until the first wave proves the seam.

**Excluded, with reasons**, so nobody re-proposes them:

- **Trees** — **and note the exclusion survived review for a different reason
  than it was written.** The original reason ("OSM already has 88%") was wrong:
  the two datasets have near-equal totals but are largely disjoint, and ~35,000
  city trees sit where OSM has none. That makes trees a *conflation* candidate,
  which the audit now tiers 4. It still does not make a good watcher: the diff
  is not bounded, so a tree beholder would open with tens of thousands of
  findings nobody can clear, which is the failure mode below.
- **Hydrants** — `MODEL` null on 97.7%, so there is nothing to audit but
  existence, and `LOCATIONID` is an internal grid reference.
- **Buildings** — 772 missing ≥50 m² is a finite backlog, not a recurring
  drift. Do it once with MapRoulette.
- **Addresses** — already beheld by `guelph-beholder`.

### Everything unlicensed is excluded until the licence lands

The audit's best two datasets — the **heritage register** (2,307 rows, 573
designated, zero `heritage=*` in OSM) and **stop signs** (2,108 with facing
direction) — are not in the open data catalog. They are anonymously readable
with `licenseInfo: null`, as are ~75 other services.

A beholder is not a read: it **ingests a source and republishes a derived view
of it**, durably, with history. That is a use the Open Data Licence would cover
and an empty licence field does not. Do not stand one up against an
uncatalogued service, and especially not against one named `_Temp`.

The unblocking action is the audit's top recommendation — one email to
`opengov@guelph.ca` asking the City to catalog the layers it already serves.
Heritage is the single highest-value beholder in Guelph the day that clears.

## The engine seam

`run.py review()` already has exactly the four seams this needs:

```
iter_active_points(cfg, bbox)      -> source load
fetch_addr_elements(url, ...)      -> OSM fetch     (hardcodes addr:housenumber)
conflate_points(pts, els, r, ...)  -> predicate + audit
record_review(...)                 -> history       (already generic)
```

Only the middle two know what an address is.

**The identity predicate is the plug point**, as doc `11` said. Add to the
dataset config:

```toml
[identity]
predicate = "housenumber+street"   # addresses, the existing behaviour
# predicate = "ref"                # key_field on the source, ref_tag in OSM
# predicate = "proximity+type"     # radius, plus a compatible type mapping
# predicate = "overlap"            # polygon IoU
```

### The rule that shapes every predicate

**The key must never be the thing you are auditing.** Pitches are the case that
proves it: OSM has `name` on 15 of 303 pitches, and the missing names are the
whole point of the dataset — so matching on name would report the gap as
"missing feature" instead of "unnamed feature", and would silently exclude every
object worth flagging. Pitches key on *proximity plus compatible sport*, and
audit name, surface and lit.

Transit is the inverse and the easy case: `ref` is already correct on 528 of 618
stops, so it is a sound key, and shelter/bench/name are the audited fields.

### What the domain pack carries (L3)

Per doc `11`: the OSM filter tags for the Overpass query, the field→tag mapping,
and the checks. `addresses` is the existing pack, unchanged. Each new dataset
declares its pack rather than the engine growing a branch per layer.

### Non-negotiable regression gate

Doc `07` guardrail #3. Baseline captured 2026-09-12 **before** any change:

| dataset | PRESENT | MISSING |
|---|--:|--:|
| guelph-beholder | 45,397 | 8,449 |
| toronto-import-beholder | 523,380 | 466 |

with Guelph's issue table at `deprecated_addr_province` 44,820 · `duplicate_osm`
782 · `postcode_missing` 704 · `city_missing` 354 · `far_match` 265 ·
`civic_on_unit_object` 236 · `postcode_mismatch` 44 · `postcode_format` 28 ·
`street_spelling` 5 · `city_mismatch` 1, and Toronto's at `duplicate_osm`
95,636 · `far_match` 869 · `street_spelling` 67.

A change that moves any of these is a regression, not a discovery.

## L1 — where the source comes from

Doc `11` rules out the tracker, and is right: these are not addresses and
`ontario-address-changes` keeps its scope. But `address-vault` already has
`addressvault/fetch/arcgis.py`, and every Guelph layer in the shortlist is an
ArcGIS FeatureServer. **Check whether the vault's ArcGIS fetcher can be pointed
at an arbitrary layer URL before writing a new one** — the audit's
`guelph-osm-import-audit/inventory.py` already has the pagination and the
`?f=json` shape if it cannot.

The per-dataset store wants: stable source id, geometry, a props blob,
first-seen/last-seen. That is the vault's snapshot shape, which is why it is
worth checking first.

## Deployment

Per-dataset repos, following `guelph-beholder`'s thin-dir convention:
`guelph-transit-beholder`, `guelph-pitches-beholder`, and so on. Decided
2026-09-12; doc `07` had left single-set vs multi-set open. Multi-set remains
available if a "how is Guelph doing" dashboard is ever wanted, and the configs
should stay uniform enough that one could read them all without migration.

Known cost, inherited: the OSM OAuth2 app and its
`http://127.0.0.1:5000/auth/callback` redirect are shared, so only one dataset
can be *served* at a time. Reviews are unaffected. Registering an app per
dataset, or moving to distinct ports, is the fix when it starts to bite.

## Order of work

1. Cut the seam, with the addresses path byte-identical and the regression gate
   green. — *first*
2. **pitches** as the exemplar: hardest predicate, and the attribute audit is
   the whole value. If the seam is right, this is a config plus a fetcher.
3. **transit** next: trivial once the seam exists, and the highest-confidence
   gap in the audit.
4. swm ponds, parks, gardens as a batch.
5. Heritage the day the licence clears.
