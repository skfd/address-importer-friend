-- Cross-run upload guard (osm_export.skip_cross_run_duplicates) looks up every
-- row for a source candidate_id across runs to find one already UPLOADED. The
-- only existing candidates indexes are keyed by run_id first (PK is
-- (run_id, candidate_id)), so that lookup table-scanned the whole table on
-- every upload. Index by (candidate_id, stage) so the guard is an index seek.

CREATE INDEX IF NOT EXISTS idx_candidates_candidate_id
    ON candidates(candidate_id, stage);

INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (14, datetime('now'));
