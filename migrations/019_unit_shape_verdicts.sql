-- Operator verdicts on the collapse-vs-nodes decision, recorded at
-- /units/shapes. One row per civic group the operator has overruled; groups
-- with no row take whatever units.classify says.
--
-- Mirrors multi_address_verdicts (010, 011): an operator overrules a
-- classifier and the decision persists across runs. It differs in when it
-- applies. A multi-address verdict transforms tags on export and can be
-- applied late; a shape verdict changes how many candidates exist -- one node
-- becomes fifty-two -- so candidates._emit_group consults it BEFORE ingest.
-- A verdict saved after a group was ingested does nothing to those rows.
--
-- civic_key is source_db.civic_key_text: number|street|municipality, the raw
-- source street and not the expanded one candidates.street_raw carries.
-- unit_hash is units.unit_hash over the group's sorted designators -- never
-- coordinates -- so a building that gains a floor re-surfaces for a fresh
-- decision instead of inheriting one made about a different building, while
-- geocoding jitter between snapshots changes nothing.
-- frozen_at is a stamp, set once a candidate of the group reached OSM
-- (candidates.stage = 'UPLOADED'). The live query is authoritative; the stamp
-- survives the run being deleted. After that both flips are mutations
-- (nodes->collapse deletes fifty-two nodes and creates one) and this import
-- only creates, so a frozen verdict is not editable.

CREATE TABLE IF NOT EXISTS unit_shape_verdicts (
    civic_key   TEXT NOT NULL,
    verdict     TEXT NOT NULL CHECK (verdict IN ('nodes','collapse','civic-only','skip')),
    unit_hash   TEXT NOT NULL,
    note        TEXT,
    updated_at  TEXT NOT NULL,
    frozen_at   TEXT,
    PRIMARY KEY (civic_key)
);

-- The same key on the candidate, set at emission under per-door-or-collapse
-- and NULL under every other policy. It is what lets a verdict find the runs
-- its group already landed in, and what freezes it once one of them is
-- uploaded. Candidates ingested before this migration carry NULL; Guelph had
-- not ingested under the policy when it landed, so nothing is backfilled.
ALTER TABLE candidates ADD COLUMN civic_key TEXT;
CREATE INDEX IF NOT EXISTS idx_candidates_civic_key
    ON candidates(civic_key) WHERE civic_key IS NOT NULL;

INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (19, datetime('now'));
