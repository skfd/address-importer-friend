-- Allow the `split` verdict: a group's floor-coded suites collapse to one node
-- listing them, while a lettered row beside them that is numbered in sequence
-- and spaced like front doors becomes door nodes. Found 2026-10-02 at
-- 53 Arthur Street South, a tower (101-1005) with two townhouse rows (AT1-8,
-- RL1-6) on the same civic number. SQLite cannot alter a CHECK, so the table
-- is rebuilt with every row carried over.

CREATE TABLE unit_shape_verdicts_new (
    civic_key   TEXT NOT NULL,
    verdict     TEXT NOT NULL CHECK (verdict IN ('nodes','collapse','civic-only','skip','split')),
    unit_hash   TEXT NOT NULL,
    note        TEXT,
    updated_at  TEXT NOT NULL,
    frozen_at   TEXT,
    PRIMARY KEY (civic_key)
);
INSERT INTO unit_shape_verdicts_new (civic_key, verdict, unit_hash, note, updated_at, frozen_at)
    SELECT civic_key, verdict, unit_hash, note, updated_at, frozen_at FROM unit_shape_verdicts;
DROP TABLE unit_shape_verdicts;
ALTER TABLE unit_shape_verdicts_new RENAME TO unit_shape_verdicts;
INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (20, datetime('now'));
