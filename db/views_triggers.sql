-- Views and triggers: the database-resident business logic (spec D1–D4, A1/A4).
-- This file is DROP+CREATE-run on every application startup, so iterating on it
-- never needs a migration. Requires SQLite >= 3.34 (CTEs inside trigger bodies).

------------------------------------------------------------------------------
-- D1: cycle protection. Error messages carry the 'CYKEL:' prefix; the app
-- catches IntegrityError, matches the prefix and shows the Swedish text inline.
------------------------------------------------------------------------------

DROP TRIGGER IF EXISTS funktion_cykel_insert;
CREATE TRIGGER funktion_cykel_insert
BEFORE INSERT ON funktion
WHEN NEW.foralder_id IS NOT NULL AND NEW.foralder_id = NEW.id
BEGIN
    SELECT RAISE(ABORT, 'CYKEL: En nod kan inte vara sin egen förälder.');
END;

DROP TRIGGER IF EXISTS funktion_cykel_update;
CREATE TRIGGER funktion_cykel_update
BEFORE UPDATE OF foralder_id ON funktion
WHEN NEW.foralder_id IS NOT NULL
BEGIN
    -- A node may not become a child of itself or of any of its descendants.
    SELECT RAISE(ABORT, 'CYKEL: Noden kan inte flyttas till sig själv eller sin egen undergren.')
    WHERE NEW.foralder_id = NEW.id
       OR NEW.foralder_id IN (
            WITH RECURSIVE undergren(id) AS (
                SELECT id FROM funktion WHERE foralder_id = NEW.id
                UNION ALL
                SELECT f.id FROM funktion f JOIN undergren u ON f.foralder_id = u.id
            )
            SELECT id FROM undergren
       );
END;

------------------------------------------------------------------------------
-- Avgångskrav: en nod med status 'planerad' eller 'driftsatt' måste ha fas
-- (UI: "avgång") ifylld. Gäller BARA skrivningar som rör status/fas — flytt,
-- sortering och synlighet tilldelar inte kolumnerna, så befintliga rader utan
-- avgång fortsätter fungera tills någon redigerar dem. Felprefixet 'AVGÅNG:'
-- följer 'CYKEL:'-mönstret ovan (appen visar svansen inline via regeltext()).
-- TRIM/COALESCE: routrarna lagrar strip() or None, men rå SQL kan lagra ''.
-- KONVENTION: en framtida tabellombyggnads-migration (jfr 0002:s
-- INSERT…SELECT av befintliga rader) måste DROPpa funktion_avgang_* och
-- funktion_stampel_* först — förra uppstartens triggers ligger kvar när
-- migrate() kör, och de återskapas ändå här vid nästa start.
------------------------------------------------------------------------------

DROP TRIGGER IF EXISTS funktion_avgang_insert;
CREATE TRIGGER funktion_avgang_insert
BEFORE INSERT ON funktion
WHEN NEW.status IN ('planerad', 'driftsatt')
     AND TRIM(COALESCE(NEW.fas, '')) = ''
BEGIN
    SELECT RAISE(ABORT, 'AVGÅNG: En nod med status planerad eller driftsatt måste ha en avgång.');
END;

DROP TRIGGER IF EXISTS funktion_avgang_update;
CREATE TRIGGER funktion_avgang_update
BEFORE UPDATE OF status, fas ON funktion
WHEN NEW.status IN ('planerad', 'driftsatt')
     AND TRIM(COALESCE(NEW.fas, '')) = ''
BEGIN
    SELECT RAISE(ABORT, 'AVGÅNG: En nod med status planerad eller driftsatt måste ha en avgång.');
END;

------------------------------------------------------------------------------
-- Tidsstämplar (migration 0005): skapad sätts vid INSERT, uppdaterad vid
-- INNEHÅLLSändringar. WHEN-villkoret (IS NOT hanterar NULL) gör att bara
-- faktiska ändringar stämplar — sortera_syskon skriver foralder_id på hela
-- syskongruppen även när värdet står stilla, och redigeringsformuläret
-- skriver alla kolumner varje spar. sortering är medvetet utelämnad: att
-- ordna om syskon är inte en innehållsändring. COALESCE bevarar stämplar
-- som en framtida ombyggnads-migration eller import redan satt.
------------------------------------------------------------------------------

DROP TRIGGER IF EXISTS funktion_stampel_insert;
CREATE TRIGGER funktion_stampel_insert
AFTER INSERT ON funktion
BEGIN
    UPDATE funktion
    SET skapad = COALESCE(NEW.skapad, datetime('now')),
        uppdaterad = COALESCE(NEW.uppdaterad, NEW.skapad, datetime('now'))
    WHERE id = NEW.id;
END;

DROP TRIGGER IF EXISTS funktion_stampel_update;
CREATE TRIGGER funktion_stampel_update
AFTER UPDATE OF namn, foralder_id, typ, status, fas, beskrivning,
                synlig_externt, lank_dokumentation, lank_jira,
                rankning_last, rankning_last_kommentar ON funktion
WHEN OLD.namn IS NOT NEW.namn
  OR OLD.foralder_id IS NOT NEW.foralder_id
  OR OLD.typ IS NOT NEW.typ
  OR OLD.status IS NOT NEW.status
  OR OLD.fas IS NOT NEW.fas
  OR OLD.beskrivning IS NOT NEW.beskrivning
  OR OLD.synlig_externt IS NOT NEW.synlig_externt
  OR OLD.lank_dokumentation IS NOT NEW.lank_dokumentation
  OR OLD.lank_jira IS NOT NEW.lank_jira
  OR OLD.rankning_last IS NOT NEW.rankning_last
  OR OLD.rankning_last_kommentar IS NOT NEW.rankning_last_kommentar
BEGIN
    UPDATE funktion SET uppdaterad = datetime('now') WHERE id = NEW.id;
END;

------------------------------------------------------------------------------
-- D2: history. Copy the old row to bedomning_historik before UPDATE/DELETE.
------------------------------------------------------------------------------

DROP TRIGGER IF EXISTS bedomning_hist_update;
CREATE TRIGGER bedomning_hist_update
BEFORE UPDATE ON bedomning
BEGIN
    INSERT INTO bedomning_historik
        (medlem_id, funktion_id, svar, oppen_kommentar, oppen_delning,
         intern_kommentar, besvarat_av, besvarat)
    VALUES
        (OLD.medlem_id, OLD.funktion_id, OLD.svar, OLD.oppen_kommentar, OLD.oppen_delning,
         OLD.intern_kommentar, OLD.besvarat_av, OLD.besvarat);
END;

DROP TRIGGER IF EXISTS bedomning_hist_delete;
CREATE TRIGGER bedomning_hist_delete
BEFORE DELETE ON bedomning
BEGIN
    INSERT INTO bedomning_historik
        (medlem_id, funktion_id, svar, oppen_kommentar, oppen_delning,
         intern_kommentar, besvarat_av, besvarat)
    VALUES
        (OLD.medlem_id, OLD.funktion_id, OLD.svar, OLD.oppen_kommentar, OLD.oppen_delning,
         OLD.intern_kommentar, OLD.besvarat_av, OLD.besvarat);
END;

------------------------------------------------------------------------------
-- D4: funktion_trad — the whole tree in display order.
--   djup        depth (roots = 0)
--   vag         sortable path, one '%04d%06d' segment (sortering + id as
--               tiebreaker) per level; ORDER BY vag = display order everywhere
--   synlig_stig transitive external visibility: 0 if the node OR any ancestor
--               has synlig_externt = 0 (T5: hiding a node hides its subtree)
-- printf() is one of the few accepted SQLite-only points (D5) — a PostgreSQL
-- port replaces it with lpad().
------------------------------------------------------------------------------

DROP VIEW IF EXISTS funktion_trad;
CREATE VIEW funktion_trad AS
WITH RECURSIVE trad(id, djup, vag, synlig_stig) AS (
    SELECT f.id, 0,
           printf('%04d%06d', f.sortering, f.id),
           f.synlig_externt
    FROM funktion f
    WHERE f.foralder_id IS NULL
    UNION ALL
    SELECT f.id, t.djup + 1,
           t.vag || '.' || printf('%04d%06d', f.sortering, f.id),
           CASE WHEN t.synlig_stig = 1 AND f.synlig_externt = 1 THEN 1 ELSE 0 END
    FROM funktion f
    JOIN trad t ON f.foralder_id = t.id
)
SELECT t.id, t.djup, t.vag, t.synlig_stig,
       f.namn, f.beskrivning, f.foralder_id, f.typ, f.status, f.fas,
       f.synlig_externt, f.sortering, f.lank_dokumentation, f.lank_jira,
       f.skapad, f.uppdaterad, f.rankning_last, f.rankning_last_kommentar
FROM trad t
JOIN funktion f ON f.id = t.id;

------------------------------------------------------------------------------
-- A1/A4: effective answers. Two views with the SAME column shape so every
-- analysis query is written once and only the FROM relation differs (the A3
-- toggle). kalla_funktion_id = the node the answer actually lives on, for the
-- "ärvt: <svar> (från <nod>)" label (A2).
------------------------------------------------------------------------------

DROP VIEW IF EXISTS bedomning_direkt;
CREATE VIEW bedomning_direkt AS
SELECT medlem_id, funktion_id, funktion_id AS kalla_funktion_id, svar, 0 AS arvd
FROM bedomning;

DROP VIEW IF EXISTS bedomning_effektiv;
CREATE VIEW bedomning_effektiv AS
WITH RECURSIVE eff(medlem_id, funktion_id, kalla_funktion_id, svar) AS (
    SELECT m.id, f.id,
           CASE WHEN b.svar IS NULL THEN NULL ELSE f.id END,
           b.svar
    FROM medlem m
    JOIN funktion f ON f.foralder_id IS NULL
    LEFT JOIN bedomning b ON b.funktion_id = f.id AND b.medlem_id = m.id
    UNION ALL
    SELECT e.medlem_id, f.id,
           CASE WHEN b.svar IS NULL THEN e.kalla_funktion_id ELSE f.id END,
           COALESCE(b.svar, e.svar)
    FROM funktion f
    JOIN eff e ON f.foralder_id = e.funktion_id
    LEFT JOIN bedomning b ON b.funktion_id = f.id AND b.medlem_id = e.medlem_id
)
SELECT medlem_id, funktion_id, kalla_funktion_id, svar,
       CASE WHEN kalla_funktion_id = funktion_id THEN 0 ELSE 1 END AS arvd
FROM eff
WHERE svar IS NOT NULL;
