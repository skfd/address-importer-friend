# Portfolio survey results — 42 datasets, 2026-08-12

Status: **run and validated**, with one row corrected. Supersedes the hypotheses
in [08-portfolio-survey.md](08-portfolio-survey.md). Raw output:
[08-survey-results-2026-08-12.json](08-survey-results-2026-08-12.json).
Produced by `scripts/portfolio_survey.py` (throwaway research script, kept for
re-runs, not a library).

**Amendments after the original 2026-08-12 run.** Tier 2 findings (the 2018
peak, Ottawa, York, Wellington, Hamilton, Oakville) are dated in place. Two
later passes changed the document rather than extending it:

- **peel-region was misread as typeless** and is retracted below; its row in the
  full table is re-measured. The JSON still carries the original figures.
- **A source-overlap census** (2026-08-13) found the datasets barely overlap
  each other, which splits `10` into two mechanisms.

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

- ~~**peel-region (1.0%)**~~ — **retracted 2026-08-13. This entry was wrong.**
  It read: "the source carries no street type for 96% of rows… its 337,581 is
  not a gap number… conflating Peel needs street type inferred from the road
  network." In fact `STREETTYPE` is populated for **98.8%** of Peel rows
  (Mississauga 98.2%, Brampton 99.8%, Caledon 100%). The 4% figure was measured
  against the canonical `street` column, which maps to `STREETNAME` — the name
  component only, exactly the same name+type split as `durham` and
  `niagara-falls`, which the same run resolved correctly.

  Re-measured with the right recipe, Peel's `street-known%` is **90.5%**, one of
  the better scores in the portfolio, and its gap is a real 270,150. The 1.0%
  score was the guard metric working — an absurd number *did* mean something was
  wrong — but the fault was in the reading, not the dataset. See `03` for the
  design consequence.
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

**But measure the right column.** This score is a property of the *canonical
field*, not of the dataset, and reading it as the latter is what wrote Peel off
as unusable (retracted above). Peel scores 9% here while carrying `STREETTYPE`
on 98.8% of its rows. A low score means "resolution is required", never "the
type is missing".

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
| york | 364,225 | 274,938 | 277,946 | 76.3 | 84.4 | 15 | street | 5,541 | 3 | 2026 (128,307) |
| peel-region † | 339,723 | 154,552 | 270,150 | 79.5 | 90.5 | 13 | props | 3,803 | — | 2018 (73,569) |
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

† **peel-region re-measured 2026-08-13** against the same PBF, after the
`typeless` misreading was corrected (see below). The OSM side reproduced
exactly — 154,552 distinct keys, 178,491 elements, 13% ways, 2018 peak 73,569 —
which confirms only the source resolution was ever broken. `top20%` was not
recomputed; it needs a second full PBF pass and is the least load-bearing column
in the table.

Because Peel is the sole source for two of its three municipalities, its gap
splits usefully:

| municipality | source | missing | miss% | street-known% |
|---|--:|--:|--:|--:|
| Mississauga | 148,262 | 116,109 | 78.3 | **96.6** |
| Brampton | 162,260 | 131,963 | 81.3 | 88.3 |
| Caledon | 29,201 | 22,078 | 75.6 | 71.9 |

Brampton's row here (131,963 / 88.3%) against the City layer's own row above
(135,117 / 87.1%) is a useful cross-validation: two independently published
layers, resolved by different recipes, agree on the gap to within 2%.

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

### Wellington's 2025 spike was Guelph — answered (2026-08-13)

The last unexplained anomaly, and it is York's story again. **Guelph's bbox is
wholly contained in Wellington's** (`43.475..43.586, -80.325..-80.155` inside
`43.388..44.026, -80.990..-79.972`), and Guelph's 2025 import is 44,279
elements against Wellington's 48,096 spike.

Confirmed rather than inferred, with an Overpass `out count` splitting
Wellington's rectangle on Guelph's:

| year | Wellington rect | inside Guelph | pure Wellington |
|---|--:|--:|--:|
| 2025 | 48,153 | 44,336 (**92.1%**) | 3,817 |
| 2026 | 2,560 | 771 (30.1%) | 1,789 |

Pure Wellington's 3,817 in 2025 is ordinary activity. Nobody is importing
Wellington. The live count also revalidates the survey: 48,153 against the PBF's
48,096, a three-day drift.

Note the containment is *total*, not partial as York's was — Guelph is a
separated city that sits geographically inside Wellington County, so the county
dataset's rectangle can never avoid it. No amount of bbox tuning fixes this one;
it needs the polygon (`10`).

## Finding: the source datasets barely overlap each other (2026-08-13)

The Wellington/Guelph result above is about **OSM elements** inside a rectangle.
The obvious follow-on — do the two *sources* also publish the same addresses? —
turns out to have a much cleaner answer, and it separates a problem that `10`
was treating as one thing.

Census over all 861 dataset pairs: bbox intersection → point containment →
shared `number|street` key → coordinate proximity under 150 m. Scripted as
`scripts/source_overlap_census.py`; the design consequence is written up in
`10`.

**Wellington and Guelph do not overlap at all.** Wellington's 42,925 rows carry
a `Municipality` field with exactly seven values — Centre Wellington, Erin,
Wellington North, Guelph-Eramosa, Mapleton, Minto, Puslinch. Guelph is not among
them, because a separated city is legally outside its county. The 1,442
Wellington points inside Guelph's *rectangle* are Guelph-Eramosa (922) and
Puslinch (520) addresses in the corners.

The 73 genuine duplicates run the **opposite way to the assumption**: both sides
label them `PLACE='Guelph/Eramosa Twp'` and `Municipality='Guelph-Eramosa'`. One
subdivision in the NE corner (Eramosa Cres, Promenade Rd, Hillside Dr, Gazer
Cres). It is Guelph's layer reaching *out* past the city boundary — the same 75
rows `10` already noted — not Wellington reaching in.

The same shape holds for every separated city in the portfolio: cornwall/sdg 0
duplicates, brantford/brant 0, kingston/frontenac 0, barrie/york 0,
toronto/york 0 (against 6,792 shared keys — the keys collide, the coordinates
never do).

**Only two pairs in 42 genuinely duplicate**, and both are a lower-tier
municipality inside its upper tier rather than a separated city:

| pair | shared, colocated | share of the city layer | median offset |
|---|--:|--:|--:|
| lambton ⊃ sarnia | 25,704 | 96.1% | 0 m (90.6% coordinate-identical) |
| peel-region ⊃ brampton | 161,200 | 98.0% | 3 m |

Where they overlap, the city layer wins, but for different reasons. **Brampton
beats Peel decisively** — 34 populated props including `POSTAL_CODE` (229,865)
and `UNIT_NO` (69,186) against Peel's 12 and no postcode, plus 54 tracked
snapshots against Peel's 1. **Sarnia beats Lambton narrowly** — 26,568 keys
against 26,288, near-identical field sets, neither carrying units. The
disagreements read as genuine rather than as one copy lagging — of 5,611 keys
exclusive to one side, 7 have ever been seen on the other — though only the
Brampton side has enough snapshot history (54, against 1–2 for the rest) to make
that a strong test.

Worth stating because it is the opposite of what the portfolio-scale worry
predicted: **no two municipal sources disagree about where a house is.** Where
they overlap they agree to 3 m, and 90.6% of the Lambton/Sarnia pairs are
identical to the metre. Source conflict is not the problem; source *ownership*
is, and Ontario's two-tier municipal structure already answers it. The design
consequence — dedup on the municipality attribute, reserve the polygon for the
OSM side — is written up in `10`.

Third category, not overlap but the reason regional datasets cannot simply be
deprioritised: **Peel is the sole source for Mississauga and Caledon**, as
Durham is for its 8 municipalities, York for its 9, Niagara for its 12.

## Hamilton's entry state — established (Tier 2, 2026-08-13)

Hamilton was the shortlist leader on an **assumption** that it had no prior
import. Probed per `05` with `scripts/entry_state_probe.py`: three ~0.012 deg
`out meta` boxes (downtown, Dundas, Stoney Creek), 2,031 elements, plus
changeset lookups, a tag tally and a wiki check.

**Verdict: greenfield for a municipal address import — but not empty.** Three
strata, none of them a municipal import, and no one to stand down for.

| stratum | evidence | year |
|---|---|---|
| NRCan/CanVec base layer | `source=NRCan-CanVec-7.0` (371), `CanVec 6.0 - NRCan` (361) — 90% of sampled elements | pre-2018 |
| StatCan address ranges | Mojgan Jadidi, cs 37445896, 3,096 changes, `source=StatCan 92-500-X`, "Adding address ranges for GTHA" | 2016 |
| Manual local infill | Kevo, four changesets 280-542 changes, `source=Statistics Canada LODE, Bing` | 2022 |

Combined users: Matthew Darwin 835, Kevo 796, Mojgan Jadidi 71, andrewpmk 64.
Years: 2018 (823), 2022 (576), 2026 (153).

**The 2018 peak is a retag, not an import.** The three heaviest changesets —
56445760 (9,750 changes), 56446765 (6,716), 56445427 (9,750), all Matthew
Darwin, all 2018-02-17, all `source=Discussion on talk-ca; NRCan` — carry the
comment **"City of Hamilton => Hamilton"**. A mass `addr:city` rename, the exact
signature already seen in Bruce ("Municipality of Kincardine => Kincardine").
Hamilton's 55,469-element 2018 peak in the table above is that sweep passing
over a layer that predates it.

**`source` names the layer even when import tags do not.** No `import=yes` and
no `import:page` appears anywhere — not in the samples, not in the 100 most
recent changesets over the extent. But the `source` *tag on the elements
themselves* names CanVec outright. This upgrades Tier 2's "province-wide NRCan
layer" from well-supported inference to **directly observed** in Hamilton, and
it hands `05` a detection signal that costs one query and does not depend on
changeset hygiene.

**No wiki page.** `Canada:Ontario:Hamilton` is a redirect to `Hamilton`; there
is no Hamilton address import page. Wiki searches surface only Hamilton County,
Ohio and generic Canada-wide import pages.

### Tag convention to match

Dominant form is `addr:city` + `addr:housenumber` + `addr:street` (738 of 811).
Postcode and province are sparse and inconsistent — `addr:province` splits `ON`
(27) against `Ontario` (2), so there is no convention to honour there, and
Toronto's `Ontario` is as defensible as anything present.

`addr:city` is **not uniformly `Hamilton`**: 738 `Hamilton`, but 32 `Dundas` and
5 `Stoney Creek` survived the 2018 rename. An amalgamated city retains
former-municipality names in the field its own cleanup pass targeted. Whatever
we upload has to take a position on this rather than assume one value.

### Who to talk to

Per `05`, detection produces a person. Here it produces **Kevo**, who in 2022
was adding Hamilton addresses from StatsCan LODE *by hand* — the changeset
comments say so explicitly: "Manually added some addresses from StatsCan LODE
data (by hand, no copy & paste or import)". That is precisely the labour this
platform automates, done by someone who chose to do it manually rather than
import. Approach accordingly. Matthew Darwin is the second contact, as the
Ontario-wide maintainer whose fingerprints are on the 2018 sweep here, in
Bruce, and in Guelph's tally.

## Mississauga's entry state — established (Tier 2, 2026-08-13)

Mississauga became a candidate only after the Peel correction, and the shortlist
entry above deferred it for want of a probe. Probed the same way: three
~0.012 deg `out meta` boxes in Port Credit, Streetsville and Malton — the two
towns that were independently incorporated until the 1974 amalgamation, plus the
detached north-east community — **1,086 elements**, plus changeset lookups, a tag
tally and a wiki check.

**Verdict: greenfield for a municipal address import.** The same strata as
Hamilton, minus the manual infiller. No wiki page, no import tags, no active
importer.

| stratum | evidence | year |
|---|---|---|
| NRCan/CanVec base layer | `source=CanVec 6.0 - NRCan` (309), `NRCan-CanVec-7.0` (251) — 80% of the 698 source-tagged elements | pre-2018 |
| StatCan address ranges | Mojgan Jadidi, cs 37570399, 2,102 changes, `source=StatCan 92-500-X`, "Adding address ranges for GTHA" | 2016 |
| POI mapping on top | `Bing` (50), `yahoo` (11); `shop`/`amenity`/`phone`/`website`/`check_date` throughout | ongoing |

Users: Matthew Darwin 637, andrewpmk 172, Mojgan Jadidi 54, Bootprint 41,
Schmooploop 35. Years: 2019 (581), 2026 (124), 2018 (71), 2016 (69), 2025 (69).

**The same StatCan campaign covers both cities.** Mojgan Jadidi's cs 37570399
here and cs 37445896 in Hamilton are the same 2016 "address ranges for the GTHA"
push, five days apart. Whatever adjudication policy we settle for one of these
cities against the federal layer applies unchanged to the other.

**The year distribution is entirely retag artifact.** Every peak resolves to one
of Matthew Darwin's province-wide cleanup sweeps, none of which added an address:

- 2019 (581) — cs 74017685 (6,942 changes) and 74017655 (7,074), both
  *"Remove redundant addr:country, addr:province"*
- 2018 (71) — cs 56806457 (9,831 changes), *"Remove addr:state in ON. addr:state
  is not used in Canada"*

The split across boxes makes the point sharply: 2019 is 293 of Port Credit and
286 of Streetsville but **2 of Malton**, while Malton's own modal year is 2018
(61 of 107). Nothing distinguishes those neighbourhoods except which sweep
touched them last. This is `05`'s last-touch-year caveat in its purest form —
the visible year says only when a bot-scale cleanup passed over, and the data
underneath is CanVec plus StatCan 2016 in both cases.

**The 2026 count is POI mapping, not an import** — which settles TODO item 1b's
question for this city. Port Credit carries 111 of the 124, and its box is a
dense commercial main street: `check_date` on 138 elements, `shop` on 106,
`amenity` on 112. The heaviest 2026 changesets are andrewpmk's ("Created a
beauty shop; Updated an estate_agent office…"). The 100 most recent changesets
over the full extent carry **no** `import` or `import:page` tag; the largest are
trails, sidewalks, crossings and Lyft-affiliated POI work.

### Tag convention to match

Dominant form is `addr:city` + `addr:housenumber` + `addr:street` (770 of 1,086),
with `addr:housenumber` + `addr:street` alone on 168.

**`addr:city` is uniformly `Mississauga`** — 893, against a single `Port Credit`.
This is the one place Mississauga is *cleaner* than Hamilton, where 32 `Dundas`
and 5 `Stoney Creek` survived the rename. Mississauga's amalgamation cleanup
finished; Hamilton's did not. The open `addr:city` policy question in TODO item 1
is therefore a Hamilton problem, not a general amalgamated-city one.

`addr:province` splits `ON` (46) against `Ontario` (16) — the same absence of a
convention found in Hamilton, in the same direction and ratio.

`addr:postcode` is on only 69 of 1,086 (6.4%). Peel publishes no postcode
either (`10`'s field-richness table), so unlike Guelph there is no enrichment
win available here.

### Who to talk to

Detection produces **Matthew Darwin** and no one else — the Ontario-wide
maintainer already named as Hamilton's second contact. There is no Kevo
equivalent: nobody has been hand-adding Mississauga addresses. Mojgan Jadidi is
a 2016 contact at most. This is a *shorter* contact list than Hamilton's, and
the two cities share it.

### How it ranks

Against Hamilton, on the four things that decide city #2:

| | Hamilton | Mississauga |
|---|---|---|
| missing | 128,065 | 116,109 |
| street-known | 91.6% | **96.6%** |
| entry state | greenfield | greenfield |
| source | own dataset | Peel, via `MUNICIPALITY` |
| `addr:city` policy | **unresolved** (Dundas, Stoney Creek) | settled |
| someone to stand down for | Kevo (manual infiller) | nobody |

**`MUNICIPALITY` is a clean split, measured 2026-08-13**, so the
`municipality_name` reservation the shortlist attached to Mississauga is weaker
than it looked. Peel's latest snapshot carries exactly three values, no nulls
and no variants: Mississauga 264,641 rows, Brampton 207,421, Caledon 31,861,
each 100% `STREETNAME`-populated and ≥98.2% `STREETTYPE`. Per the overlap
census, source-side separation is an attribute lookup and needs no polygon — so
reaching Mississauga does **not** wait on `10`.

**Units are the real asymmetry, and they are cheaper than `09` implies.**
Mississauga's 264,641 rows collapse to 148,037 distinct `number|street` keys
(the survey's independently-derived 148,262, to within 0.2%). The stacking is
almost entirely condo towers:

- 144,489 keys (97.6%) carry exactly one unit
- 3,548 keys (2.4%) absorb the remaining 120,152 rows — 34 deep on average,
  **591** at 4011 Brickstone Mews, then 3880/3888 Duke of York Blvd (484, 482)
  and 310 Burnhamthorpe Rd (472), all city-centre towers

`09` treats units as blocking, on Guelph's 24.4%-of-rows figure. Mississauga is
44% of rows but 2.4% of *addresses*, which is a different problem: the deferral
is an enumerable exclusion list of 3,548 civic addresses, not a pervasive
condition. Deferring units costs Mississauga 2.4% of its coverage; Hamilton's
dataset carries no unit field to defer at all.

## Oakville is brownfield-active — found by accident

The recent-changeset check over Hamilton's extent surfaced eight changesets from
**`TronnaLegacy`**, dated 2026-08-08/09, comment *"Oakville, Ontario addresses
from government data #maproulette"*, `source = Esri World Imagery; Oakville
Address Points (Open Government Licence - Town of Oakville)`.

Oakville is dataset #29 in our own portfolio: 49,322 missing (75.7%), 2026 peak
of 4,326 elements. **Someone is actively importing it, from the same municipal
source we would use, via MapRoulette, this week.** That is `05`'s
*brownfield, active* class — the one that says do not start anything, contact
first. Oakville was never on our shortlist, so nothing is lost, but it must be
marked before anyone reaches for it.

Two things follow. The find was incidental — Oakville sits in the corner of
Hamilton's rectangular extent, so this is `10`'s bbox bleed handing us something
useful for once. And the 2026 peaks in the Tier 1 table are worth re-reading as
possible live activity rather than noise, now that one of them demonstrably is.

## Candidate shortlist

Cities, not regions, and only where `street-known%` supports the number:

1. **Hamilton** — 128,065 missing, 91.6% street-known, single municipality,
   street resolves cleanly from `FULL_STREET_NAME` in props. The strongest
   single-city candidate in the portfolio, and as of 2026-08-13 the only one
   whose entry state has actually been established (§above): no municipal
   import, no wiki page, no active importer.
2. **London** — 98,973 missing, 77.9%, single municipality, clean `street`
   column.
3. **Brampton** — 135,117 missing, 87.1%. The City layer and the Region of Peel
   layer do cover the same ground (98.0% shared keys, 3 m median offset), but
   the caveat that used to sit here is **resolved as of 2026-08-13**: the City
   layer is authoritative on field richness (34 populated props incl.
   `POSTAL_CODE` and `UNIT_NO`, against Peel's 12) and on tracking history (54
   snapshots against 1). Use `brampton.toml`; Peel keeps Mississauga and
   Caledon.
4. **Windsor** (74,551, 72.8%) and **Kitchener** (48,489, 84.9%) behind those.

**Added 2026-08-13: Mississauga**, at 116,109 missing and **96.6%
street-known** — the highest street-known score of any candidate on this list,
Hamilton included. It ranks between Hamilton and London on size and above both
on data quality, and the Peel correction is the only reason it was not here from
the start.

**Probed and ranked the same day** (§"Mississauga's entry state" above). Both
reservations dissolved: it is greenfield on the same evidence that cleared
Hamilton, and `MUNICIPALITY` splits Peel cleanly enough that reaching it is an
attribute filter rather than a `10` dependency. It belongs **at position 1 or 2,
tied with Hamilton**, and the survey numbers do not break the tie — Hamilton is
10% larger, Mississauga is 5 points cleaner and has a settled `addr:city` and
nobody to stand down for; Mississauga owes 2.4% of its addresses to deferred
units and Hamilton owes none.

The tie breaks on what we want city #2 to *prove*, which is a judgment the
survey cannot make. Hamilton exercises the single-city path already built.
Mississauga forces the regional-dataset path (`03`'s `municipality_name`) that
19 of 42 datasets will eventually need, on the friendliest possible instance of
it — one attribute, three clean values, no polygon. Picking Mississauga buys
generalisation; picking Hamilton buys a shorter road to a second import.

Regional datasets (york 277,946, durham 181,390) are larger but each spans many
municipalities, which makes `municipality_name` handling (`03`) and polygon
clipping (`10`) prerequisites rather than nice-to-haves. `08` guessed ~19 of 42
are counties or regions; that holds. Mississauga is the first case where that
prerequisite blocks a specific, attractive city rather than a category.

## What this changes

- **`README`'s "assume brownfield until proven otherwise" is backwards.** The
  measured default is greenfield. Keep surveying first, but expect a gap.
- **The import machinery is not obsolete.** It was written for a case that
  looked like a one-off and is in fact the common case in Ontario.
- **`02` needs a correction**: canonical fields are not conflation-ready, and
  street resolution is a required per-dataset step.
- **`03`'s capability gating gains a concrete first case**: `has_street_type`.
  A consumer that doesn't check will silently produce garbage rather than
  refusing to run. Peel was cited here as the dataset that fails it; **it does
  not** (correction above), and the capability must be measured *after* street
  resolution or it answers the wrong question.
- **A survey can be wrong in the direction of refusal, not just of confidence.**
  Peel was written off as unusable for a day on a metric that was measuring the
  tracker's change-detection key rather than the dataset. The guard metric fired
  correctly; the reading of it did not. Every "this number is not trustworthy"
  verdict in this document deserves the same suspicion as the numbers it
  disqualifies.
- **`05` needs a new detection case.** The NRCan work carries no `import=yes`
  and no `import:page`, so a prior-import check that looks only for import tags
  returns "greenfield" for a city that already has a bulk-loaded address layer.
  Detect on *shape* — one user, one year, thousands of changes in a changeset —
  not on tags alone.
- **`03`'s `municipality_name` gate is narrower than assumed.** It was recorded
  as blocking Mississauga specifically. Peel's `MUNICIPALITY` field turns out to
  be three clean values, so the gate is real but the *capability* is satisfied
  here — which is the first evidence that regional datasets vary on this rather
  than failing as a class. Measure it per dataset before deferring a city for it.
- **Hamilton is cleared as city #2** (2026-08-13). The probe found a CanVec base
  layer and a manual local infiller, not a municipal import. `source` on the
  elements, not changeset tags, is what identified it.
- **Oakville is off-limits without a conversation** — actively being imported
  by `TronnaLegacy` as of this week.
- **Tier 2 is complete.** Every anomaly in the table is now accounted for: the
  2018 peak (NRCan + rename sweeps), Ottawa (a community, not an import),
  York's 2026 spike (our own Toronto upload) and Wellington's 2025 spike
  (Guelph's import, wholly contained in the county rectangle).
- **Three of those four explanations were bbox artifacts or retags, not
  activity.** The naive reading of the `peak year` column was wrong in every
  case it looked interesting. Treat the column as a prompt to investigate, never
  as a finding.
- **Source-side overlap is nearly absent, and `10` splits in two** (2026-08-13).
  Only 2 of 861 dataset pairs genuinely duplicate. Ontario's two-tier structure
  decides it: separated cities are outside their county's layer by construction,
  lower-tier municipalities are inside it. So source dedup is a municipality
  **attribute** lookup, and the polygon is needed for the **OSM** side — where
  every conclusion a rectangle actually changed was found.
