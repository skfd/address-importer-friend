# Unit-level addresses (`addr:unit`)

Status: **option 2 taken for Hamilton, 2026-08-14** (see "The decision, for
Hamilton" below). Unit-level *modeling* stays deferred; the collapse is an
explicit, config-declared deferral, not a silent drop. Captured 2026-08-10.

**Does not gate city #2 (2026-08-13)** — **falsified 2026-08-14 by the first
Hamilton baseline.** The claim "like Toronto its source carries no unit field"
came from reading the tracker's *canonical* columns, where Hamilton maps no
unit. But the props do carry one: `UNIT_NUMBER_COMPLETE` on 36.8% of rows
(measurements below). The baseline surfaced it immediately — 8,621 exactly
co-located groups, 632 stacked rows at 75 James Street South alone, and ~91k
`city_duplicate` review flags that are all this one phenomenon. **Units gate
Hamilton's upload** (not its conflation runs); a decision between the options
below is needed before the first changeset. The lesson for onboarding (`04`):
probe for a unit field in the *props*, not just the tracker's canonical
mapping.

## Why this is not a refactor

Toronto's source has no unit field, so `t2` has no concept of one — not in
ingest (`t2/candidates.py`), not in conflation, not in the review UI, not in
`t2/osm_export.py`. Every other source in the portfolio appears to have one:
`ontario-address-changes/datasets/*.toml` maps a canonical `unit` field for
Guelph (`UNIT_NO`), Ottawa (`UNITID`), Oakville (`UNIT`), and others.

This is **new product surface**, not generalization. It should be scoped
separately and not smuggled into the multi-city refactor.

## The Guelph numbers

Measured 2026-08-10 against snapshot 37 (2026-08-09), 53,846 active rows:

- **13,162 rows (24.4%) carry a unit.** `HAS_UNIT='Y'` on 12,885.
- Collapsing units gives **40,634 distinct `(number, street)`** civic addresses.
- Unit values are mostly numeric (12,462), some mixed (`D8`, 527), some alpha
  (`B`, 173).
- **Stacks are large.** Largest by civic address: 214 units at 302 College Ave W,
  200 at 824 Woolwich St, 193 at 93 Arthur St S, 172 each at 1878 and 1880
  Gordon St.
- **Coordinates are shared.** Up to 172 rows at one exact lat/lon.

Naively ingesting Guelph today would attempt to upload 172 stacked nodes at a
single point. The OSM community would reject that on sight, and correctly.

## The Mississauga numbers (2026-08-13)

A second data point, measured against Peel's latest non-skipped snapshot,
264,641 Mississauga rows. It changes how expensive option 1 is:

- **116,442 rows (44.0%) carry a `UNIT_IDENTIFIER`** — nearly double Guelph's
  share of rows.
- Collapsing gives **148,037 distinct `(number, street)`** civic addresses.
- But **only 3,548 civic addresses (2.4%) are stacked at all.** The other
  144,489 are already one-to-one.
- Stacks are correspondingly deeper: 34 units on average, **591** at 4011
  Brickstone Mews, 484 and 482 at 3880/3888 Duke of York Blvd, 472 at 310
  Burnhamthorpe Rd — all Mississauga city-centre condo towers.

## The Hamilton numbers (2026-08-14)

Found by the first baseline conflation, not by a survey — measured against
snapshot 36 (273,374 active rows):

- **100,587 rows (36.8%) carry `UNIT_NUMBER_COMPLETE`** in props. The tracker
  TOML maps no canonical unit for Hamilton, which is how the 2026-08-13
  "no unit field" reading happened.
- Collapsing gives **172,267 distinct `(number, street)`** civic addresses.
- **9,708 civic addresses (5.6%) are stacked**, deepest **632** at
  75 James Street South; 511 at 360 King Street East. Between Guelph's
  spread-out shape and Mississauga's tower-list shape, closer to Mississauga.
- Unit rows stack at the parcel point: 8,621 exact-coordinate groups hold
  81,784 surplus rows. In the baseline these read as MISSING candidates and
  flood `city_duplicate` (~91k review items ≈ all noise from this).

**Rows are the wrong denominator.** Guelph reads as 24.4% and Mississauga as
44.0% by rows, which suggests Mississauga is the harder case; by *addresses*
Mississauga is 2.4% and the deferral is an enumerable list of towers, while
Guelph's stacking is spread across a much larger share of its civic addresses.
The cost of option 1 is the share of **distinct addresses** that lose data, not
the share of rows — and those two numbers can point in opposite directions.

This also sharpens the guardrail below: the summary to print before upload is
per-coordinate stack depth, since one 591-unit tower is the entire problem and
144,489 clean addresses are not.

## What the prior importer did

Guelph's existing import (`05`) mapped `UNIT_NO` → `addr:unit` directly, with
source values unchanged. Result on the ground: **6,289 OSM elements carry
`addr:unit` against 13,162 source unit rows — roughly 48% coverage.** So even
the human doing this in JOSM did not complete the unit half.

That is useful evidence: units are the part that is genuinely hard, and it is
where a tool could add real value over manual work — if the review UX for
"here are 214 units at one point" can be solved.

## A data-quality trap

Guelph's `full` field concatenates the unit with no delimiter:
`"44 Regent Street B"`, `"70 Silvercreek Parkway North 31"`. That makes it a
poor key for anything, and `t2/conflate.py` currently uses
`(address_full, municipality_name)` as the Land-canonical dedup key
(`conflate.py:388-451`). Any city with this `full` shape will key badly.
Prefer composing from `(number, street, unit)` rather than trusting `full`.

## The decision, for Hamilton (2026-08-14)

**Option 2 — collapse to civic now, design units separately.** Implemented as
engine config, not a Hamilton hack: `[source_fields] unit` declares where the
unit lives (`"unit"` or `"props:<KEY>"`), and declaring it *forces* a
`[units] policy` choice at config load — a unit-bearing source can no longer
be ingested with units silently flooding review. The one policy so far,
`"collapse-to-civic"`, makes the source projection emit one representative row
per civic address (`source_db.build_*_query`, applied to ingest, new-since and
retired-since alike, so maintenance inherits the behaviour).

Two things the implementation corrected in this file's numbers:

- **The collapse key needs the municipality.** Amalgamated Hamilton reuses
  street names across its former municipalities: 776 `(number, street)` pairs
  span communities, so the bare key would merge 818 genuinely distinct civic
  addresses. Keyed `(number, street, COMMUNITY)` the collapsed set is
  **173,085**, not the 172,267 quoted below.
- **Representative election must be deterministic** (candidate ids must be
  stable across runs): the unit-less row when one exists — it is the parcel's
  own civic point; all but 87 of Hamilton's 9,196 stacked groups have one to
  elect — else the lowest `identity_key`. The 550 unit-only groups keep one unit row
  as representative (its unit value rides along in `extra`, unused).

Covered by `tests/test_units_collapse.py`; the Toronto guardrail holds by
construction (no policy → the exact pre-collapse queries, and Toronto declares
no unit field).

**Baseline 2 (2026-08-14, same snapshot 36 / same PBF):** 173,156 candidates →
**2.9% MATCH (5,024), 0.4% MATCH_FAR (756), 96.7% MISSING (167,376)**; review
queue 96,267 → 5,103 items (`city_duplicate` 91,638 → 910). The check on
baseline 1: counting *distinct civic addresses* per verdict in the archived
pre-collapse DB gives 5,038 / 777 / 167,196 — baseline 2 within 0.3%, so the
collapse lost nothing. The lesson: **stacking inflated MATCH more than
MISSING** (the OSM-covered downtown is where the towers are), so baseline 1's
"9.4% MATCH" flattered coverage by 3×. Hamilton's real state is ~5k of 173k
civic addresses in OSM. The 71-row excess over the measured 173,085 is
representative election running per tile-bbox query: a group spread wider than
a tile (trailer parks, Times Square Blvd) can elect one representative per
tile it straddles — noise at 0.04%, and visible to `city_duplicate` review.
Archived: `data/hamilton/tool.db.baseline1-preunits`.

## The options (as originally recorded; option 2 taken for Hamilton, above)

1. **Collapse to civic address, drop units.** Ingest the 40,634 distinct
   `(number, street)` set. Safest and fastest; discards real source data.
   Matches what Toronto does by accident.
2. **Collapse now, design units separately.** Same runtime behaviour, but
   recorded as an explicit deferral with its own design round rather than a
   silent drop. This is the reason this file exists.
3. **Model units first-class.** Correct, but requires answering how a reviewer
   approves 214 units at one point, and whether units become separate nodes,
   entrance nodes, or tags on a building.
4. **Ask the local OSM community.** Unit-level address nodes are contentious in
   OSM; the answer may make the whole branch moot. For Guelph there is a
   specific person to ask (`05`).

## Guardrail

Whatever is chosen, the *count* of things that would be uploaded must be
visible before any upload. A city-level "this run would create N nodes at M
distinct coordinates" summary would have caught the 172-stacked-nodes problem
before it reached a changeset.
