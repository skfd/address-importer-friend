# Two products for city data — layers and beholders. Guelph first

Status: **planned 2026-09-12**, revised 2026-09-13 after the Guelph open-data
audit in `C:/Users/kk/Code/guelph-osm-import-audit` and two independent reviews
of it. Doc `11` named the feature-type axis and deliberately declined to
schedule it. This document schedules it — and, in the revision, corrects its own
assumption that a beholder is the answer for all of it.

Reads on top of `07` (beholder generalization, implemented), `11` (feature
types), and `06` (the adjudication layer, which is the "third place" below).
Doc `11`'s guidance stands: L1 stays address-only.

## Why not an import

The audit found that **Guelph OSM is not a blank map**. OSM has more buildings
than the City publishes, more road kilometres, more trails, more pitches. Of 46
catalogued layers, none justified a bulk import. What the City has that OSM
lacks is **attributes**: official names, surfaces, lighting, separation,
classification.

So the deliverables are ongoing comparisons, not uploads.

## The two products — and the line between them

The family already contains both, and they are not the same tool:

**The layer** (`toronto-parks-layer`, `toronto-addresses-layer`,
`toronto-streets-layer`). A `download → slim → compare → tiles → site →
publish` pipeline. It renders the City data as MVT + PNG tiles a mapper adds to
**JOSM or iD as a reference overlay**, and publishes a **gap page** —
`missing` / `mismatch` / `unnamed` — from spatial overlap against Overpass.
Stateless, rebuilt weekly, no login, no database.

**The beholder** (`address-beholder`). Tracks every *source record* over time
with an append-only history, a correctness audit, and notes from allowlisted
mappers. It has a **third place**: somewhere to record a judgment that belongs
to neither dataset — *this City point is a placeholder*, *this one is
demolished*, *this address does not exist*. `notes.py`'s preset vocabulary is
that place today; doc `06` is where it grows up.

### The discriminator is not "is the City data correct"

It is tempting to say the layer assumes the City is right and the beholder
handles a City that is wrong. That is not quite it — **`toronto-parks-layer`
already handles bad City data**. `INCLUDE_AREA_CLASSES` drops traffic islands,
road slivers, boulevards and hydro corridors; the numbered TRCA parcels are kept
out of the tiles and given their own gap category.

The real line:

> **Categorical defects want a layer. Per-record defects want a beholder.**

A categorical defect is fixed *once*, with a filter rule, usually keyed on a
field the source already carries. A per-record defect needs a **human judgment
per row, and that judgment has to persist across rebuilds** — which is exactly
what a stateless weekly rebuild cannot hold, and exactly what the third place is
for.

That is why addresses need the full beholder: "this is a placeholder point",
"this building was demolished", "this unit was never built" are per-record
verdicts, tens of thousands of them, and re-deriving them every week is not
possible.

## Which Guelph datasets fall where

The audit classified every layer's defects. **Almost all are categorical**, and
live in a field:

| dataset | the defect | the rule |
|---|---|---|
| swm ponds | 38 of 152 are swales, not basins | filter on `TYPE` |
| donation bins | 9 bins, 13 thrift counters, 8 consignment shops | filter on `LocationType` |
| fire / EMS | spans 8 municipalities; EMS republishes the fire rows | filter on the municipality field |
| restrooms | 63 of 80 are seasonal portables | filter on `RestroomType` |
| guelph areas | 3 of 23 are "Non-Residential - A/B/C" tabulation units | filter on `AREA_NAME` |
| gardens | the point and polygon layers disagree on type | use layer 28, the later vocabulary |
| pitches | 3 cricket rows are the wicket strip; 2 disc golf rows are whole courses | filter on area + `Type` |

Every one is a slim rule. **They are layers.**

### Layer products

| dataset | source | gap page keys on | what the overlay gives a mapper |
|---|---|---|---|
| **parks** | `OD1/5` (126) | overlap + name | official names, incl. Anishinaabemowin renamings |
| **pitches** | `OD1/22` + `OD1/23` (191) | overlap + sport; name/surface/lit | the 162 official names to type in |
| **transit stops** | GTFS (618) | `ref` = `stop_id` | the 80 stops with nothing within 100 m |
| **swm ponds** | `OD2/10` (114 after filter) | polygon overlap | 36 absent basins; classification for the rest |
| **bike facilities** | `OD2/1` (1,462) | overlap on the street | separation and buffer type |
| **truck routes** | `OD1/1` field (322) | overlap on the street | a truck network OSM does not have at all |
| **trails** | `OD1/21` (2,118) | overlap | surface and winter service |
| **gardens** | `OD1/28` (42) | overlap + name | small, keyed, stable |

**Guelph tags stormwater basins `natural=water` + `water=basin` (10 today), not
`landuse=basin`.** A predicate built on the wrong scheme reports correct ponds
as failures. Follow the local scheme; do not retag into the other one.

### Beholder products

| dataset | why it needs the third place |
|---|---|
| **addresses** ✔ | already live as `guelph-beholder`. Placeholder, stale and demolished points are per-record verdicts that must persist |
| **AEDs** | 262 devices geocoded onto 170 coordinates, 14 on one node, 18 rows are vehicles or loaner spares. Untangling which device is where is one human judgment per device, and it has to stick |

AEDs are second wave: their identity predicate resolves `ADDID` → address →
building, so it reuses the address identity and should wait until that is
proven.

### Neither

**Trees.** The original exclusion here was written on a wrong reason ("OSM
already has 88%") — the two datasets have near-equal totals but are largely
disjoint, and ~35,000 city trees sit where OSM has none, which is why the audit
now tiers trees 4 / conflate. It still fails precondition (4) below: a gap page
would open with ~35,000 unclearable findings. An **overlay with no gap page**
would still help a mapper adding trees by hand; that is the only form worth
offering.

## The four preconditions for a gap page

Either product, when it compares against OSM:

1. the source is **automatable** — a live endpoint, not a zip;
2. an **identity predicate** exists that is **not the thing being audited**;
3. the gap **recurs** rather than being a one-shot backlog;
4. the diff is **bounded** — a run surfaces a queue a person could work through.

On (2): pitches prove it. OSM has `name` on 15 of 303 pitches and those missing
names *are the product*, so keying on name would report them as missing features
and hide exactly what matters. Pitches key on proximity plus compatible sport.
Transit is the inverse and easy: `ref` is already right on 528 of 618 stops.

On (4): a large gap looks like a strong reason to build a watcher and is the
opposite. A tool that opens with 35,000 findings gets closed, not worked. Added
after review, and the precondition most likely to be forgotten.

## Licence — and an obligation only the layer carries

The catalogued layers are clear: the OSMF LWG approved the Guelph Open Data
Licence 2.0 on 2024-09-09, listed `compatible`.

**But a published tile layer is a redistribution, which the beholder never
does.** Every layer site must carry the licence's required attribution:

> Contains information licensed under the Open Government Licence – City of Guelph.

The audit's two best datasets — the **heritage register** and **stop signs** —
are *not* in the catalog and carry `licenseInfo: null`. Do not build either
product on them, least of all the one that republishes tiles to a public URL.
The unblocking action is one email to `opengov@guelph.ca`.

## The engine seam — done

Implemented 2026-09-12 in `address-beholder`: `run.py review()` dispatches
through **domain packs** (`beholder/packs/`); a dataset declares
`[dataset] feature_type` and `[identity] predicate`, and a mismatch between them
stops the run. `packs/addresses.py` is an adapter, not a rewrite.

Regression gate (doc `07` guardrail 3) held exactly, with **0 change events**:

| dataset | PRESENT | MISSING |
|---|--:|--:|
| guelph-beholder | 45,397 | 8,449 |
| toronto-import-beholder | 523,380 | 466 |

Tests 65 → 92.

**`guelph-pitches-beholder` was built as the exemplar, and on this revision it
is the wrong product for pitches.** Pitches has no per-record source defects,
and what its mappers need is the editor overlay a beholder cannot produce. Its
findings are sound — 177/191 present, `name_missing` 162, and the structural
discovery that 35 city rows resolve to 13 OSM objects because OSM maps the court
*block* where the City inventories the courts inside it. Keep it as the proof
that the pack seam works; move pitches to a layer.

## Deployment

Per-dataset repos. Beholders follow `guelph-beholder`'s thin-dir convention;
layers follow `toronto-parks-layer`'s own-repo-plus-GitHub-Pages convention.
Decided 2026-09-12.

Known costs, inherited: the OSM OAuth2 app and its
`http://127.0.0.1:5000/auth/callback` redirect are shared between beholders, so
only one can be *served* at a time (reviews are unaffected). The layer template
needs tippecanoe under WSL2 (`wsl-setup.md`) and depends on `addressvault.net`
for its fetching.

## Order of work

1. **`guelph-parks-layer`** — clone `toronto-parks-layer`, point `download` at
   `OD1/5`, everything downstream unchanged. Proves the template survives a new
   source and a new city. — *first, decided 2026-09-13*
2. **`guelph-pitches-layer`** — needs `compare.py` extended from
   `missing/mismatch/unnamed` to diff `surface` and `lit` too. The first real
   change to the layer template.
3. transit, ponds, bike facilities, truck routes, trails, gardens.
4. AED beholder, once the address identity is proven reusable.
5. Heritage — either product — the day the licence clears.
