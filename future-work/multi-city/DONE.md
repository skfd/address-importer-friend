# Multi-city — completed

Finished items, split out of [TODO.md](TODO.md) on 2026-08-13 so the action
list carries only open work. Kept because several open items depend on what was
decided here, and the reasoning is not recoverable from the code.

Full context lives in [08-survey-results-2026-08-12.md](08-survey-results-2026-08-12.md).

## Units decision + baseline 2 — DONE 2026-08-14

`09` option 2 taken for Hamilton: **collapse to civic now, design unit-level
import separately** — as engine config, not a city hack. `[source_fields]`
gained `unit` (`"unit"` | `"props:<KEY>"`); declaring it *forces* a `[units]
policy` at config load, so a unit-bearing source can never again silently
flood review (Guelph and Mississauga hit this guard on onboarding day). The
one policy, `collapse-to-civic`, wraps all three source iterators (ingest,
new-since, retired-since — maintenance inherits it) in a window election:
one row per **(number, street, municipality)**, unit-less row preferred,
lowest `identity_key` as tie-break.

Two corrections the implementation forced on `09`'s numbers:

- **Municipality is part of the civic key.** 776 `(number, street)` pairs span
  Hamilton's former municipalities; the bare key would merge 818 real
  addresses. Collapsed set: **173,085**, not 172,267.
- **Baseline 1's MATCH was stack-inflated too, by 3×.** Distinct-civic recount
  of the archived DB: 5,038 MATCH / 777 MATCH_FAR / 167,196 MISSING — the
  "9.4% MATCH" headline was unit rows riding their parcel's match. Stacking
  concentrated where OSM coverage is (downtown towers), so it flattered
  exactly the number used to judge coverage.

**Baseline 2** (same snapshot 36, same PBF, fresh DB; baseline 1 archived as
`tool.db.baseline1-preunits`): 680/680 tiles green, 173,156 candidates →
**2.9% MATCH, 0.4% MATCH_FAR, 96.7% MISSING**; matches baseline 1's
distinct-civic recount within 0.3%, so the collapse provably lost nothing.
Review queue: 96,267 → **5,103** (`city_duplicate` 91,638 → 910 — the noise
prediction held). Known artifact: +71 rows over 173,085 from per-tile-bbox
election on groups wider than a tile (0.04%). Review triage is unblocked;
upload still waits on TODO §2. Tests: `tests/test_units_collapse.py` (14
cases); Toronto guardrail by construction — no policy, no wrapper, and the
byte-identical projection test still pins Toronto's SQL.

## Tier 2 source projection + capability gating — DONE 2026-08-14

The real work of `02`, and the dangerous half of `03`. The engine no longer
bakes in Toronto's props keys anywhere.

**New required config block: `[source_fields]`** — the per-city projection
recipe. `street_from` / `full_from` are mandatory (no default, so a config
cannot silently inherit another city's street resolution); the optional keys
(`municipality`, `ward`, `lo_num(_suf)`, `hi_num(_suf)`, `address_class`) are
*capabilities* — absent means the projection emits SQL `NULL` and dependents
are disabled-for-cause. Unknown keys raise (a typo would otherwise silently
drop a capability).

**`_ADDRESS_COLS` is generated** (`source_db.build_address_cols`, pure, plus
`source_db.expr()` for callers building their own source queries — `ranges`
and `source_multi` now go through it instead of embedding `$.LO_NUM`
literals). The guardrail held by construction: a test asserts Toronto's
declaration generates the pre-Tier-2 SQL **byte-identically**, and a live
smoke test against both checkouts confirmed Toronto unchanged and Hamilton
projecting correctly (31,279 rows in the Gore Park test bbox; synthesized
`address_full`, typed streets, `COMMUNITY` as municipality, NULL ranges).

**Checks declare `requires`** (logical `[source_fields]` names). At run start,
a check whose requirements the city lacks is forced off; the run UI shows
"n/a — source declares no lo_num, hi_num" instead of an operator toggle, so
*could not run* is never mistaken for *ran and found nothing* or for a
choice. Gated for Hamilton: `suffix_range` (no ranges) and
`intra_source_duplicate` (no address class). The reason is derived from config
at render time, not persisted — the recipe is git-tracked in the city
checkout, so no schema change.

**A config that explicitly enables an impossible check fails the run start**
(`ValueError` naming the missing fields) rather than being silently
overridden — Hamilton's config.toml had exactly this bug (`suffix_range =
true`, copied from Toronto's) and now documents why the line is absent.

**Two judgement calls.**

1. *`suffix_range` gates whole*, though its I/O/Q-suffix half could run from
   `housenumber` alone. Splitting the check is deferred until a rangeless city
   demonstrably wants suffix flagging (noted in TODO "Not blocking").
2. *Hamilton's `street_from` is `"street"`, not props.* The survey's
   `street_source: "props"` described the survey's own resolution recipe;
   Hamilton's tracker TOML already maps `street = FULL_STREET_NAME`, typed and
   100% populated. The correction in `02` ("canonical fields are not
   conflation-ready") stands portfolio-wide — it just isn't Hamilton's case.

The Land Entrance skip reads its props key from config too
(`address_class_key`), so it is Toronto-only by construction now, not by
string literal. What `03` still leaves open: **measured** capabilities
(`has_street_type` evaluated after resolution, refusal printing the values it
judged) — the declared-field half is done, the measured half is not.

## Repo-per-city split — DONE 2026-08-13

The single Toronto repo became three, following the `address-layerist` house
pattern (engine + thin per-city checkouts):

- **`address-importer-friend`** (this repo) — the engine, created as a fork of
  `toronto-2-address-import` with full history, then slimmed of Toronto docs.
  `run.py --city-dir <checkout>` / `T2_CITY_DIR` selects the city; config,
  `.env.*`, and all `data/` state resolve against it (`t2/config.py CITY_DIR`).
- **`toronto-2-address-import`** — kept its name, URL, Pages site, and
  releases; slimmed to the proposal, evidence, `config.toml`, and (local)
  `data/`. Import milestones tagged: `import-start` (2026-05-13),
  `import-complete` (2026-05-28, 1,297 changesets), `maint-1`, `maint-2`.
  The tags predate the fork, so they exist in both histories.
- **`hamilton-address-import`** — new thin checkout for city #2, config
  drafted from the measured source extent; no runs yet.

The beholder got its milestones tagged too (`v0.1` — built in one day,
2026-06-06 — and `upstream-restructure`, 2026-08-10) but stays a separate,
Toronto-coupled tool pending `07`.

This split is repo layout only — it does not prejudge the `accordeur`
library extraction (`01`), which remains open and happens inside this repo.

## Tier 1 de-Torontoization — DONE 2026-08-13

The mechanical half of `02`'s coupling list. Every Toronto literal that a second
city would have had to edit code to change is now config.

**New in `config.toml`:** a `[city]` block (`slug`, `name`) and an `[export]`
block (`attribution`, `import_plan`). `[osm] toronto_bbox` is now
`[osm] city_bbox`; `cfg.osm_toronto_bbox` is `cfg.osm_city_bbox`.

**The filename.** `toronto-addresses.json` was a literal in nine places. It is
now one property, `cfg.osm_extract_json` = `extract_dir/<slug>-addresses.json`.
With `slug = "toronto"` it resolves to the existing file, so **no data
migration** — the 94 MiB extract on disk is still the one stage 2 reads.

**Two deliberate choices.**

1. *No defaults for city identity.* `[city] slug`/`name` and `[osm] city_bbox`
   raise at config load if absent, naming the old key in the message. A default
   would let a stale config clip Hamilton to Toronto's rectangle and look like
   it worked — the failure mode `03` warns about, where a bad reading is
   indistinguishable from a bad dataset.
2. *Attribution is checked at upload, not at load.* `[export] attribution` and
   `import_plan` are optional to load and raise inside `osm_export.build_tags` /
   `changeset_tags`. A city can conflate and be reviewed before its attribution
   string and wiki page exist; it must never upload without them. This keeps
   Tier 1 from blocking TODO §1's conflation on TODO §2's wiki page.

**Persisted-key rename.** `meta.json` and the streets artifact write `city_bbox`
now. `streets.html` reads `data.city_bbox or data.toronto_bbox`, so pages
computed before today still render.

**Guardrail held.** Toronto's emitted tags are byte-identical — `source=City of
Toronto Open Data`, the same `import_plan` URL, and the templated changeset
comment still renders `Toronto Open Data address import, run={run_name}`. 70/70
tests pass; `/osm`, `/osm/multi`, `/data`, `/streets` and `/` all render. Nothing
in conflation was touched, so match rates cannot have moved.

Not included, and still Toronto-specific by design: the footer links and the
proposal/repo URLs in `base.html`, which name the project rather than the import
target.

## Slugged data layout — DONE 2026-08-13

Not on `02`'s tier list — surfaced when planning the Hamilton switch: Tiers 1
and 4 made the *code* city-neutral while the *data layer* stayed a Toronto
singleton. Flipping `config.toml` to Hamilton would have overwritten Toronto's
`tiles.json` and interleaved Hamilton runs into the living `tool.db`, where
`runs.source_snapshot_id` would become silently ambiguous — snapshot ids are
per-source-DB (see `memory/maintenance_tool.md` for the id-translation trap).

**The move, not the migration.** Per-city state now lives under
`data/<slug>/` — `tool.db`, `tiles.json` + `tiles/`, `neighbourhoods/`,
`streets.json`, `osm_current_run*.json`, `upload_run_*.osm`, `multi_fixes/`,
sweep/status files. Deliberately **no** `city` column in `tool.db`: decision 7
(README) makes the dataset the unit of work, so isolation is by database, not
by row — no migration on a living 2 GiB DB, no filter on every query forever,
and each DB's snapshot ids mean what they always meant.

Stays at the shared `data/` root: `osm/` (one Ontario PBF serves every city;
the filtered jsons are already slugged), `osm_auth.json` (the OAuth token
belongs to the OSM account, which uploads for all cities — switching `[city]`
must not force a re-login), `release/`, `archive/`, and the one-off artifacts.
`cfg.data_root` names it; `cfg.data_dir` is now `data_root/<slug>`.

A guard in `config.load()` refuses to run when `data/tool.db` exists at the
root but `data/<slug>/tool.db` does not — a checkout with new code and
unmigrated data would otherwise start a fresh empty DB beside 1,300 runs of
history. (Verified to fire on the true unmigrated branch; both-exist is fine —
the slugged DB wins.)

Toronto's 1,311 files were moved 2026-08-13 (WAL was checkpointed; no -wal/-shm
existed). Verified after the move: 1,301 runs / 768,976 candidates readable,
1,297 tiles load, 73 tests pass, and the dashboard renders byte-identical to
before the move. `scripts/publish_db.py`, `build_operator_animation.py` and
`count_entrance_addrs.py` now derive paths from config instead of hardcoding
`data/`; `merge_v1_living.py` was left untouched as a record of a completed
one-off against the old layout.

## Tier 4 no-neighbourhood-layer fallback — DONE 2026-08-13

`02` predicted the quadtree was already generic and only needed a fallback.
That was right, and stronger than expected: **the fallback was already there**,
unreachable. `build_tiles` bucketed addresses falling outside every polygon into
an "Unassigned" tile built from `city_rect.difference(union(hoods))`. With no
features at all, that union is empty and the leftover *is* the whole city
rectangle — so the existing orphan branch already tiles a bare bbox correctly.

So the change is small: `[city] neighbourhoods_url`, optional. Empty means
`run()` skips the HEAD and download entirely (verified: it raises if `_head` is
called) and passes no features. `build_tiles` gained one parameter,
`orphan_name`, so those tiles are named after the city rather than
"Unassigned" — nothing was assigned elsewhere, so there is nothing for them to
be unassigned from. Default is still `"Unassigned"`, so the layer-backed build
is untouched.

Also folded the two builds' identical 40-line tail into `_write_tiles`, so
`tiles.json` and the sidecar cannot drift between the paths.

**Guardrail held, measured rather than argued.** Running the pre-change
`build_tiles` and the new one over the same 158 neighbourhoods and 525,473
points at snapshot 104 gives byte-identical tiles and identical stats — 1,297
tiles, 0 orphans. (Diffing against the committed `data/tiles.json` instead is
misleading: it differs in `address_count` on 132 tiles because it was built at
snapshot 37. Geometry, ids, names and parents match it too.) `data/tiles.json`
was not rewritten.

New: `tests/test_tiles_no_layer.py` — 1,600 points, no features; asserts every
address lands in a tile, no tile exceeds the hard ceiling, tiles carry the city
name, and the default is still "Unassigned". 73 tests pass.

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
