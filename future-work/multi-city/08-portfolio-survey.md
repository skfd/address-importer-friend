# Portfolio survey — all 42 tracked datasets

Status: **proposed research, not run.** Captured 2026-08-10. Awaiting a
go-ahead.

## The argument

Guelph was picked as city #2 on intuition and turned out to be 94% already
imported by someone else who finished ten months earlier. A survey would have
said so in advance.

More importantly: **the survey is not throwaway work.** It runs exactly the
probes the onboarding flow needs (`04`). Build once, run 42 times, and the
design input and the product feature fall out of the same code.

## Inputs are already on disk

All 42 city DBs exist locally under
`C:/Users/kk/Code/ontario-address-changes/data/<slug>/<slug>.db`, ~3.2 GB
total. Largest: toronto 393 MB, york 316, peel-region 204, brampton 203,
guelph 187, hamilton 146, ottawa 121. Smallest: cornwall 9 MB.

The source side therefore costs **nothing** — no network at all.

For the OSM side, use the **Geofabrik Ontario PBF** that `t2/osm_refresh.py`
already downloads. One offline pass covers every city in the portfolio.
Do **not** issue 42 full-city Overpass queries against the volunteer-run public
instance.

## What to measure per city

Per `04`: source field profile and population rates, unit/postcode coverage,
OSM element counts split by type, gap size in both directions, gap
distribution across ~500 m cells, and provenance (top editors, last-touch
years, changeset import tags).

## What it is expected to surface

Hypotheses, not findings — this has not been run.

**Regional multi-municipality datasets are nearly half the portfolio.** From
the directory names alone: `york`, `peel-region`, `durham`, `muskoka`,
`wellington`, `huron`, `bruce`, `hastings`, `renfrew`, `lambton`, `elgin`,
`frontenac`, `leeds-grenville`, `lennox-addington`, `dufferin`, `brant`, `sdg`,
`peterborough-county`, `kawartha-lakes` — roughly **19 of 42 are counties or
regions, not single cities**. `municipality_name` is currently treated as a
field Toronto happens to have (`03`); in this portfolio it is closer to the
norm than the exception. If one hypothesis here is worth testing first, it is
this one.

**Rural addressing.** Lot/concession schemes, `addr:place` instead of
`addr:street`, unnamed roads. `t2/reverse_sweep.py:240-241` already reads
`addr:place`/`addr:hamlet`, so there is partial awareness downstream but
nothing upstream of it. Likely candidates: `kawartha-lakes`, `chatham-kent`,
`bruce`, `huron`, `renfrew`.

**Bilingual street names.** Ottawa, Cornwall, SDG. Breaks the assumption that
one anglophone suffix table serves a profile (`01`).

**Greenfield cities.** The single most valuable output: which cities have *no*
prior import and a large gap. That is where the import machinery still earns
its keep, and right now which those are is unknown.

## Output

A comparison table across all 42, plus a shortlist of candidate cities by entry
state. Expected to change which city is worked on next, and to change the
`[source_fields]` capability set in `02` once the real distribution of source
schemas is visible rather than inferred from two examples.

## Cost note

Cheap and mostly offline, but the PBF is ~600 MB on first download and the
filtering pass over 42 city extents is not instant. Worth running once,
deliberately, and keeping the output as a dated artifact rather than
re-deriving it.
