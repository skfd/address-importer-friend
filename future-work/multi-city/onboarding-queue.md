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
| quinte-west | 2026-08-15 | greenfield (CanVec seed) | import target; contacts Matthew Darwin + CanadianRob; local repo only (gh blocked) |
| cornwall | 2026-08-15 | **PARKED: brownfield-active-informal** | TheRandomGamrTRG adds addresses from the city portal (cs 182902244, 2026-05); contact before anything visible. Scaffold done; local repo only |
| barrie | 2026-08-15 | greenfield (CanVec seed) | import target; contacts Matthew Darwin, Exasecond, useless2764 (active 2026-08); forced the [status] capability + the street-from-full fix; local repo only |
| cambridge | 2026-08-15 | greenfield (StatCan seed) | import target; the Mojgan Jadidi 2016 GTHA campaign (TODO §3 covers it, now 3 cities); 38 Planning Neighbourhoods fabric; local repo only |
| waterloo | 2026-08-16 | greenfield (StatCan seed), active locals | coordinate with jtracey + active locals first; forced number_from="full" + unit="full-after-street"; tracker pulls stopped 2026-06-27 (freshness caveat); addr:province convention is ON here; local repo only |
| kingston | 2026-08-16 | greenfield (CanVec seed) | import target; contacts trigonometric (StreetComplete, active), zzptichka, Matthew Darwin; 40% units (portfolio high); 42-hood fabric; local repo only |
| thunder-bay | 2026-08-16 | greenfield (purest CanVec) | cleanest import target; FWFN jurisdiction question gates upload; forced number_from="props:<KEY>"; contacts Matthew Darwin, eireidium; local repo only |

## Queue (green-tier, in order)

Single-tier cities first, small to large — cheap lessons early. Regional
datasets (durham, york) last, honouring the "Mississauga deferred as first
regional-dataset city" decision: regionals need the per-municipality
ownership map (TODO §5) and should not go first. York's OSM-side numbers are
contaminated by our own Toronto upload — re-measure before trusting any gap.

1. **greater-sudbury** — 53.8% missing; amalgamated.
7. **lambton** — county containing Sarnia: first genuine source-overlap pair
   (lambton ⊃ sarnia); exercises the dedup-on-municipality policy.
8. **ottawa** — largest remaining; 15.3% missing, community-mapped
   (NOT an import target until the etiquette pass says so — the survey's
   "by hand, no import" mapper is owed a conversation; Matthew Darwin is
   the second contact).
9. **niagara-falls** — **reclassified 2026-08-15: a REGIONAL dataset in
   disguise.** The slug names the portal host, but snapshot 21 holds 208,004
   rows across all 12 Niagara municipalities (St. Catharines 54,508; the
   city of Niagara Falls only 39,529, 19%). Deferred with the other
   regionals; needs the per-municipality ownership map (TODO §5) and an
   entry state *per municipality*, not per dataset. Also the family's first
   non-Active rows: 260 `LifeCycleStatus='Proposed'` — the status-filter
   capability (TODO §11) gates any consumer of this dataset.
   **Queue-lesson: read Municipality cardinality from the DB before
   ordering the queue — a slug is not a scope.**
10. **durham** — regional dataset; street name-component only.
11. **york** — regional; OSM baseline contaminated by our Toronto upload.

## Parked pending license review (human decision, not a probe)

yellow-ogl: brantford, dufferin, hastings, huron, kitchener, oakville†
orange-ccby-waiver: brampton
† oakville is also brownfield-active (TronnaLegacy, 2026-08) — do not touch
regardless of license.

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
   Smoke-test `t2.config.load()` via `T2_CITY_DIR`. git init + commit.
   (GitHub repo creation is currently permission-blocked for the agent — leave
   local, note it in the Done row, and ask the user to run `gh repo create`.)
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
