# Unit-shape overrides — making `/units/shapes` editable

**Designed 2026-09-15. Not implemented.** The read-only page is landed
(`f967749e`); this is the wiring that lets an operator disagree with it.

Read [`t2/unit_shapes.py`](../t2/unit_shapes.py) and the `[units]` block of
`guelph-address-import/config.toml` (the decision log — the UI design is at
line 253, the classifier history above it) before starting. The design
questions below were settled on 2026-09-15; what is left is execution and the
traps in §6.

## 1. What exists today

`/units/shapes` lists all 409 of Guelph's multi-unit civic groups with the
shape each takes under `[units] policy = "per-door-or-collapse"`: **239 nodes,
111 collapse, 3 civic-only, 56 review**. It reads the source tracker directly,
owns no run state, needs no pipeline run, and is gated on `source_db.PER_DOOR`
in both route and nav. `_outcome()` mirrors `candidates._emit_group` step for
step.

It is **read-only**. The operator can see that `252 Stone Road West` is a mall
whose 140 "units" are storefronts, and can do nothing about it.

## 2. Why the page has the grain it has

Do not re-litigate this; it is the reason the feature is shaped this way.

An override **changes how many candidates exist** — one node becomes fifty-two.
That is unlike every other operator decision in the engine:
`multi_address_verdicts` transforms *tags on export*, so it can be applied
late. A shape override has to reach `_emit_group` **before ingest**, because
after ingest the candidate rows are already the wrong shape.

That forces the page to be city-wide and run-independent:

- `classify` must see a group as the *source* has it. A tower cut by a tile
  boundary shows one floor's worth of units on each side and reads as
  sequential doors in both.
- Door groups **scatter across runs** — each door lands in the tile that
  contains it — while a collapsed group is emitted once, at the elected
  representative's tile. No per-run view can hold a group whole.

## 3. Data model

Mirror `multi_address_verdicts` (`migrations/010`, `011`), which is the
engine's existing "operator overrules a classifier, decision persists across
runs" pattern. Next migration number is **019**.

```sql
CREATE TABLE IF NOT EXISTS unit_shape_verdicts (
    civic_key   TEXT NOT NULL,   -- normalized number|street|municipality
    verdict     TEXT NOT NULL CHECK (verdict IN ('nodes','collapse','civic-only','skip')),
    unit_hash   TEXT NOT NULL,   -- see below
    note        TEXT,
    updated_at  TEXT NOT NULL,
    frozen_at   TEXT,            -- set when the group's shape reached OSM
    PRIMARY KEY (civic_key)
);
```

**`unit_hash` is over the sorted unit designators only — never coordinates.**
Geocoding jitter between snapshots would otherwise invalidate every verdict on
every refresh. Its job is narrow: a building that gains a floor must
*re-surface* rather than silently inherit a decision made about a different
building. Follow `011`'s precedent of clearing derived state when the verdict
changes.

## 4. The four verdicts, concretely

`_emit_group` consults the verdict before `units.classify`. The branch table is
not obvious, so here it is in full:

| verdict | `_emit_group` behaviour |
|---|---|
| `nodes` | force the NODES branch — yield every row in the group, regardless of what `classify` says |
| `collapse` | force elect + `flats_tag`. **If the listing is still over 255 characters the override cannot make it fit** — fall through to `civic-only` and say so on the page, rather than writing a truncated tag |
| `civic-only` | elect, `flats=None`, and no reason downgrade — the operator chose this, it is not a failure |
| `skip` | yield nothing. The group produces **zero** candidates |

`skip` needs checking downstream: confirm nothing treats "active source row
with no candidate" as an error or a coverage gap — `reverse_sweep`,
`city_duplicate`, and the `missing_sample` spot-check are the three to look at.

**Record the override in `candidates.unit_shape`, not the classifier's
verdict**, or the per-run badge and the `unit_shape_ambiguous` check will both
lie. But keep the classifier's opinion — put it in `unit_shape_reason`
(`"override: rule said nodes"`) or the audit trail is gone.

## 5. Freeze — there are two conditions, not one

Once a group's shape is in OSM, **both flips are mutations**: `nodes→collapse`
means deleting fifty-two nodes and creating one. This import only creates. So a
frozen verdict is not editable, and later disagreement routes to a QA finding.

1. **We uploaded it.** Upload state lives on the run
   (`runs.upload_status = 'uploaded'`, migration `012`), and candidates belong
   to runs — so the check is "does any candidate for this civic key sit in an
   uploaded run". See the join trap in §6.
2. **Somebody else already uploaded it.** `ARandomThumbtack` put ~5,500
   hyphenated unit nodes in OSM in 2025. The 89 groups where OSM carries *only*
   the `714-30` form are per-door structure already mapped; overriding one to
   `collapse` would put a civic node beside thirty existing unit nodes. This is
   why the "what OSM has" column is **not cosmetic** — it is the second freeze
   condition.

The OSM column needs the OSM extract, which is absent from `data/` locally, so
phase C cannot be built or tested without fetching it first.

**Sequencing caveat:** that column lies until mechanical edit #2 runs. The
batches are prepared in `guelph-address-import/mechanical-edits/unit-split/`
(36 JOSM batches over 5,521 objects) but had not been run as of 2026-09-15.
Before the split, a door candidate `(714, unit 30)` fails the housenumber
compare against OSM's `714-30` and reads as MISSING. The engine has a test
named for this: `test_a_door_does_not_recognise_its_own_double_encoded_self`.

## 6. The join trap — read this before writing the freeze query

`candidates.housenumber` **is** `civic_key[0]`:

```python
housenumber = row.get("address_number") or ""      # candidates.py, _candidate_values
```

`candidates.street_raw` **is not** `civic_key[1]`:

```python
street_raw = expand_street_name(apply_street_override(_street_from_row(row)))
```

The civic key uses raw `linear_name_full`; the candidate stores an expanded,
override-applied form. **They will not join.** Either store the civic key on
the candidate when emitting under `PER_DOOR` (cleanest — one column, set where
the group is already in hand) or apply the identical transform on both sides of
every query. Do not assume `street_raw` round-trips.

## 7. Phasing — each phase ships on its own

**A. Record verdicts.** Migration 019, a POST route, option chips per row on
the existing page. Verdicts persist; nothing reads them yet. *Useful alone* —
it lets an operator work through the 56 REVIEW groups today and have the
answers waiting.

**B. Honour them.** `_emit_group` consults verdicts, `unit_shape` records the
override, freeze condition 1. This is where the cardinality change lands, so
it needs the `skip` audit from §4 and a test per branch.

**C. Context.** Per-run badge and back-link, sibling view, OSM column
(freeze condition 2).

On C, the per-run half is cheaper than it looks: `candidates.unit_shape`
already exists per row (migration `018`), so the badge in `_review_list.html`
is a pill reading that column. The back-link needs the group key in the URL
(`/units/shapes?focus=<civic_key>`). The **sibling view** — showing a door
candidate the other doors of its building in `_review_detail.html` — is the one
thing a per-run page can do that the city-wide page cannot, and the reviewer
currently has no way to tell that a node is 1 of 12 doors at one address.

## 8. Out of scope

**The maintenance path.** `candidates.ingest_rows` still raises under
`PER_DOOR` and should keep raising — a new unit at a collapsed tower needs
`addr:flats` *modified* on an existing node, which is a mutation path this
import does not have. Tracked in `config.toml` line 165. Do not try to close it
here; the overrides land on the tile path only.

The appealing follow-on, once overrides exist, is to route source deltas at
unit groups into this page as QA findings — which unblocks the easy case (a new
unit at a *door* group is just one more node) without building mutation at all.
That is a separate proposal.

## 9. Verification

`_outcome()` and `_emit_group` must agree; if they drift the page describes an
upload that will not happen. `tests/test_unit_shapes.py` pins the four
outcomes. Re-run the city-wide diff after any classifier or emission change:

```bash
cd address-importer-friend
T2_CITY_DIR=../guelph-address-import python -c "
from t2 import unit_shapes; d = unit_shapes.collect()
print(d['counts'], d['nodes_created'], d['door_nodes'])"
```

Snapshot 46 baseline: `{'nodes': 239, 'collapse': 111, 'civic-only': 3,
'review': 56}`, 6,412 nodes created, 6,242 of them doors. A change to those
numbers that you did not intend is the signal.
