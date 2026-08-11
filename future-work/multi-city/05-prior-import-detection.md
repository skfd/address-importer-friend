# Prior-import detection

Status: **proposed as a platform capability, not implemented.** The method
below was executed by hand against Guelph on 2026-08-10 and worked end to end.

## Why this matters

Toronto in 2026 was greenfield. That is not the normal case. Building-footprint
imports and local mappers have already seeded most mid-size Canadian cities, so
a new city usually arrives with an *entry state* — and possibly with an owner.

Showing up with an import proposal in a city someone else already imported is
both wasted work and bad OSM citizenship. Detecting this must happen before any
config is written, not after a proposal is drafted.

## The method, as executed on Guelph

Every step is scriptable; step 5 needs a human.

1. **Count the OSM side** over the city extent. Guelph: 47,687
   `addr:housenumber` elements — 43,064 ways, 4,617 nodes, 6 relations. The
   way-dominant ratio is itself a signal: addresses are on building polygons,
   which is the preferred OSM form and implies a deliberate import rather than
   organic mapping.
2. **Compute the gap** against the source. Guelph: 2,523 of 40,634 distinct
   source addresses missing (6.2%); 7,818 OSM addresses absent from the source
   (mostly bbox bleed — see `10`).
3. **Tally provenance** with an Overpass `out meta` query. Guelph:

   | Elements | Editor |
   |---|---|
   | 42,435 | `ARandomThumbtack_Import` |
   | 918 | Matthew Darwin |
   | 836 | ARandomThumbtack |
   | 572 | skfd |

   Last-touch by year: 44,338 in 2025, 768 in 2026, everything else scattered
   and small. A single account holding 89% of elements with a one-year spike is
   an import, not organic growth.
4. **Fetch changeset tags** for the top changesets via
   `GET /api/0.6/changeset/{id}`. Guelph changeset 173187168:

   ```
   comment        = Updating addresses for WillowElmira-WoolwichEdinburgh
   created_by     = JOSM/1.5 (19439 en_CA)
   import         = yes
   import:page    = https://wiki.openstreetmap.org/w/index.php?title=Guelph/Address_Import
   source         = Guelph Open Data
   source:license = OGL-Canada-2.0
   source:url     = https://explore.guelph.ca/datasets/cityofguelph::addresses-1/explore
   ```

   Note changeset 173687382 carries `source` but **not** `import=yes` or
   `import:page` — tagging is inconsistent even within one import, so sample
   several changesets rather than trusting the first.
5. **Read the wiki page.** Guelph's says: solo operation, first changeset
   2025-09-16, **declared complete 2025-10-23**, ahead of a self-imposed
   Nov 15 deadline. Changeset regions named after major-road intersections
   (`WillowElmira-WoolwichEdinburgh`) rather than a formal grid. Leftovers
   parked in a `RemainingAddresses.osm` file for future work.

## What to capture in config

The prior import's **tag mapping** is load-bearing, not trivia. Guelph's:

| Source | OSM tag |
|---|---|
| `STREETNO` | `addr:housenumber` |
| `FULLNAME` | `addr:street` |
| `PLACE` | `addr:city` |
| `POSTCODE` | `addr:postcode` |
| `UNIT_NO` | `addr:unit` |
| — | `addr:province=Ontario` (added) |

Anything this platform later uploads into Guelph must be consistent with that,
or it introduces a second convention into a city that already has one. This
belongs in a `[prior_import]` block in the per-city TOML (`02`).

## Resolved: Guelph's two source URLs are the same layer

The prior import's `source:url` is
`https://explore.guelph.ca/datasets/cityofguelph::addresses-1/explore`, while
`ontario-address-changes/datasets/guelph.toml` uses
`https://gismaps.guelph.ca/hosting/rest/services/OpenData/OpenData1/FeatureServer/0`.
Different strings, so this was flagged as a possible "we are comparing two
different datasets" confound on the 2,523 gap.

Resolved 2026-08-10 via the ArcGIS Hub API:

```
GET https://hub.arcgis.com/api/v3/datasets?filter[slug]=cityofguelph::addresses-1
  name        = Addresses
  url         = https://gismaps.guelph.ca/hosting/rest/services/OpenData/OpenData1/FeatureServer/0
  owner       = GuelphGIS_cityofguelph
  recordCount = 53846
```

Identical to our `data_url`, owner matches the TOML's comment, and 53,846
matches our active row count at snapshot 37 exactly. The Hub page is the
human-facing portal for the same service. **The gap number stands.**

Generalizable lesson for the onboarding skill (`04`): a prior import's
`source:url` is usually a portal page, not a service endpoint. Resolve it
through the Hub API (`filter[slug]`) before concluding the datasets differ.

Related: `address-vault` seeds its source registry from
`ontario-address-changes/datasets/*.toml` (`addressvault/sources.py`), so
tracker, vault, and layerist already share one `data_url` per dataset.
Consumers should read snapshots *through the vault* rather than pulling the
city directly — which is what the vault exists for.

## Their conflation rule

Also worth recording: their conflation rule, quoted from the wiki —
*"conflation is only done when the number of reference objects selected matches
the number of source objects selected."* That is crude, and it bounds how much
to trust the existing data. It also explains an observable gap: they imported
units, but only **6,289 of 13,162** source unit rows landed (~48%).

## Entry-state taxonomy

The output of detection is a classification that picks the consumer:

- **Greenfield** — no import, large gap. Import machinery earns its keep.
- **Brownfield, complete** — prior import declared done, small diffuse gap.
  Observer/QA is the product. Guelph is here.
- **Brownfield, active** — import in progress. Do not start anything; contact
  first.
- **Brownfield, abandoned** — import started and stalled. The most delicate
  case: possibly the highest-value target, definitely the one most needing a
  conversation before acting.

## Etiquette

For Guelph specifically, the right move is almost certainly to contact
`ARandomThumbtack_Import`, show them the 2,523-address diff and the ~52% unit
gap, and offer the tooling as an ongoing QA layer over work they already own —
not to open a competing import proposal for 2,523 addresses.

Generalized: **prior-import detection produces a person to talk to, and that
output is as important as the gap number.**
