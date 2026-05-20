# t2-address-import

[GitHub](https://github.com/skfd/toronto-2-address-import) · [Pilot evidence site](https://skfd.github.io/toronto-2-address-import/) · [OSM community discussion](https://community.openstreetmap.org/t/address-import-for-toronto/119368) · MIT licensed

Local tool that reads Toronto address points from the sibling
[`toronto-addresses-import`](https://github.com/skfd/toronto-addresses-import) project's SQLite DB,
conflates them against live OSM data, routes questionable items to a human
reviewer via a web UI, and uploads approved candidates to the OpenStreetMap
**dev sandbox** (`master.apis.dev.openstreetmap.org`). Every auto and manual
action is written to an append-only audit log.

## Status

Live status of the [import proposal](IMPORT_PROPOSAL.mediawiki) against the [OSM Import Guidelines](https://wiki.openstreetmap.org/wiki/Import/Guidelines) workflow:

| Stage | State |
|---|---|
| Draft proposal | Complete (last revised 2026-05-13) |
| Wiki page (`Toronto/Import/AddressPoints`) | [Published 2026-05-01](https://wiki.openstreetmap.org/wiki/Toronto/Import/AddressPoints) |
| OSM Community Forum announcement | Posted 2026-05-01 — [thread](https://community.openstreetmap.org/t/address-import-for-toronto/119368) (tagged `import`; the [Import Guidelines](https://wiki.openstreetmap.org/wiki/Import/Guidelines) route announcements through the forum now, not the deprecated `imports@` list) |
| 14-day feedback window | Closes 2026-05-15 (measured from wiki publication; discussion resolved) |
| Phase 1 pilot upload (production) | Completed 2026-05-13 — [changeset 182585291](https://www.openstreetmap.org/changeset/182585291) (tile `high-park-swansea-sw-se`, 176 uploaded, 72 skipped, 4 rejected). [Upload manifest](https://skfd.github.io/toronto-2-address-import/pilot/uploads/all.csv). One-week hold before Phase 2. |

All uploads from this tool to date have used the OSM dev sandbox (`master.apis.dev.openstreetmap.org`). No production edits have been made and none will be made until the proposal has cleared the customary feedback window. The OSM account used for production uploads will be [`skfd imports`](https://www.openstreetmap.org/user/skfd%20imports) (dedicated, not the maintainer's personal account).

## Terminology

**Candidate** and **AddressMatch** are synonyms — both refer to one row from
the input CSV paired with its OSM lookup result, the unit flowing through the
pipeline. Code, DB schema, and templates use `candidate`; discussion and new
docs may use either term. Each one carries three orthogonal axes:

- **`verdict`** — what conflation decided (`MATCH`, `MATCH_FAR`, `MISSING`, `SKIPPED`)
- **`status`** — what the operator decided (`OPEN`, `APPROVED`, `REJECTED`, `DEFERRED`); `AUTO_APPROVED` is a synthetic status the review queue derives for clean MISSING rows that bypass manual review
- **`stage`** — where it sits in the pipeline (`INGESTED`, `CONFLATED`, `CHECKED`, `REVIEW_PENDING`, `APPROVED`, `REJECTED`, `UPLOADED`, `FAILED`, `SKIPPED`)

A **Run** is one execution of the pipeline (produces many candidates) and is
also the unit of upload — one run becomes one OSM changeset.

## Setup

1. **Python 3.11+** (uses `tomllib`).
2. From the project root:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate    # PowerShell / cmd
   pip install -e .
   ```
3. **Register an OAuth2 application** on the OSM dev server:
   - Log into <https://master.apis.dev.openstreetmap.org/>.
   - My Settings → OAuth 2 applications → **Register new application**.
   - Name: anything (e.g. `t2-address-import-dev`).
   - Redirect URI: `http://127.0.0.1:5000/oauth/callback` (OSM rejects `localhost` as non-HTTPS).
   - Permissions: tick **read user preferences**, **modify the map**,
     **comment on changesets**.
   - Save; copy the resulting Client ID and Client Secret.
4. **Create `.env.dev`** (copy `.env.dev.example`) and fill in:
   ```
   OSM_CLIENT_ID=...
   OSM_CLIENT_SECRET=...
   FLASK_SECRET_KEY=<any random string>
   FERNET_KEY=<generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
   ```
   For prod, also create `.env.prod` from `.env.prod.example` with a separate
   set of OSM creds (registered on real OSM, not the dev sandbox) and its own
   freshly generated `FERNET_KEY`.
5. Adjust `config.toml` if your sibling DB lives somewhere else or you want a
   different default bbox.

## Run

```bash
python run.py
```

Then visit <http://localhost:5000/>.

## Targeting dev vs prod OSM

The tool defaults to the OSM **dev sandbox**
(`master.apis.dev.openstreetmap.org`). The header shows a `DEV` / `PROD`
badge so you always know which server uploads will go to.

Selection is via the `--env` flag on `run.py` (default `dev`):

- **DEV (default):** loads `.env.dev` → `master.apis.dev.openstreetmap.org`
- **PROD:** loads `.env.prod` → `api.openstreetmap.org`

Each server has its own OAuth2 application registry, so a prod run also needs
a prod-side `OSM_CLIENT_ID` / `OSM_CLIENT_SECRET` — register a second app on
<https://www.openstreetmap.org/oauth2/applications> with the same redirect URI.

To launch against prod:

```bash
python run.py --prod        # or: python run.py --env prod
```

That's the only switch — `run.py --prod` is what flips the tool to production.
The standalone CLIs (`scripts/run_one_tile.py`, `python -m t2.run_for_all`,
`osm_refresh`, `tiles_build`, the static-export scripts) never touch the OSM
API for uploads, so they always run against dev and take no `--env` flag.

All config — `OSM_API_BASE`, `OSM_CLIENT_ID`/`OSM_CLIENT_SECRET`,
`OSM_REDIRECT_URI`, `FLASK_SECRET_KEY`, `FERNET_KEY` — is read **only** from
the selected `.env.{dev,prod}` file; the tool reads no environment variables
for these. To point at a different server (a local OSM instance, a staging
host), edit the relevant `.env` file (or create a third one).

Only one OAuth token set is stored at a time (`data/tool.db`), so switching
env requires re-authorizing on the new server. Each env file gets its own
`FERNET_KEY` — they don't need to match.

The Geofabrik extract (Stage 2 read source) is the same in both modes — there
is no dev-server slice from Geofabrik, and the dev sandbox has no realistic
Toronto data anyway. Only the upload target changes.

## Local OSM extract (default source)

Stage 2 reads addresses from a locally-cached Toronto extract instead of
querying Overpass every time. First-time setup:

```bash
python -m t2.osm_refresh
```

This downloads the latest Ontario PBF from Geofabrik (~600 MB) into
`data/osm/ontario-latest.osm.pbf`, filters it to `addr:housenumber`-tagged
features clipped to the City-of-Toronto bbox in `config.toml`, and writes
`data/osm/toronto-addresses.json` + a `meta.json` sidecar. Stage 2 then just
bbox-clips that JSON per run — no network, sub-second.

Re-run whenever you want a fresher snapshot. The tool HEAD-checks Geofabrik
and skips the download if `Last-Modified` hasn't changed; pass `--force` to
re-download regardless. `--dry-run` does only the HEAD check.

You can also trigger a refresh from the web UI at <http://localhost:5000/osm>.
The page shows the extract's freshness, element counts, sha256s, and tails
`data/osm/refresh.log` so you can watch progress. The button spawns the same
CLI as a detached subprocess, so Flask stays responsive while the download
runs.

To fall back to live Overpass queries (e.g. bbox experiments outside
Toronto), set `[osm] source = "overpass"` in `config.toml`.

## Tile layer (run area picker)

Toronto is too big to pick by typing lat/lon, so the tool precomputes a tile
layer you can click on. Generate it once with:

```bash
python -m t2.tiles_build
```

This downloads the City of Toronto's 158-neighbourhood polygon layer from
[Open Data](https://open.toronto.ca/dataset/neighbourhoods/), counts active
source addresses inside each polygon, quadtree-splits any neighbourhood with
more than 500 addresses, then merges any tile under 250 addresses into a
border-sharing neighbour (soft ceiling 500, hard ceiling 750) so the operator
never reviews a near-empty tile. The result (~1,300 tiles, 250–750 addresses
each) lands in `data/tiles.json` + a `data/tiles/meta.json` sidecar.
Regenerate when a new source snapshot lands.

The dashboard's **Pick on map** button opens `/map` — click any tile to land
on its detail page, which lists prior runs on that tile and has a "Start new
run" form pre-filled with the tile's bbox. The manual bbox form on the
dashboard remains as an escape hatch for arbitrary rectangles.

## First end-to-end run

1. **Create a run** from the dashboard. Either **Pick on map** and click a
   tile, or type a small downtown rectangle like
   `(43.645, -79.42, 43.665, -79.39)` into the bbox form.
2. On the run page, click the four pipeline buttons in order:
   **Ingest → Fetch OSM → Conflate → Run checks**.
3. Open the **Review queue** — items flagged by any enabled check land here.
   Approve, reject, or defer each. MISSING candidates with no flags are
   auto-approved; MATCH candidates are auto-skipped.
4. Back on the run page, scroll to the **Upload** card and pick one:
   - `Upload to OSM` opens a changeset on the dev server, uploads the
     osmChange diff, and closes the changeset. Visit `/oauth/start` first
     if you haven't authorized yet.
   - `Download .osm (JOSM)` writes a `.osm` file with the run's APPROVED
     candidates; open it in JOSM and upload via JOSM's own auth, then click
     `Mark uploaded (JOSM)` back on the run page.
5. The **Audit log** at `/runs/<id>/audit` shows every event.

## Resumability

Every candidate has a `stage` column. Killing the process mid-run and
restarting is safe — each stage skips work already done:

- Re-running **Ingest** only adds new rows (`INSERT OR IGNORE`).
- Re-running **Fetch** reuses the cached `data/osm_current_run<id>.json`.
- Re-running **Conflate** resumes from any candidate still at `INGESTED`.
- Re-running **Checks** skips any `(candidate, check_id, check_version)` that
  already has a result row. Bump a check's `version` in code to force rerun.
- **Uploads** look up prior changesets by their `import:client_token` tag
  before opening a new one.

## How conflation decides

Match targets are **pure address nodes** (`addr:housenumber` + no POI tags) and
**polygons** (ways/relations with an address — typically buildings, including
amenity-tagged footprints like a hospital).

**POI nodes** (nodes carrying `amenity`, `shop`, `office`, `tourism`, `leisure`,
`craft`, `healthcare`, `building`, including any lifecycle-qualified form such
as `disused:amenity` or `amenity:disused` — see `POI_TAG_KEYS` /
`LIFECYCLE_QUALIFIERS` in `t2/conflate.py`) are **ignored** for matching: their address
is a courtesy annotation, not the canonical address feature. When a POI sits at
a MISSING candidate's address, the review UI acknowledges it with a pill, and
any `addr:postcode` on the POI is copied into the proposed upload tags.

Even after that filter, a matched "pure address" node can quietly carry
non-address tags (`name`, `ref`, `entrance`). The `potential_amenity` check
flags those with `severity=info` so we can refine the POI filter over time.
Metadata keys like `source`, `opendata:type`, `check_date`, `note` are on an
ignore list inside the check and don't trigger it.

Street-name normalization (`STREET` → `ST`, `AVENUE` → `AVE`, etc. — see
`STREET_SUFFIXES` in `t2/conflate.py`) covers suffix and direction variants
but cannot bridge spelling differences inside the proper-noun part of the
name, including space-vs-no-space splits like source `Deane Field Crescent`
vs OSM signage `Deanefield Crescent`. Conflation calls those MISSING; the
`nearby_street_mismatch` check then flags any MISSING candidate whose OSM
neighbour within ~20 m shares the housenumber under a different street
name, so a reviewer can decide whether to accept the variant or fix the
source. Default radius is in `config.toml` under
`[check_params.nearby_street_mismatch]`.

Once a variant is confirmed, it goes into `STREET_NAME_OVERRIDES` in
`t2/conflate.py` — a hardcoded source-name → OSM-name table applied at
ingest. From then on the candidate carries the OSM name in `street_raw`
(and the upload tag), so it MATCHes the existing OSM addresses instead of
duplicating them under a parallel spelling. Current entries cover proper-
noun spacing (`Deane Field Cres → Deanefield Cres`, `Golfcrest Rd →
Golf Crest Rd`, `Forest View Rd → Forestview Rd`, `Greenhouse Rd → Green
House Rd`, `Posthorn Grv → Post Horn Grv`) and one outright suffix
correction (`Kathleen Ave → Kathleen Cres` — the source has the street
type wrong; the addresses sit on what OSM and signage call Kathleen
Crescent).

## Out of scope (possible next phase)

The current pipeline is one-directional: Toronto source → OSM lookup → upload
additions. Two cleanup flows in the opposite direction are **explicitly out of
scope** and left for a later phase. Documented here so reviewers don't assume
they were overlooked.

### Removing OSM addresses absent from Toronto source

If OSM has an address that Toronto's active snapshot doesn't, we do not flag,
propose, or remove it.

Reasoning — the absence direction is asymmetric. Toronto's open data is
authoritative when it asserts an address exists; silence is a weaker signal.
The feed has refresh lag, known-missing neighborhoods, and retired-address
states that aren't cleanly separable from "never existed." Deleting OSM data
based on absence alone would destroy real addresses on worse evidence than we
accept for additions.

A future phase would need, at minimum: a reverse-sweep stage enumerating OSM
addresses in the run bbox; a separate review queue (not `Candidate` — the
verdicts don't fit); a street-level cross-check to suppress the common case
where Toronto's feed is missing a whole street; prioritization by OSM metadata
(`start_date`, last-edit age, `source`); and human-only approval — no
automation, since OSM deletions are high blast radius and hard to reverse.

### Removing `addr:interpolation` ways

OSM `addr:interpolation` ways synthesize housenumbers along a street segment
between two endpoint nodes. When Toronto's per-address points cover the same
segment with real data, the interpolation way is technically redundant. We
still don't touch them.

Reasoning — an interpolation way isn't an address, it's a geometry-anchored
range declaration. Our matching model (housenumber + street + point) doesn't
describe what's being replaced. Replacement needs cross-validation: every
integer in the interpolation range must have a real Toronto point before
removal, otherwise the delete leaves mapped gaps. It's also a bulk structural
edit to OSM, not an address-import operation — different review bar, different
changeset hygiene, different rollback story than what this tool was built for.

A future phase would need: enumeration of `addr:interpolation` ways in the
bbox; coverage check that every integer in the range has a colocated Toronto
point; a proposed delete-way-plus-preserve-endpoints changeset for human
review; and care around tags (`addr:street`, `addr:postcode`) that the
interpolation way carries on behalf of its endpoints.

### Why defer both

The shipping scope — "get Toronto's missing civic addresses into OSM without
creating duplicates" — has standalone value. Folding cleanup into the same
pipeline expands blast radius and review burden without proportional benefit,
and the two reverse flows have different enough semantics (different data
sources, different review criteria, different failure modes) that they
deserve their own pipelines when we get to them.

## Writing a new check

1. Create `t2/checks/<name>.py` exporting a class that matches the `Check`
   protocol in `t2/checks/base.py`.
2. Register it in `t2/checks/__init__.py`.
3. Restart the app. The new check appears in the run's toggle list.

## Drift back-scan

`scripts/drift_backscan.py` re-evaluates the `match_number_drift` check
against runs that were already conflated — useful for finding OSM positional
drift in runs processed before the check existed. It is read-only: it never
writes to `tool.db` and never creates review items.

```bash
python -m scripts.drift_backscan                       # uploaded runs only
python -m scripts.drift_backscan --status all          # every run
python -m scripts.drift_backscan --min-flags 3         # widen the summary
python -m scripts.drift_backscan --out C:/tmp/d.csv    # custom CSV path
```

It writes one CSV row per flagged candidate (`data/drift_backscan.csv` by
default) — matched OSM element, the closer different-numbered OSM element,
and both distances — and prints a console summary of "systemic" runs (those
at or above `--min-flags`) and their drifted streets. The check's `slack_m`
is read from `config.toml`, so the scan matches a fresh pipeline run.

## Data sources & attribution

This tool moves data between three open datasets. Downstream uploads inherit OSM's licence, but the upstream sources each have their own terms:

- **Toronto Open Data** — "Address Points (Municipal) – Toronto One Address Repository", published under the [Open Government Licence – Toronto](https://open.toronto.ca/open-data-licence/). Consumed indirectly via the sibling [`toronto-addresses-import`](https://github.com/skfd/toronto-addresses-import) project.
- **OpenStreetMap** — © OpenStreetMap contributors, [ODbL 1.0](https://www.openstreetmap.org/copyright). All uploads target the OSM **dev sandbox** (`master.apis.dev.openstreetmap.org`); any future production import must separately comply with the OSMF [import guidelines](https://wiki.openstreetmap.org/wiki/Import/Guidelines) and [contributor terms](https://osmfoundation.org/wiki/Licence/Contributor_Terms).
- **Geofabrik** — Ontario `.osm.pbf` extracts, redistributed under ODbL from OSM.

## License

MIT — see [LICENSE](LICENSE).
