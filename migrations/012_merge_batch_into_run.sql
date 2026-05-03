-- Collapse the batches/batch_items tables into runs+candidates.
-- An upload is now a state on the run: one client_token, one changeset_id,
-- one upload_status. Per-candidate OSM node-id mapping moves onto candidates.

ALTER TABLE runs ADD COLUMN upload_status     TEXT;
ALTER TABLE runs ADD COLUMN upload_mode       TEXT;
ALTER TABLE runs ADD COLUMN client_token      TEXT;
ALTER TABLE runs ADD COLUMN changeset_id      INTEGER;
ALTER TABLE runs ADD COLUMN uploaded_at       TEXT;
ALTER TABLE runs ADD COLUMN upload_error_msg  TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_client_token
    ON runs(client_token) WHERE client_token IS NOT NULL;

ALTER TABLE candidates ADD COLUMN local_node_id INTEGER;
ALTER TABLE candidates ADD COLUMN osm_node_id   INTEGER;

-- Fold any uploaded batch onto its run.
UPDATE runs SET
    upload_status    = 'uploaded',
    upload_mode      = (SELECT mode         FROM batches WHERE batches.run_id = runs.run_id AND status='uploaded'),
    client_token     = (SELECT client_token FROM batches WHERE batches.run_id = runs.run_id AND status='uploaded'),
    changeset_id     = (SELECT changeset_id FROM batches WHERE batches.run_id = runs.run_id AND status='uploaded'),
    uploaded_at      = (SELECT uploaded_at  FROM batches WHERE batches.run_id = runs.run_id AND status='uploaded'),
    upload_error_msg = (SELECT error_msg    FROM batches WHERE batches.run_id = runs.run_id AND status='uploaded')
WHERE EXISTS (SELECT 1 FROM batches WHERE batches.run_id = runs.run_id AND status='uploaded');

-- Copy per-candidate OSM mappings from batch_items.
UPDATE candidates SET
    local_node_id = (SELECT bi.local_node_id FROM batch_items bi
                     JOIN batches b ON b.batch_id = bi.batch_id
                     WHERE b.run_id = candidates.run_id AND bi.candidate_id = candidates.candidate_id),
    osm_node_id   = (SELECT bi.osm_node_id   FROM batch_items bi
                     JOIN batches b ON b.batch_id = bi.batch_id
                     WHERE b.run_id = candidates.run_id AND bi.candidate_id = candidates.candidate_id)
WHERE EXISTS (SELECT 1 FROM batch_items bi
              JOIN batches b ON b.batch_id = bi.batch_id
              WHERE b.run_id = candidates.run_id AND bi.candidate_id = candidates.candidate_id);

-- Operator data fix: run 676 was uploaded externally via JOSM. Fold its draft
-- batch's client_token onto the run, mark uploaded (no changeset_id since the
-- JOSM upload didn't round-trip one back to us), and flip all of its remaining
-- APPROVED+BATCHED candidates to UPLOADED.
UPDATE runs SET
    upload_status = 'uploaded',
    upload_mode   = 'josm_xml',
    client_token  = (SELECT client_token FROM batches WHERE run_id = 676 LIMIT 1),
    uploaded_at   = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE run_id = 676 AND upload_status IS NULL;

UPDATE candidates SET stage = 'UPLOADED', stage_updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE run_id = 676 AND stage IN ('APPROVED', 'BATCHED');

-- Drop BATCHED stage entirely: any remaining BATCHED candidates (from never-
-- uploaded draft batches on other runs) revert to APPROVED.
UPDATE candidates SET stage = 'APPROVED', stage_updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE stage = 'BATCHED';

DROP TABLE IF EXISTS batch_items;
DROP TABLE IF EXISTS batches;

ALTER TABLE events DROP COLUMN batch_id;

INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (12, datetime('now'));
