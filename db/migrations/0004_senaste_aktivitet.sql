-- Last-activity stamps for the admin accounts view (/konton) and the member
-- list. Deliberately data-minimal (GDPR): a single timestamp overwritten on
-- each login/link use — no history — shown only to the admin role, and
-- disclosed on /integritet. NULL means "never".
ALTER TABLE forvaltare ADD COLUMN senast_inloggad TEXT;
ALTER TABLE medlem ADD COLUMN senast_anvand TEXT;
