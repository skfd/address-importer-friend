# Source-side multi-address (range) rows — FAQ

Empirical reference for contributors reading `IMPORT_PROPOSAL.mediawiki`,
particularly Open Question #6. Every figure here is from snapshot **#38**
(2026-05-06) and reproducible via `scripts/source_multi_audit.py`.

For OSM-side multi-value `addr:housenumber` nodes (a separate shape), see
`/osm/multi` and the deferred-work entry in §8 of the proposal.

## What counts as a multi-address row?

A row in the source `addresses` table where `lo_num != hi_num`. The
`address_full` is rendered as `lo-hi linear_name_full`, e.g.
`100-110 Main St`. The schema also has `lo_num_suf` / `hi_num_suf`
columns, but no row in the active snapshot uses them as the only
range axis (see "How many are there?" below).

## How many are there?

| | |
|---|---:|
| Active rows total | 525,413 |
| Range rows (`lo_num != hi_num`) | **1,639** (0.312%) |
| of which suffix-only (`lo_num == hi_num`, suffixes differ) | 0 |
| Reversed (`lo_num > hi_num`) | 0 |

Small absolute slice, but ~1,000 of these are addresses that exist in
neither the source's per-number set nor in OSM today (see "OSM coverage"
below).

## What classes carry ranges?

| Class | Range rows |
|---|---:|
| `Land` | 1,447 |
| `Structure` | 160 |
| `Structure Entrance` | 31 |
| `Land Entrance` | 1 |

Mostly parcel-level. The 31 `Structure Entrance` ranges are unusual —
worth spot-checking individually if class-aware handling is added.

## What forms do the housenumbers take?

| Form | Count |
|---|---:|
| Pure numeric (`100-110`) | 1,590 |
| With letter suffix on either end (`100A-110A`) | 49 |

All 49 lettered ranges have matching suffixes on both endpoints
(`A-A`, `B-B`, …) except one `A-` (suffix only on lo) and one `I-I`
(the `I` is digit-confusable per the `suffix_range` check).

Top suffix pairs: `A-A` (24), `B-B` (10), `C-C` (5), `D-D` (3).

## What spans appear?

| Span (`hi - lo`) | Count |
|---|---:|
| 1 | 3 |
| 2 | 869 |
| 3-10 | 446 |
| 11-100 | 314 |
| >100 | 7 |

Span-2 dominates — typical "two consecutive house numbers on the same
side of street" case. The seven >100 outliers are big complexes, e.g.
`3401-3561 Lawrence Ave E` (Scarborough Town Centre).

Parity: 824 both-odd, 793 both-even, 22 mixed. Almost all respect the
North-American odd/even side-of-street convention.

## Are they really unique, or duplicated by per-number rows?

**100% unique.** No range row overlaps any per-number row on the same
street.

Method: for each range row, build the expected list of integers
(`range(lo, hi+1, 2)` if both endpoints share parity, else step 1) and
look for any per-number row carrying that integer on the same
`(linear_name_full, municipality_name)`.

| Coverage of expected numbers by per-number siblings | Range rows |
|---|---:|
| Zero siblings (range row is the only record) | **1,639 (100%)** |
| Partial | 0 |
| Full (range row is redundant) | 0 |

Reverse check: per-number rows whose number falls inside any same-street
range — also **0**. Range rows and per-number rows are perfectly
disjoint.

Concrete example — `Cather Cres`, North York:

```
1-65 Cather Cres   (range row, lo=1, hi=65)
2-56 Cather Cres   (range row, lo=2, hi=56)
58 Cather Cres     (per-number, lo=58)
60 Cather Cres     (per-number)
62 Cather Cres     (per-number)
64 Cather Cres     (per-number)
```

The two range rows cover the strip the per-number rows don't, and meet
exactly at the parity boundary (even numbers 2-56 in the range, 58-64
enumerated). The City declines to enumerate inside complexes where one
parcel owns many numbers; the range row is its representation of "this
lot owns these numbers".

## How are they spread across streets?

227 streets carry more than one range row. Top concentrations:

| Street | Range rows |
|---|---:|
| `Lake Shore Blvd W` (Etobicoke) | 83 |
| `Eglinton Ave W` (York) | 51 |
| `Wilson Ave` (North York) | 36 |
| `Yonge St` (North York) | 32 |
| `Kingston Rd` (Scarborough) | 30 |

Pattern: arterial roads with strip-mall / multi-unit-commercial frontage.

## Does the municipality trap apply?

No. **Zero** range `address_full` strings appear in more than one former
municipality. The `(address_full, municipality_name)` rule from
`SOURCE_DATA.md` is still the right key, but it's not load-bearing for
range rows specifically.

## Do range rows link to a parent?

| | Range rows |
|---|---:|
| With `extra.ADDRESS_ID_LINK` (parent set) | 192 |
| Without (standalone) | 1,447 |

So most range rows are top-level, not children of a `Land` parent.

## How is the range string rendered?

ASCII `-` in all 1,639 cases. Never en-dash, em-dash, or " to ". Safe to
parse with a single regex.

## OSM coverage of the same numbers

Cross-checked against the cached OSM extract
(`data/osm/toronto-addresses.json`, 334,264 elements). For each range
row, expanded `(lo..hi)` and looked up per-integer presence in OSM under
the `expand_street_name`-mapped street name (so source `Cather Cres` is
matched against OSM `Cather Crescent`). Multi-value OSM nodes
(`;`/`,`/`N-M`) are split before indexing; `addr:interpolation`
endpoints are excluded.

| OSM coverage | Range rows | Share |
|---|---:|---:|
| None of the numbers in OSM | 992 | 60.5% |
| Some of the numbers in OSM | 446 | 27.2% |
| All of the numbers in OSM | 201 | 12.3% |

Combined with the 100% per-number-uniqueness above: **992 range rows
represent address numbers that exist in neither the source's per-number
set nor in OSM today.** That's the net-new headline figure for Open
Question #6.

## What does the pipeline do with them today?

Ingested into the `addresses` table like any other source row, then
matched against OSM. The `suffix_range` check
(`t2/checks/suffix_range.py`) detects `lo_num != hi_num` and emits a
`FLAG` with `reason_code='range'`, which blocks auto-approval. Reviewer
can opt in per-row but the default disposition is `SKIPPED` — no upload.

## Why `SKIPPED` by default?

A range row carries a single `(latitude, longitude)` for the whole
range. We have no parity flag, no per-number coordinates, and no
guarantee the City means strict step-2 (the 22 mixed-parity rows prove
they don't always). Uploading either:

- the verbatim `lo-hi` string on the single point — non-canonical OSM
  housenumber tagging; or
- expanded per-number nodes — requires synthesising coordinates we don't
  have

…is a policy decision the proposal defers to community input.

## Reproducing the counts

`python scripts/source_multi_audit.py` from the repo root. Output
sections mirror the headings above; numbers should match this doc as
long as the snapshot hasn't moved. Source DB access is read-only via
`t2.source_db.connect_readonly`; OSM coverage is read from the cached
JSON at `data/osm/toronto-addresses.json`.
