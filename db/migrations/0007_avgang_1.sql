-- Avgången "Medlem 1" heter nu "Avgång 1" (namnet ska inte läsas som en
-- medlemsorganisation). Den är fast först i roadmapen (FASTA_FASER i
-- services/roadmap.py), så namnet måste följa med i datat.
-- Stämpeltriggern droppas först så att namnbytet inte flyttar
-- uppdaterad-stämpeln på varje berörd nod — det är ingen innehållsändring
-- någon gjort. Den återskapas av views_triggers.sql efter migrationerna.
DROP TRIGGER IF EXISTS funktion_stampel_update;
UPDATE funktion SET fas = 'Avgång 1' WHERE fas = 'Medlem 1';
