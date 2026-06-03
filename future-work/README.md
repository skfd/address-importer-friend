# Future work

Design proposals that are **not implemented** and not scheduled. Each file
captures enough context (assumptions, guardrails, data-model sketch, phasing)
that a future implementer can pick it up without re-deriving the reasoning.

Before implementing anything here, re-read the proposal and verify the
assumptions still hold against the current code — these documents are frozen
at the date they were written.

## Index

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
- [source-tag-rewrite.md](source-tag-rewrite.md) — bulk-rewrite the
  per-node `source=City of Toronto Open Data` tag this import wrote on
  ~449,052 nodes to `addr:source=City of Toronto Open Data`. First mutation
  pass over the import's own output; shares the `<modify>` plumbing
  sketched in [postcode-enrichment.md](postcode-enrichment.md).
