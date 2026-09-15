-- Units become uploadable under [units] policy = "per-door-or-collapse".
--
-- A candidate is no longer always one source row reduced to a civic address.
-- Where the source gives each unit its own front door, the candidate IS that
-- unit and carries `unit` (-> addr:unit). Where the units are stacked suites,
-- one candidate stands for the whole building and carries `flats` (-> a
-- semicolon-separated addr:flats listing every unit behind it). The two are
-- mutually exclusive by construction and both are NULL under every other
-- policy, which is what keeps Toronto and Hamilton byte-identical.
--
-- These also make conflation and upload dedup unit-aware: without them a
-- per-door candidate and the civic node at the same number look like the same
-- address, and 12 townhouse doors collapse back into 1 at upload time. See
-- t2/units.py for what decides which shape a group is.
ALTER TABLE candidates ADD COLUMN unit TEXT;
ALTER TABLE candidates ADD COLUMN flats TEXT;
INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (17, datetime('now'));
