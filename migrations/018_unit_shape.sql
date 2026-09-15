-- Carry units.classify's verdict onto the candidate, so a group the rule was
-- unsure about does not arrive looking like one it was certain about.
--
-- REVIEW groups are emitted collapsed, exactly like COLLAPSE ones: same node,
-- same addr:flats. That is the right upload either way, but it means 252 Stone
-- Road West -- a mall whose 140 "units" are storefronts -- would otherwise be
-- indistinguishable from a 14-storey tower. The unit_shape_ambiguous check
-- reads these two columns and puts the difference in front of a reviewer.
--
-- NULL for every candidate under every other policy, and for the plain civic
-- addresses that were never part of a multi-unit group at all.
ALTER TABLE candidates ADD COLUMN unit_shape TEXT;
ALTER TABLE candidates ADD COLUMN unit_shape_reason TEXT;
INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (18, datetime('now'));
