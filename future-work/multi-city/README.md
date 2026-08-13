# Multi-city generalization

Status: **design discussion, nothing implemented.** Opened 2026-08-10.

These documents capture a design conversation about making the address-import
family work for cities other than Toronto. Nothing here is scheduled, and no
code has been written. Each file is ideas-focused: enough context and enough
of a data-model sketch that the next session can pick it up cold.

Everything below is frozen at 2026-08-10. Re-verify against current code
before implementing — in particular the file:line references, and the Guelph
and OSM numbers, which were measured once and will drift.

## The family this spans

Multi-city is not a change to one repo. Five sibling projects share the
problem, and two of them have already solved parts of it:

| Repo | Role | Multi-city status |
|---|---|---|
| `ontario-address-changes` | acquires + change-tracks municipal address feeds | **already generic** — 42 datasets, all 42 DBs on disk |
| `address-layerist` | turns a feed into iD/JOSM tile layers | **already generic** — engine + thin per-city repos + onboarding skill |
| `address-vault` | data acquisition | separate tool, generic by design |
| `toronto-import-beholder` | audits OSM address completeness over time | Toronto-coupled but only ~5 references in 1,122 LOC |
| `toronto-2-address-import` (this repo) | conflate → review → upload | Toronto-coupled across four tiers (see `02`) |

`address-layerist` already established the house pattern and it works:
**reusable engine + thin per-city repo carrying one TOML + a Claude Code skill
for the fuzzy onboarding step**, with the config's data-source block
byte-compatible with `ontario-address-changes/datasets/<slug>.toml`. New work
should align to that pattern rather than invent a second one.

## Decisions taken in discussion

1. **Baseline conflation always runs in full**, for every city, regardless of
   how much of it is already mapped. Upload is the conditional part, not
   conflation. Rationale: entering a brownfield city in maintenance-only mode
   inherits the prior state's errors invisibly — you only ever see changes from
   the watermark forward and never learn what was already wrong.
2. **One core, two consumers.** The conflation baseline is the shared thing.
   The import machinery (this repo) and the observer (`beholder`) are two
   consumers of it. An earlier framing of "two products" was wrong.
3. **Cities have an entry state**, and it determines the consumer:
   greenfield → import; brownfield-complete → observer/QA; brownfield-active
   → coordinate with the existing importer before doing anything.
4. **Stable things live in git; shifting things live in the adjudication
   store.** Street-name mappings, per-city policy, capability declarations —
   all git-tracked config, discovered during onboarding or during an import.
   Only per-point, changes-over-time adjudications go to the shared store,
   which is publicly observable and limited-audience writable (`06`).
5. **Start with the beholder** (`07`). It is 1,122 LOC, nearly generic
   already, and it is the product a brownfield city actually needs.
6. **Locked vs fuzzy**, borrowed from `address-layerist`: deterministic probes
   belong in the library, judgment belongs in a skill.
7. **The unit of work is a dataset, not a city** — a `(jurisdiction,
   feature-type)` pair, so deployments, allowlists, watermarks and review
   queues are per-dataset. Feature-type genericity applies to `accordeur`, the
   beholder and the importer **only**; `ontario-address-changes` stays
   address-only and keeps its name. The hydrant case is hypothetical — shape
   the code for it, don't build for it. See `11`.
8. **Write access is a hand-edited per-dataset allowlist.** No moderation UI,
   no signup flow. Closes the abuse surface by construction (`06`).
9. **`address-layerist` stays separate.** It needs only the bottom layer (source
   reading + field mapping + vault access), never conflation (`11`).
10. **The library is built here, in this repo**, and this repo becomes its first
    consumer.
11. **The library is named `accordeur`** (decided 2026-08-10). French, from
    *accorder* — to bring into agreement; the everyday sense is a piano tuner.
    Chosen for what it says about the work: the job is agreement between two
    records, not conquest of one by the other. Accent-free, no collision with
    OSM tooling or Python packages. Deliberately **not** `osm-conflate` /
    `conflator`, which is Ilya Zverev's established OSM tool in this same
    problem space.

    Prospective sibling names, not decided: `greffier` (the register-keeper) for
    the adjudication store, and the vault keeping the raw record. Three names
    that explain their relationship rather than three unrelated words.

12. **City #2 is Hamilton** (decided 2026-08-13). Both it and Mississauga
    probed greenfield and the survey numbers tied; the tie-break was to keep the
    first generalization outing on the single-city path already built, rather
    than test a regional source split and a unit deferral at the same time.
    Mississauga becomes the designated first regional-dataset city. See TODO
    §1c and `08`'s "How it ranks".

## The finding that drove all of this

Guelph was picked as city #2 on intuition. A survey on 2026-08-10 found it is
**~94% already in OSM** — 47,687 `addr:housenumber` elements against 40,634
distinct source addresses, leaving a gap of **2,523**. Toronto's import was
~449,000. The prior Guelph import was run by someone else, in JOSM, with a
wiki page, and was declared complete on 2025-10-23 (`05`).

Toronto was the outlier, not the template. Building-footprint imports have
already seeded most mid-size Canadian cities. Assume every new city is
brownfield until a survey proves otherwise.

**Corrected 2026-08-12 by the portfolio survey
([08-survey-results-2026-08-12.md](08-survey-results-2026-08-12.md)): the
generalisation above is wrong.** Toronto (0.5% missing) and Guelph (6.3%) are
the only two datasets below 15%; 33 of 42 are above 75%. Ontario is mostly
greenfield, and Guelph was a coincidence rather than evidence. What survives is
the narrower lesson: **survey before committing to a city** — just expect a gap
rather than expect it to be gone.

## Index

The action list is [TODO.md](TODO.md) — open work only, ordered by what blocks
what. Finished items live in [DONE.md](DONE.md), kept because several open
items depend on what was decided there. Start in TODO.md; the numbered design
docs below are reference.

- [01-core-library.md](01-core-library.md) — extract the shared conflation +
  street-normalization core. The normalizer is currently triplicated.
- [02-city-config-contract.md](02-city-config-contract.md) — the per-city TOML,
  what it declares, and the cross-repo `keep_fields` contract with
  `ontario-address-changes`.
- [03-capability-gating.md](03-capability-gating.md) — checks and features that
  must disable themselves when a source lacks the fields they need. Currently
  they would fail silently open.
- [04-city-onboarding.md](04-city-onboarding.md) — the onboarding flow:
  deterministic probes in the library, judgment in a skill.
- [05-prior-import-detection.md](05-prior-import-detection.md) — how to find
  out whether someone already imported this city, worked end-to-end on Guelph.
- [06-adjudication-layer.md](06-adjudication-layer.md) — the collective
  "this mismatch is deliberate" store. The largest and least-settled design.
- [07-beholder-generalization.md](07-beholder-generalization.md) — first
  implementation target.
- [08-portfolio-survey.md](08-portfolio-survey.md) — sweep all 42 tracked
  datasets to design against real distributions instead of two data points.
  **Run 2026-08-12** →
  [08-survey-results-2026-08-12.md](08-survey-results-2026-08-12.md) (+ raw
  [JSON](08-survey-results-2026-08-12.json)). Validated against Guelph and
  Toronto; inverts the greenfield/brownfield assumption and shows the tracker's
  canonical `street` column is not conflation-ready.
- [09-units.md](09-units.md) — `addr:unit`, deferred but recorded. Guelph has
  13,162 unit rows and stacks of up to 214 at one civic address.
- [10-boundary-clipping.md](10-boundary-clipping.md) — bbox bleed into
  neighbouring municipalities; needs polygon clipping, not rectangles.
- [11-feature-types.md](11-feature-types.md) — the second axis. Hydrants, not
  just cities. Splits the core into a dataset layer and a conflation layer,
  and explains why layerist stays separate.

## Open questions

Carried into the next session, in priority order:

1. Adjudication data model — scope levels, key stability, auto-reopen (`06`).
   Largest remaining design. Everything else adapts to it.
2. How much pushes back into OSM natively vs stays in the store (`06`).
3. ~~Whether to run the 42-dataset survey now (`08`)~~ — **done 2026-08-12**,
   and ~~which city is #2~~ — **answered 2026-08-13: Hamilton.** Both it and
   Mississauga probed greenfield; the tie was which path to exercise first, and
   Hamilton runs on the single-city path already built. Mississauga is the
   designated first regional-dataset city, deferred not rejected (TODO §1c).
   The survey's other question — the province-wide 2018 edit peak — is answered
   too (a retag sweep, Tier 2).
4. Units: collapse-and-defer vs design first (`09`). Blocks Guelph and
   Mississauga; **does not block Hamilton**, which defers no unit addresses.
5. Does `accordeur`'s dataset config gain an explicit `feature_type` key (`11`)?
6. Whether to contact `ARandomThumbtack_Import` before doing anything in
   Guelph (`05`). An action decision, not a design one, and the kind that gets
   postponed indefinitely unless it is on a list.
7. Licensing of contributed adjudications (`06`).
8. Which boundary is authoritative — municipal or OSM `admin_level=8` (`10`).

Questions 1 and 2 are really one conversation and are the natural place to
resume.

## Safe to start before the above settle

Neither prejudges any open question:

- Extracting the street normalizer into `accordeur` — pure refactor, covered by
  `tests/test_expand_street_name.py` and `tests/test_street_override.py`.
  Guardrail: Toronto's match rates must not move (`tool.db` is living).
- The portfolio survey (`08`) — it is research, and it becomes the onboarding
  probe (`04`).
