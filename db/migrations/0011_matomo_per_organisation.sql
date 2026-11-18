-- Matomo-sajt per organisation. Med flera organisationer delar de operatörens
-- Matomo (MATOMO_URL och MATOMO_TOKEN i miljön), men var och en har sin egen
-- sajt, så att statistiken inte blandas. Sätts av operatören med
-- scripts/organisationer.py matomo, aldrig av organisationens admin: sajten
-- ligger i operatörens Matomo, och en admin ska inte kunna rapportera in i
-- en annan organisations statistik. Tom = ingen statistik för organisationen.
-- Med en organisation används MATOMO_SITE_ID i miljön som förut.
ALTER TABLE instans ADD COLUMN matomo_site_id TEXT NOT NULL DEFAULT '';
