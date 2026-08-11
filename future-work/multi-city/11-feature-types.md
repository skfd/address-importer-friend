# The second axis: feature types, not just cities

Status: **new constraint, surfaced in discussion 2026-08-10.** Changes the
domain model in `01` and `02`.

## The constraint

Multi-city is only one axis. The platform will also grow **beyond addresses** —
fire hydrants were the example given, imported the same way addresses are.

The family already spans feature types without having named the axis:
`toronto-parks-layer`, `toronto-streets-layer`, `toronto-streets-osm`,
`bikeshare-toronto-maproulette`. Addresses are simply the first and
best-developed instance.

So the unit of work is not a city. It is a **dataset**: a
`(jurisdiction, feature-type)` pair. Guelph addresses, Toronto hydrants,
Oakville addresses. These must not be bundled — a hydrant run and an address
run share machinery but share no review queue, no watermark, and no
adjudications.

## What this does to the layering

It splits the core in two, at a seam that also answers the `address-layerist`
question (see below):

**L1 — dataset layer.** The TOML contract, vault access, SCD-2 snapshot
reading, field mapping, watermarks. Its *shape* is feature-type agnostic — any
"dated snapshots of a point layer with a stable identity key and a props blob"
fits, and `ontario-address-changes` proves the shape holds across all 42
datasets.

**But `ontario-address-changes` stays address-only.** Clarified in discussion
2026-08-10: it will not track hydrants. It keeps its name, its scope, and its
42 address datasets, and needs no rename. Feature-type genericity is a property
of **L2–L4 only** — `accordeur`, the beholder, and the importer.

Consequence: if a hydrant dataset ever happens, its L1 is *not* the tracker.
It would come from the vault directly, or from a sibling tracker, or ad hoc.
Do not generalize the tracker in anticipation — the hydrant case is
hypothetical and no L1 work should be done for it speculatively.

**L2 — conflation layer.** Spatial index, verdicts, check registry,
adjudication client. Mostly generic, with one domain-specific hole: the
**identity predicate**. For addresses it is `housenumber + normalized street`
within a radius. For hydrants it is probably proximity alone, possibly plus a
municipal id. That predicate is the plug point.

**L3 — domain packs.** Everything that knows what an address *is*: street
normalization and profiles (`01`), housenumber semantics, `addr:*` tag
mapping, the address-specific checks. A `hydrants` pack would carry
`emergency=fire_hydrant`, its own matching rule, and its own tag mapping.

**L4 — consumers.** Beholder (observe), import tool (upload), layerist (tiles).

Street normalization moving from "the core" to "the addresses domain pack" is
the main correction this forces on `01`.

## What it does to `address-layerist`

Decided in discussion: layerist **stays a separate project**. The layering
above explains why that is right rather than merely convenient — layerist needs
**L1 only**. It reads a source, maps fields, and renders tiles. It never
conflates, so it has no use for L2 or L3.

So the "common logic into its own lib" intuition resolves to: **layerist and
the conflation stack share L1, and nothing above it.** L1 is small, stable, and
already half-built across `address-vault` (acquisition + snapshot store) and
the `datasets/*.toml` contract (field mapping). Extracting it is mostly
consolidation of things that already agree, not new design.

That also means the shared artifact is as much **data files as code** — the
dataset TOMLs are the contract, and they are already byte-compatible across
tracker, vault, and layerist.

## Open questions

1. Does the dataset TOML gain a `feature_type` key, or is feature type implied
   by which domain pack a consumer loads? Note this is a question about
   `accordeur`'s config, not the tracker's — the tracker's TOMLs are all
   addresses and stay that way.

## What this axis is and isn't

It is a constraint on how `accordeur` and the beholder are *shaped* — keep the
identity predicate pluggable, keep review queues and watermarks per-dataset,
don't hardcode `addr:*` into the conflation engine. All of that is cheap if
done from the start and expensive to retrofit.

It is **not** a mandate to build hydrant support. Nothing in this document
should be read as scheduled work.
