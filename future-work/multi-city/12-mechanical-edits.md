# Mechanical edits — per campaign, not an engine subsystem

Decided 2026-08-27, when Guelph's published plan gave the engine its first
requirement to *modify* an existing OSM object. The engine only ever created
nodes.

## The decision

**Campaigns are written per campaign, in the city checkout. The engine
provides transport only.**

What shipped here is three primitives in `t2/osm_client.py` —
`create_changeset(tags)`, `upload_osmchange(changeset_id, body)`,
`close_changeset(id)` — generic, with the run pipeline as one caller. A
campaign script imports them so it can reuse the encrypted OAuth token, the
401-refresh and the 429-backoff, and so there is never a second place holding
write access to the import account. Everything above the transport — which
objects, what to skip, what to record — lives with the campaign.

What was declined: a general mechanical-edit subsystem in the engine, with its
own batch model, review UI, audit tables and revert path. Two one-shot
transforms in one city, gated on a consent window that may not close in favour,
is not a second consumer. This repo's own history is extract-on-the-second-
consumer; the same rule applies to itself. If a third campaign in a second city
wants the same shape, extract it then, from two working examples.

## What a campaign may not drop

The handover that prompted this bundled two kinds of requirement, and only one
kind is the city's to trade away. Splitting them is the point of this file.

**Engine hygiene — droppable, and dropped.** Reusing the engine's review queue
and audit log; batching by the neighbourhood-tile partition the import uses.
None of it is promised to anyone. A rendered diff the operator reads and signs
off satisfies "a human approves"; batching by size is fine.

**Published or corruption-preventing — not droppable, wherever the code
lives.** Guelph's wiki page (§ Mechanical edits) promises these in print:

- **Refetch every object's version immediately before upload and skip any that
  moved.** Never overwrite an object edited since the batch was prepared.
- **Record the prior value and prior version, per object**, committed to the
  city checkout — that is what makes a revert mechanical rather than a
  reconstruction.
- **One campaign, one batch, one changeset**, touching exactly one tag key.
  Attribute-only: no geometry, no deletions, no node creation.
- **Changeset tags as the import's**, with `mechanical=yes` in place of
  `import=yes`, a comment naming the campaign, and `import_plan` pointing at
  the wiki section.
- **Tests for the cases that corrupt silently**, living with the script.

## The two Guelph campaigns (not run)

Both are gated on the forum's 14-day feedback window closing with consent, and
neither is written yet.

**(a) Remove `addr:province`** — ~3,699 objects, no replacement value, the
`=ON` variants removed on the same pass.

**(b) Split double-encoded unit housenumbers** — ~5,422 objects with
`addr:housenumber="714-30"` **and** `addr:unit="30"` become
`addr:housenumber="714"` with `addr:unit` untouched. The two traps: a letter
suffix that *is* the civic number (`645A`) is not a unit and must survive
unchanged, and the ~17 objects carrying the combined form with **no**
`addr:unit` must be skipped, not guessed — they are hand-work. Apply only when
`addr:unit` exists and confirms the split.

Explicit non-goals: unit-level address import, deletions, `addr:interpolation`
cleanup, polygons, geometry editing, and the ~800 `;`-list housenumbers (a
MapRoulette challenge, not a batch).

## Related

- `03-capability-gating.md` — the absent-key-absent-capability convention the
  two config keys that shipped alongside this follow (`[export] node_tags`,
  `[export] source_license`).
- TODO §10 — "units that are civic numbers in disguise" is the same `645A`
  distinction, seen from the import side rather than the cleanup side.
