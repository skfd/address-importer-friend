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

**Tier 1 — mechanical.**
- `cfg.osm_toronto_bbox` (`t2/config.py:28,84,103`) → a city-neutral name.
- The literal filename `toronto-addresses.json` in `t2/osm_refresh.py:44`,
  `t2/streets.py:42`, `t2/reverse_sweep.py:332`, and `t2/web/app.py:1660,1667,1674,1943`.
- `STATIC_TAGS = {"source": "City of Toronto Open Data"}` (`t2/osm_export.py:12-14`).
- `[upload] changeset_comment_template` in `config.toml` — already templated,
  but the literal string says Toronto.
- `[osm] pbf_url` — already config, and notably **unchanged for Guelph**: the
  Geofabrik Ontario extract covers every city in the portfolio. Only the clip
  changes.

**Tier 2 — the source projection.** See `03`. This is the real work.

**Tier 3 — street conventions.** See `01`.

**Tier 4 — geography.** `t2/tiles_build.py:40` hardcodes the City of Toronto
158-neighbourhood GeoJSON URL. The quadtree ≤500-addresses-per-tile logic
underneath is already generic and needs no change; it needs a fallback for
cities with no neighbourhood layer. See also `10` for boundary clipping.

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
