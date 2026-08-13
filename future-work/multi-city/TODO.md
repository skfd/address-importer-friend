# Multi-city TODO

Open work after the 2026-08-12 portfolio survey. Ordered by what blocks what.
Context lives in [08-survey-results-2026-08-12.md](08-survey-results-2026-08-12.md);
this file is only the action list.

## 1. Establish Hamilton's entry state — DONE 2026-08-13

**Cleared as city #2.** Greenfield for a municipal import: a CanVec/NRCan base
layer (`source` on ~90% of sampled elements), StatCan address ranges from 2016,
and Kevo's manual 2022 LODE infill. The 2018 peak is a mass `addr:city` rename,
not an import. No wiki page, no active importer, nobody to stand down for.

Written up in `08-survey-results-2026-08-12.md`; scripted as
`scripts/entry_state_probe.py` (rerunnable, Wellington boxes pre-filled).

Follow-ups this leaves open, none blocking:

- [ ] Contact **Kevo** before doing anything visible — they did this work by
      hand and said so in their changeset comments
- [ ] Decide what we write for `addr:city` in an amalgamated city (Hamilton's
      own rename left `Dundas` and `Stoney Creek` behind) and for
      `addr:province` (`ON` 27 vs `Ontario` 2 — no convention to honour)
- [ ] Adjudication policy for municipal-vs-CanVec disagreement (`06`)

## 1b. Oakville is brownfield-active — do not touch

Found incidentally by the recent-changeset check: `TronnaLegacy` is importing
Oakville addresses from Town of Oakville open data via MapRoulette, 2026-08-08
onward. Oakville is dataset #29 in the portfolio (49,322 missing). It was never
on the shortlist, so nothing is lost — but it is now marked.

- [ ] Re-read the 2026 peaks in the Tier 1 table as possible live activity now
      that one of them demonstrably is

## 2. Teach `05` shape-based prior-import detection — DONE 2026-08-13

`05` now carries a "Tag-based detection is not sufficient" section: element
`source` first (cheapest, survives retagging, does not depend on changeset
hygiene), then shape, then self-declaration in comments. Plus the bulk-edit
false-positive case (rename sweeps), the last-touch-year caveat, and the
federal-vs-municipal adjudication note.

## 3. Explain Wellington's 2025 spike — DONE 2026-08-13

**It was Guelph.** Guelph's bbox is *wholly* contained in Wellington's, and an
Overpass count split puts 92.1% of the 48,096 inside it. Pure Wellington 2025 is
3,817 — ordinary activity. **Tier 2 is now complete**; every anomaly in the
survey table is accounted for.

The probe script's Wellington sample boxes were never needed and remain untested.

## 4. Correct `02` — DONE 2026-08-13

`02` now carries a "canonical fields are not conflation-ready" correction: a
mandatory per-dataset street resolution step, its four-branch precedence,
`portfolio_survey.py`'s `_resolve` as the reference implementation, and a
proposed `street_from` key so the recipe lives in config rather than code.

## 5. Give `03` its first concrete capability — DONE 2026-08-13

`has_street_type` written into `03`. Two things it forced that the Toronto-only
fields never did: the capability model needs **derived** capabilities (the field
is present, its *content* is insufficient), and it needs a second severity —
*refuse to run* alongside *disable and report*, because there is no degraded
mode for conflating without street names.

## 6. Polygon clipping is a blocker, not a cleanup (`10`)

Documented 2026-08-13; the implementation is still open.

`10` now records **three** conclusions changed by rectangles (York, Wellington,
Oakville), and the key structural point: **containment can be total.** Guelph is
a separated city inside Wellington County, so no bbox tuning can exclude it.
Ontario's other separated cities in the portfolio — Barrie/Simcoe,
Brantford/Brant, Kingston/Frontenac — have the same shape, so every county
dataset paired with its separated city is contaminated by construction.

- [ ] Implement it. `t2/reverse_sweep.py:48` `_load_toronto_boundary` already
      returns a Shapely polygon and is generic apart from its name; ingest
      already clips to a tile polygon (`016_run_polygon.sql`). The mechanism
      exists, it is just not applied at city level.
- [ ] Must clip **both** sides — source rows and OSM elements — or the asymmetry
      creates a new false signal.

**Scope narrowed 2026-08-13 by the source-overlap census** (`10`, "Two different
problems, two different mechanisms"). The polygon's job is the **OSM side**;
source-side dedup is an attribute lookup on the municipality field and needs no
boundary. Wellington and Guelph share *zero* addresses — a separated city is
outside its county's layer by construction — and only 2 pairs of 42 genuinely
duplicate (lambton ⊃ sarnia, peel-region ⊃ brampton).

- [ ] Portfolio-level **ownership map**: municipality → authoritative dataset.
      Must be keyed per municipality, not per dataset, because Peel is
      authoritative for Mississauga and Caledon while losing Brampton.
- [ ] Rule to encode: lower tier wins; and clip the city layer to its own
      boundary so Guelph's 75 `Guelph/Eramosa Twp` rows go to Wellington.

## 7. Peel was misread as typeless — corrected 2026-08-13

`peel-region` was recorded as having no street types (`street-known%` 1.0, gap
"not a gap number", `03`'s worked failure case). **`STREETTYPE` is populated for
98.8% of its rows** — Mississauga 98.2%, Brampton 99.8%, Caledon 100%. The 4%
figure was measured against the canonical `street` column, which maps to
`STREETNAME`: the same name+type split as Durham and Niagara, both resolved
correctly by the same run.

Fixed in `scripts/portfolio_survey.py` (`RESOLUTION["peel-region"]`), re-measured
against the survey's own PBF, and corrected in `02`, `03` and `08`.

Re-measured: Peel's gap is **270,150 of 339,723 (79.5%) at 90.5% street-known**,
not 337,581 at 1.0%. The OSM side reproduced exactly (154,552 distinct keys,
178,491 elements, 13% ways, 2018 peak 73,569), so only the source resolution was
ever broken. Peel drops below york in the sorted table.

- [ ] **Mississauga is a new candidate** the survey wrote off: 116,109 missing
      at **96.6% street-known**, the best score of any shortlist candidate,
      Hamilton included. Sole source, no city layer tracked. Needs the `05`
      entry-state probe before it can be ranked — and it is the first case where
      `municipality_name` handling (`03`) blocks a specific attractive city
      rather than a category.
- [ ] `has_street_type` must be evaluated **after** street resolution, never
      against raw canonical fields (`03`). Ordering decides the answer.
- [ ] A failed capability should print the values it judged. The guard metric
      flagged Peel correctly; the absurd number was read as "dataset broken"
      rather than "our reading is broken", and those are indistinguishable from
      the metric alone.

## Not blocking, worth doing when touching the normalizer

Cheap suffix-table wins measured by the survey: `AV`, `CR`, `BV`, `WY`, `TERR`,
`TL`, `PRIV`, plus French `RUE`/`BOUL`/`PROM`/`CROIS`. Would materially move
Ottawa, Cornwall, Muskoka, SDG and Frontenac, whose gaps are currently
overstated. Rural numbered roads (`County Road 43`) need a rule, not a table.

Guardrail: Toronto's match rates must not move (`tool.db` is living).

## Housekeeping

- [ ] The whole multi-city line of work is unpushed on `main` — everything from
      `659467f` (design docs) onward. Check `git log origin/main..HEAD`.
- [ ] Maintenance run is due ~2026-08-22 (last: `maint-snap90`, 2026-07-23,
      watermark snapshot 90 / 2026-07-22). Unrelated to the above — it conflates
      against live Overpass and needs none of this.
