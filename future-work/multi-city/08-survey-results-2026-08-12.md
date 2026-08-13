# Portfolio survey results — 42 datasets, 2026-08-12

Status: **run and validated.** Supersedes the hypotheses in
[08-portfolio-survey.md](08-portfolio-survey.md). Raw output:
[08-survey-results-2026-08-12.json](08-survey-results-2026-08-12.json).
Produced by `scripts/portfolio_survey.py` (throwaway research script, kept for
re-runs, not a library).

## Method

Source side: every `ontario-address-changes` city DB, active rows at the latest
non-skipped snapshot. OSM side: **one** pass over the Geofabrik Ontario PBF
(replication stamp 2026-08-10T20:21Z, fresh for this run), bucketing every
`addr:housenumber` node and way into all 42 city extents simultaneously. Not 42
scans — Toronto's single-bbox filter alone takes ~375 s.

Extents are each dataset's own point bbox. No Overpass was used. `data/osm/`
was left untouched; the PBF was downloaded separately so the live Toronto
extract kept its May provenance.

**Provenance by editor is absent by necessity.** The Geofabrik public extract
zeroes `uid`, `user` and `changeset` — verified, not assumed. Only the
last-touch year survives. Editor tallies and `import:page` tags need Overpass
`out meta` per city, which is Tier 2.

## Validation

The survey reproduces both independently known numbers:

| | survey | known | source of known |
|---|---|---|---|
| Guelph missing | **2,574** of 40,632 (6.3%) | 2,523 of 40,634 (6.2%) | hand-measured via Overpass, 2026-08-10 (`05`) |
| Toronto missing | **2,810** of 522,262 (0.5%) | ~0 expected | our own completed import |

The 2% Guelph difference is method (PBF way-centroids vs Overpass semantics),
not data. Toronto's peak year is 2026 with 464,853 elements — our own upload,
showing up exactly where it should.

## Headline: Ontario is mostly greenfield. Guelph was a coincidence.

`README` concluded from Guelph that *"building-footprint imports have already
seeded most mid-size Canadian cities. Toronto was the outlier, not the
template."* **The survey says the opposite.**

Toronto (0.5%) and Guelph (6.3%) are the only two datasets below 15% missing.
Ottawa is next at 15.3%, then a cliff: Greater Sudbury 53.8%, and **33 of 42
datasets above 75% missing**. Toronto and Guelph are outliers *because* they
were imported, and Guelph was simply the one city where someone else got there
first. One data point generalised to a province.

An independent signal agrees. The `way%` column — addresses on building
polygons rather than loose nodes — is 90% for Guelph and 82% for Ottawa, the
two known deliberate imports, against 2–3% for Huron, Sarnia, Thunder Bay and
Peterborough County. Imports put addresses on buildings; organic mapping
doesn't.

## Where the numbers are not trustworthy

Reported honestly rather than buried. The `street-known%` column is the guard:
for each missing address, does its street exist in OSM without that
housenumber? High means a real gap; low means the match failed.

- **peel-region (1.0%)** — the source carries no street type for 96% of rows
  (`STREETTYPE` is populated for 4%, exotic types like `ABBEY`, while
  Bloor/Hurontario/Dundas sit bare). Not a tracker omission: `peel-region.toml`
  sets no `keep_fields`. **Its 337,581 is not a gap number.** Conflating Peel
  needs street type inferred from the road network.
- **ottawa (26.2%)** — `PRIV` (21,642 rows, Ottawa's "Private" suffix), `TERR`,
  and French `RUE`/`BOUL`/`DE`/`DU`. The 53,508 gap is materially overstated.
- **muskoka (24.6%)**, **cornwall (50.5%)**, **frontenac (55.2%)**,
  **renfrew (56.8%)**, **sdg (60.9%)**, **barrie (62.5%)**, **brant (65.4%)**,
  **wellington (69.7%)** — mixed, overstated to varying degrees.

Also: for county/region datasets the rectangular bbox bleeds into neighbours,
which inflates the OSM-side counts (wellington shows 123,350 OSM addresses
against 41,539 source; sdg 105,548 against 31,520). The source→OSM direction
used for `missing` is unaffected, but nothing in the reverse direction should
be read as meaningful until polygon clipping exists (`10`).

## Finding: the tracker's `street` column is not a street name

The largest design consequence, and it invalidates a premise in `02`.

The canonical `[fields]` mapping exists to detect *changes* between snapshots,
so `street` only ever had to be stable — never complete. Share of rows whose
`street` ends in a known type token: Toronto 99%, Guelph 100%, Kitchener 100%
— but Durham 0%, Renfrew 0%, Thunder Bay 0%, Brampton 1%, Windsor 1%, Peel 9%.
Roughly **18 of 42 store the name component only** (`street='Armitage'`,
`ROAD_TYPE='Crescent'`, `TYPE_SHORT='Cr'` in the props blob), under per-city
key names: `ROAD_TYPE`, `StreetType`, `STREETTYPE`, `STTYPE`, `WC_Suffix`.

So `02`'s cross-repo `keep_fields` contract does **not** make the canonical
fields sufficient for consumers. Every conflation consumer needs a per-dataset
**street resolution** step ahead of normalization. That belongs in `accordeur`'s
dataset layer, and the recipe is per-dataset config like the override table.

Resolution is best *measured*, not declared: the typed-token distribution is
sharply bimodal, so "use `street` if ≥80% of its values carry a type, else
`full`, else reassemble from props" classifies all 42 correctly. Anything from
40 to 85 gives the same answer.

Traps found the hard way, each of which silently corrupted a first run:

- `full` appends the **unit** in Guelph — preferring it inflated Guelph's
  distinct count from 40,634 to 53,706 (+13,072 ≈ its 13,162 unit rows) and its
  gap from 2,574 to 15,691.
- `full` appends the **locality** in kawartha-lakes and leeds-grenville
  (`"903 Cottingham Road, Emily Twp, Kawartha Lakes"`), producing 100% missing
  — zero matches, which is how the bug announced itself.
- chatham-kent glues on a **split** municipality (`COMMUNITY_NAME` "BLENHEIM" +
  `COMMUNITY_TYPE` "TOWN") and needs iterative stripping.
- waterloo has `number` at 0% and lennox-addington `street` at 0%; both parse
  out of `full`.

## Finding: the normalizer's suffix table is Toronto-shaped, and it is measurable

`01` said per-city suffix tables would be needed. Quantified now, top unmapped
trailing tokens:

| dataset | tokens |
|---|---|
| ottawa | `PRIV` 21,642 · `TERR` 6,057 · `DE` 2,436 · `BOUL` 2,399 · `DU` 1,909 · `RUE` 1,481 |
| cornwall | `AV` 4,767 · `CR` 1,560 · `BV` 343 |
| muskoka | numbered roads (`2`, `1`, `3`) · `SHORE` · `CR` · `TL` · `AV` |
| sdg / frontenac | numbered county roads (`43`, `18`, `38`, `509`) · `AV` · `CR` |
| renfrew | `LINE` 653 · `SIDEROAD` 50 · `CRESENT` 29 (a misspelling in the source) |
| toronto | `MEWS` 901 · `QUEENSWAY` 715 · `KINGSWAY` 541 — **genuine names, correctly unmapped** |

Toronto is the control: its unmapped tokens are real street names, not missing
mappings. Cheap wins that would move several cities materially: `AV`, `CR`,
`BV`, `WY`, `TERR`, `TL`, `PRIV`, plus French `RUE`/`BOUL`/`PROM`/`CROIS`.
Rural numbered roads (`County Road 43`) are a different problem and need a
rule, not a table.

## Full table

Sorted by missing count. `street-known%` = share of missing addresses whose
street *is* in OSM (high = real gap). `col` = which column the street name was
resolved from. `cells` = ~500 m cells the missing addresses fall in; `top20%` =
share in the 20 densest (low = diffuse, high = concentrated).

| dataset | source | OSM | missing | miss% | street-known% | way% | col | cells | top20% | peak year |
|---|--:|--:|--:|--:|--:|--:|:--|--:|--:|:--|
| peel-region | 338,238 | 154,552 | 337,581 | 99.8 | 1.0 | 13 | typeless | 4,125 | 3 | 2018 (73,569) |
| york | 364,225 | 274,938 | 277,946 | 76.3 | 84.4 | 15 | street | 5,541 | 3 | 2026 (128,307) |
| durham | 231,354 | 160,749 | 181,390 | 78.4 | 84.0 | 23 | props | 6,502 | 5 | 2018 (69,484) |
| niagara-falls | 180,519 | 103,614 | 142,875 | 79.1 | 85.6 | 5 | props | 6,016 | 5 | 2018 (87,530) |
| brampton | 164,524 | 45,427 | 135,117 | 82.1 | 87.1 | 16 | full | 981 | 7 | 2018 (24,785) |
| hamilton | 172,267 | 86,158 | 128,065 | 74.3 | 91.6 | 10 | props | 2,890 | 7 | 2018 (55,469) |
| london | 116,795 | 28,535 | 98,973 | 84.7 | 77.9 | 10 | street | 1,337 | 7 | 2018 (27,585) |
| windsor | 81,593 | 11,274 | 74,551 | 91.4 | 72.8 | 11 | full | 569 | 12 | 2018 (10,893) |
| muskoka | 66,152 | 15,937 | 62,919 | 95.1 | 24.6 | 16 | full | 6,999 | 8 | 2018 (6,919) |
| ottawa | 349,143 | 374,990 | 53,508 | 15.3 | 26.2 | 82 | street | 3,409 | 11 | 2018 (123,167) |
| barrie | 63,325 | 17,426 | 50,847 | 80.3 | 62.5 | 28 | full | 455 | 18 | 2018 (7,960) |
| oakville | 65,134 | 24,636 | 49,322 | 75.7 | 83.0 | 21 | street | 514 | 15 | 2014 (12,947) |
| kitchener | 70,113 | 33,262 | 48,489 | 69.2 | 84.9 | 45 | street | 504 | 15 | 2016 (16,143) |
| lambton | 56,412 | 34,309 | 48,411 | 85.8 | 91.4 | 3 | full | 4,881 | 10 | 2018 (25,660) |
| burlington | 60,184 | 25,821 | 47,565 | 79.0 | 75.9 | 16 | full | 654 | 16 | 2018 (11,741) |
| chatham-kent | 48,415 | 23,340 | 43,276 | 89.4 | 73.6 | 6 | full | 5,547 | 11 | 2018 (22,404) |
| bruce | 48,039 | 32,299 | 43,087 | 89.7 | 85.3 | 5 | full | 5,929 | 8 | 2018 (26,126) |
| peterborough-county | 40,350 | 42,780 | 36,884 | 91.4 | 76.3 | 3 | full | 6,743 | 6 | 2018 (16,395) |
| thunder-bay | 44,943 | 11,576 | 35,704 | 79.4 | 92.7 | 3 | full | 1,044 | 15 | 2018 (9,895) |
| milton | 40,827 | 24,766 | 35,170 | 86.1 | 77.1 | 16 | street | 1,058 | 24 | 2018 (11,122) |
| renfrew | 38,075 | 18,790 | 34,668 | 91.1 | 56.8 | 7 | full | 6,136 | 11 | 2018 (16,200) |
| kingston | 45,386 | 21,077 | 34,626 | 76.3 | 88.5 | 22 | street | 1,200 | 18 | 2018 (13,747) |
| kawartha-lakes | 39,615 | 33,324 | 33,783 | 85.3 | 85.3 | 7 | street | 5,634 | 10 | 2018 (16,402) |
| wellington | 41,539 | 123,350 | 33,297 | 80.2 | 69.7 | 50 | props | 4,474 | 14 | 2025 (48,096) |
| greater-sudbury | 58,876 | 30,288 | 31,679 | 53.8 | 84.5 | 60 | street | 2,409 | 11 | 2018 (11,823) |
| cambridge | 42,126 | 14,124 | 31,283 | 74.3 | 91.1 | 18 | street | 437 | 18 | 2016 (7,412) |
| leeds-grenville | 51,964 | 55,382 | 31,171 | 60.0 | 76.3 | 36 | full | 6,520 | 9 | 2018 (17,478) |
| brantford | 38,980 | 10,857 | 30,350 | 77.9 | 84.6 | 10 | full | 334 | 20 | 2018 (9,618) |
| sdg | 31,520 | 105,548 | 28,516 | 90.5 | 60.9 | 62 | full | 5,920 | 11 | 2018 (38,320) |
| huron | 34,279 | 37,899 | 27,916 | 81.4 | 89.6 | 2 | street | 5,476 | 12 | 2018 (36,357) |
| hastings | 27,679 | 33,902 | 25,846 | 93.4 | 78.0 | 3 | full | 6,256 | 8 | 2018 (20,365) |
| sarnia | 26,734 | 9,718 | 21,940 | 82.1 | 92.3 | 2 | full | 462 | 23 | 2018 (9,315) |
| waterloo | 32,221 | 23,381 | 20,851 | 64.7 | 96.3 | 59 | street | 275 | 24 | 2016 (7,361) |
| dufferin | 23,382 | 14,269 | 20,018 | 85.6 | 75.5 | 6 | full | 3,103 | 21 | 2018 (5,603) |
| lennox-addington | 22,591 | 27,205 | 19,983 | 88.5 | 85.5 | 5 | full | 3,588 | 20 | 2018 (16,079) |
| frontenac | 20,824 | 47,612 | 18,636 | 89.5 | 55.2 | 12 | street | 5,096 | 4 | 2018 (21,638) |
| elgin | 20,504 | 28,726 | 17,427 | 85.0 | 81.7 | 46 | full | 3,180 | 15 | 2018 (11,738) |
| quinte-west | 18,900 | 11,016 | 16,315 | 86.3 | 82.5 | 5 | street | 1,303 | 20 | 2018 (9,711) |
| brant | 17,925 | 22,589 | 15,033 | 83.9 | 65.4 | 7 | full | 1,871 | 27 | 2018 (13,072) |
| cornwall | 18,330 | 7,891 | 14,871 | 81.1 | 50.5 | 36 | full | 189 | 39 | 2018 (3,467) |
| toronto | 522,262 | 583,393 | 2,810 | 0.5 | 76.9 | 14 | street | 953 | 24 | 2026 (464,853) |
| guelph | 40,632 | 45,875 | 2,574 | 6.3 | 98.9 | 90 | street | 249 | 49 | 2025 (44,279) |

## The 2018 peak — answered (Tier 2, 2026-08-13)

Nearly every dataset peaks in **2018**, including rural counties with almost no
address coverage. Four small Overpass `out meta` samples plus changeset lookups:

| county | user | changeset | comment | source tag |
|---|---|---|---|---|
| Huron | `LogicalViolinist` | 58533674 | "adding missing addresses" | `NRCan` |
| Bruce | `Matthew Darwin` | 56622908 | "Municipality of Kincardine => Kincardine" | `Discussion on talk-ca; NRCan` |

Both JOSM, both bulk (10,000 and 3,815 changes), and **neither carries
`import=yes` or `import:page`**. So rural Ontario already has an
**NRCan-derived address layer** that formal prior-import detection (`05`) would
miss completely — it is tagged like ordinary editing. That is a gap in `05`'s
method, not just a fact about Ontario.

**Two corrections this forces:**

1. Bruce's changeset is a mass `addr:city` **rename**, not an address import.
   So the 2018 peak is partly *retagging of older data*, and the underlying
   NRCan import may predate it. **`peak year` in the table below measures last
   touch, not import date** — it should not be read as dating anything.
2. The pre-existing layer is **federal** (NRCan) while our sources are
   **municipal**. Where the two disagree, the OSM value is differently-sourced
   rather than simply wrong — which is an adjudication question (`06`), not a
   conflation bug.

Caveat: two rural samples of ~300 elements each. "Province-wide NRCan layer" is
a well-supported inference, not proof.

### Ottawa is not an import

Separate probe, because Ottawa's profile differs from everything else: five-plus
distinct users (`Matthew Darwin`, `DannyMcD`, `ott2map`, `andrewpmk`,
`ordinarysparrow`) with edits spread evenly across 2022-2026. A sustained local
community, matching its 82% way ratio and smallest-in-portfolio gap. Ottawa is a
"coordinate with locals" city, not an import target.

### York's 2026 spike was us

York's 128,307-element 2026 peak looked like an active import — `05`'s
"brownfield, active" case, the one that forbids acting before contacting
someone. It isn't. York's source bbox starts at lat **43.753**, south of
Steeles, overlapping Toronto's bbox by 0.101 deg — **38% of Toronto's height**.
Splitting the York extent at Toronto's northern bbox edge, where no Toronto
element can reach:

| year | overlap band (43.753-43.854) | pure York (>43.854) |
|---|--:|--:|
| 2026 | 126,524 | 1,203 |
| 2025 | 6,998 | 3,511 |
| 2024 | 6,630 | 6,345 |

**99.1% of the 2026 spike is in the Toronto overlap band** — our own upload.
Pure York shows 1,203, ordinary organic activity. Nobody is importing York and
there is no one to contact.

This is `10`'s rectangular-bbox problem changing a *conclusion*, not just
inflating a count, and it is the strongest argument yet for polygon clipping:
the naive reading would have had us stand down from a city on the strength of
our own edits. York's OSM-side numbers in the table below are contaminated for
the same reason.

## Candidate shortlist

Cities, not regions, and only where `street-known%` supports the number:

1. **Hamilton** — 128,065 missing, 91.6% street-known, single municipality,
   street resolves cleanly from `FULL_STREET_NAME` in props. The strongest
   single-city candidate in the portfolio.
2. **London** — 98,973 missing, 77.9%, single municipality, clean `street`
   column.
3. **Brampton** — 135,117 missing, 87.1%. Caveat: the City layer and the Region
   of Peel layer are separate datasets covering the same ground
   (`brampton.toml` vs `peel-region.toml`), and Peel's is unusable. Decide which
   is authoritative before touching either.
4. **Windsor** (74,551, 72.8%) and **Kitchener** (48,489, 84.9%) behind those.

Regional datasets (york 277,946, durham 181,390) are larger but each spans many
municipalities, which makes `municipality_name` handling (`03`) and polygon
clipping (`10`) prerequisites rather than nice-to-haves. `08` guessed ~19 of 42
are counties or regions; that holds.

## What this changes

- **`README`'s "assume brownfield until proven otherwise" is backwards.** The
  measured default is greenfield. Keep surveying first, but expect a gap.
- **The import machinery is not obsolete.** It was written for a case that
  looked like a one-off and is in fact the common case in Ontario.
- **`02` needs a correction**: canonical fields are not conflation-ready, and
  street resolution is a required per-dataset step.
- **`03`'s capability gating gains a concrete first case**: `has_street_type`.
  Peel fails it, and a consumer that doesn't check will silently produce
  garbage rather than refusing to run.
- **`05` needs a new detection case.** The NRCan work carries no `import=yes`
  and no `import:page`, so a prior-import check that looks only for import tags
  returns "greenfield" for a city that already has a bulk-loaded address layer.
  Detect on *shape* — one user, one year, thousands of changes in a changeset —
  not on tags alone.
- **Tier 2 remaining**: Wellington's 2025 spike (48,096) is unexplained, and
  Hamilton's entry state was never established (the probe was cut short). Do
  Hamilton before committing to it as city #2 — everything above says it is the
  best candidate, but "no prior import" is currently an assumption, and the
  NRCan finding is exactly the kind of thing that hides from a naive check.
