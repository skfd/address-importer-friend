# Multi-city TODO

Open work after the 2026-08-12 portfolio survey. Ordered by what blocks what.
Context lives in [08-survey-results-2026-08-12.md](08-survey-results-2026-08-12.md);
this file is only the action list.

Completed items moved to [DONE.md](DONE.md) on 2026-08-13 — the entry-state
probes for Hamilton and Mississauga, the city-#2 decision, the `05`/`02`/`03`
doc work, Wellington's spike, and the Peel correction.

## 1. Import Hamilton — the run itself

**The gap between "picked" and "imported".** City #2 was selected 2026-08-13
(DONE.md) but nothing on this list tracked producing the import, only the policy
and design work surrounding it. Written down 2026-08-13.

Tiers 1 and 4 are **done** (2026-08-13, see DONE.md). What remains is pointing
the source at Hamilton and running it.

- [x] **Tier 1, mechanical** (`02`) — done 2026-08-13.
- [x] **Tier 4, geography** (`02`) — done 2026-08-13. The prediction held: the
      quadtree needed no change.
- [x] **Slugged data layout** — done 2026-08-13 (DONE.md). Not on `02`'s tier
      list; found when planning the switch. Per-city state is `data/<slug>/`,
      so flipping `config.toml` can no longer overwrite Toronto's tiles or
      interleave runs into its DB.
- [x] **Repo-per-city split** — done 2026-08-13 (DONE.md). This repo is now the
      engine (`address-importer-friend`, forked with full history);
      `toronto-2-address-import` and `hamilton-address-import` are thin city
      checkouts selected with `run.py --city-dir` / `T2_CITY_DIR`.
- [x] Point the source at
      `ontario-address-changes/data/hamilton/hamilton.db` — done 2026-08-13:
      `hamilton-address-import/config.toml` declares it, with a measured
      `city_bbox` (273,441 rows, lat 43.051..43.468, lon -80.244..-79.625).
- [x] **Tier 2, the source projection + declared-field gating** (`02`/`03`) —
      done 2026-08-14 (DONE.md). `[source_fields]` per city; projection
      generated (Toronto byte-identical, guardrail test); `suffix_range` and
      `intra_source_duplicate` disabled-for-cause for Hamilton, visible in
      the run UI. Smoke-tested against both real checkouts. Nothing blocks
      the first Hamilton ingest now.
- [x] Run **baseline conflation in full** — done 2026-08-14. 680 tiles (the
      no-layer quadtree path's first real use), all four stages green:
      273,233 candidates → 9.4% MATCH, 2.7% MATCH_FAR, 87.9% MISSING against
      a fresh 2026-08-13 Ontario PBF. Two findings:
      - **Engine bug fixed:** `missing_sample` did `candidate_id % every_nth`,
        which is string formatting when the id is the tracker's synthetic
        `syn:<sha1>` (Hamilton has no numeric point id) — 676/680 tiles
        errored. Now `_sample_ordinal`: integer ids keep their value (Toronto's
        sampled set unchanged, no version bump needed), string ids go through
        crc32. Covered by `tests/test_missing_sample.py`.
      - **The MISSING number is inflated by unit rows** — see the new item
        below; read the baseline as ~160k true civic gap, not 240k.
- [x] Guardrail throughout: **Toronto's match rates must not move** — held: the
      only engine change is the sampler above, behavior-identical for integer
      ids (test-pinned); Toronto's tool.db untouched.
- [x] **Units gate Hamilton after all** — resolved 2026-08-14 (see DONE.md
      "Units decision + baseline 2"). `09` option 2 taken: `[source_fields]
      unit` + `[units] policy = "collapse-to-civic"`, enforced at config load.
      Baseline 2 ran the same day: 173,156 civic candidates → 2.9% MATCH /
      96.7% MISSING; review queue fell 96,267 → 5,103. Baseline 1's 9.4%
      MATCH was itself stack-inflated (distinct-civic recount: 2.9%). Review
      triage is unblocked.

Ordering against §2: conflation and review can proceed before Kevo is
contacted. Only *upload* is downstream of §2, which is about the first visible
changeset.

## 2. Hamilton's pre-changeset obligations

Both were "none blocking" while Hamilton was a candidate; selecting it promoted
them onto the critical path, because both precede a visible changeset.

- [ ] Contact **Kevo** before doing anything visible — they did the 2022 LODE
      infill by hand and said so in their changeset comments. A courtesy owed
      before the first Hamilton changeset, not before design.
- [ ] Decide what we write for `addr:city` in an amalgamated city (Hamilton's
      own rename left `Dundas` and `Stoney Creek` behind) and for
      `addr:province` (`ON` 27 vs `Ontario` 2 — no convention to honour).
      **Narrowed 2026-08-13:** the `addr:city` half is Hamilton-specific —
      Mississauga's rename finished (893 `Mississauga`, 1 `Port Credit`), so
      this is not a general amalgamated-city policy question. `addr:province`
      is unconventioned in both and stays general.
      **Re-generalized 2026-08-16 by Greater Sudbury:** its `addr:city`
      splits three ways ('Greater Sudbury' 612 / 'Sudbury' 565 /
      'Chelmsford' 99 in the probe sample) — Mississauga was the special
      case, not Hamilton. An amalgamated-city addr:city policy is needed
      per city, informed by each probe's convention tally.

## 3. Adjudication policy for municipal-vs-CanVec disagreement (`06`)

Covers both candidates: the same Mojgan Jadidi StatCan GTHA campaign seeded
Hamilton (cs 37445896) and Mississauga (cs 37570399) five days apart in 2016,
so one policy settles both. **Cambridge too** (2026-08-15 probe: cs 37554310
et al., 796 of 1,361 sampled elements, mostly bare housenumber+street nodes)
— one policy now settles three cities. **Waterloo makes four** (2026-08-16:
440 of 1,122 sampled, the same 2016-03-01 batch).

## 4. Oakville is brownfield-active — do not touch

Found incidentally by the recent-changeset check: `TronnaLegacy` is importing
Oakville addresses from Town of Oakville open data via MapRoulette, 2026-08-08
onward. Oakville is dataset #29 in the portfolio (49,322 missing). It was never
on the shortlist, so nothing is lost — but it is now marked.

- [ ] Re-read the 2026 peaks in the Tier 1 table as possible live activity now
      that one of them demonstrably is. **Mississauga checked 2026-08-13: not
      live** — its 2026 elements are commercial-strip POI mapping, and the 100
      most recent changesets over the extent carry no import tag. One down.

## 5. Polygon clipping is a blocker, not a cleanup (`10`)

Documented 2026-08-13; the implementation is still open.

`10` records **three** conclusions changed by rectangles (York, Wellington,
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

## 6. Capability evaluation, from the Peel correction (`03`)

The correction itself is in DONE.md; these two consequences are not done.

- [ ] `has_street_type` must be evaluated **after** street resolution, never
      against raw canonical fields (`03`). Ordering decides the answer.
- [ ] A failed capability should print the values it judged. The guard metric
      flagged Peel correctly; the absurd number was read as "dataset broken"
      rather than "our reading is broken", and those are indistinguishable from
      the metric alone.

## 7. Tile-layer lifecycle, from the Hamilton rebuild (DONE.md 2026-08-15)

Rebuilding Hamilton's tiles (squares → neighbourhood fabric) was free only
because pre-announcement Hamilton can drop its runs at will. Two gaps become
blocking the moment a city has runs we must keep:

- [ ] **Tile ids are unstable across rebuilds.** `_merge_underfilled` protects
      id continuity *within* a build; nothing does across builds (layer update,
      new snapshot). A rebuild orphans every prior run's tile association.
      Runs already store `polygon_json` (016), so spatial re-association —
      match a run to the new tile that best overlaps its stored polygon — is
      the obvious mechanism. Decide and build it before announcing any import.
- [ ] **The UI has no staleness detection.** After the rebuild, the old
      run-for-all state (680/680 done) kept describing tiles that no longer
      existed; the operator had to know to reset it. `tiles.json generated_at`
      vs the state's timestamp is a one-line comparison that should surface a
      visible warning on `/map`.

## 8. Number-less source rows (Quinte West, 2026-08-15)

Quinte West publishes 342 rows (1.7%) with no housenumber — named features
("Dam 7", "Dam at Sonoco") and unnumbered road frontages. They cannot become
OSM addresses as-is, and today the engine ingests them as candidates whose
identity key starts `None|`, which conflates nonsensically and pollutes the
MISSING count. Expect the same in other rural datasets.

- [ ] Decide the policy: skip-with-visible-count at ingest (the Land Entrance
      shape), or a distinct terminal status. Silent ingestion is the one wrong
      answer. Gate: needed before Quinte West's first baseline is read.

## 9. Case normalization for upload (Quinte West, 2026-08-15)

Quinte West's street names are ALL-CAPS ("ANNA COURT") — the first such
source in the family. Conflation is case-insensitive so baselines are fine,
but an upload would write shouting `addr:street` values.

- [ ] Title-case step on the export path, driven by a per-city flag (Toronto/
      Hamilton/Guelph must stay byte-identical: their sources are already
      mixed-case). Mind the hard cases: "O'NEIL CRESCENT", "MCGILL",
      hyphenated roads, "COUNTY ROAD 40". Gate: blocks any Quinte West upload,
      not conflation.

## 10. Units that are civic numbers in disguise (Quinte West, 2026-08-15)

23 GOULD STREET records 40 "units" whose values are street-facing civic
numbers (unit='58', full='58 GOULD STREET', unit_type=TOWNHOUSE).
collapse-to-civic folds them into one candidate; OSM likely wants each as
its own address. A second unit semantics for `09` — neither Hamilton's
parcel-stack nor Guelph's apartment shape.

- [ ] When designing unit-level import (09's deferred half), classify
      unit-as-civic-number complexes explicitly rather than trusting
      unit_type labels.

## 11. Lifecycle-status filtering (Niagara Region, 2026-08-15)

The "niagara-falls" dataset (really the 12-municipality Niagara Region — see
onboarding-queue.md) carries the family's first non-Active rows: 260
`LifeCycleStatus='Proposed'` of 208,004. A Proposed address must not be
imported, and today the projection has no status concept at all — every
prior source was 100% Active, so the absence was invisible.

- [ ] `[source_fields] status = "props:<KEY>"` + a declared active-value
      policy, same lie-together pattern as unit/[units]. Gate: blocks any
      consumer of the Niagara dataset; harmless everywhere else.

## Not blocking, worth doing when touching the normalizer

Split `suffix_range` if a rangeless city ever wants the I/O/Q
digit-confusable-suffix half: it could run from `housenumber` alone, but the
whole check is gated on `lo_num`/`hi_num` for now (decided 2026-08-14 with
Tier 2; Hamilton loses nothing — its odd suffixes are street types, not
housenumber letters).

Cheap suffix-table wins measured by the survey: `AV`, `CR`, `BV`, `WY`, `TERR`,
`TL`, `PRIV`, plus French `RUE`/`BOUL`/`PROM`/`CROIS`. Would materially move
Ottawa, Cornwall, Muskoka, SDG and Frontenac, whose gaps are currently
overstated. Rural numbered roads (`County Road 43`) need a rule, not a table.

Guardrail: Toronto's match rates must not move (`tool.db` is living).

## Housekeeping

- [ ] Maintenance run is due ~2026-08-22 (last: `maint-snap90`, 2026-07-23,
      watermark snapshot 90 / 2026-07-22). Unrelated to the above — it conflates
      against live Overpass and needs none of this.
      **Finish the month with `/publish-db ../toronto-2-address-import`.** The
      snapshot is half the month's work and the half that gets skipped: the
      `maint-snap90` month was finalized on 2026-07-23 but never published until
      2026-08-16, leaving `tool-db-20260605` as the newest public record of a DB
      six weeks ahead of it.
      **Enforced 2026-08-16** — it is no longer a convention: `/maintenance`
      refuses to advance the watermark while the month being closed has no
      published snapshot (`t2.maintenance.snapshot_status`,
      `tests/test_snapshot_gate.py`), with an explicit "Advance anyway"
      override for cities that have nowhere to publish. `snapshot.published_*`
      in `kv` is written only by
      `scripts.publish_db --record-published <date>`, which checks the release
      exists first. Toronto is recorded at `tool-db-20260722` and un-gated.
