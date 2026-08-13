# Per-city config contract

Status: **proposed, not implemented.** Captured 2026-08-10.

## Motivation

Toronto-specific values are scattered across `config.toml`, module constants,
and hardcoded filenames. A second city cannot be added without editing code.

The house pattern already exists: `address-layerist` consumes one `layer.toml`
per city whose data-source block is **byte-compatible with
`ontario-address-changes/datasets/<slug>.toml`**, so a config can be lifted
from that registry. Follow it.

## Current Toronto coupling, by tier

Measured 2026-08-10. Tiers are ordered by effort, not importance.

**Tier 1 — mechanical. IMPLEMENTED 2026-08-13** (see DONE.md for what shipped
and why the two judgement calls went the way they did).
- ~~`cfg.osm_toronto_bbox`~~ → `cfg.osm_city_bbox`, from `[osm] city_bbox`.
- ~~The literal filename `toronto-addresses.json`~~ → `cfg.osm_extract_json`,
  derived from `[city] slug`.
- ~~`STATIC_TAGS = {"source": "City of Toronto Open Data"}`~~ →
  `[export] attribution`, enforced on the upload path.
- ~~`[upload] changeset_comment_template`~~ → takes `{city}` from `[city] name`.
- `[osm] pbf_url` — already config, and notably **unchanged for Guelph**: the
  Geofabrik Ontario extract covers every city in the portfolio. Only the clip
  changes.

Confirmed while implementing: `[city]` and `[export]` are the two blocks the
sketch below did not have. `slug` and `name` are required with no default —
identity must not fall back to Toronto.

**Tier 2 — the source projection.** See `03`. This is the real work.

**Tier 3 — street conventions.** See `01`.

**Tier 4 — geography. IMPLEMENTED 2026-08-13.** The URL is now
`[city] neighbourhoods_url`, and leaving it empty splits `[osm] city_bbox`
directly. The prediction that the quadtree was already generic held — better
than stated: the existing "Unassigned" orphan branch *was* the fallback, since
an empty polygon union leaves the whole city rectangle. See DONE.md. Boundary
clipping (`10`) is still open and is a separate concern: a rectangle is not a
boundary.

## Sketch of the config

Not settled. The shape below is a discussion object, not a spec.

```toml
# Data-source block: byte-compatible with ontario-address-changes/datasets/<slug>.toml
slug = "guelph"
provider = "City of Guelph"
license_name = "Open Government Licence - City of Guelph"

[source]
db = "../ontario-address-changes/data/guelph/guelph.db"

# Which optional source fields exist. Absent key = absent capability (see 03).
[source_fields]
municipality = "PLACE"
postcode     = "POSTCODE"
unit         = "UNIT_NO"
status       = "STATUS"
# Toronto-only, absent here: lo_num, hi_num, lo_num_suf, hi_num_suf, address_class

[geo]
bbox     = [43.4748, -80.32545, 43.58629, -80.15481]
boundary = "data/guelph/boundary.geojson"   # see 10

[streets]
profile          = "ontario-en"
expand_suffixes  = false   # Guelph's FULLNAME is already OSM long form
overrides        = "cities/guelph/street-overrides.toml"

[export]
attribution = "City of Guelph Open Data"
extra_tags  = { "addr:province" = "Ontario" }   # match the prior import — see 05

[prior_import]   # see 05
```

## Street overrides live in git

Agreed in discussion. `STREET_NAME_OVERRIDES` (`t2/conflate.py:125-144`) is a
curated, slow-moving, high-blast-radius artifact — one entry fixes tens to
hundreds of addresses at once. It is discovered during onboarding or during an
import (the `nearby_street_mismatch` check exists to surface candidates), and
it belongs in a git-tracked per-city file, reviewed like code.

This is deliberately **not** the adjudication store (`06`). The dividing line:
stable and structural → git; per-point and changing over time → store.

Cross-reference `memory/street_override_alt_name.md`: canonicalization stays a
curated table, and a naive global map derived from OSM `alt_name` is unsafe
because of citywide name collisions. Moving overrides to config does not
reopen that — it is the same curated table, in a better location.

## The cross-repo `keep_fields` contract

This is the coupling most likely to be forgotten.

`ontario-address-changes/datasets/toronto.toml` has a `keep_fields` block whose
comment says, in effect, *these fields are kept only because
toronto-2-address-import needs them* — `ADDRESS_CLASS_DESC` for the Land
Entrance skip and Land-canonical dedup, `LO_NUM`/`HI_NUM(_SUF)` for the range
safety gate. They are excluded from change detection but still written to
`props`.

So every capability this repo relies on requires a matching `keep_fields`
entry in the *other* repo, per city. Today that contract exists only as a
prose comment in one city's TOML. It needs to be written down explicitly:
"a t2-ready dataset TOML must keep X, Y, Z if the city has them."

Guelph's `keep_fields` is `["PIN", "GPID", "ROLL_NO"]` — parcel and tax-roll
join keys, kept for reasons unrelated to this repo. Nothing there serves
conflation, which is consistent with Guelph having none of the Toronto fields.

### Correction 2026-08-13: canonical fields are not conflation-ready

The section above implies that once `keep_fields` is honoured, the tracker's
canonical fields suffice for a consumer. **The portfolio survey disproved this.**

`street` is not a dependable street. Of 42 datasets, **18 store the name
component only** — `MAIN` where conflation needs `MAIN STREET`. The field is
populated and looks fine; it is simply a different thing in different datasets.
Peel is the extreme case at 96%: a consumer trusting `street` there matches
nothing and reports a clean ~100% gap. The type is sitting in `STREETTYPE` on
98.8% of rows the whole time, which is precisely the point — the canonical field
being useless says nothing about the dataset being usable (`03`).

So a **street resolution step is mandatory per dataset, ahead of any
normalization**, and it belongs in this contract rather than in each consumer:

1. Prefer `street` **when it carries a type** — measured, not assumed.
2. Else derive from `full`, truncated at the first comma.
3. Else reassemble from `props` using the dataset's own field names
   (Hamilton's `FULL_STREET_NAME` is the worked example).
4. Else the dataset fails `has_street_type` and the consumer must refuse to
   run rather than proceed.

`scripts/portfolio_survey.py` (`_resolve`, `_split_full`, `_strip_muni`)
implements this over all 42 datasets and is the reference for what the contract
has to specify — including that the resolution recipe is **per dataset** and
therefore config, not code.

The `street_source` column in the survey results records which branch each
dataset lands on. That column is effectively the missing piece of this contract,
and it should be promoted into the per-city TOML:

```toml
[source_fields]
street_from = "props:FULL_STREET_NAME"   # or "street" | "full" | ...
```
