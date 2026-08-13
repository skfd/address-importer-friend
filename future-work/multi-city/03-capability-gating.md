# Capability gating

Status: **proposed, not implemented.** Captured 2026-08-10.

## The problem, stated precisely

Several features read fields that only Toronto's source has. If you point
`config.toml`'s `sqlite_path` at another city's DB today, those features do not
crash — they **fail silently open**, producing a clean-looking result that is
wrong.

This is the most dangerous single issue in multi-city support, because the
failure mode is invisible. A reviewer sees an empty check result and concludes
"nothing flagged" rather than "this check could not run."

## The Toronto-only fields and what depends on them

`t2/source_db.py:111-123` (`_ADDRESS_COLS`) hardcodes Toronto's `props` keys.
Dependents, verified 2026-08-10:

| Field | Dependent | Location |
|---|---|---|
| `ADDRESS_CLASS_DESC` | Land Entrance ingest skip | `t2/candidates.py:44,50` |
| `ADDRESS_CLASS_DESC` | Land-canonical dedup | `t2/conflate.py:406-451` |
| `LO_NUM` / `HI_NUM` | `suffix_range` check | `t2/checks/suffix_range.py:24-34` |
| `LO_NUM` / `HI_NUM` | range coverage + safety gate | `t2/ranges.py` (whole module) |
| `MUNICIPALITY_NAME` | cross-municipality dedup keying | `t2/conflate.py:388-451`, `t2/ranges.py:32-137`, `t2/review.py:235` |

Guelph has **none** of the first four. It has `PLACE` as a municipality
equivalent (`'Guelph'` on 53,771 rows, `'Guelph/Eramosa Twp'` on 75).

## What Guelph adds that Toronto lacks

Gating is not only about absence. Guelph carries fields Toronto has never had,
and the pipeline has nowhere to put them:

- **`POSTCODE` on 90.9% of rows** (48,956 of 53,846). Toronto has none — there
  is a whole `future-work/postcode-enrichment.md` about wanting this signal,
  which assumes the only source is a nearby POI node. For Guelph the source
  hands it over directly. (Tempering the win: OSM Guelph is already 88.5%
  postcoded, largely from the prior import.)
- **`UNIT_NO` on 24.4% of rows** (13,162). See `09`.
- **`STATUS`** — all `'Active'` today, so no filter is needed *yet*. The field
  existing at all is a latent gate: if the feed ever emits non-Active rows,
  ingesting them would be wrong and nothing would notice.

So the capability model needs both directions: features that turn **off** when
a field is missing, and features that turn **on** when a field is present.

## First concrete capability: `has_street_type`

Everything above was written from Toronto-vs-Guelph, where the gated features
were optional extras. The portfolio survey (`08`) supplied a capability that
gates the **core** operation, with a real dataset failing it.

`has_street_type` — does the source's street value carry a street type
(`Street`, `Road`, `Avenue`) at all, or only the name component?

**Peel fails it.** 96% of `peel-region` rows carry a bare name with no type. A
normalizer that assumes a type will produce `MAIN` where OSM has `MAIN STREET`,
match nothing, and report a ~100% gap as if it were a finding. The survey caught
this only because of its guard metric — Peel's "is the street in OSM anyway"
score was 1.0%, absurd on its face, which is what exposed the number as an
artifact rather than a result.

This is exactly the failure `03` exists to prevent, and it is now instanced
rather than hypothetical: **a consumer that does not check produces confident
garbage instead of refusing to run.**

Two properties make it a better exemplar than the Toronto-only fields:

1. It is not a simple field-presence check. The field is *present*; its
   **content** is insufficient. So the capability model cannot be purely "is
   this key declared" — it needs derived capabilities, measured from the data.
2. Failing it must **stop the run**, not disable a feature. There is no degraded
   mode for "conflate without street names". Compare the Toronto-only fields,
   where disabling a check and saying so is the correct response.

So the registry needs at least two severities: *disable and report*, and
*refuse to run*. Both must be visible for the same reason as §3 below.

Related: 18 of 42 datasets store the street name component only, which makes
street resolution a required per-dataset step rather than a quirk — see the
correction in `02`.

## Design sketch

Not settled. The direction discussed:

1. `_ADDRESS_COLS` becomes **generated** from the `[source_fields]` map in `02`,
   projecting SQL `NULL` for any field the city does not declare. Callers stay
   unchanged — the projection already exists precisely to keep the row contract
   stable across the `addresses.db` → `toronto.db` migration, so this extends a
   pattern rather than introducing one.
2. Each check declares its **required fields**. The registry disables checks
   whose requirements are unmet.
3. **Disabled-for-cause must be visible.** A check that cannot run must be
   distinguishable in the UI and in any published output from a check that ran
   and found nothing. This is the whole point; getting it wrong reproduces the
   silent-failure bug with extra steps.
4. Features keyed on a field that is *present but degenerate* — Guelph's
   `PLACE`, which is one value for 99.9% of rows — should be allowed to run.
   They collapse harmlessly. No special case needed, but worth confirming that
   the dedup keying does something sane with a constant key.

## Guardrail

Toronto's behaviour must not change. `tool.db` is living (~2 GiB, runs through
2597) and prior runs are compared against new ones. Every Toronto field is
declared, every check stays enabled, and the generated `_ADDRESS_COLS` must
produce the same SQL it does today.

## Verification idea

A fixture DB shaped like Guelph — no `LO_NUM`/`HI_NUM`, no `ADDRESS_CLASS_DESC`,
with `UNIT_NO` and `POSTCODE` — asserting that ingest completes, that the four
dependent features report *disabled*, and that none of them silently returns an
empty result. The real `guelph.db` is on disk and can back this, but a small
fixture keeps the test hermetic.
