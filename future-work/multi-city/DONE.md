# Multi-city — completed

Finished items, split out of [TODO.md](TODO.md) on 2026-08-13 so the action
list carries only open work. Kept because several open items depend on what was
decided here, and the reasoning is not recoverable from the code.

Full context lives in [08-survey-results-2026-08-12.md](08-survey-results-2026-08-12.md).

## Street normalizer extracted into `accordeur` (`01`) — DONE 2026-08-28

The family has two engines and six datasets now, and one table answering "are
these the same street" was being maintained in two of them. It is one package:
**`accordeur`** (github.com/skfd/accordeur), a standalone sibling checkout both
engines install with `pip install -e ../accordeur`.

**The rot `01` predicted had already happened.** That document warned on
2026-08-10 that a divergence between the copies "rots silently — a street
override added to one copy makes the two tools disagree about whether an
address is present, with no error anywhere." By 2026-08-28 there were two:

- The importer gained Cornwall's `AV`/`CR`/`BV`/`WY` suffixes on 2026-08-15.
  The beholder's copy never got them.
- `normalize_street` had drifted semantically. The beholder glued a standalone
  "Mc" onto the following word; the importer did not, because it glued earlier,
  in `expand_street_name`, at ingest.

Nothing anywhere noticed either. They were found by diffing the two modules
while planning the extraction, which is the argument for doing it: this class
of bug has no symptom until someone compares the two tools' answers by hand.

**Two divergences had to be resolved rather than merged.**

- *Tables:* took the superset. Checked first — `AV`/`CR`/`BV`/`WY` appear zero
  times in the toronto, guelph, hamilton or quinte-west source DBs and zero
  times in Toronto's or Guelph's OSM `addr:street` values, so adding them to
  the shared table moves nothing in either engine.
- *Mc-gluing:* unified on gluing, the beholder's behaviour, because the
  symmetry invariant demands it — OSM writes "McCaul Street" joined, so a raw
  source "Mc Caul St" must reach the same key without depending on having been
  expanded first. The exclusion list took the importer's superset, so "Mc St"
  is no more a surname than "Mc Street" is.

**The override table went the other way — out of the engine, into the city.**
`STREET_NAME_OVERRIDES` was a module constant in `t2/conflate.py`: thirteen
Toronto streets where the City source and OSM disagree about the actual name.
Guelph and Hamilton had been ingesting through it since they were scaffolded.
It is now `[streets] overrides` in the city checkout, the same shape the
beholder already shipped, absent section = no overrides. A no-op entry — one
the normalizer already covers — is refused at load.

It fired on nothing outside Toronto: none of the thirteen keys appears in
`hamilton.db` or `guelph.db` (all thirteen appear in `toronto.db`), which is
why this is a move and not a re-baseline. That it was harmless was luck, not
design — the failure mode is a curated Toronto table silently rewriting another
city's street names, and nothing was preventing it.

**Both engines' guardrails were checked by comparison against the deleted
code, not by argument.**

- *Importer:* old and new run over every distinct street string in the toronto,
  guelph and hamilton tracker DBs and every cached OSM extract — 627,572 of
  them. The ingest path (`street_raw`) and the stored `street_norm` are
  byte-identical in all of them, so Toronto's match rates cannot move.
- *Beholder:* the deleted module and `accordeur` over Toronto's and Guelph's
  full vocabulary — 602,960 strings — comparing `normalize_street`,
  `collapse_conventions` and `StreetProfile.norm` under Toronto's thirteen.
  Zero differences, so no dataset's PRESENT/MISSING counts or audit findings
  move.

**One deliberate behaviour change, outside conflation.** Because
`normalize_street` now glues "Mc" itself, the importer's reports that normalize
a *raw* source name — ranges coverage, `/source/multi`, the OSM-not-in-source
sweep — stop producing "MC CAUL ST" while the candidate and OSM both say
"MCCAUL ST". 353 Toronto source strings across nine streets stop failing to
match themselves. Stored candidate values are unaffected, which is why this
lands as a fix rather than a re-baseline.

**Decision 10 was amended, deliberately.** The README said the library would be
built inside this repo and split out later. The trigger `01` itself named —
"split out when the seam holds" — had fired: `StreetProfile` shipped and held
in the beholder, and a second engine consumer existed. A package nested here
would have made `address-beholder` depend on the importer checkout, against
`07`'s first guardrail ("do not couple it to `t2`"). Recorded here rather than
done quietly, because the `guelph-beholder` fork was a lesson about exactly
that.

What did **not** move, and is still open in `01`: the conflation primitives
(`GridIndex`, `haversine`, `_is_poi_node`), the SCD-2 source-DB projection, and
the deterministic onboarding probes. Each wants its own pass and its own
verification; bundling them would have made one unverifiable change out of
four verifiable ones.

State: `accordeur` 39 tests, importer 212, beholder 65.

## Beholder generalization (`07`) — DONE 2026-08-28

`07`'s first-implementation-target status held, three weeks late: the engine is
**`address-beholder`** (github.com/skfd/address-beholder, private), with
`toronto-import-beholder` and `guelph-beholder` reduced to thin dataset
directories carrying one `config.toml` each. The house pattern again — the
*new* repo is the engine, so neither city repo's name or URL moved. The seam is
`run.py --dataset-dir` / `BEHOLDER_DATASET_DIR`, mirroring `T2_CITY_DIR`.

**How it got here matters for the next one.** `guelph-beholder` was built on
2026-08-27 as a *fork* of the Toronto beholder, in ignorance of this folder —
the fork/generalize decision was made from the `*-address-import` repo pattern
without reading `07`. That was caught the next day and the fork became the
engine, but the lesson is cheap to state: the plan existed and was not
consulted, because nothing in the beholder repos pointed at it. Both dataset
READMEs now link here.

What `07` asked for, and what actually happened:

- **Config slug-driven** — done, and further: `[source_fields]` projects a
  tracker row (column / `props:KEY` / absent), so Toronto's
  `MUNICIPALITY_NAME`/`LO_NUM`/`HI_NUM` and Guelph's `PLACE`/`WARD`/`POSTCODE`
  differ only in TOML. Same Tier 2 contract as `02`, arrived at independently.
  Undeclared disables the dependent feature rather than failing open (`03`).
- **Boundary polygon** — *not* done. The bbox is still a rectangle and Guelph
  still bleeds into Eramosa; `10` stays open.
- **`streets.py` deleted in favour of the core** — half done, deliberately. The
  engine owns *one* profile-driven copy (`[streets] overrides`) instead of the
  three that existed, and `StreetProfile` is the seam that moves into
  `accordeur` when `01` is built. Waiting for `01` would have blocked this.
- **Notes → adjudications (`06`)** — not started; still a local table.
- **Per-dataset allowlist** — done, by construction: the allowlist is in the
  dataset's config, and the engine has none.
- **Deployment shape** — single-set is what exists; `create_app` takes one
  dataset and the pages are named from `[dataset] name`. Multi-set is not built.

**Two design decisions `07` did not anticipate**, both forced by Guelph:

1. **Readings.** Guelph's 2025 import wrote units into the housenumber, so its
   conflation must accept `addr:housenumber=714-30` as civic `714`. That is a
   fact about one city's data on one set of dates, so it is a *plugin* in the
   dataset directory (`guelph-beholder/readings.py`), deleted when the split
   campaign lands. The engine reads addresses literally. Two guardrails: a
   plugin reading must rank below the literal one, so correct tagging always
   wins the match; and readings only add candidate keys, so a bad plugin can
   never hide a real address. The user's framing decided this — "if we allow
   something like that it should be some pluggable piece not part of engine".
2. **A correctness audit beside present/missing.** `07` scoped the beholder to
   coverage. It now also checks postcode, `addr:city`, street literal, match
   distance, duplicate objects and deprecated tags, per point, with the issue
   set part of the append-on-change tuple.

**The acceptance test was `07`'s third guardrail** — a Guelph-driven change that
moves Toronto's counts is a regression. Over 523,835 points the engine
reproduces the old code's per-point `(status, osm_ref)` digest exactly
(`bbe3b978…`). It caught one: a distance rounding introduced during the Guelph
work let a marginally-further element tie and win on insertion order,
reassigning 16 points.

**Scale taught the audit three lessons Guelph could not**, all now engine
behaviour:

- `street_spelling` must compare *after* collapsing suffix and direction
  abbreviations. Toronto's short-form source against OSM's long-form tags gave
  490,076 findings; after the fix, 67.
- A tag absent from OSM is only a defect if the tagging plan promised it
  (`[audit] expect_tags`). Toronto writes no `addr:city` by design and its
  source municipality is the *former* municipality where OSM says "Toronto":
  512,885 false `city_mismatch` findings.
- An issue carried by most of a city is a bulk campaign, not a per-address
  defect (`[audit] campaign_issues`). Toronto's `duplicate_osm` covers 95,639
  addresses; drawing them made the map 16.5 MB of amber hiding 452 red.

Guardrail 2 (append-only history) held: `init_db` adds missing columns to an
older DB and reports them, so Toronto's 2026-06-06 and 2026-08-10 runs are still
readable beside the runs under the engine.

State: Toronto 523,383 present / 452 missing; Guelph 45,397 / 8,449 with 7,216
matches resting on a workaround reading. 68 tests.

## Hamilton neighbourhoods layer + orphan policy — DONE 2026-08-15

The 2026-08-13 config comment "Hamilton has no neighbourhood polygon layer"
was an unverified absence claim, and it was wrong. Open Hamilton publishes
**"Neighbourhoods"** — 234 planning-unit polygons, the direct analogue of
Toronto's 158 — found via the Hub search API (portal pages are JS shells;
see the cheat sheet in `05`). Point-tested before adopting: 99.99% of the
273,374 snapshot-36 addresses fall inside; 27 orphans citywide.
`neighbourhoods_url` set; 657 natural tiles replaced the 680 bbox squares
(prior runs dropped deliberately — pre-announcement Hamilton is the lab
mouse). This is the **second** wrong absence claim in two days (units were
"unmapped" while props carried them at 36.8%) — the rule that absence claims
need dated probe evidence is now in `04`.

Two engine changes fell out, both generic:

- **Duplicate feature names get a community prefix.** Hamilton repeats
  neighbourhood names across and within its former municipalities (ten
  distinct "Industrial" units). `build_tiles` now pre-counts base names and
  prefixes only ambiguous ones with the layer's COMMUNITY-style field
  ("Stoney Creek Industrial"); a name equal to its community is never
  doubled; same-name-same-community leftovers keep the `-N` id dedup.
  Toronto unaffected (unique `AREA_NAME`s, no community field).
  `tests/test_tiles_duplicate_names.py`.

- **Every orphan gets bucketed — the >=1% gate is gone.** The old
  `ORPHAN_BUCKET_PCT` silently stranded sub-1% orphans in no tile:
  unreachable from the picker and from Run-for-All (Hamilton: 27 addresses,
  38 of the published-geometry stragglers outside every tile *bbox* too).
  Latent until now — Toronto's layer covers wall-to-wall (0 orphans) and the
  no-layer path can't orphan by construction. The naive fix has a trap: 27
  points ≤ threshold means the catch-all ring never splits, one tile whose
  bbox — and therefore whose runs — spans the whole city. So layer-backed
  orphan pieces are force-split below `ORPHAN_MAX_SPAN_DEG` (~1 km) and the
  merge pass absorbs them into bordering real tiles. Measured on Hamilton:
  26 of 27 absorbed into 7 real tiles, 1 genuinely isolated address kept as
  its own visible tile, 0 orphans, no megatile (max span ~9 km, a rural
  tile). The no-layer path deliberately skips the cap — big rural tiles are
  the point there. `tests/test_tiles_orphans.py`.

Also: `NEIGHBOURHOOD` (bare, all-caps) added to `_feature_name`'s key list —
which is itself now a recorded tension, see the Tier 4 note in `02`.

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

## Campaign wrap-up page — DONE 2026-08-28

Toronto's final stats one-pager (`docs/wrap-up.html` in the city checkout) was
hand-authored: every figure a literal, every bar height an inline style. Wanted
for every import from Guelph onward, so it had to become a generator.

**Nothing needed instrumenting.** Every number on the page was already in
`tool.db` — the pipeline writes `events`, `runs`, `changesets`, `candidates`
and `conflation` as it goes — plus `tiles.json` for the area rollup. A city's
page can therefore be generated long after its last changeset closed, and
Guelph needs no preparation before it starts. `t2/campaign_stats.py` reproduces
the published Toronto figures exactly: 768,888 source pool, 449,052 uploaded,
206,621 duplicates, 8,967 streets, 1,297 changesets, 627,390 auto / 38,373
manual, 16 days, 25 sessions, all five top streets, every bar of the daily
chart.

Three definitions had to be pinned down, none of which the hand-made page
recorded:

- **Scope is the import, not the database.** Monthly maintenance runs share the
  city's `tool.db` and stretched Toronto's campaign from 16 days to 108, with a
  bar chart of 92 empty days. Excluded via the `maintenance` key
  `t2/maintenance.py` already writes into `runs.config_json` — the marker it
  deliberately stores on the run "rather than infer it from the name". The tail
  is reported as a footnote instead of vanishing.
- **Hands-on time is a session-gap threshold**, and there is no clock in the
  schema, so the threshold *is* the definition. The published "65h across 25
  sessions" used a value nobody wrote down (near 50 minutes). 30 minutes is now
  the documented default — it reproduces the 25 sessions — and
  `[stats] session_gap_minutes` overrides it.
- **`REVIEW_CLEARED` is presence, not a decision.** It reverts one, so counting
  it would tally a candidate twice. Excluding it yields the published 38,373;
  the hand-made page had made the same call silently.

Shipped as a Flask route (`/stats`) plus
`python -m t2.static_export --stats` → `<city-dir>/docs/stats/index.html`. The
template does not extend `base.html`: its CSS is inline so the exported file
survives being emailed or opened with no server. Below 100% of tiles uploaded
it renders an "import in progress" notice with the figures so far, rather than
a dead link or a half-filled wrap-up — the state Guelph will sit in for its
whole run.

Presentation comes from an optional `[stats]` block (Tier-2 style: absent
section = engine defaults, never a silent inheritance of Toronto's identity).
The default palette is the operator animation's own legend colours, so a city
that declares nothing still gets two artifacts that look related; Toronto's
config carries the TTC subway colours its page was built in.

Folded into the same pass: `scripts/build_operator_animation.py` read paths
from config but still wrote "Toronto" into its title and heading, and wrote
into the **engine's** `docs/` rather than the city checkout's — a second city
would have got a mislabeled page in the wrong repo. It now takes the name from
`[city] name`, writes to `_config.CITY_DIR`, and shares
`campaign_stats.OPERATOR_EVENTS` so its action count and the wrap-up's clock
cannot drift apart.

The animation takes the same scope. It was already free of maintenance, but by
accident: maintenance runs are named `maint-snapNN`, which matches no tile id,
so they fell out of its name-based tile lookup. That is a naming convention
doing a scope's job. It now filters on `campaign_stats.IMPORT_RUNS` like the
wrap-up does. Verified a no-op on Toronto's data — tiles, events and gaps are
byte-identical either way, and identical to the artifact committed in May, so
the published page needed no refresh.

## Housekeeping

- [x] The multi-city line of work is pushed — `659467f` (design docs) through
      `33cdd12`, pushed 2026-08-13. `main` is in sync with `origin/main`.
