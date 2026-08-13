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
overlap each other constantly. Two cities' bounding boxes claiming the same
addresses would double-count in any portfolio-level rollup, and would make each
city's gap number wrong in opposite directions.

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
