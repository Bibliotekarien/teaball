-- Skapande-/uppdateringsstämplar på noderna, för listvyns sortering.
-- Befintliga rader får NULL = "före spårningen" — ärligare än att stämpla
-- migrationsögonblicket, som skulle få hela beståndet att se nyskapat ut.
-- Listvyn sorterar NULL sist oavsett riktning. Stämplingen sköts av
-- funktion_stampel_*-triggrarna i db/views_triggers.sql.
ALTER TABLE funktion ADD COLUMN skapad TEXT;
ALTER TABLE funktion ADD COLUMN uppdaterad TEXT;
