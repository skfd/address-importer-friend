-- Persist the source address class (Land / Structure / Structure Entrance / Land Entrance)
-- on each candidate so conflation can dedup colocated non-Land rows against their Land sibling
-- and the review UI can surface the source class on each item. See SOURCE_DATA.md.

ALTER TABLE candidates ADD COLUMN address_class TEXT;
CREATE INDEX IF NOT EXISTS idx_candidates_class ON candidates(run_id, address_class);

UPDATE candidates
   SET address_class = json_extract(extra_json, '$.ADDRESS_CLASS_DESC')
 WHERE address_class IS NULL AND extra_json IS NOT NULL;

INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (6, datetime('now'));
