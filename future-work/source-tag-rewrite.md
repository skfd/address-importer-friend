# Bulk rewrite of `source=…` to `addr:source=…` on uploaded address nodes

Status: **abandoned (2026-06-03).** Investigated and dropped after a read-only
pilot showed the premise does not hold. Kept as a record so the idea is not
re-proposed without the evidence below.

## Update 2026-08-27: new nodes write `addr:source`, and 49 do not

Two things moved after this was abandoned, neither reviving it.

**Forward-only correction.** New nodes now write `addr:source` directly, so the
backlog this campaign would have cleared stopped growing. The premise sentence
below ("every node this import uploaded carries `source=…`") is true of the
rollout, not of maintenance runs from 2026-08-27 onward. `STATIC_TAGS` is gone
with it — `osm_export.build_tags` is the one builder now.

**A 49-node seam.** That change landed on the preview path first and on the
upload path 52 minutes later, and one maintenance run went out in between:
changeset [188123936](https://www.openstreetmap.org/changeset/188123936),
run 2599, 49 nodes, uploaded 2026-08-28T00:55Z with the bare `source` key while
the review UI and the proposal page both said `addr:source`. They are ours
provably — the run's candidate rows carry their node ids — so if anything ever
does rewrite manifest nodes, these 49 belong in the same set. Nothing else is
affected: the run before it was 2026-07-23.

**The proposal page needs a look either way.** § Post-import follow-ups
describes this campaign as scoped and forthcoming, and links it as
`toronto-2-address-import/blob/main/future-work/source-tag-rewrite.md` — a path
that 404s, since future-work moved to the engine repo in the split. A public
page pointing at a missing file that would have told the reader the campaign
was abandoned is worse than either fact alone.

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
