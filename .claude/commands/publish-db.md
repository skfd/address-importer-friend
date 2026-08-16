---
description: Publish a credential-scrubbed snapshot of a city's living tool.db as a dated GitHub release on that city's repo
argument-hint: <city-dir> [YYYYMMDD]
---

Publish a snapshot of the living `data/<slug>/tool.db` of a city checkout as a
dated release asset **on that city's repo**. This is the engine-level command:
it works for any city, selected by `$1` (a path like `../toronto-2-address-import`
or `../hamilton-address-import`). `$2` optionally overrides the date stamp.

## When to run it

- After finalizing a maintenance month (the watermark advanced).
- After a city's **first production upload** — that snapshot is the first
  durable record of what the import pushed. Do not wait for the import to be
  "finished": there is no final version. Each city's `tool.db` is a *living* DB
  that keeps growing through monthly maintenance, so the strategy is a dated
  snapshot per milestone, not one terminal release.

## Usage

```
/publish-db ../toronto-2-address-import            # date = watermark feed date
/publish-db ../hamilton-address-import 20260816    # explicit date stamp
```

## What it does

1. Confirm no web app is holding **that city's** DB. `run.py` locks only the
   city it was started with (`--city-dir`), so check the command line of any
   running `run.py` before stopping anything — another city's app is harmless.
   `VACUUM` needs a clean read lock on the target DB.
2. Build the artifact from this (engine) checkout:
   `T2_CITY_DIR=<city-dir> python -m scripts.publish_db [--date <YYYYMMDD>]`.
   It compacts the DB into `<city-dir>/data/release/tool-db-<date>.db`,
   **deletes the OAuth / PKCE rows from `kv`** (keeping the maintenance
   watermark), self-verifies that no credential rows remain, and xz-compresses
   it to `.db.xz`. The default date stamp is the City-feed publication date of
   the maintenance watermark snapshot — "the latest maintenance we did",
   independent of when you publish.
3. **Independently verify the scrub before upload** (the credential leak is the
   one unforgivable failure here):
   ```
   python -c "import lzma,shutil;shutil.copyfileobj(lzma.open(r'<artifact>'),open(r'<tmp>.db','wb'))"
   sqlite3 -readonly <tmp>.db "SELECT key FROM kv;"
   ```
   The output must contain `maintenance.watermark_snapshot` and **no**
   `osm_oauth*` or `pkce:*` keys. Delete the temp copy afterward.
4. Upload with the `gh release create` line the script prints — it already
   carries `--repo <owner/repo>` resolved from the city checkout's `origin`, so
   the release lands on the city repo, never on the engine. Tags are
   `tool-db-<date>`, unambiguous because they are per-repo.
5. **Record the publish** — this is what un-gates the maintenance watermark:
   `T2_CITY_DIR=<city-dir> python -m scripts.publish_db --record-published <YYYYMMDD>`.
   It verifies with `gh release view` that the release really exists before
   stamping the living DB (`snapshot.published_*` in `kv`), so the record can
   never mean "I built a file". Skipping this step leaves `/maintenance`
   refusing to advance the watermark.
6. Report the release URL.

## Notes

* Most onboarded cities are **local-only** (no GitHub remote — `gh repo create`
  is permission-blocked for the agent). The script still builds and verifies the
  artifact and tells you there is nowhere to publish it; ask the user to create
  the repo, then upload.
* Artifacts (~124 MB for Toronto) live under `<city-dir>/data/release/`
  (gitignored). Pruning old dated releases/assets is the operator's call — they
  are not auto-deleted.
* A published snapshot is a **read-only reference**: it has no stored OSM auth,
  so re-pointing the running tool at it is not supported.

## Rules

* Never upload an artifact you have not verified is credential-free (step 3).
* Don't use emojis in scripts or output.
* If the build script aborts (e.g. it found credential rows after scrub),
  surface the error verbatim — never force-upload past it.
