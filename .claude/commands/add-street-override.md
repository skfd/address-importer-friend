---
description: Add a source-to-OSM street-name override and refresh affected non-uploaded runs
argument-hint: <Source Name> -> <OSM Name>
---

Add a new entry to `STREET_NAME_OVERRIDES` (the hardcoded source-name to
OSM-canonical-name table in `t2/conflate.py`), then apply it to any
already-ingested runs that still carry the old name.

## Input

Arguments: `$ARGUMENTS`

Parse them into two names split on `->` (or `→`):

- **SOURCE** — the name as the City source spells it (its `linear_name_full`),
  keeping the source's short suffix if it has one (Rd / Cres / Ave / Grv / …).
- **OSM** — the canonical name OSM uses, with the same source-style short
  suffix — or no suffix at all if OSM genuinely has none (e.g. `Sunny Slope`).

If an argument is missing or there is no `->` separator, ask the user for both
names before continuing.

## 1. Code changes

**`t2/conflate.py`** — add `"<SOURCE>": "<OSM>",` to the `STREET_NAME_OVERRIDES`
dict. Insert it as the last entry *before* the `# OSM's canonical name carries
no street-type suffix...` comment block — that Sunnyslope block must stay last
because its comment documents that one entry.

**`tests/test_street_override.py`** — in `test_known_overrides_use_osm_canonical_name`,
add `assert apply_street_override("<SOURCE>") == "<OSM>"` on the line before the
`Sunnyslope Ave` assertion.

**`IMPORT_PROPOSAL_CHANGELOG.md`** — add a row with today's date after the most
recent `STREET_NAME_OVERRIDES` row:
`` | <today> | `STREET_NAME_OVERRIDES`: added `<SOURCE> → <OSM>` — <shape>. | ``
`<shape>` is one short clause: proper-noun spacing split / suffix correction /
suffixless OSM name.

## 2. Verify the override

Run `python -m pytest tests/test_street_override.py -q`.
`test_override_table_entries_are_self_consistent` fails if the override does not
change the normalized form — that means the normalizer already covers this case
and the override is a no-op. If so, revert the three edits and tell the user.

## 3. Find affected non-uploaded runs

The override only runs at ingest, so runs already in `data/tool.db` still carry
the old name. Compute the old normalized name with
`t2.conflate.normalize_street(SOURCE)` and query:

```sql
SELECT r.run_id, r.name, COUNT(*) AS n
FROM candidates c JOIN runs r ON r.run_id = c.run_id
WHERE r.upload_status IS NULL AND c.street_norm = '<OLD_NORM>'
GROUP BY r.run_id;
```

Report the runs found. If there are none, you are done after steps 1-2.

## 4. Refresh affected runs (confirm before mutating the DB)

If runs were found, tell the user and ask whether to refresh them now. Only
proceed on an explicit yes — this mutates `data/tool.db`. The pipeline has no
re-ingest path (`ingest` is `INSERT OR IGNORE`; `conflate` only touches
`stage='INGESTED'`), so the refresh is surgical:

1. Back up `data/tool.db` via the sqlite online-backup API (`src.backup(dst)` —
   handles WAL).
2. In one transaction, for the affected candidates (the non-uploaded runs'
   candidates whose `street_norm` is the old form): rewrite `street_raw` and
   `street_norm` to the override output —
   `expand_street_name(apply_street_override(SOURCE))` and
   `normalize_street(...)` — set `stage='INGESTED'`, and delete their
   `review_items`, `check_results`, and `conflation` rows.
3. For each affected run, run `pipeline.conflate_stage(run_id)` then
   `pipeline.run_checks(run_id)`.
4. Verify: the affected candidates should leave `REVIEW_PENDING` (most become
   `SKIPPED`/`MATCH` once they match OSM's existing addresses — that MATCH count
   also confirms the OSM name is right); each run's `APPROVED` count must be
   unchanged.

Report the before/after stage breakdown and the backup path.

This command does not commit — run `/gh-push` afterward to commit and push.
