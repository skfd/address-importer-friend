# Future work

Design proposals that are **not implemented** and not scheduled. Each file
captures enough context (assumptions, guardrails, data-model sketch, phasing)
that a future implementer can pick it up without re-deriving the reasoning.

Before implementing anything here, re-read the proposal and verify the
assumptions still hold against the current code — these documents are frozen
at the date they were written.

## Index

- [multi-city/](multi-city/) — **design discussion, opened 2026-08-10.** Making
  the address-import family work for cities other than Toronto: core library
  extraction, per-city config contract, capability gating, city onboarding,
  prior-import detection, the collective adjudication layer, and a 42-dataset
  portfolio survey. Spans five sibling repos, not just this one. Start at
  [multi-city/README.md](multi-city/README.md).
- [postcode-enrichment.md](postcode-enrichment.md) — fill `addr:postcode` on
  matched OSM nodes that lack one, sourced from same-address POI nodes.
  First mutation flow in an otherwise create-only pipeline.
- [maplibre.md](maplibre.md) — swap the review UI's Leaflet maps for
  MapLibre GL JS (vector tiles, richer styling).
- [no-anchor-osm-buildings.md](no-anchor-osm-buildings.md) — post-import
  MapRoulette challenge for the ~1,580 OSM buildings with
  `addr:housenumber` but no `addr:street`. These can't be matched by
  conflation and are an acknowledged duplicate-creation path
  (`IMPORT_PROPOSAL.mediawiki` § Conflation).
- [source-tag-rewrite.md](source-tag-rewrite.md) — **abandoned (2026-06-03).**
  Idea was to bulk-rewrite `source=City of Toronto Open Data` →
  `addr:source` on imported objects. A pilot showed that tag is a shared
  community convention (used by other mappers/imports for 15+ years), so it
  can't be claimed as ours beyond our own manifest node ids. Kept as a record.
