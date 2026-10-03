-- The source's own postal code, for a city that declares [source_fields]
-- postcode. Written at ingest only after config.check_postcode accepts it
-- (well-formed, and in one of the city's [postcode] prefixes), normalized to
-- "N1H 4E2". A rejected value is NULL here and an audit POSTCODE_REJECTED row.
--
-- build_tags writes it as addr:postcode, ahead of the same-address POI
-- fallback (conflation.proposed_postcode), which still fills the gap where
-- this is NULL.
--
-- NULL for every candidate of a city that declares no postcode, and for every
-- candidate ingested before this migration: re-ingest a run to fill it.
ALTER TABLE candidates ADD COLUMN postcode TEXT;
INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (21, datetime('now'));
