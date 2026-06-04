-- Tile runs now carry the tile's actual polygon so ingest can clip source
-- addresses to the tile shape, not just its bounding box. Adjacent tiles have
-- overlapping bounding boxes but disjoint polygons; clipping by polygon stops
-- the same source point being ingested into two neighbouring runs (and thus
-- reviewed/uploaded twice). NULL = legacy/manual bbox-only run: ingest falls
-- back to pure-bbox behaviour. See candidates.ingest and pipeline.start_run.
-- Stored as the tile's Leaflet-style polygon_latlon ([[[lat, lon], ...]]).
ALTER TABLE runs ADD COLUMN polygon_json TEXT;
INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (16, datetime('now'));
