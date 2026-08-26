# Kravspecifikation: Förmågekartan

Kravdatabas och förmågekarta för ett system under omskrivning, med ca 50 medlemsorganisationer.
Verktyget ska hålla en hierarkisk funktions-/kravstruktur, en roadmap, och medlemmarnas
bedömning av varje krav — så att vi kan se gemensamma nämnare, blockerare för go-live
och migreringsordning.

En klickbar designprototyp finns i `formagekarta-prototyp.jsx` (React). Den definierar
utseende, interaktioner och terminologi för de tre vyerna. Slutprodukten ska följa
prototypens design men byggas enligt stacken nedan.

## 1. Användare och faser

| Fas | Användare | Åtkomst |
|-----|-----------|---------|
| 1 (nu) | Förvaltare (2 st: konsult + produktägare) | Full CRUD på allt. Enkel inloggning. |
| 2 | Medlemsorganisationer (~50) | Egen bedömningsvy via unik länk (token) per medlem. Ser och ändrar endast egna bedömningar. |
| 3 (framtid, ej i scope nu) | Medlemmar via SAML/Shibboleth (SWAMID) | Ersätter tokenlänkarna. Bygg fas 2 så att autentiseringen är utbytbar. |

## 2. Teknisk stack

- **Backend:** Python 3.12+, FastAPI
- **Databas:** SQLite (en databasfil, WAL-läge). All logik som kan ligga i databasen ska ligga där:
  constraints, triggers, vyer. Anslutningar öppnas alltid med `PRAGMA foreign_keys=ON`,
  `PRAGMA journal_mode=WAL`, `PRAGMA busy_timeout=5000`. Databasfilen ska ligga på lokal disk —
  aldrig på CIFS-/nätverksmontering (endast backupkopior får ligga där).
- **Frontend:** Server-renderad Jinja2 + htmx. Ingen SPA, ingen build-kedja. Tailwind via CDN eller förkompilerad statisk CSS.
- **Drift:** en enda tjänst — app-container (docker-compose med en tjänst) eller systemd-tjänst med
  venv, på en enkel Linux-VPS bakom befintlig reverse proxy (TLS termineras utanför). Ingen databasserver.
- **Språk:** Allt användarvänt gränssnitt på svenska. Kod och kodkommentarer på engelska.

## 3. Datamodell

```sql
-- SQLite-dialekt. Enum ersätts av CHECK, boolean av INTEGER 0/1,
-- tidsstämplar lagras som ISO 8601-text i UTC.

CREATE TABLE funktion (
    id             INTEGER PRIMARY KEY,
    namn           TEXT NOT NULL,
    beskrivning    TEXT,
    foralder_id    INTEGER REFERENCES funktion(id) ON DELETE RESTRICT,
    typ            TEXT NOT NULL CHECK (typ IN ('förmåga','funktion','krav')),
    status         TEXT NOT NULL CHECK (status IN ('befintlig','planerad','idé','utgår')),
    fas            TEXT,                            -- roadmap: 'nu' | 'nästa' | 'senare' | fritext (kvartal)
    synlig_externt INTEGER NOT NULL DEFAULT 1,      -- 0 = visas aldrig för medlemmar
    sortering      INTEGER NOT NULL DEFAULT 0       -- ordning inom syskongrupp
);

CREATE TABLE medlem (
    id       INTEGER PRIMARY KEY,
    namn     TEXT NOT NULL,
    kategori TEXT,                                  -- universitet, högskola, myndighet, museum ...
    token    TEXT UNIQUE                            -- fas 2: slumpad, revokerbar åtkomstnyckel (lagras hashad)
);

CREATE TABLE bedomning (
    medlem_id   INTEGER NOT NULL REFERENCES medlem(id) ON DELETE CASCADE,
    funktion_id INTEGER NOT NULL REFERENCES funktion(id) ON DELETE CASCADE,
    svar        TEXT NOT NULL CHECK (svar IN ('golive_krav','kan_vanta','behovs_ej')),
    workaround  TEXT,                               -- endast meningsfull vid 'kan_vanta'
    workaround_delas INTEGER NOT NULL DEFAULT 0,    -- 1 = andra medlemmar får se workaround
    kommentar   TEXT,                               -- alltid privat: syns bara för medlemmen själv + förvaltare
    besvarat_av TEXT,                               -- fritext: namn/roll, eller 'proxy: <förvaltare>'
    besvarat    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (medlem_id, funktion_id)
);

CREATE TABLE bedomning_historik (
    id          INTEGER PRIMARY KEY,
    medlem_id   INTEGER NOT NULL,
    funktion_id INTEGER NOT NULL,
    svar        TEXT NOT NULL,
    workaround  TEXT,
    workaround_delas INTEGER,
    kommentar   TEXT,
    besvarat_av TEXT,
    besvarat    TEXT,
    ersatt      TEXT NOT NULL DEFAULT (datetime('now'))
);
```

**Krav på databaslogik:**

- **D1. Cykelskydd:** trigger på `funktion` som vid INSERT/UPDATE av `foralder_id` avvisar
  ändringen om noden skulle bli sin egen förfader. Fel ska ge begripligt meddelande i UI:t.
- **D2. Historik:** trigger på `bedomning` som vid UPDATE och DELETE kopierar den gamla raden
  till `bedomning_historik` innan ändringen.
- **D3. Hierarkin är fri:** inga regler som kopplar `typ` till trädnivå. Ett krav kan ligga
  direkt under en förmåga eller djupt ner, och kan ha egna barn.
- **D4.** Databasvy `funktion_trad` med rekursiv CTE som ger id, djup och sorterbar väg
  (`0001.0003.0002`-mönster) för hela trädet i visningsordning.
- **D5. Portabilitet:** håll SQL:en dialektneutral där det inte kostar något, så att en framtida
  flytt till PostgreSQL (om samtidigheten någon gång kräver det) är en export/import-övning,
  inte en omskrivning.

## 4. Arvsregeln (central affärslogik)

En bedömning på en nod gäller implicit alla dess ättlingar tills en ättling har ett eget svar.

- **A1.** "Effektivt svar" för (medlem, nod) = nodens eget svar, annars närmaste förfaders svar, annars inget.
- **A2.** I bedömningsvyn visas ärvda svar tydligt märkta ("ärvt: Kan vänta, från Import") och kan
  när som helst överskuggas med ett eget svar på noden.
- **A3.** I analysvyn räknas som standard endast **direkta** svar. En växel "räkna med ärvda svar"
  aktiverar effektiva svar i beräkningarna. (Direkt räkning är default för att inte blåsa upp siffror.)
- **A4.** Arvsberäkningen implementeras i SQL (rekursiv CTE), inte i applikationskod, så att
  samma logik kan användas från rapporter och ad hoc-frågor.

## 5. Vyer och funktioner

### 5.1 Kravträd (endast förvaltare)

- **T1.** Trädvy enligt prototypen: indrag, fäll ut/ihop per gren, etiketter för typ, status, fas.
- **T2.** Skapa nod (under vald förälder eller på rotnivå), redigera alla fält, ta bort nod.
  Borttag av nod med barn eller med bedömningar kräver bekräftelse som anger vad som påverkas.
- **T3.** Flytta nod: byta förälder (med cykelskydd) och ändra ordning bland syskon
  (upp/ner räcker; drag-och-släpp är inte nödvändigt).
- **T4.** Sök/filtrera på namn, typ, status, fas.
- **T5.** Fält `synlig_externt` kan togglas per nod; en icke-synlig nod döljer även hela sin undergren i medlemsvyn.

### 5.2 Bedömning

- **B1.** Förvaltarläge: välj medlem i lista och mata in svar å dennes vägnar (proxy).
  `besvarat_av` sätts då till `proxy: <inloggad förvaltare>`.
- **B2.** Medlemsläge (fas 2): URL `/svara/<token>` visar samma vy låst till medlemmens egna svar,
  utan inloggning i övrigt. Token ska kunna regenereras/revokeras per medlem av förvaltare.
- **B3.** Per nod: tre knappar (Go-live / Kan vänta / Behövs ej) enligt prototypen.
  Klick på redan valt svar tar bort svaret. Allt sparas direkt (htmx), ingen "spara"-knapp.
- **B4.** Workaround-fält visas endast när svaret är `kan_vanta`, med kryssruta
  "Dela med andra medlemmar" (`workaround_delas`).
- **B5.** Kommentarsfält tillgängligt vid alla svar (bakom knapp, som i prototypen). Kommentarer
  är alltid privata: synliga endast för medlemmen själv och förvaltarna.
- **B6.** Ärvda svar visas enligt A2.
- **B7.** Medlemsvyn visar endast noder med `synlig_externt = true` och ska fungera väl i mobil.
- **B8.** Delade workarounds från andra medlemmar visas för medlemmen som inspiration vid
  respektive nod (utan att visa vilken medlem som skrev den — endast antal + text).

### 5.3 Analys (endast förvaltare)

- **N1.** Blockerar-rankning enligt prototypen: per nod antal `golive_krav` / `kan_vanta` /
  `behovs_ej`, sorterad på blockerare, med stapeldiagram, status- och fasetikett.
- **N2.** Varningsflagga när en nod har ≥1 `golive_krav` men `status` ∈ {'idé'} eller `fas` = 'senare'.
- **N3.** Täckning alltid synlig: "X av Y medlemmar har lämnat minst ett svar" + lista över
  medlemmar som inte svarat. Obesvarat får aldrig framställas som "behövs ej".
- **N4.** Workaround-bank: alla workarounds aggregerade per nod (förvaltare ser allt, inkl. odelade,
  med medlemsnamn).
- **N5.** Medlemsprofil: välj medlem → deras alla svar, samt go-live-beredskap:
  lista över medlemmens `golive_krav`-noder vars status ≠ 'befintlig' ("utestående blockerare").
- **N6.** Migreringsöversikt: tabell över alla medlemmar sorterad på antal utestående blockerare
  (stigande) — de överst kan migreras först.
- **N7.** Gemensamma nämnare: för vald nod, vilka medlemmar (och kategorier) som kräver den;
  omvänt, för vald medlemsdelmängd, vilka krav de delar.

### 5.4 Roadmap

- **R1.** Läsvy grupperad på `fas`, inom fas ordnad enligt trädet, endast typ ∈ {'förmåga','funktion'}
  som standard med möjlighet att visa krav.
- **R2.** Export av roadmapen som fristående statisk HTML-fil (för utskick/styrgrupp),
  respekterar `synlig_externt`.

### 5.5 Export och import

- **E1.** Exportera hela databasen som JSON och funktionsträdet + bedömningar som CSV.
- **E2.** Importskript som läser en enkel CSV/JSON för initial inläsning av funktionsträdet
  (namn, förälder, typ, status, fas) så att befintligt underlag kan läsas in utan handpåläggning.

## 6. Autentisering och säkerhet

- **S1.** Fas 1: inloggning för förvaltare med användarnamn/lösenord (två konton räcker, i konfig
  eller enkel användartabell med bcrypt/argon2). Sessionscookie, CSRF-skydd på formulär.
- **S2.** Medlemstoken (fas 2): ≥128 bitar slump, lagras hashad, jämförs konstanttidsäkert.
- **S3.** Autentiseringen isoleras i en modul med tydligt gränssnitt så att SAML (fas 3) kan
  ersätta token utan att vyerna ändras.
- **S4.** All skrivning loggas (vem, vad, när) — historiktabellen täcker bedömningar; för
  `funktion` räcker enkel applikationslogg.
- **S5.** Parametriserade frågor överallt; ingen rå SQL-interpolering av användarinput.

## 7. Icke-funktionella krav

- **I1.** Allt UI på svenska, terminologi enligt prototypen (Go-live / Kan vänta / Behövs ej,
  Kravträd / Bedömning / Analys).
- **I2.** Fungerar utan JavaScript utöver htmx (progressiv förbättring; inga tunga beroenden).
- **I3.** Sidladdningar < 500 ms med 500 noder, 50 medlemmar, 10 000 bedömningar.
- **I4.** Backupskript ingår i repot: `sqlite3 <dbfil> ".backup <mål>"` (säker ögonblickskopia även
  under drift) med daterade filer, exempel-cronrad, rotation (behåll t.ex. 30 dagliga + 12 månatliga)
  och kontroll av ledigt utrymme på målet innan skrivning. Målet förutsätts vara en separat
  montering (t.ex. CIFS), aldrig samma katalog som databasfilen.
- **I5.** Testsvit: minst datamodellens triggers (cykelskydd, historik), arvsregeln (A1),
  och behörighetsgränserna (medlem A kan inte läsa/skriva medlem B:s data).
- **I6.** README på svenska: installation via docker-compose, initial datainläsning, skapa
  förvaltarkonton, generera medlemstoken.

## 8. Utanför scope

- SAML/SWAMID-integration (fas 3) — men se S3.
- Fritextinlämning av nya behov från medlemmar ("inkorg") — kan bli senare tillägg.
- Notifieringar/e-post.
- Flerspråkighet.
- Redigering av kravträdet av någon annan än förvaltare.

## 9. Acceptanstest (urval)

1. Skapa nod "Dubblettdetektering" som barn till "Import från Web of Science"; flytta den till
   rotnivå; försök göra "Import" till barn av "Dubblettdetektering" efter att ha flyttat tillbaka —
   cykeln ska avvisas med begripligt fel.
2. Som medlem via tokenlänk: svara `kan_vanta` på en funktionsnod, skriv workaround, bocka i
   delning. Kontrollera att barnen visar "ärvt", att en annan medlem ser workarounden anonymt,
   och att kommentaren inte syns för den andra medlemmen.
3. Ändra ett svar från `kan_vanta` till `golive_krav` — gamla raden ska finnas i historiken
   med workaround och kommentar intakta.
4. Sätt `synlig_externt = false` på en förmåga — hela undergrenen försvinner ur medlemsvyn
   och ur exporterad roadmap-HTML, men syns för förvaltare.
5. Analysvyn visar korrekt täckning när 3 av 6 medlemmar svarat, och N2-flaggan tänds för en
   nod med `golive_krav` i fas "senare".
