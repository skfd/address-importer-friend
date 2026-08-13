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

Tier 1 is **done** (2026-08-13, see DONE.md). Tier 4 is still open, and the
source still points at `toronto.db`.

- [x] **Tier 1, mechanical** (`02`) — done 2026-08-13.
- [ ] Point the source at
      `ontario-address-changes/data/hamilton/hamilton.db` — already on disk,
      dataset slug `hamilton`.
- [ ] **Tier 4, geography** (`02`): `t2/tiles_build.py:40` hardcodes the City of
      Toronto 158-neighbourhood GeoJSON URL. Hamilton needs the no-neighbourhood
      -layer fallback; the quadtree ≤500-per-tile logic underneath is already
      generic and needs no change.
- [ ] Run **baseline conflation in full** — README decision 1: conflation always
      runs in full for every city, upload is the conditional part.
- [ ] Guardrail throughout: **Toronto's match rates must not move** (`tool.db`
      is living).

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

## 3. Adjudication policy for municipal-vs-CanVec disagreement (`06`)

Covers both candidates: the same Mojgan Jadidi StatCan GTHA campaign seeded
Hamilton (cs 37445896) and Mississauga (cs 37570399) five days apart in 2016,
so one policy settles both.

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

## Not blocking, worth doing when touching the normalizer

Cheap suffix-table wins measured by the survey: `AV`, `CR`, `BV`, `WY`, `TERR`,
`TL`, `PRIV`, plus French `RUE`/`BOUL`/`PROM`/`CROIS`. Would materially move
Ottawa, Cornwall, Muskoka, SDG and Frontenac, whose gaps are currently
overstated. Rural numbered roads (`County Road 43`) need a rule, not a table.

Guardrail: Toronto's match rates must not move (`tool.db` is living).

## Housekeeping

- [ ] Maintenance run is due ~2026-08-22 (last: `maint-snap90`, 2026-07-23,
      watermark snapshot 90 / 2026-07-22). Unrelated to the above — it conflates
      against live Overpass and needs none of this.
