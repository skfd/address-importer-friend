-- Per-street review state for the /drift dashboard. The match_number_drift
-- check flags individual MATCH candidates, but drift is a street-level
-- phenomenon fixed in OSM one street at a time, so review status is tracked
-- per normalized street name rather than per candidate.
--   open      - not yet looked at
--   fixed     - OSM nodes corrected for this street
--   dismissed - inspected, not actually drift (e.g. arterial false positive)

CREATE TABLE IF NOT EXISTS drift_street_status (
    street_norm TEXT PRIMARY KEY,
    status      TEXT NOT NULL DEFAULT 'open',
    note        TEXT,
    updated_at  TEXT
);

INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (15, datetime('now'));
