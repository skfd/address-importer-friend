# Boundary clipping

Status: **proposed, not implemented.** Captured 2026-08-10. Small, concrete,
and a prerequisite for trusting any cross-city gap number.

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
