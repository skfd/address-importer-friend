# Adjudication layer

Status: **least-settled design in this set.** Captured 2026-08-10. This is the
piece most likely to be the actual product, and the one with the most open
questions.

## The idea

A public, collectively-maintained record of address mismatches that are
**deliberate** — cases where the municipal source and OSM disagree and the
disagreement is known, understood, and should not be re-surfaced as a defect on
every subsequent run.

## You already do this, in the most primitive possible form

`STREET_NAME_OVERRIDES` (`t2/conflate.py:125-144`) is a table of 13 human
adjudications — "the City calls it Kathleen Ave, OSM calls it Kathleen
Crescent, OSM is right." It lives in a Python dict, is duplicated verbatim into
`toronto-import-beholder/beholder/streets.py`, and is curated by one person.

The beholder goes one step further with `notes.py` and its preset tags:
*"Doesn't exist / demolished"*, *"Merged into building"*, *"Wrong location /
bad data"* — with an `allowlist = ["skfd"]` and an append-on-change history.

Both are the feature described here, at n=1 curator. The design question is
what they become when public, multi-city, and collective.

## The git / store split (decided)

Agreed in discussion, and it resolves what would otherwise be the messiest part
of the design:

- **Git-tracked config** — stable, structural, high-blast-radius things
  discovered during onboarding or during an import: street-name mappings,
  per-city policy, capability declarations, prior-import tag mappings. Reviewed
  like code. See `02`.
- **Adjudication store** — shifting, per-point, changes-over-time things.
  Publicly observable, limited-audience writable.

The rule of thumb: *if it is a fact about the city, it goes in git; if it is a
judgment about one address at one moment, it goes in the store.*

## Scope levels

Adjudications are not all at the same granularity, and a store that only
handles point-level records misses the highest-leverage cases:

| Scope | Example | Blast radius | Home |
|---|---|---|---|
| Point | "51 Cork St W is demolished" | 1 | store |
| **Street** | "source 'Kathleen Ave' → OSM 'Kathleen Cres'" | 10s–100s | **git** |
| City policy | "don't import units here"; "clip to boundary" | 1000s | git |
| Check/rule | "suppress `suffix_range` — no LO/HI in this source" | a whole class | git |

Note the git/store split maps cleanly onto scope: everything above point level
is stable enough to be config. That is a satisfying result and worth
preserving — it means the store has exactly one record type to get right.

## Key stability — the hard technical problem

What does a point-level adjudication key on?

- **Source identity** (`ADDID`, `ADDRESS_POINT_ID`) — evaporates when the city
  reissues an ID. This is not hypothetical: `t2/source_db.py:174-215`
  (`iter_retired_since`) already carries explicit re-issue handling because
  Toronto retires a point and emits a new one for the same civic address.
- **OSM element ref** — evaporates when a mapper replaces a node with a
  building, which is the single most common *good* edit in a brownfield city.
- **Normalized civic address** — survives both, but cannot distinguish two
  points at one address. Guelph has 172 source rows at one exact coordinate.

**Proposed:** key on normalized civic address (+ unit where present), and store
the source ID and OSM element ref as **evidence, not identity**.

## Auto-reopen — the rule that keeps the store honest

Record the facts as they stood when the adjudication was made, and re-surface
the adjudication when those facts change. "Merged into building" should reopen
if the building disappears.

Without this the store rots into a graveyard of stale suppressions, which is
**worse than having no store at all** — because a suppression makes a real
problem invisible rather than visible. The beholder's append-on-change event
model is already the right shape for this and is the strongest reason to build
this on the beholder rather than on `t2`.

## Where truth should live — prefer OSM

A tiering, offered as a recommendation rather than a decision:

1. **If OSM has a convention, use OSM.** `not:addr:housenumber`,
   `noaddress=yes`, lifecycle prefixes like `demolished:building`. An
   adjudication expressed this way is durable, benefits every tool and mapper,
   and needs no hosting.
2. **OSM notes** for things needing a human local mapper. The beholder already
   creates notes, so the path exists.
3. **Our store** only for what OSM cannot or should not carry: tool-internal
   check suppressions, per-city policy, anything that is an opinion about our
   pipeline rather than a fact about the world.

The reason to be strict about this ordering is community perception. An import
tool maintaining a large private opinion-database *about* OSM data invites
suspicion; one that pushes conclusions back into OSM where conventions allow,
and keeps only tooling config privately, reads very differently. Worth
resolving before building, because it changes how much store there is to build.

## Backend options

- **Git as the store** — adjudications as JSON/YAML per city, contributed via
  PR. Free, fully auditable, moderation free via review, fits existing `gh`
  tooling. Poor casual-contributor UX.
- **Small shared API** (Cloudflare Workers + D1, Fly + Postgres) — fast writes,
  needs hosting, auth, moderation.
- **Hybrid (recommended).** Writes go to a small shared API; the API
  periodically materializes a signed JSON export **committed to git**. Static
  per-city sites read the export — fast, free, no runtime dependency on our
  uptime. Git history is the public audit log. The API stays small and
  replaceable.

## Write access — settled, and deliberately minimal

Decided in discussion 2026-08-10: **a per-dataset allowed-users file, edited by
hand.** No moderation UI, no self-service signup, no nomination flow.

This is a much smaller design than the moderation machinery originally sketched
here, and it is the right starting point. A hand-edited allowlist means the
abuse surface is closed by construction — you cannot get a bad suppression in
without someone adding you to a file first. The beholder's existing
`allowlist = ["skfd"]` is already this design; it just becomes per-dataset and
gains more names.

What still holds regardless:

- OSM OAuth for identity (the beholder already has it) — the allowlist keys on
  OSM usernames.
- Append-only history with attribution, and a revert path. This is the audit
  trail and the basis for auto-reopen; it is not moderation overhead.

Deferred until there is a reason: reputation gates, moderation queues, abuse
reporting. Revisit only if the allowlist stops scaling.

Still unresolved: licensing of contributed adjudications. If a record is derived
from OSM data, ODbL considerations apply; if the store is published, it needs
its own stated licence.

## Open questions for the next session

1. Is the point-level record the only store record type, given scope levels
   above point map to git? (Believed yes; worth confirming.)
2. How much pushes into OSM natively (tier 1 above) vs stays in the store?
3. What exactly is captured as "facts at time of adjudication" to drive
   auto-reopen, without storing so much that every OSM edit reopens everything?
4. One shared store across all cities (favoured — one auth, one moderation
   surface) vs per-city stores matching per-city sites?
