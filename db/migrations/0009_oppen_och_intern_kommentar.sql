-- Workaround → öppen kommentar, kommentar → intern kommentar.
-- Workaround-fältet fanns bara vid "Kan vänta" och delades alltid anonymt.
-- Nu blir det en öppen kommentar som går att skriva vid alla tre svaren,
-- med tre delningslägen: privat (bara förvaltarna), anonym (alla medlemmar,
-- utan avsändare) och namn (alla medlemmar, med organisationens namn).
-- Den gamla kommentaren byter bara namn; den är som förut privat för
-- medlemmen och förvaltarna.
--
-- Befintliga delade workarounds blir anonyma öppna kommentarer — samma
-- synlighet som de hade. Ej delade blir privata.
--
-- Historiktriggrarna (D2) räknar upp kolumnerna och ligger kvar från förra
-- uppstarten — de droppas först, annars vägrar DROP COLUMN, och UPDATE:n
-- nedan skulle skriva migreringen som historik. views_triggers.sql
-- återskapar dem med de nya namnen efter migreringarna.
DROP TRIGGER IF EXISTS bedomning_hist_update;
DROP TRIGGER IF EXISTS bedomning_hist_delete;

ALTER TABLE bedomning RENAME COLUMN workaround TO oppen_kommentar;
ALTER TABLE bedomning RENAME COLUMN kommentar TO intern_kommentar;
ALTER TABLE bedomning ADD COLUMN oppen_delning TEXT NOT NULL DEFAULT 'privat'
    CHECK (oppen_delning IN ('privat', 'anonym', 'namn'));
UPDATE bedomning SET oppen_delning = 'anonym' WHERE workaround_delas = 1;
ALTER TABLE bedomning DROP COLUMN workaround_delas;

ALTER TABLE bedomning_historik RENAME COLUMN workaround TO oppen_kommentar;
ALTER TABLE bedomning_historik RENAME COLUMN kommentar TO intern_kommentar;
ALTER TABLE bedomning_historik ADD COLUMN oppen_delning TEXT;
UPDATE bedomning_historik SET oppen_delning =
    CASE workaround_delas WHEN 1 THEN 'anonym' WHEN 0 THEN 'privat' END;
ALTER TABLE bedomning_historik DROP COLUMN workaround_delas;
