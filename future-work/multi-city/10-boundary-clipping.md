# Boundary clipping

Status: **proposed, not implemented.** Captured 2026-08-10. Small, concrete,
and a prerequisite for trusting any cross-city gap number.

**Upgraded 2026-08-13: this is no longer a metric-quality issue.** The portfolio
survey produced *three* wrong conclusions from rectangles, not three wrong
numbers — see "Rectangles have changed conclusions" below. Treat it as a
blocker for any regional dataset rather than a cleanup.

## The problem

Cities are clipped by rectangle today. `config.toml` carries
`[osm] toronto_bbox = [43.58, -79.64, 43.86, -79.11]`, and
`toronto-import-beholder/config.toml` carries the same rectangle. For Toronto
this is roughly fine — the city is large and the surrounding area is more of
the same GTA.

For a small city it is not fine. Guelph's source data spans
`43.4748..43.58629, -80.32545..-80.15481`, and that rectangle contains a lot of
Wellington County that is not Guelph.

## Measured impact on Guelph

Of the survey's **7,818 OSM addresses absent from the source**, a large share
are outside the city. Visible directly in the street names present in OSM but
absent from the Guelph feed: `WELLINGTON RD 30`, `SIDEROAD 10 N`,
`WELLINGTON 29 RD`, `TOWNSHIP 1 RD`, `MARDEN RD`, `LAKE RD`. 82 such streets.

The source side leaks too, in the other direction: 75 rows carry
`PLACE='Guelph/Eramosa Twp'` rather than `'Guelph'`.

So the rectangle produces a false "OSM has thousands of addresses your source
doesn't" signal that is really "your rectangle includes the neighbours." Any
reverse-sweep or completeness metric built on it is misleading.

## Rectangles have changed conclusions, not just counts

Three instances from the 2026-08 survey, all in `08-survey-results-2026-08-12.md`:

| case | the rectangle said | the truth |
|---|---|---|
| **York** 2026 spike, 128,307 elements | an active import — do not touch | 99.1% was our own Toronto upload; pure York 1,203 |
| **Wellington** 2025 spike, 48,096 | an unexplained anomaly | 92.1% is Guelph's import, wholly contained in the county rectangle |
| **Oakville** found in Hamilton's box | *(nothing — it was noise)* | a genuinely active import by `TronnaLegacy`, worth knowing |

The first two would have had us stand down from a city on the strength of
someone else's edits — in York's case, our own. The third cut the other way and
handed us a real finding by accident. Bbox bleed is not a bias in one direction
that can be corrected for; it is noise that reads as signal.

**Containment can be total.** Guelph is a *separated city* sitting geographically
inside Wellington County, so the county's rectangle can never exclude it. This
is not a tuning problem with a bbox answer. Ontario's separated cities
(Guelph/Wellington, Barrie/Simcoe, Brantford/Brant, Kingston/Frontenac and
others in the portfolio) all have this shape, so every county dataset paired
with its separated city is contaminated by construction.

Corollary for the survey table: any per-city gap number for a **region or county**
dataset is contaminated on the OSM side until this is fixed, and roughly 19 of
the 42 datasets are regions or counties.

## Why it matters more in a portfolio

With 42 datasets, many of them adjacent (guelph / wellington, toronto / york /
peel-region / durham, kitchener / cambridge / waterloo), rectangles will
overlap each other constantly.

The double-counting worry that used to sit here — "two cities' bounding boxes
claiming the same addresses" — has now been measured and is much smaller than
assumed. See the next section.

## Two different problems, two different mechanisms — measured 2026-08-13

Everything above is about the **OSM side**, where a rectangle is all we have and
the polygon is the only fix. The **source side** turns out to be a separate
problem with a cheaper answer, and conflating the two was hiding that.

Census: all 861 dataset pairs, bbox intersection → point containment → shared
`number|street` key → coordinate proximity under 150 m. Ontario's two-tier
municipal structure predicts the entire result. Scripted as
`scripts/source_overlap_census.py` — re-run it when datasets are added to the
tracker; the numbers below are its output.

**Kind 1 — separated city inside a county. Zero duplicate coverage.** A
separated city is legally outside its county, so the county's layer never
contained it. The county's `Municipality` vocabulary says so directly:
`wellington` lists seven values and Guelph is not one of them.

| pair | county points in the city's *bbox* | true duplicates |
|---|--:|--:|
| guelph / wellington | 1,442 (Guelph-Eramosa 922, Puslinch 520) | 73 |
| cornwall / sdg | 1,160 | **0** |
| brantford / brant | 1,057 | **0** |
| kingston / frontenac | 6,741 (South Frontenac, Frontenac Islands) | **0** |
| barrie / york | 0 | **0** |
| toronto / york | — (6,792 shared keys) | **0** |

Guelph's 73 are the exception that proves the rule, and they run the *opposite*
way to the assumption in "Measured impact on Guelph" above: both datasets label
them `Guelph/Eramosa Twp` / `Guelph-Eramosa`. It is the **city layer reaching
out past its own boundary**, not the county reaching in — the same 75 rows
already noted under "Measured impact on Guelph", seen from the other side.

**Kind 2 — lower-tier municipality inside its county/region. Real duplication.**
Only two instances in 42:

| pair | shared, colocated | share of the city layer | median offset |
|---|--:|--:|--:|
| lambton ⊃ sarnia | 25,704 | 96.1% | 0 m (90.6% identical) |
| peel-region ⊃ brampton | 161,200 | 98.0% | 3 m |

Sarnia is a lower-tier municipality of Lambton, Brampton of Peel. Neither is
separated. That single administrative fact predicts both tables.

Both sides' municipality labels agree on the duplicates (`lambton='Sarnia'` /
`sarnia='Sarnia'` on 25,690 of them; `peel-region='Brampton'` /
`brampton='BRAMPTON'` on 161,199). Label agreement is what tells a genuine
containment apart from a boundary strip, where the labels differ — and it is the
census's actual output, not an interpretation of it.

**Kind 3 — the region is the sole source.** Peel is the only source for
Mississauga and Caledon; likewise Durham's 8 municipalities, York's 9, Niagara's
12, Muskoka's 6, Chatham-Kent's 24. Not overlap, but the reason regional
datasets cannot simply be deprioritised in favour of city layers.

Everything else is boundary-strip noise in the tens, and the municipality labels
disagree in every one of them: kitchener/waterloo 54, dufferin/wellington 54
(labelled Erin and Centre Wellington), milton/peel-region 33 (labelled
Mississauga), burlington/hamilton 7, frontenac/lennox-addington 7.

### Consequence: dedup on the attribute, clip on the polygon

Every dataset with an overlapping partner already carries a municipality field —
`lambton.MUNICIPALITY`, `peel-region.MUNICIPALITY`, `wellington.Municipality`,
`durham`/`york`/`niagara-falls.MUNICIPALITY`. For source-side dedup that field
is **exact, free, and needs no boundary file**, where a polygon would be
approximate and require sourcing a boundary per city. The nine datasets with no
municipality field (sdg, brant, hastings, renfrew, dufferin, huron,
peterborough-county, leeds-grenville, lennox-addington) have no Kind 2 partner,
so none of them has an ownership question to answer. Their boundary-strip
overlaps are tens of addresses and are the polygon's job, not the attribute's.

The polygon is still required, and this does not soften that — but its job is
now specifically the **OSM side**, where elements carry no municipality
attribute to key on and where all three changed conclusions (York, Wellington,
Oakville) actually happened.

Two rules follow for source-side ownership:

1. **Lower tier wins.** City layer over county/region layer where both cover the
   same municipality. Brampton beats Peel decisively (34 populated props
   including `POSTAL_CODE` and `UNIT_NO`, against Peel's 12 and no postcode; 54
   tracked snapshots against 1). Sarnia beats Lambton narrowly (26,568 keys
   against 26,288, near-identical field sets). The disagreements look like
   genuine differences rather than one copy lagging — of 5,611 keys exclusive to
   one side, 7 have ever been seen on the other. Weak evidence for three of the
   four layers, though: sarnia, peel-region and brampton@peel have 1–2 tracked
   snapshots each, so only the brampton side (54 snapshots) really tests it.
2. **Clip the city layer to its own boundary too**, so Guelph's 75
   Guelph/Eramosa rows go to Wellington rather than being claimed twice.

Ownership has to be recorded **per municipality, not per dataset** — Peel is
authoritative for Mississauga and Caledon while losing Brampton, which no
dataset-level flag can express. A portfolio-level ownership map is also the only
place a cross-dataset conflict is visible at all.

## What already exists

`t2/reverse_sweep.py:48` has `_load_toronto_boundary(geojson_path)`, returning
a Shapely (Multi)Polygon, used at `reverse_sweep.py:343` when the file is
present. So the mechanism exists — it is file-driven and already generic apart
from its name. It is simply not applied at ingest or in the beholder.

`t2/pipeline.py` / `t2/candidates.py` also already clip ingest to a **tile
polygon** (migration `016_run_polygon.sql`), so polygon clipping at ingest is a
solved problem in this codebase. City boundary is the same operation one level
up.

## Sketch

- `[geo] boundary = "..."` in the per-city TOML (`02`), optional, falling back
  to bbox when absent.
- Applied on **both** sides — source rows and OSM elements — or the asymmetry
  creates a new false signal.
- Sourced per city. Statistics Canada census subdivision boundaries or the
  city's own open-data boundary layer are the obvious candidates; OSM's own
  `admin_level` relation is another and has the advantage of matching what
  mappers consider the city.

## Open question

Which boundary is authoritative when the municipal boundary and OSM's
`admin_level=8` relation disagree? For gap metrics, OSM's own idea of the city
is arguably the right frame, since the question being asked is "what does OSM
have." Not resolved.
