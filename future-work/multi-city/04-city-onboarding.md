# City onboarding

Status: **proposed, not implemented.** Captured 2026-08-10.

## Motivation

On 2026-08-10 the question "should Guelph be city #2?" was answered by hand, in
about six tool calls, and the answer reversed the plan — Guelph turned out to
be 94% already imported by someone else. That investigation should be a
capability of the platform, not something a person improvises per city.

`address-layerist` already established the split to use: **locked vs fuzzy**.
Deterministic machinery in the engine; judgment in a Claude Code skill
(`address-layerist/skills/onboard-city/SKILL.md`).

## Locked — deterministic probes, belong in the core library

Each of these is a pure function of inputs that can be re-run and diffed:

- **Source profile.** Open the city DB, read the latest non-skipped snapshot,
  tally `props` keys and their population rates, detect which of the optional
  capability fields exist (`03`), measure unit and postcode coverage, compute
  the data's own bbox.
- **OSM state.** Count `addr:housenumber` elements in the city's extent, split
  by element type (node vs way vs relation) — the node/way ratio alone tells you
  whether addresses sit on buildings or as standalone points.
- **Gap size.** Distinct `(housenumber, normalized street)` in source but not
  in OSM, and the converse. This is the go/no-go number.
- **Gap distribution.** Bucket missing addresses into ~500 m cells. Concentrated
  → an un-done region. Diffuse → leftovers plus new construction. (Guelph:
  255 cells, top 20 holding only 48% — diffuse.)
- **Provenance.** Tally last-touch editors and years; fetch changeset tags for
  the top-N changesets; extract `import=yes`, `import:page`, `source`,
  `source:license`. See `05`.
- **Neighbourhood-layer probe** (added 2026-08-15, from the Hamilton lesson —
  see DONE.md). Search the city's ArcGIS Hub for polygon datasets matching
  neighbourhood/community/planning/ward (the search API, not the portal pages —
  `05` has the cheat sheet). For each candidate: feature count vs the service's
  `maxRecordCount` (paging risk), `contentStatus` (Hub returns deprecated
  datasets), the name and parent-area fields, and — the go/no-go number —
  **point-test coverage**: what fraction of source addresses falls inside the
  polygons. Hamilton's probe would have printed "Neighbourhoods: 234 polygons,
  99.99% coverage" and made the tiling decision trivial; instead the city ran
  for a day on bbox squares because of an assumed absence.
  Two refinements from Quinte West (2026-08-15): probe **every** polygon
  candidate, because the best-*looking* layer can fail — its Planning
  Districts (81 polygons, "planning" in the name, exactly the Hamilton shape)
  point-tested at 63%: a settlement fabric that excludes rural wards, while
  the unglamorous 4-polygon ward layer scored 99.87%. And when the Hub search
  API returns nothing useful, list the org's services directory directly
  (`https://<org>.arcgis.com/ArcGIS/rest/services?f=json`) — Quinte West's
  hub search missed layers its own directory listed. Report the name field
  per candidate: the winner kept its name in `mapguide`, findable only by
  reading attribute values, which is why the tile builder's name field is now
  declared config (`02`, settled).

Use the **Geofabrik PBF, not Overpass**, for the OSM side wherever possible.
`t2/osm_refresh.py` already downloads `ontario-latest.osm.pbf`, and one pass
covers every city in the portfolio. Running 42 full-city address queries against
the volunteer-run public Overpass instance would be rude and slow.

## Fuzzy — judgment, belongs in a skill

None of these have a deterministic answer:

- Is `ARandomThumbtack_Import` an import account, or a prolific mapper whose
  name merely ends in `_Import`? (The `_Import` suffix is a strong OSM
  convention, but it is a convention, not a rule.)
- Is the wiki page found in `import:page` the authoritative one, and is the
  import complete, stalled, or active?
- Does the prior import's `source:url` point at the same layer our
  `datasets/<slug>.toml` uses? For Guelph the two URLs differ textually and
  **resolving them was a genuine judgment call that turned out to have a
  deterministic answer** — see the resolved case in `05`. The lesson for the
  skill: URL inequality is not evidence of different data; resolve through the
  ArcGIS Hub API before concluding anything.
- Which street-name disagreements are genuine overrides vs normalizer gaps?
- Is this a city we should show up in at all? (`05`, etiquette section.)
- Which candidate polygon layer is the right planning fabric, and which field
  is the name? (The probe reports the candidates; picking is judgment.)

**Rule, from being burned twice in two days: an absence claim may only enter a
city config with the dated probe evidence that failed to find the thing.**
Hamilton's config said "no neighbourhood polygon layer" (2026-08-13, assumed,
wrong — 234 planning units existed); the tracker said no canonical unit field
(the props carried `UNIT_NUMBER_COMPLETE` on 36.8% of rows, found only by the
first baseline). Same failure shape both times: an authoritative-*looking*
source says X doesn't exist, nobody probes the actual data or portal, and the
absence gets encoded in config where `03`'s gating faithfully enforces it.
Declared absences are load-bearing — they disable engine features — so they
need the same evidence standard as declared presences.

## Output

The onboarding pass should produce a **draft per-city TOML** (`02`) including
the `[prior_import]` block, plus a short written survey report — gap size,
distribution, entry state, recommended consumer (import vs observer), and
whom to contact.

The survey report is worth keeping as an artifact even after onboarding: it is
the evidence for the decision, and re-running it later shows drift.

## Relationship to the portfolio survey

`08` proposes running exactly these probes across all 42 tracked datasets. That
is not separate work — the survey *is* the onboarding probe, run 42 times. Build
it once and both the design input and the product feature fall out.
