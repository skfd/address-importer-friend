# Core library extraction

Status: **proposed, not implemented.** Captured 2026-08-10.

## Motivation

Three tools in the family need the same conflation primitives, and today they
each carry their own copy.

`t2/conflate.py:14-46` defines `STREET_SUFFIXES`, `DIRS`,
`STREET_SUFFIX_EXPAND`, `DIRS_EXPAND`. `toronto-import-beholder/beholder/streets.py`
defines byte-identical `STREET_SUFFIXES` and `DIRS`, plus the same 13
`STREET_NAME_OVERRIDES` entries. The beholder's module docstring says this is
deliberate:

> "Reimplemented from the import tool's t2/conflate.py (referenced, not imported)."

That was a defensible call at two Toronto-only tools. At *n* tools × *m*
cities it is the first thing that rots, and it rots silently: a street override
added to one copy makes the two tools disagree about whether an address is
present, with no error anywhere.

Note this is also the most *city-specific* code in the family. So it is
simultaneously the thing most needing sharing and the thing least able to be
shared as a single fixed table. It has to become **engine + per-city profile
data**, not one table.

## What belongs in the core

Deterministic, no I/O beyond reading files it is handed:

- **Street normalization** — `normalize_street`, `expand_street_name`,
  `apply_street_override`, `_glue_mc_prefix`, driven by a named profile rather
  than module-level constants.
- **Conflation primitives** — `GridIndex`, `haversine`, the POI-node filter
  (`_is_poi_node`), the match/near radius logic.
- **Source-DB reading** — the SCD-2 projection over
  `ontario-address-changes`' output schema. That schema is already identical
  across cities (verified: `guelph.db` and `toronto.db` have the same
  `addresses` columns); only the `props` blob differs, which is what `02`
  and `03` address.
- **Onboarding probes** — the deterministic half of `04`/`05`.

## What must NOT go in the core

- Anything reading `config.toml`, `.env`, or `tool.db`. The core takes values,
  not configuration.
- The review UI, upload, changeset, and OAuth machinery. Those are the import
  consumer's concern and most cities will never invoke them.
- The adjudication client (`06`) — that is a separate, networked concern.

## The street profile question

Guelph proves a single table cannot serve every city. Measured 2026-08-10:

- Guelph's `FULLNAME` is **already OSM long form** — `"Cork Street West"`,
  with `STSUF="Street"` and `STDIR="North"` as separate props. Toronto's
  `expand_street_name()` is a **no-op** there. It happens to be harmless
  because the long forms are not keys in `STREET_SUFFIX_EXPAND`, but that is
  luck, not design — an expander built for a short-form source ran against a
  long-form source and silently did nothing.
- Guelph has suffixes Toronto's table has never seen: `Glen`, `Walk`, `Run`,
  `Crossing`. `normalize_street` leaves unknown tokens alone, so matching still
  works *as long as both sides are left alone consistently* — the invariant
  that matters is symmetry, not correctness.

So a profile needs at least: the suffix/direction tables, whether expansion
runs at all and in which direction, and the per-city override table. The
override table stays in git (see `02`) — it is a stable, curated artifact.

## Guardrails

1. **The normalizer must stay symmetric.** Both the source side and the OSM
   side go through the same function. Any change that normalizes one side
   differently from the other silently changes match rates across every city.
2. **Extraction must be provably behaviour-preserving for Toronto.** The
   existing tests (`tests/test_expand_street_name.py`,
   `tests/test_street_override.py`) are the contract. Toronto's `tool.db` is
   living (2 GiB, runs through 2597) — a normalizer change that shifts match
   rates would invalidate comparisons against prior runs.
3. **Do not "fix" the Sunnyslope entry.** `t2/conflate.py:138-143` documents an
   override whose value intentionally has no street-type suffix. It will look
   like a bug to anyone generalizing the table.

## Naming / packaging

**Named `accordeur`, decided 2026-08-10.** From French *accorder*, to bring
into agreement — everyday sense, a piano tuner. The name states the thesis:
the tool's job is to bring two independent records into agreement, not to
overwrite one with the other.

Rejected: `osm-conflate` / `conflator` — Ilya Zverev's OSM Conflator is an
established tool in this exact problem space and the collision would be both
confusing and discourteous. Also considered and passed over: `concordance`
(precise but inert), `arpenteur`, `recenseur`, `concordancier`,
`collationneur`, `rapprochement`.

Note `accordeur` names the **conflation layer (L2 + the L3 domain packs)**, not
the dataset layer — see `11` for the split. L1 is unnamed and may simply become
part of `address-vault` rather than a separate package.

It should be installable standalone (`pip install -e ../accordeur`), matching
how `oakville-address-layer` depends on `address-layerist`. Built inside this
repo first, with this repo as its first consumer, and split out when the seam
holds.

## Possible first step

This is the safest thing to start, if we want code before the design settles:
extracting the normalizer is a pure refactor with existing test coverage, and
it does not prejudge any of the open questions in `06`.
