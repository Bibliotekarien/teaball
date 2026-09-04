-- Staff accounts get a role:
--   admin  — full rights (today's behaviour)
--   intern — read-only, sees everything including internal data
--   extern — read-only, restricted to externally visible content
-- Existing accounts keep full rights via the constant DEFAULT (which is what
-- lets SQLite add a NOT NULL column with CHECK in-place), so nobody is locked
-- out when this deploys.
ALTER TABLE forvaltare ADD COLUMN roll TEXT NOT NULL DEFAULT 'admin'
    CHECK (roll IN ('admin', 'intern', 'extern'));
