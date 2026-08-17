# Hosted review instance (Oakville / TronnaLegacy)

**Status:** designed 2026-08-16, **not implemented**, no schedule.
**Decision owner:** user. **Audience of one:** `TronnaLegacy`.

Frozen at the date above — re-verify every code reference below against the
current tree before implementing. Line numbers especially.

## Why

`TronnaLegacy` has been adding Oakville addresses by hand from the Town of
Oakville open-data layer via MapRoulette (challenge 55881, changesets dated
2026-08-08/09, found incidentally during the Hamilton bbox sweep —
`multi-city/08-survey-results-2026-08-12.md:562`). He is a friend of the
user. Rather than hand him a static worklist or JOSM files, the decision is
to give him **the real review UI, hosted**, where he signs in with his own
OSM account, switches between the dev sandbox and production himself, and
runs the whole pipeline — ingest, conflate, review, upload — without the
user in the loop.

Oakville is the family's only *brownfield-active* city where the incumbent
mapper is a known, willing collaborator. That is what makes this worth
building: it is not a hosting exercise, it is handing a city to its local.

## Decisions taken (2026-08-16)

| question | decision |
|---|---|
| Delivery shape | Fully hosted service, not tailnet, not static export |
| Host | Rented VPS at **Hetzner** |
| Login | **OSM OAuth2** — the same flow the tool already uses for uploads |
| Authorization | **Flat allowlist of OSM usernames.** No roles, no per-route split — he does all the work |
| Upload identity | His own OSM account. The tool never uploads Oakville under the user's account |
| Dev/prod switch | Two processes, one per env (see §3). Not a config refactor |

Explicitly **not** in scope: multi-tenancy, N cities on one box, per-user
queue claiming, a job scheduler, any change to conflation logic.

## 1. What already exists (do not rebuild)

Verified against the tree on 2026-08-16.

- **OAuth2 + PKCE against OSM is complete and working** —
  `t2/osm_client.py:98-137`. `SCOPES = "read_prefs write_api"`
  (`osm_client.py:23`), so the token can both identify the user and modify
  the map. The PKCE verifier is already keyed per-flow in `kv` under
  `pkce:<state>`; that part needs no change.
- **Tokens already live outside `tool.db`**, Fernet-encrypted, at
  `data_root/osm_auth.json` (`osm_client.py:45`) — deliberately at
  *data_root*, not data_dir, because the OSM account spans cities. A
  published DB snapshot can therefore never carry credentials. Preserve
  this property.
- **The audit log is already multi-actor.** `events.actor` is
  `TEXT NOT NULL` (`migrations/001_init.sql:128`), and
  `review.resolve(run_id, candidate_id, new_status, actor="operator", ...)`
  (`t2/review.py:48`) already takes the actor as a parameter — it is simply
  always left at its default. No migration is needed for per-user
  attribution.
- **Concurrency is handled.** `db.connect()` sets `journal_mode=WAL` and
  `busy_timeout=120000` (`t2/db.py:14-19`) for parallel `run_for_all`
  workers. Two processes and two humans are far below what that was built
  for.
- **The DEV/PROD badge already exists** in the UI header, driven by config.
  Under the two-process design it keeps working with no change and becomes
  the primary "which server am I about to write to" signal.

## 2. What must change

### 2.1 Authentication gate — the core of the work

**Today there is none.** `session[` appears **zero** times in
`t2/web/app.py`; there is no session, no user object, and no authorization
check on any of the **53 routes** (18 of them `POST`, including
`/runs/delete_all`, `/runs/<id>/upload`, `/map/run_all`, and
`/maintenance/advance`). The app is safe only because it binds to
`127.0.0.1`.

Build:

1. **`GET /login`** → reuse `osm_client.build_auth_url()`. The existing
   `/oauth/*` routes stay as they are for the *upload* authorization; login
   piggybacks on the same flow and the same token.
2. **New `osm_client.user_details(token)`** → `GET /api/0.6/user/details`,
   returns `(uid, display_name)`. `read_prefs` is already in `SCOPES`, so no
   re-consent is needed. This function does not exist yet; it is the only
   new OSM API call in the whole plan.
3. **Session** — `flask.session` signed with `cfg.flask_secret_key`
   (already wired at `app.py:109`). Store `osm_uid` and `display_name` only.
   Set `SESSION_COOKIE_SECURE=True`, `HTTPONLY=True`, `SAMESITE="Lax"`.
   `FLASK_SECRET_KEY` must be a real random value per env — `_oauth_status()`
   (`app.py:1837`) already flags the literal `"dev-secret"`, so extend that
   check to refuse boot on a placeholder when not on localhost.
4. **`@app.before_request` gate** — deny by default. Allow unauthenticated
   access to exactly: `/login`, `/oauth/start`, `/oauth/callback`, `/static/*`,
   and a `/healthz` (new, for the reverse proxy). Everything else requires a
   session whose `display_name` is in the allowlist. A blanket gate is
   correct here precisely *because* there are no roles — there is no route
   that an allowlisted user may not touch.
5. **Allowlist** — `T2_ALLOWED_OSM_USERS=skfd,TronnaLegacy` in
   `.env.{dev,prod}`, parsed into `Config`. **Not `config.toml`:** city
   checkouts are public GitHub repos, and while OSM usernames are public
   information, an access-control list should not be edited by anyone with a
   PR. Compare case-insensitively; OSM display names are case-preserving but
   collisions are not possible.
6. **Log the login.** `audit.log(actor=display_name, event_type="LOGIN")`
   on successful sign-in, and `SESSION_DENIED` on an allowlist rejection —
   the latter is the tripwire that tells you the box is being probed.

### 2.2 Per-user, per-env token storage — non-optional

`_AUTH_PATH = _CONFIG.data_root / "osm_auth.json"` (`osm_client.py:45`)
holds **exactly one token set for the entire installation**, and
`load_tokens()` takes no arguments. Two consequences, both fatal to this
design if unfixed:

- Two users on one box share one OSM identity — uploads would be attributed
  to whoever authorized last.
- Dev and prod share one `data_root`, so the two processes of §3 would
  **overwrite each other's tokens**. The README's "switching env requires
  re-authorizing" is a symptom of this, tolerable for one local operator and
  not tolerable hosted.

Change the blob's shape to be keyed by `(osm_uid, env)`:

```jsonc
// data_root/osm_auth.json — Fernet-encrypted values, as today
{
  "tokens": { "<osm_uid>:<dev|prod>": "<fernet blob>" },
  "stored_at": { "<osm_uid>:<dev|prod>": "<iso8601>" }
}
```

Touches `store_tokens`, `load_tokens`, `_refresh_tokens`,
`token_blob_present`, `token_stored_at`, `_request`, and every caller of
`osm_client.upload()`. Keep the existing last-writer-wins `os.replace()`
atomicity — with per-user keys, concurrent writes to *different* keys still
need the whole file rewritten under a lock, so add a small file lock or
accept the (now real) lost-update risk on simultaneous re-auth. Two users:
low stakes, but write it down in the code.

Also: a one-shot migration for the existing single-token blob, or simply
require everyone to re-authorize once on first boot of the hosted instance.
**Prefer re-authorize** — it is one click and avoids migration code for a
credential.

### 2.3 The upload path must follow the session, not the process

`osm_client.upload(run_id)` (`osm_client.py:232`) resolves its token
globally. Once tokens are keyed by user, it needs the acting user's uid
threaded in from the request. Verify while implementing whether
`POST /runs/<id>/upload` (`app.py:1464`) calls it synchronously in-process —
if it does, plumbing is trivial; if it was moved to a subprocess, the uid
must be passed on the command line and the token re-read there.

Background jobs (`run_for_all`, `osm_refresh`) never upload, so they need no
token at all. Keep it that way — it means no OSM credential is ever handed
to a detached process.

### 2.4 Actor attribution

Thread the session's `display_name` into `review.resolve(actor=...)` and the
handful of `actor="operator"` literals in `app.py` and `pipeline.py`. After
this, `events.actor` distinguishes `TronnaLegacy` from `skfd` from
`pipeline` for every decision — which is the entire audit story for a shared
instance, and it costs one parameter per call site.

## 3. Deployment topology

### Two processes, one city dir

Environment is **baked in at import time**: `config.load()` reads the
module-global `OSM_ENV` (`t2/config.py:340-344`), and at least eight modules
capture `_CONFIG = _config.load()` at import — `db`, `osm_client`,
`osm_export`, `osm_fetch`, `candidates`, `multi_fixes`, plus
`candidates._SOURCE_FIELDS`. `run.py:35-44` documents the ordering hazard in
comments. A live in-process dev↔prod toggle therefore means deleting every
module-level `_CONFIG` in favour of request-scoped config — invasive surgery
across the whole package, for a toggle.

Instead:

```
                    ┌─ oakville.example.org      → nginx → :8002  PROD process
   Internet ─ TLS ──┤
                    └─ oakville-dev.example.org  → nginx → :8001  DEV process
```

- Both processes run the same code against the **same city dir and the same
  `tool.db`** — WAL makes that safe, and it is *desirable*: one DB remains
  the single source of truth for what Oakville has pushed, exactly as the
  README's snapshot policy requires.
- The switch in the UI is a link in the header next to the existing
  DEV/PROD badge. Honest, obvious, and impossible to get wrong by accident —
  the hostname itself tells you which server you are about to write to.
- Two OSM OAuth applications, one per server, because each OSM server has
  its own registry:
  - dev app on `master.apis.dev.openstreetmap.org`, redirect
    `https://oakville-dev.example.org/oauth/callback`
  - prod app on `openstreetmap.org`, redirect
    `https://oakville.example.org/oauth/callback`
- Separate `FLASK_SECRET_KEY` and `FERNET_KEY` per env file (already the
  documented convention — they need not match).

### Serving

- **`run.py` is a dev runner and must not be used.** It binds `127.0.0.1`
  and sets `debug=True` (`run.py:48`) — the Werkzeug debugger is a remote
  code execution console, and it would sit one directory away from the
  encrypted-but-present OSM token file. Add a `wsgi.py` entry point, or a
  `--host/--port/--no-debug` triple with `debug` defaulting to *off* and
  refusing to enable when the host is not loopback.
- **waitress** (pure Python, no fork semantics to worry about, trivially
  portable back to the user's Windows box) or **gunicorn** with a small
  worker count. Either is fine; waitress keeps dev/prod parity with the
  user's machine.
- nginx terminates TLS (Let's Encrypt / certbot), proxies to both ports,
  sets `X-Forwarded-Proto`; the app needs `ProxyFix` so `url_for` builds
  `https://` redirect URIs — **this bites the OAuth callback specifically**,
  which must match the registered URI byte-for-byte.
- systemd units, one per env, `Restart=on-failure`.

### Box sizing

The web UI is trivial; the *jobs* are not. `POST /map/run_all`
(`app.py:469-511`) and `POST /osm/refresh` (`app.py:1781-1812`) spawn
detached `subprocess.Popen` multiprocessing jobs that run for tens of
minutes to hours and saturate every core.

- Oakville is ~65k–71k source rows (~49k missing per the survey) — roughly a
  sixth of Toronto. Toronto's `data/toronto` is 2.3 GB; budget **~500 MB**
  for Oakville's, plus **~1 GB** for the Geofabrik extract, plus room for
  `data/archive`-style growth.
- Target: **4 vCPU / 8 GB / 80 GB**. At Hetzner that is the CX32 class, or
  the ARM CAX21 for less — Python and the whole dependency set are
  arch-clean, so ARM is worth pricing. Roughly €7–15/month; **verify current
  pricing and generation at build time**, this doc will rot.
- **Location: Ashburn or Hillsboro (US), not Falkenstein.** Both humans are
  in Ontario; a European box makes an already-chatty UI feel slow.

## 4. Data that must be on the box

Easy to overlook until ingest fails on day one:

- **The tracker DB.** `config.toml`'s `sqlite_path` is an absolute local
  path into the sibling `ontario-address-changes` checkout
  (`config.example.toml:21`). The Oakville tracker DB — or the whole tracker
  — has to live on the server, **and it needs a refresh path**: today that
  is a Windows-scheduled `daily-update.ps1` on the user's machine. Options:
  a cron'd pull of the tracker repo's data, or rsync from the user's box, or
  run the daily update on the server. Decide before phase 3.
- **The Geofabrik extract** — fetched by `t2.osm_refresh`, which the UI can
  trigger. Just needs disk and bandwidth.
- **Backups of `tool.db`.** This is the single source of truth for what
  Oakville has pushed to OSM; losing it means losing the ability to know
  what was already uploaded. Nightly `sqlite3 .backup` to object storage
  (Hetzner Storage Box), plus a dated release via `/publish-db` at the usual
  milestones — the release is provenance, not a backup, and does not
  substitute.

## 5. Security checklist

Every item is a hard gate before the box faces the internet:

- [ ] `debug=False` everywhere; no Werkzeug debugger reachable
- [ ] Real random `FLASK_SECRET_KEY` and `FERNET_KEY` per env; boot refuses on placeholders
- [ ] `before_request` deny-by-default gate covers all 53 routes
- [ ] Session cookies `Secure` + `HttpOnly` + `SameSite=Lax`
- [ ] TLS only; HTTP redirects to HTTPS; HSTS
- [ ] SSH keys only, no password auth; firewall to 22/80/443; unattended-upgrades
- [ ] `data/` not served by nginx under any path — `osm_auth.json` lives there
- [ ] Allowlist rejections written to the audit log and actually reviewed
- [ ] Restore from a `tool.db` backup rehearsed **once**, before first prod upload

## 6. Phasing

1. **Scaffold Oakville.** Thin checkout on the Hamilton/Guelph pattern,
   `04` probes, tiles, baseline conflation. Invisible, gated on nothing,
   prerequisite for every other phase. The field mapping already exists in
   `ontario-address-changes/datasets/oakville.toml`
   (`STREET_NUM` / `SNAME` / `UNIT` / `ADDRESS`, synthesized identity).
2. **Auth locally.** §2.1 + §2.2 + §2.4 on the user's machine, still bound
   to loopback, both users' accounts against the **dev** server only. This
   is the whole software change; everything after it is ops.
3. **Deploy to Hetzner, dev only.** §3, §4, §5. `TronnaLegacy` signs in,
   reviews, and uploads to the sandbox until both parties trust it.
4. **Import governance** (§7) — must clear before phase 5.
5. **Enable prod.** Second process, second OAuth app, first real changeset.

Phases 1–3 are safe to do at any time and commit to nothing visible.

## 7. Prerequisites that are not code

Both are blocking for phase 5 and neither is a technical task.

- **Licence.** Oakville is `yellow-ogl` — a verified clean clone of
  OGL-Canada 2.0, sitting in the drafted-but-**unsent** LWG variant email
  along with five other clones (`multi-city/license-contacts-todo.md`,
  `ontario-address-changes/LICENSING.md:60`). Scaffolding and a dev-only
  instance are invisible and stay ungated. A production upload is the
  visible step the gate is about — regardless of whose account it goes out
  under.
- **Import governance.** `TronnaLegacy`'s manual MapRoulette work is
  ordinary mapping. Running *this* pipeline against prod makes him the
  operator of an **import**, which under the OSM import guidelines means a
  documented import plan, notice to `imports@`, and conventionally a
  dedicated import account. Toronto's is
  `toronto-2-address-import/IMPORT_PROPOSAL.mediawiki` and is the template.
  He should agree to that consciously — it is a real obligation being
  transferred along with the login, and it is better discovered now than
  after a large changeset draws attention.

## 8. Deliberately rejected

- **Roles / per-route permissions.** The premise is that he does all the
  work. A flat allowlist is the honest encoding of that; roles would be
  ceremony around a two-person trust relationship.
- **A pasted "import profile key".** OSM has no user-facing API key — the
  API is OAuth 2.0 only and vanilla `openstreetmap-website` has no personal
  access token. OSM sign-in is the real primitive: nothing to leak, nothing
  to rotate by hand, revocable by him from his own settings page, and it
  yields the username for the audit log in the same round trip.
- **Request-scoped config refactor** to get an in-process env toggle — see
  §3. Two processes cost an nginx server block; the refactor costs the
  package.
- **Multi-tenancy.** One city, two users, one box. If a third city ever
  wants this, revisit — do not generalize speculatively now.
