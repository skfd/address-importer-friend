# Beholder generalization — first target

Status: **agreed as the first implementation target, not started.**
Captured 2026-08-10.

Repo: `C:/Users/kk/Code/toronto-import-beholder`.

## Why it goes first

- **It is nearly generic already.** 1,122 LOC total, with Toronto references in
  exactly three files: `beholder/config.py` (3), `beholder/osm.py` (1),
  `beholder/city.py` (1). Compare `t2` at ~10,800 LOC across four coupling
  tiers.
- **Its core abstraction is already right for brownfield cities.** "For every
  City address point: PRESENT or MISSING, and in what *representation* — node /
  building / way / relation / interpolation." That representation concept is
  exactly what a 94%-mapped city needs, and it does not exist in `t2`.
- **It is the product Guelph actually needs.** A city with a 2,523-address gap
  and a completed prior import does not want an import pipeline; it wants a
  tracked completeness audit with mapper notes.
- **It already thinks in append-on-change events**, which is the data model the
  adjudication layer needs (`06`).
- **Low risk.** It is standalone by design — it does not import `t2`'s code or
  DB, so generalizing it cannot disturb Toronto's living 2 GiB `tool.db`.

## What actually needs changing

**Config** (`config.toml`, `beholder/config.py`): `[city] sqlite_path` becomes
slug-driven; `[osm] toronto_bbox` becomes a city bbox **plus a boundary
polygon** (`10` — Guelph's rectangle bleeds into Eramosa Township and accounts
for most of its 7,818 OSM-only addresses).

**Street normalization** (`beholder/streets.py`): delete in favour of the
shared core package (`01`). This file is the clearest instance of the
triplication problem — byte-identical tables and the same 13 overrides as
`t2/conflate.py`.

**OSM source**: `[osm] source` is already `overpass` | `file`. For a portfolio
of 42 cities, the PBF path matters more than Overpass — see `04`.

**Notes → adjudications** (`beholder/notes.py`): grows into the client for
`06`. Its three preset tags are a good starting taxonomy and should be
preserved as the seed vocabulary.

**Auth** (`beholder/auth.py`): `allowlist = ["skfd"]` keeps its shape and
becomes **per-dataset**, keyed on OSM usernames via OAuth (`06`). Reputation
gates and moderation queues were sketched here originally and are now
deliberately deferred — the hand-edited allowlist closes the abuse surface by
construction, so there is nothing to moderate.

## Deployment shape — settled

Decided in discussion 2026-08-10: **per-dataset deployment**, with the beholder
supporting two modes:

- **single-set mode** — one dataset (e.g. Guelph addresses). The default.
- **multi-set mode** — several related datasets in one instance, where bundling
  them genuinely makes sense.

The deciding argument was not cities at all, but **feature types** (`11`). The
platform will grow beyond addresses — hydrants were the example — and a hydrant
import has no business sharing a deployment, a review queue, or a watermark
with an address import. "One instance per city" would have forced exactly that
bundling.

So the unit of deployment follows the unit of work: a `(jurisdiction,
feature-type)` dataset, with multi-set as an opt-in for cases that want it.

Consequence for config: per-dataset config is a **file**, not a table, and the
allowlist (`06`) is per-dataset for the same reason.

## Guardrails

1. **Do not couple it to `t2`.** Its standalone status is a feature. The
   shared dependency should be the new core library (`01`), not this repo.
2. **Preserve the append-only history.** It is the audit trail and the basis
   for auto-reopen. Any schema change must keep old events readable.
3. **Verify against Toronto first.** A Guelph-driven change that alters
   Toronto's PRESENT/MISSING counts is a regression, and the beholder's whole
   value is that its history is comparable over time.
