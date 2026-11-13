-- Instansens texter: organisationen, systemet som ersätts och
-- integritetssidans personuppgiftsansvarig och kontaktväg. De låg tidigare i
-- .env och gällde därmed hela processen. I databasen kan admin ändra dem, och
-- med flera organisationer på samma server (en databasfil per organisation)
-- följer de med organisationens fil.
--
-- Exakt en rad. fran_miljon = 0 betyder att raden ännu inte fyllts från
-- miljövariablerna; app/instans.py gör det en gång vid start, så att en
-- befintlig instans behåller sina texter utan åtgärd.
CREATE TABLE instans (
    id                     INTEGER PRIMARY KEY CHECK (id = 1),
    organisation           TEXT NOT NULL DEFAULT '',
    nuvarande_system       TEXT NOT NULL DEFAULT '',
    personuppgiftsansvarig TEXT NOT NULL DEFAULT '',
    dataskydd_kontakt      TEXT NOT NULL DEFAULT '',
    fran_miljon            INTEGER NOT NULL DEFAULT 0
);

INSERT INTO instans (id) VALUES (1);
