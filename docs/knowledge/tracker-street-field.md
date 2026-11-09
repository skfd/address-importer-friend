# The tracker's `street` column is not conflation-ready

Measured 2026-08-10 during the Tier 1 portfolio survey. The tracker's canonical
`[fields]` mapping (`number`/`street`/`unit`/`full`) exists to detect *changes*
between snapshots, so `street` only has to be stable — it never had to be a
complete street name. It frequently isn't.

Share of rows whose `street` ends in a suffix the Toronto normalizer knows:
Toronto 99%, Guelph 100%, but Durham 0%, Renfrew 0%, Thunder Bay 0%,
Brampton 1%, Windsor 1%, Peel 9%. Roughly **18 of 42 store the name component
only** ("Armitage", "Schmon"), with type and direction left in the props blob
under per-city key names (`ROAD_TYPE`+`TYPE_SHORT`, `StreetType`, `STREETTYPE`,
`STTYPE`, `WC_SUFFIX`). The dataset TOMLs document this in comments.

**Recovery:** prefer the `full` column — it carries the complete street for
every name-only city checked. Exceptions that need real work:
- no `full` at all: `durham`, `niagara-falls`, `peel-region`, `hamilton`,
  `wellington` (hamilton's `street` is already 97% typed, so only the first
  three need props reassembly)
- `waterloo` has `number` at 0% — parse `full`
- `lennox-addington` has `street` at 0% — parse `full`
- `chatham-kent` appends the municipality to `full` ("3 ALLISON LINE BLENHEIM
  TOWN") — trim before use

**Why:** `future-work/multi-city/02-city-config-contract.md` assumes the cross-repo
`keep_fields` contract makes the canonical fields sufficient for consumers. It
doesn't. Any conflation consumer needs a per-dataset street-resolution step
ahead of normalization, and that belongs in `accordeur`'s dataset layer.

**How to apply:** never conflate straight off the tracker's `street` column.
Resolve a street name per dataset first (prefer `full`, else reassemble from
props), and treat the resolution recipe as per-city config like the street
override table. See [street-overrides.md](street-overrides.md).

**Implemented 2026-08-14** (engine commit 4e3b233): the recipe is the required
`[source_fields]` block in each city checkout's config.toml (`street_from`,
`full_from`, optional props capabilities); `t2/source_db.build_address_cols`
generates the projection. Check the *tracker TOML's* `[fields]` mapping before
assuming props reassembly is needed: Hamilton maps `street = FULL_STREET_NAME`,
so its canonical column is already typed and `street_from = "street"` — the
survey's `street_source: "props"` label described the survey's own recipe.
