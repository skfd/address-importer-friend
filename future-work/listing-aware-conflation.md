# Listing-aware conflation — a building that lists its units is the building

**Proposed 2026-09-15; built 2026-09-16 (`38ea7459`).** Landed as designed, with
two additions the build surfaced: `conflate.run` had never selected `unit` or
`flats`, so every door compared as the bare civic point (fixed, with a test
through `run()` itself), and a civic point inside a matched polygon's bounds
now reads MATCH rather than MATCH_FAR. Simulated on the fresh extract: the 125
collapsed candidates go 115 MATCH / 10 MATCH_FAR; the 642 doors of the 51 door
groups go 597 MATCH_LISTED / 45 MISSING. Kept as the design record. Found by the OSM column on
`/units/shapes` ([unit-shape-overrides.md](unit-shape-overrides.md)) the
evening it was built. Blocks any upload under `[units] policy =
"per-door-or-collapse"`, so it is the next engine change for Guelph, ahead of
running the mechanical edits.

## 1. The problem in one sentence

Guelph's multi-unit buildings are already in OSM as one building way carrying
every unit under `addr:unit` — `addr:unit=101-116;201-215;301-314;…` — and
`conflate._same_address` demands unit *equality*, so nothing we emit for those
buildings ever matches them and conflation proposes a second address object
beside each one.

## 2. What the extract says

Measured 2026-09-15 against a fresh Ontario extract, over the 409 unit-bearing
civic groups:

| OSM state at the civic address | groups |
|---|---|
| one or more objects **listing** units (`addr:flats`, or a multi-valued `addr:unit`) and no door objects | **176** |
| door objects (`714` + `addr:unit=30`, or the double-encoded `714-30`) | 162 |
| a bare civic object only | 25 |
| nothing | 46 |

The 176 listing groups, by what the rule would upload for them:

| rule says | groups | OSM listing vs source unit set |
|---|---|---|
| collapse | 98 | 89 identical, 9 at ≥90% (23 Woodlawn Road East: OSM lists 104, source has 103) |
| review (emitted collapsed) | 27 | 27 identical |
| nodes | 51 | 51 identical (190 Fife Road: 72 units, both sides) |

167 of 176 listings match the City's unit set **exactly**. Somebody mapped
these from the same data. 146 groups carry the listing on a single object;
30 spread it over several — terrace rows mapped as a few building ways each
listing its own doors (120 Country Club Drive: 37 objects).

## 3. What conflation does with them today

`build_osm_index` sets `el["_norm_unit"]` to the raw `addr:unit`, so a listing
way has `_norm_unit = "101-116;201-215;…"`. Then:

- **125 collapsed candidates** (98 collapse + 27 review) carry `unit = None`.
  `_same_address` compares `""` to the listing: no match. Verdict **MISSING**.
  Upload creates a node with `addr:flats=101-116;…` inside a building way that
  already says `addr:unit=101-116;…`. 125 duplicate buildings.
- **51 door groups** emit one candidate per unit, `unit = "30"`. Compared to
  the listing: no match. Every door is **MISSING**. Upload creates, for 190
  Fife Road, 72 door nodes inside one way that already lists all 72.

Neither is a bug in the rule. The rule read the source correctly; the
representation in OSM is simply a third one it was never told about. The
per-door design in `config.toml` argued `addr:unit` means identity and
`addr:flats` means containment; the mapper who did these 176 buildings used
`addr:unit` for containment, and that is the fact on the ground.

## 4. The change

All in `t2/conflate.py`, gated on `_UNIT_AWARE` like the rest of the unit
logic, so Toronto and Hamilton see nothing.

**`build_osm_index`:** recognise a listing. `addr:flats`, or an `addr:unit`
containing `;` or shaped `^[A-Z]*\d+-[A-Z]*\d+$` (the same `_UNIT_LISTING`
test `unit_shapes` uses — move it somewhere shared, `units` is the natural
home). For such an element set `_norm_unit = ""` — it is the building, not a
unit — and add `_listed_units`, the expanded set of designators, leading zeros
stripped, so `LL01` and `LL1` agree. Expansion is per-part: a numeric range
with equal prefixes expands, anything else is a single value. Guard the range
width; a typo like `1-1000` must not allocate.

**`_same_address(el, num, street, unit)`:**

```
housenumber and street must agree, as now
if not unit-aware:            match
if el has no _listed_units:   el._norm_unit == unit          (unchanged)
if unit == "":                match       -- the building is the building
else:                         unit in el._listed_units       -- containment
```

**A verdict that says what happened.** A door matched by containment is not a
MATCH in the sense the reviewer knows — there is no node for unit 30, there is
a line in a listing that says 30 exists. Add **`MATCH_LISTED`** alongside
MATCH / MATCH_FAR / MISSING: uploadable as nothing, reviewable as "OSM already
carries this unit on the building". It should count as matched everywhere
MATCH does (auto-approve, campaign stats, `dup_group_all_match`) and be
distinguishable in the queue filter, because the *whole group* being
MATCH_LISTED is the reviewer's cue that a door group was mapped as a building
— which is fine, and which they might one day want to explode by hand.

The collapsed candidate against a listing building is a plain **MATCH**; the
tag diff will show our `addr:flats` against their `addr:unit`, and that diff
is the retag question in §6, not a conflation one.

**Partial listings.** The 9 groups at ≥90% and the 30 multi-object groups
fall out naturally: a door is matched by whichever nearby building lists it,
and a door no building lists is MISSING — one new node for the one unit OSM
lacks, which is the correct answer. For the collapsed candidate against
several partial-listing buildings, `unit == ""` matches the nearest; the
proposed `addr:flats` will then be a superset of that building's list. Flag
it rather than solve it: a check that fires when the matched element's
`_listed_units` is a strict subset of the candidate's flats.

## 5. Tests to pin

- A collapsed candidate MATCHes a way whose `addr:unit` is a listing.
- A door candidate `30` is MATCH_LISTED against a way listing `1-40`, and
  MISSING against one listing `1-20`.
- Leading zeros: `LL01` in the source matches `LL1-LL4` in OSM.
- A single-valued `addr:unit=30` is still a unit, not a listing, and
  `test_a_door_does_not_recognise_its_own_double_encoded_self` still passes:
  the hyphenated housenumber is a different problem with a different edit.
- Off the policy, nothing changes: the listing way behaves as it always did.

Then re-run the Guelph tiles' conflation and expect the 176 groups to leave
MISSING; the count of MISSING candidates city-wide should drop by roughly
125 + the door count of the 51 groups.

## 6. What this does and does not decide

**The retag is decided (2026-09-16): standardise.** `addr:unit` is identity —
this address *is* unit 30 — and the wiki allows several values on it only for
one address spanning adjacent units. `addr:flats` is containment — "the range
of unit numbers within a larger building or complex", on the building way or
its entrance, in exactly our `3-7;10;14-18` format. Guelph has both meanings
on one key today (5,863 single-valued `addr:unit`, 453 list-valued, 1
`addr:flats`), which is the whole reason conflation had to guess from the
shape of the value. So the 453 listing objects move to `addr:flats`, key only,
value verbatim, as **mechanical edit #3** — announcement drafted in
`guelph-address-import/mechanical-edits/unit-listing-retag/`, wiki section
written, consent still to be asked. Only the June Avenue pilot of edit #2 has
been uploaded, so nothing is built on the old form yet.

This changes nothing in §4. Conflation still learns both forms, because the
extract lags the edit, the retag waits on a 14-day window, and door objects
keep `addr:unit` regardless. After the retag the listing-shaped `addr:unit`
branch is a safety net rather than the path. It also means the tag diff on a
collapsed MATCH — our `addr:flats` against their `addr:unit` — can generate
the edit #3 batches, the way `multi_fixes` builds its exports.

**Whether a door group mapped as a building should be exploded.** With
MATCH_LISTED the 51 door groups are simply done. The source's opinion that
they are doors survives on `/units/shapes` (rule says nodes, OSM says
listing) for anyone who wants to take it up by hand.

**The freeze.** `/units/shapes` freezes a listing group today because its
shape is in OSM. That stays true after this change; the difference is that
the frozen groups stop producing duplicates.

*Superseded 2026-09-29:* a listing no longer freezes. Campaign 3 moved every
list-valued `addr:unit` to `addr:flats` with no shape check, so the listing
is often the thing under review (275 Hanlon Creek's bays), and mechanical
edit #6 reads the page's verdicts to decide which listings to strip. Because
MATCH_LISTED is skipped, a verdict on a listed group uploads nothing beside
the listing. Door objects in OSM still freeze.

## 7. Order of work

1. This change, with the tests in §5. Small: two functions and a verdict.
2. Re-conflate Guelph and check the MISSING drop against §2.
3. Mechanical edit #2 (the hyphen split) as already prepared — it is what
   makes the *other* 162 groups match.
4. Only then, any upload under the policy.
