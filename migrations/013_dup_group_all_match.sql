-- Group-level guard for the intra_source_duplicate check: 1 when every Land
-- row sharing this (address_full, municipality_name) already MATCHed OSM, so
-- the in-source duplicate is pure noise (nothing importable). The check then
-- lets these rows auto-SKIP instead of entering the operator review queue.
-- A group with any non-MATCH sibling (notably a MISSING one — the actual
-- duplicate-upload risk) stays flagged. NULL/absent => treat as not-all-match
-- (flag as before): conservative for runs whose conflation predates this
-- column. Set by t2/conflate.py after every row's verdict is known.

ALTER TABLE conflation ADD COLUMN dup_group_all_match INTEGER;

INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (13, datetime('now'));
