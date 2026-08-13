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

## 3. Explain Wellington's 2025 spike

48,096 elements, unexplained. Lower stakes — Wellington is not a near-term
candidate — but it is the last unexplained anomaly in the table.

`python scripts/entry_state_probe.py wellington` runs the whole probe now. Its
sample boxes (Fergus, Mount Forest, Erin) are untested approximations — check
the element counts look sane before trusting the output.

## 4. Correct `02`

`02-city-config-contract.md` still asserts the cross-repo `keep_fields` contract
makes the tracker's canonical fields sufficient for consumers. The survey
disproved this: 18 of 42 datasets store the street *name component only*.

- [ ] Amend `02` to require a per-dataset **street resolution** step ahead of
      normalization (prefer `street` when it carries a type, else `full`
      comma-truncated, else reassemble from props)
- [ ] The correction is already written up in the results doc; this is applying
      it at the source

## 5. Give `03` its first concrete capability

`has_street_type`. Peel fails it — the source carries no street type for 96% of
rows, so a consumer that does not check will silently produce garbage instead of
refusing to run. That is the failure mode `03` exists to prevent, and it now has
a real instance rather than a hypothetical one.

## 6. Polygon clipping is no longer cosmetic (`10`)

Rectangular bboxes changed a *conclusion*, not just counts: York's 2026 spike
read as an active import until it turned out to be our own Toronto upload
bleeding through an overlapping rectangle. Any per-city gap number for a
region/county dataset is contaminated in the OSM direction until this is fixed.

## Not blocking, worth doing when touching the normalizer

Cheap suffix-table wins measured by the survey: `AV`, `CR`, `BV`, `WY`, `TERR`,
`TL`, `PRIV`, plus French `RUE`/`BOUL`/`PROM`/`CROIS`. Would materially move
Ottawa, Cornwall, Muskoka, SDG and Frontenac, whose gaps are currently
overstated. Rural numbered roads (`County Road 43`) need a rule, not a table.

Guardrail: Toronto's match rates must not move (`tool.db` is living).

## Housekeeping

- [ ] 3 commits on `main` are unpushed (`659467f`, `e438e23`, `4c5258f`)
- [ ] Maintenance run is due ~2026-08-22 (last: `maint-snap90`, 2026-07-23,
      watermark snapshot 90 / 2026-07-22). Unrelated to the above — it conflates
      against live Overpass and needs none of this.
