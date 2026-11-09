# Address-import family — shared knowledge

Every city checkout's `CLAUDE.md` imports this file, and so does the engine's.
It holds what is true across the whole family. **A new family-wide fact goes
here (or in a `docs/knowledge/` page linked from here), not into one project's
memory**: per-project memory drifts, and this file is the one copy. Keep it
short: it loads into every session. Detail belongs in a linked page.

This repo is public, and so are the city checkouts. Nothing private goes here.

## Repos

- **`address-importer-friend`** is the engine (`t2/`, `tests/`, `scripts/`,
  `migrations/`, `run.py`, `.venv`). Engine code changes happen only here.
- **Thin city checkouts** (`<city>-address-import`, all siblings in `~/Code`)
  carry `config.toml`, the import proposal, `.env.*` and a gitignored `data/`
  holding the living `tool.db`. City state and proposal edits happen there.
- Run from the engine: `python run.py --city-dir ../<city>-address-import
  [--prod]`. The seam is `T2_CITY_DIR`: config, `.env.*` and `data/` resolve
  against the city dir, `migrations/` stays with the engine.
- Siblings: `accordeur` (the shared street normalizer, consumed by both
  engines), `address-beholder` (the observer engine + thin dataset repos),
  `ontario-address-changes` (feed tracker, one DB per dataset), `address-vault`
  (acquisition), `address-layerist` (tile layers).
- `oakville-address-import` is run by another mapper. Leave it alone.
- Before designing anything multi-city, read
  `future-work/multi-city/README.md`, then `DONE.md` / `TODO.md` there. A
  session that skipped that folder once rebuilt the beholder as a fork.
- New city: follow the recipe in `future-work/multi-city/onboarding-queue.md`.
  Lessons flow backwards, so re-check the done cities against what you learn.

## Rules that bite

- **`Candidate` ≡ `AddressMatch`.** They are synonyms. Don't rename code.
  Verdict, status and stage are three separate axes:
  [docs/knowledge/glossary.md](docs/knowledge/glossary.md).
- **Street overrides live in the city's `config.toml` `[streets.overrides]`.**
  Never put them in another city's table or back into the engine. Never build
  an automatic OSM `alt_name → name` map: alt_names collide with real roads.
  New overrides don't reach existing runs on their own:
  [docs/knowledge/street-overrides.md](docs/knowledge/street-overrides.md).
- **Never conflate off the tracker's `street` column.** About 18 of 42
  datasets store the name only. Each city's `[source_fields]` resolves it:
  [docs/knowledge/tracker-street-field.md](docs/knowledge/tracker-street-field.md).
- **Datasets barely overlap.** Dedup sources on the municipality attribute,
  never a polygon. The polygon is for the OSM side. Lower tier wins
  (`future-work/multi-city/10-boundary-clipping.md`).
- **Assume every city is brownfield** until a survey proves otherwise. Size the
  real gap before committing to one (Guelph was ~94% already in OSM).
- **Monthly maintenance** is in the README § Monthly maintenance. Two traps:
  snapshot ids are per database, so translate by feed *date* and never carry
  the integer; and a City re-issue (same address, new `point_id`) is an
  addition, not a retirement.
- **Licensing:** any licence finding, tier change or contact goes into
  `ontario-address-changes/LICENSING.md` in the same change.
- **"Publish data"** after an import means `/publish-db <city-dir>`: a
  credential-scrubbed `tool-db-<date>.db.xz` release on the city repo. Stop
  that city's `run.py` first, and check that `kv` holds no credentials.
- **Republishing a proposal to the OSM wiki** goes through Claude in Chrome:
  [docs/knowledge/wiki-publish-via-browser.md](docs/knowledge/wiki-publish-via-browser.md).
- **Verify a shared change against the real vocabulary**, not just tests: run
  old and new code over every distinct street string in the tracker DBs and
  OSM extracts, and report the diff count.
