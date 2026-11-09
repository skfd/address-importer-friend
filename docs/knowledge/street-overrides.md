# Street overrides

Street-name canonicalization (source spelling → OSM canonical) is a **curated
table declared per city**, applied at ingest: `[streets.overrides]` in the city
checkout's `config.toml`. `config.example.toml` documents the format, and the
README covers how `nearby_street_mismatch` surfaces candidates.

Until 2026-08-28 the table was `STREET_NAME_OVERRIDES` in `t2/conflate.py`, so
Guelph and Hamilton ingested through Toronto's table. That was harmless only
because none of the keys occur in their sources. `t2.conflate.apply_street_override`
is still the call site and now delegates to `accordeur.StreetProfile`. An entry
that `normalize_street` already covers is refused at config load.

**Add an entry to the city that needs it.** Never add it to another city's table,
and never put it back into the engine. Key = exact source `linear_name_full`
with a short suffix. Lookup ignores case and whitespace, and runs before
`expand_street_name`. A value may have no suffix (`Sunnyslope Ave → Sunny
Slope`) when the OSM canonical name has no street type.

## Why there is no automatic `alt_name → name` map

A naive global map is unsafe, because some alt_names are *also the canonical
`name` of a different road elsewhere in the same city*. Checked against the
2026-05-15 Ontario PBF: of Toronto's 6 override entries at the time, four
collide. `Golfcrest Road`, `Forest View Road`, `Greenhouse Road` and `Kathleen
Avenue` are each a real road's canonical `name` (the last three on several
roads), while also being an alt_name of the override target. A blind map would
rewrite every legitimate "Kathleen Avenue" address citywide, which is worse
than the bug it fixes.

If this is ever automated, the map MUST exclude any alt_name that also exists
as a canonical `name` anywhere in the city, and collisions fall back to the
manual table. Note that the pipeline's OSM extract (`t2/osm_refresh.py`
`_filter`) keeps only `addr:housenumber` features, so highway
`name`/`alt_name` is not in the pipeline data today.

In Toronto, a new override also means a row in `IMPORT_PROPOSAL_CHANGELOG.md`.

## Applying a new override to runs that already exist

A new entry only affects *future* ingests. There is no re-ingest path:

- `ingest_stage` refuses when the source snapshot has moved on since the run
  was created ("Create a new run").
- `candidates.ingest` uses `INSERT OR IGNORE`, so it never rewrites rows.
- `conflate.run` only processes `stage='INGESTED'`.

Surgical fix, per affected street:

1. Find non-uploaded runs (`upload_status IS NULL`) with candidates on the old
   `street_norm`.
2. Back up the city's `tool.db` with the sqlite online backup API (it handles
   WAL).
3. In one transaction, for those candidates: rewrite `street_raw` /
   `street_norm` to the override output
   (`expand_street_name(apply_street_override(...))` / `normalize_street(...)`),
   reset `stage='INGESTED'`, and delete their `review_items`,
   `check_results` and `conflation` rows.
4. Run `pipeline.conflate_stage(run_id)` then `pipeline.run_checks(run_id)` per
   run. Conflate touches only the reset candidates. Checks skip untouched
   candidates via the existing-result guard, so `APPROVED`/`SKIPPED` rows
   elsewhere are not disturbed.

Done once in Toronto for `Scenic Millway → Scenic Mill Way` on runs
2207/2222/2265 (2026-05-21): all 200 candidates went from REVIEW_PENDING/MISSING
to SKIPPED/MATCH. `nearby_street_mismatch` keeps surfacing new overrides, so
this recurs.
