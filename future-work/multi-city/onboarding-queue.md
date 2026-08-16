# City onboarding queue

Started 2026-08-15 at the user's direction: **onboard every OSM-compatible
city now, import later.** The engine should be ready for everything before we
ever import a new city — breadth-first onboarding is how it gets there. Each
city is scaffolded as a thin checkout (the Hamilton/Guelph pattern), its
locked probes run (`04`), and its nuances fed back into the engine and into
the *previous* cities' configs when relevant.

Worked by a self-paced loop, one city per iteration. The loop's contract per
iteration is in the "Iteration recipe" section below; this file is the state.

## Scope rule

`osm_compatible` in `ontario-address-changes/datasets/<slug>.toml` gates entry:

- **green-*** → in the queue.
- **yellow-ogl / orange-ccby-waiver** → NOT scaffolded; parked for a human
  license review (a judgment call, not a probe). Listed at the bottom.
- **red-* / unknown-review** → out.

**Amendment 2026-08-16 (user decision):** datasets whose licence the 2026-08-16
human review verified as ODbL-compatible enter the queue even though the LWG
email is still unsent — scaffolding is invisible and import stays gated on the
LWG reply for the OGL clones. This admits brant (CC0, re-tiered green-cc0, no
LWG needed at all) and the five verified OGL clones: sarnia, dufferin, huron,
brantford, kitchener. Oakville is also a verified clone but stays untouched
(brownfield-active). Their tomls keep yellow-ogl until LWG replies; the queue
entry below records the exception.

Scaffolding ≠ importing. Every city enters as **onboarding** with
`import_plan = ""`; entry state decides the consumer (import vs observer),
and nothing visible happens in any city without its own etiquette pass
(`05`) — contacts owed are recorded per city below.

## Done

| city | date | entry state | note |
|---|---|---|---|
| toronto | 2026-05 | imported | the original; ~449k uploaded |
| hamilton | 2026-08-13 | greenfield | baseline 2: 173,156 civic, 2.9% MATCH; upload gated on TODO §2 |
| guelph | 2026-08-15 | brownfield-complete | QA target; contact ARandomThumbtack_Import before anything visible |
| quinte-west | 2026-08-15 | greenfield (CanVec seed) | import target; contacts Matthew Darwin + CanadianRob |
| cornwall | 2026-08-15 | **PARKED: brownfield-active-informal** | TheRandomGamrTRG adds addresses from the city portal (cs 182902244, 2026-05); contact before anything visible. Scaffold done |
| barrie | 2026-08-15 | greenfield (CanVec seed) | import target; contacts Matthew Darwin, Exasecond, useless2764 (active 2026-08); forced the [status] capability + the street-from-full fix |
| cambridge | 2026-08-15 | greenfield (StatCan seed) | import target; the Mojgan Jadidi 2016 GTHA campaign (TODO §3 covers it, now 3 cities); 38 Planning Neighbourhoods fabric |
| waterloo | 2026-08-16 | greenfield (StatCan seed), active locals | coordinate with jtracey + active locals first; forced number_from="full" + unit="full-after-street"; tracker pulls stopped 2026-06-27 (freshness caveat); addr:province convention is ON here |
| kingston | 2026-08-16 | greenfield (CanVec seed) | import target; contacts trigonometric (StreetComplete, active), zzptichka, Matthew Darwin; 40% units (portfolio high); 42-hood fabric |
| thunder-bay | 2026-08-16 | greenfield (purest CanVec) | cleanest import target; FWFN jurisdiction question gates upload; forced number_from="props:<KEY>"; contacts Matthew Darwin, eireidium |
| greater-sudbury | 2026-08-16 | greenfield, hand-mapped core | TristanA (2013-14 downtown, Kevo-style courtesy owed); status filter load-bearing (896 Retired live); addr:city splits 3 ways (TODO §2 re-generalized) |
| lambton | 2026-08-16 | greenfield county (pure CanVec) | first county checkout; upload gated on Sarnia ownership (TODO §5) + 853 First Nations rows; no boundary polygons published (quadtree); tracker stalled 2026-06-28; addr:city = local municipality |
| ottawa | 2026-08-16 | **brownfield-active-community** | observer/QA confirmed — the community maps from city data via tasks.osmcanada.ca; contacts DannyMcD (active), Undearius, zzptichka, Matthew Darwin; 116 ONS hoods at 100%; 18k qualifier-letter rows gate any import |
| brant | 2026-08-16 | greenfield (CanVec seed) | first licence-review admit (CC0); ward tiles 99.98% (settlement fabric repeated the Quinte West 72% trap); number_from="full" keeps 219 alpha qualifiers; 1,236 number-less rows = TODO §8's second consumer (331 project garbage numbers — skip policy must read the source row); contact riuri (active 2026-08); CanVec wrote addr:city="County of Brant"; **repo local-only: gh repo create classifier-blocked this session** |

## Queue (green-tier, in order)

Single-tier cities first, small to large — cheap lessons early. Regional
datasets (durham, york) last, honouring the "Mississauga deferred as first
regional-dataset city" decision: regionals need the per-municipality
ownership map (TODO §5) and should not go first. York's OSM-side numbers are
contaminated by our own Toronto upload — re-measure before trusting any gap.

**Reopened 2026-08-16** by the licence-review amendment above: six
review-verified datasets, small to large (row counts + municipality
cardinality read from the tracker DBs 2026-08-16 per the niagara lesson).
Import for the five OGL clones stays gated on the LWG reply
(`future-work/multi-city/license-contacts-todo.md`).

1. **sarnia** — 26,896 rows; city-published layer inside Lambton County.
   The lambton/sarnia pair is a true source overlap — apply the
   municipality-attribute dedup policy and let this checkout settle the
   Sarnia-ownership question gating Lambton's upload (TODO §5 note).
   No unit field; 11 hyphenated STNUM values are ranges, nothing to parse.
2. **dufferin** — 27,075 rows; county of 8 lower-tier municipalities with
   NO municipality field in props (thinnest schema yet: FULLADDY, ID,
   STREETNAME, STREETNUM). addr:city needs boundary polygons or a spatial
   join. Single snapshot 2026-06-11 — stalled-tracker freshness caveat.
3. **huron** — 38,312 rows; county, 9 municipalities via clean `Mun` field;
   rich NENA-style schema (Unit, St_PosTyp, FullAddress_Mun).
4. **brantford** — 38,984 rows; city. STNUM has embedded parseables (the
   contrast case named in sarnia.toml); STREETNUMIN numeric companion.
5. **kitchener** — 132,060 rows; city. 4,380 `STATUS='PENDING'` rows — the
   status-filter capability (TODO §11) is load-bearing here.

Regionals remain deferred on the per-municipality ownership map (TODO §5) —
a design decision, not an onboarding probe:

6. **niagara-falls** — **reclassified 2026-08-15: a REGIONAL dataset in
   disguise.** The slug names the portal host, but snapshot 21 holds 208,004
   rows across all 12 Niagara municipalities (St. Catharines 54,508; the
   city of Niagara Falls only 39,529, 19%). Deferred with the other
   regionals; needs the per-municipality ownership map (TODO §5) and an
   entry state *per municipality*, not per dataset. Also the family's first
   non-Active rows: 260 `LifeCycleStatus='Proposed'` — the status-filter
   capability (TODO §11) gates any consumer of this dataset.
   **Queue-lesson: read Municipality cardinality from the DB before
   ordering the queue — a slug is not a scope.**
7. **durham** — regional dataset; street name-component only.
8. **york** — regional; OSM baseline contaminated by our Toronto upload.

## Parked pending license review (human decision, not a probe)

Updated 2026-08-16 after the licence review: brantford, dufferin, huron,
kitchener moved to the queue (verified OGL clones); **hastings moved OUT of
the OGL bucket** — its "Open Government Licence" is aspirational, no licence
document exists; it now sits in the no-published-licence contact bucket
(`license-contacts-todo.md` §C) and its toml is re-tiered unknown-review.

yellow-ogl: oakville†
orange-ccby-waiver: brampton
† oakville is a verified OGL clone but also brownfield-active (TronnaLegacy,
2026-08) — do not touch regardless of license.

## Iteration recipe (one city per loop iteration)

1. **Locked probes** (`04`), all against the tracker DB + city's own portal:
   source profile (rows, snapshot, extent, unit/postcode/ward coverage,
   street form), civic-collapse measurement if units exist, polygon-fabric
   probe with point-test coverage (multiple Hub search terms — "neighbourhood"
   alone missed Guelph's), boundary layer noted for `10`.
2. **Entry-state probe**: add the city to `scripts/entry_state_probe.py`
   (sample boxes density-checked against the source first), run it, keep the
   JSON as `onboarding/entry-state-<date>.json` in the checkout. The
   recent-activity check is not optional (Oakville lesson).
3. **Scaffold** `<slug>-address-import` from the Guelph template: config.toml
   with dated probe evidence in comments, README with entry state + contacts,
   `[prior_import]` block when one exists, `import_plan = ""` always.
   Smoke-test `t2.config.load()` via `T2_CITY_DIR`. git init + commit, then
   `gh repo create <slug>-address-import --public --source=. --remote=origin`
   and push (permission granted 2026-08-16; all 11 checkouts published then).
4. **Feed lessons back** — the point of the exercise:
   - engine/docs: update `04`/`05`/TODO/DONE and this file with any new
     nuance; small engine fixes done in place, larger ones as TODO items.
   - **previous cities**: re-read the Done table's configs against the new
     lesson; apply and commit where relevant (the Hamilton-neighbourhoods
     lesson retroactively fixed a config — expect more of these).
5. **Update this file** (move the city to Done, note nuances) and the memory
   store. Commit engine + checkout; push repos that have remotes.
6. **Stop conditions**: queue empty → stop the loop and summarize. Any
   probe requiring a judgment call the docs don't cover (ambiguous prior
   import, license doubt, live activity) → park the city with a note and
   move on; if everything is parked, stop and report.

Overpass etiquette: one city's entry-state probe per iteration, iterations
spaced ≥20 minutes apart, never full-city queries (`08`'s rule).

## After the first upload: publish a snapshot

Not part of an onboarding iteration — a scaffolded city has no `tool.db` worth
publishing yet — but the step that closes the loop once a city actually starts
importing, and the one that was missing until 2026-08-16.

The moment a city's first production upload lands, run
`/publish-db <city-dir>` (engine-level command; `scripts/publish_db.py`) to put
a dated, credential-scrubbed snapshot on the city repo. That artifact is the
first durable record of what the import pushed — `runs` + `changesets` are the
source of truth for which addresses are live in OSM, and until it is published
that record exists only on one laptop. Repeat after each finalized maintenance
month. There is no terminal "import done" release: the DB stays living.

Two blockers to expect: the web app must be stopped for **that** city (it locks
only its own `--city-dir`), and most onboarded cities are **local-only** — the
script builds and verifies the artifact but cannot publish until someone runs
`gh repo create`.

Finish with `--record-published <YYYYMMDD>`: the maintenance page will not let a
city close its next month until that record exists (the gate added 2026-08-16;
"Advance anyway" is there for the local-only cities, which cannot satisfy it).
