# Bulk rewrite of `source=…` to `addr:source=…` on uploaded address nodes

Status: **proposed, not implemented**. Captured 2026-05-28, immediately after
the import finished. Post-import follow-up.

## Motivation

Every node this import uploaded carries

```
source=City of Toronto Open Data
```

This was the tag chosen in `IMPORT_PROPOSAL.mediawiki` § Tagging plan and used
unchanged from the dev-sandbox pilot through the 1,297 production changesets
(2026-05-13 → 2026-05-28). It satisfies the OGL-Toronto attribution
requirement and matches the changeset-level `source` tag.

After the import ran, two issues with it became clear:

1. **`addr:source` is the better-fit, more-used key for an attribute that
   describes the address itself.** Taginfo:
   `addr:source` has wider current usage on address features than a bare
   `source` tag for the same purpose, and survives object merges more
   cleanly — a mapper merging our pure-address node into a building polygon
   will copy `addr:source=…` onto the resulting building tags without
   confusion, whereas `source=…` is ambiguous (does it source the building
   geometry, or the address?).
2. **Bare `source` is per-OSM-convention a changeset-level concern.** Some
   editors and validators treat per-node `source` as dispreferred or warn
   on it. Keeping the changeset-level `source=City of Toronto Open Data`
   tag handles the attribution requirement; the per-node tag should
   describe the *address* specifically.

Maintainer commitment: noted in the Day-10 blog entry — "should have been
setting `addr:source`, instead of generic `source` tag. […] I think I will
bulk-replace it after I'm done."

## Scope

A single follow-up changeset run from the `skfd imports` account that, for
every node uploaded by this import:

1. Removes `source=City of Toronto Open Data` (only when the value matches
   verbatim — never strip a different `source` value a later mapper added).
2. Adds `addr:source=City of Toronto Open Data` if no `addr:source` is
   already present.
3. Leaves every other tag untouched.

Target set: the OSM node ids listed in
`docs/pilot/uploads/all.csv` — the cumulative upload manifest committed to
by `IMPORT_PROPOSAL.mediawiki` § Post-upload reconciliation. ~449,052 nodes
across 1,297 source changesets.

Out of scope:

- Nodes the manifest claims we uploaded but that have since been deleted or
  merged into a building polygon — skip silently.
- Nodes whose `source` tag was modified by a later mapper — skip and log;
  do not overwrite.
- Any other tag rewrite (street-name corrections, postcode additions,
  housenumber fixes). Those each get their own proposal.

## Why post-import, not at upload time

The right tag would have been `addr:source` from the start — the per-node
tag belongs in the `addr:*` namespace because it sources the address. The
mistake was made in `IMPORT_PROPOSAL.mediawiki` § Tagging plan and propagated
through the pilot review without anyone catching it. Fixing it during the
import would have meant revising the published proposal mid-flight and
breaking the uniform-tag-set guarantee the proposal asserts; deferring lets
the rewrite happen as one well-scoped, separately-reviewable changeset run.

## Hard guardrails

1. **Per-node version-checked write.** Re-fetch each node via
   `GET /api/0.6/node/{id}` immediately before upload. On 409 conflict
   (version mismatch — the node has been touched since), skip and log.
2. **Tag-value pinning.** Skip any node whose current `source` value is
   not exactly `City of Toronto Open Data` — that means a later mapper
   changed it, and we don't know whether their intent was to retag or to
   re-source.
3. **Per-batch human approval.** Process in tile-sized batches (the
   existing manifest is already tile-partitioned), each as a distinct
   changeset, each requiring an explicit operator click — no auto-approve
   across the whole 449k set.
4. **New changeset comment / tags.** Distinct from address-creation
   changesets:
   - `comment=Toronto Open Data address import — rename source to addr:source on previously-imported nodes`
   - `source=City of Toronto Open Data`
   - `import=yes`
   - `bot=no`
   - `created_by=t2-address-import`
   - `import:kind=source_to_addr_source_rewrite`
   - `import_plan=https://wiki.openstreetmap.org/wiki/Toronto/Import/AddressPoints`
5. **Public notice on the OSM Community Forum thread before starting.**
   This is a mutation pass over an existing import, not an addition; the
   community deserves the heads-up and an opportunity to object.

## Code changes

The current pipeline uploads `<create>` blocks only (see
`t2/osm_export.py:osmchange_xml`, `t2/osm_client.py:_upload_diff`). A rewrite
pass needs a `<modify>` path:

- `t2/osm_mutate.py` (new) — version-checked re-fetch + diff builder that
  emits a `<modify>` element preserving every existing tag, deleting one,
  and adding one. Same module sketched for the postcode-enrichment
  proposal (`future-work/postcode-enrichment.md`) — share the code.
- `scripts/source_tag_rewrite.py` (new) — reads the cumulative upload
  manifest, opens a changeset per tile, calls the new uploader, writes
  one CSV row per node showing the action taken (rewritten / skipped /
  conflict / deleted).
- No DB migration needed — outputs are external CSV. We do not store the
  rewrite in `tool.db` because the rewrite is one-shot and not part of the
  conflation pipeline.

The reviewer-UI changes for postcode enrichment are not required here —
this is a mechanical rewrite, not a per-node judgement call, and the
guardrails above (value pinning + version check + skip-on-conflict) make
it safe to batch.

## Verification

- Before/after counts via taginfo: the count of nodes in the Toronto bbox
  carrying `source=City of Toronto Open Data` should drop by ~the number
  of successful rewrites; the count carrying
  `addr:source=City of Toronto Open Data` should rise by the same number.
- Per-tile rewrite CSV: every row in the upload manifest should appear
  with a status (`rewritten`, `skipped_value_changed`, `skipped_deleted`,
  `conflict`).
- Spot-check 10 random nodes in JOSM before declaring the rewrite done.

## Open questions

1. Run as one continuous campaign (one changeset per minute, same cadence
   as the original import) or as a slow trickle over a few weeks? The
   former matches the import cadence the community is already familiar
   with; the latter is gentler if the validator noise is high.
2. Do we also want to retag the *changeset-level* `source` going forward
   on any future address-import work in this repo? Separate decision —
   does not block this rewrite.
