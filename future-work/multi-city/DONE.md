# Multi-city — completed

Finished items, split out of [TODO.md](TODO.md) on 2026-08-13 so the action
list carries only open work. Kept because several open items depend on what was
decided here, and the reasoning is not recoverable from the code.

Full context lives in [08-survey-results-2026-08-12.md](08-survey-results-2026-08-12.md).

## Hamilton's entry state — DONE 2026-08-13

**Cleared as city #2.** Greenfield for a municipal import: a CanVec/NRCan base
layer (`source` on ~90% of sampled elements), StatCan address ranges from 2016,
and Kevo's manual 2022 LODE infill. The 2018 peak is a mass `addr:city` rename,
not an import. No wiki page, no active importer, nobody to stand down for.

Written up in `08-survey-results-2026-08-12.md`; scripted as
`scripts/entry_state_probe.py` (rerunnable, Wellington boxes pre-filled).

Its three follow-ups were "none blocking" while Hamilton was only a candidate.
Selecting it promoted two onto the critical path — they are open in TODO §2.

## Mississauga's entry state — DONE 2026-08-13

**Greenfield, and a ranked co-candidate with Hamilton.** Probed per `05` with
the same script (`mississauga` boxes: Port Credit, Streetsville, Malton; 1,086
elements). Same CanVec + StatCan strata as Hamilton, no wiki page, no import
tags, no active importer, and **no manual infiller to stand down for** — the
contact list is Matthew Darwin alone, whom Hamilton already names.

Three things it settled beyond the entry state itself:

- **`MUNICIPALITY` splits Peel cleanly** — Mississauga 264,641 / Brampton
  207,421 / Caledon 31,861, no nulls, no variants, 100% `STREETNAME`. So `03`'s
  `municipality_name` gate does not block this city, and reaching Mississauga
  does not wait on `10`.
- **Its year peaks are pure retag artifact** — 2019 and 2018 are both Matthew
  Darwin province-wide `addr:province`/`addr:state` cleanups. Malton's modal
  year is 2018 and Port Credit's is 2019 for no reason but which sweep landed
  last.
- **2026 is POI mapping, not an import.**

- [x] **Tie broken 2026-08-13: city #2 is Hamilton.** The survey numbers never
      did it; the decision was which path to exercise first. Hamilton runs on
      the single-city path this repo already has, so city #2 tests the
      *generalization* rather than testing generalization and a new source shape
      at once. Mississauga stays the designated first instance of the
      regional-dataset path 19 of 42 datasets will need — deferred, not
      rejected, and its probe write-up stands.
- [x] Units fed into it — Mississauga defers 3,548 condo-tower addresses
      (2.4%), Hamilton defers none. Choosing Hamilton means `09` does not gate
      city #2; units stay blocking only for Guelph and for Mississauga later.

## `05` shape-based prior-import detection — DONE 2026-08-13

`05` now carries a "Tag-based detection is not sufficient" section: element
`source` first (cheapest, survives retagging, does not depend on changeset
hygiene), then shape, then self-declaration in comments. Plus the bulk-edit
false-positive case (rename sweeps), the last-touch-year caveat, and the
federal-vs-municipal adjudication note.

## Wellington's 2025 spike — DONE 2026-08-13

**It was Guelph.** Guelph's bbox is *wholly* contained in Wellington's, and an
Overpass count split puts 92.1% of the 48,096 inside it. Pure Wellington 2025 is
3,817 — ordinary activity. **Tier 2 is now complete**; every anomaly in the
survey table is accounted for.

The probe script's Wellington sample boxes were never needed and remain untested.

## `02` corrected — DONE 2026-08-13

`02` now carries a "canonical fields are not conflation-ready" correction: a
mandatory per-dataset street resolution step, its four-branch precedence,
`portfolio_survey.py`'s `_resolve` as the reference implementation, and a
proposed `street_from` key so the recipe lives in config rather than code.

## `03`'s first concrete capability — DONE 2026-08-13

`has_street_type` written into `03`. Two things it forced that the Toronto-only
fields never did: the capability model needs **derived** capabilities (the field
is present, its *content* is insufficient), and it needs a second severity —
*refuse to run* alongside *disable and report*, because there is no degraded
mode for conflating without street names.

## Peel's "typeless" misreading — corrected 2026-08-13

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

- [x] **Mississauga became a new candidate** the survey had written off: 116,109
      missing at **96.6% street-known**, the best score of any shortlist
      candidate, Hamilton included. Sole source, no city layer tracked. Probed
      2026-08-13 (above). The `municipality_name` worry did not survive
      measurement: Peel's field is three clean values, so `03` gates this city
      in principle and passes it in fact.

Two follow-ups from this correction are still open — see TODO §6.

## Housekeeping

- [x] The multi-city line of work is pushed — `659467f` (design docs) through
      `33cdd12`, pushed 2026-08-13. `main` is in sync with `origin/main`.
