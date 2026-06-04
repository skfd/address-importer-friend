# Bulk rewrite of `source=…` to `addr:source=…` on uploaded address nodes

Status: **abandoned (2026-06-03).** Investigated and dropped after a read-only
pilot showed the premise does not hold. Kept as a record so the idea is not
re-proposed without the evidence below.

## The original idea

Every node this import uploaded carries `source=City of Toronto Open Data`
(`t2/osm_export.py` `STATIC_TAGS`). The thought was that `addr:source` is the
better-fit key for an attribute describing the *address*, and that a single
automated follow-up campaign could rewrite the ~449,052 imported nodes — plus
any that had since been merged into building ways/relations — from `source` to
`addr:source`, value-pinned and version-checked.

## Why it was abandoned

The campaign hinged on one assumption: that `source=City of Toronto Open Data`
(especially combined with `addr:*`) is **unique to this import**, so it could be
discovered and rewritten mechanically — including on ways/relations found by an
Overpass tag sweep. A read-only pilot run (tool since removed) disproved this.

`source=City of Toronto Open Data` is a **shared community convention**, used by
many mappers and prior imports over 15+ years, not our signature. Evidence:

- [way/43605687](https://www.openstreetmap.org/way/43605687) — created 2009 by `andrewpmk`.
- [way/659609697](https://www.openstreetmap.org/way/659609697),
  [way/660034509](https://www.openstreetmap.org/way/660034509),
  [way/662380823](https://www.openstreetmap.org/way/662380823) — building
  footprints created 2018–19 by `DannyMcD_imports`.
- [way/1525370738](https://www.openstreetmap.org/way/1525370738) — created
  2026-06-02 by `Shrinks99`, *with* the tag from version 1. Mappers are still
  applying it to new buildings.

An Overpass sweep for `source=City of Toronto Open Data` + `addr:housenumber`
returned **~1,580 ways** citywide — far too many to be merges of our nodes in
the days since the import.

The "old geometry, address grafted on recently, so the value is ours" theory was
also tested directly against version history and failed. For
[way/659609697](https://www.openstreetmap.org/way/659609697):

| Version | Date | Changeset | By | `addr:housenumber` | `source` |
|---|---|---|---|---|---|
| v1 | 2018-12-31 | 65923628 | DannyMcD_imports | — | — |
| v2 | **2026-04-09** | 181119698 | che_ | 72 | — |
| v3 | 2026-05-25 | [183166231](https://www.openstreetmap.org/changeset/183166231) | andrewpmk | 72 | City of Toronto Open Data |

The address was added by `che_` **a month before our import started**
(2026-05-13), and the `source` tag was added by `andrewpmk` in his own JOSM
changeset ("Fix address" / "cleanup", 871 objects) — `skfd imports` never
touched the way. The tag value is `andrewpmk`'s, not ours, and is
indistinguishable by value alone from one we wrote.

**Conclusion:** there is no reliable way to identify which objects carrying
`source=City of Toronto Open Data` are ours, beyond the node ids in our own
upload manifest. A tag sweep would rewrite other mappers' edits.

## If ever revisited

Only two object sets can be *proven* ours:

1. Nodes in the upload manifest that are still present — the pilot found these
   clean (176/176 in the pilot tile, value intact, no `addr:source`).
2. Manifest nodes that now return **410 Gone** — the genuine merges into
   ways/relations, located individually from the deleted-node set (≈0 so soon
   after the import).

A blind Overpass sweep on the tag value is **not** a valid discovery method.

Even restricted to (1), this is a no-human-review automated edit over hundreds
of thousands of objects, which under the OSM Automated Edits Code of Conduct
requires documented community consensus first — a non-trivial cost for a
cosmetic key change. That cost, against the marginal benefit, is why it was not
pursued.
