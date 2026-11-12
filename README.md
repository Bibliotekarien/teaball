# Teaball

[![tests](https://github.com/Bibliotekarien/teaball/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/Bibliotekarien/teaball/actions/workflows/tests.yml?query=branch%3Amain)
[![coverage](https://raw.githubusercontent.com/Bibliotekarien/teaball/badges/coverage.svg)](https://github.com/Bibliotekarien/teaball/actions/workflows/tests.yml?query=branch%3Amain)

Behovsdatabas och förmågekarta för ett gemensamt system som byts ut, med
många medlemsorganisationer som var och en har sina behov. Verktyget håller en
hierarkisk funktions-/behovsstruktur, en roadmap och medlemmarnas bedömning av
varje behov — så att gemensamma nämnare, blockerare för go-live och
migreringsordning blir synliga.

Teaball byggdes för DiVA-konsortiets byte från DiVA Classic (ca 50
medlemsorganisationer), men inget i verktyget är bundet till det: namnen på
organisationen och det nuvarande systemet sätts per instans (se
[INSTALL.md](INSTALL.md#2-installera)). Kravspecifikationen finns i
[`requirements.md`](requirements.md), designen följer prototypen i
`formagekarta-prototyp.jsx`. (I de dokumenten bär tjänsten arbetsnamnet
*Förmågekartan* — den heter numera Teaball; dokumenten är bevarade
oförändrade.)

**Stack:** Python/FastAPI + SQLite (all affärslogik som triggers/vyer i
databasen) + serverrenderad Jinja2 med htmx. Ingen SPA, ingen build-kedja.
Dra-och-släpp i behovsträdet är en progressiv förbättring (SortableJS, vendorerad)
— allt fungerar även utan JavaScript.

## Installation

- **Egen server:** [`INSTALL.md`](INSTALL.md) — installation med
  `docker-compose.standalone.yml`, reverse proxy, backup, uppgradering och
  övertagande av en databas från en annan instans.
- **Lokal utveckling:** se [Utveckling](#utveckling) nedan, eller
  `docker compose up -d --build` med `docker-compose.yml`.
- **Instansen på bibliotekarien-vps:**
  [`docs/drift-bibliotekarien-vps.md`](docs/drift-bibliotekarien-vps.md).

## Förvaltning

### Skapa förvaltarkonton

Det första kontot skapas från kommandoraden (tjänsten heter `app` i
utvecklingskomposen och `web` i `docker-compose.standalone.yml` och
`docker-compose.prod.yml`):

```bash
docker compose exec app python scripts/skapa_forvaltare.py anna
docker compose -f docker-compose.standalone.yml exec web python scripts/skapa_forvaltare.py anna
```

Lösenordet frågas efter interaktivt och lagras argon2-hashat. Logga sedan in på
`/login`.

Resten sköts under **Konton** i appen (endast admin): skapa konto, byta roll,
slumpa nytt lösenord, ta bort. Användarnamnet föreslås slumpat — två vardagliga
ord som `stilla-lax` — så att kontolistan inte behöver innehålla några
personuppgifter; skriv över förslaget om ni vill. Lösenordet slumpas alltid och
visas en enda gång, för den som skapar kontot att lämna över; mottagaren byter
sedan själv under **Byt lösenord** i sidhuvudet (alla roller). Tjänsten har
ingen e-post och ska inte ha någon.

Två spärrar skyddar mot att låsa ute sig: ingen kan ändra, nollställa eller ta
bort sitt eget konto där, och den sista administratören kan varken tas bort
eller nedgraderas. Skriptet ovan fungerar fortfarande som reservväg
(`--roll intern|extern` sätter rollen).

Kontot får en av tre roller:

- **admin** — full behörighet (skapa/ändra/ta bort i alla vyer, samt
  instansens texter under **Inställningar**). Default för nya konton, och alla konton som fanns före rollstödet blir admin.
- **intern** — ser allt (även dolda noder, bedömningar med privata kommentarer,
  analys, export och medlemslistan) men kan inte ändra något.
- **extern** — skrivskyddad och ser bara externt synligt innehåll: behovsträdet
  och roadmapen filtrerade på `synlig_externt` (samma regel som medlemsvyn).
  Bedömningar, analys, medlemmar och export är spärrade; enda nedladdningen
  är roadmapens HTML-export, som redan är extern-säker.

Utelämnad `--roll` i skriptet lämnar ett befintligt kontos roll orörd — ett
lösenordsbyte ändrar aldrig behörighet. Rollbyte slår igenom på nästa request,
ingen ny inloggning krävs. Nytt lösenord (via skriptet eller **Konton**) och
borttagning loggar ut kontots pågående sessioner direkt.

Kontolistan under **Konton** visar roll och senaste inloggning;
medlemslänkarnas senaste användning syns under
**Medlemmar**. Endast den senaste tidpunkten sparas (skrivs över, ingen
historik) — datasnålt nog att bara kräva en notis på `/integritet`.

### Initial datainläsning

Läs in ett befintligt underlag som CSV eller JSON (kolumner/nycklar:
`namn, foralder, typ, status, fas` samt valfritt `lank_dokumentation` och
`lank_jira` — `foralder` är förälderns *namn*, tomt för rotnivå; filordningen
blir syskonordningen):

```bash
docker compose exec app python scripts/importera_trad.py underlag.csv
```

Hela importen är en transaktion — valideringsfel lämnar databasen orörd.

Giltiga statusar är `driftsatt`, `planerad`, `idé`, `utreds` och `utgår`.
`driftsatt` = finns och fungerar i nya plattformen (räknas inte som blockerare);
`utreds` = finns i det nuvarande systemet (namnet sätts under Inställningar),
identifierad men ännu inte beslutad (behandlas
som `idé` i analysens varningar). I kravspecen och prototypen heter `driftsatt`
fortfarande *befintlig* — de dokumenten är bevarade oförändrade; migration
`0002` döper om värdet i databasen automatiskt vid första uppstarten.
Förklaringarna visas även i appen, under ”Vad betyder typerna och statusarna?”.

Medlemslistan läses in på samma sätt (kolumner/nycklar: `namn, kategori`):

```bash
docker compose exec app python scripts/importera_medlemmar.py medlemmar.csv
```

Medlemmar som redan finns (samma namn) hoppas över, så importen kan köras om
när medlemslistan ändras uppströms.

I `data/` finns exempel på båda formaten, från DiVA-konsortiet där Teaball
började: `diva_medlemmar.csv` (49 medlemmar, hämtat från
[info.diva-portal.org](https://www.info.diva-portal.org/w/diva/konsortiet/))
och `diva_formagekarta_exempel.csv`, ett litet startskelett för
förmågekartan.

### Medlemslänkar (fas 2)

Under **Medlemmar** i appen: lägg till medlemsorganisationer och klicka
”skapa länk”. Den personliga svarslänken (`/svara/<token>`) visas **en enda
gång** — kopiera och skicka den direkt. Endast en SHA-256-hash av token lagras;
”ny länk” eller ”återkalla” gör den gamla ogiltig omedelbart, även för pågående
sessioner. Medlemmen ser bara noder som är markerade synliga och bara sina egna
svar; delade workarounds från andra visas anonymt.

Medlemmen har också en egen **Roadmap**-flik (`/svara/roadmap`): samma urval
som styrgruppens HTML-export — synliga noder grupperade per avgång, med namn,
typ och status — kompletterat med medlemmens eget effektiva svar per rad, så
att biblioteket ser om något det kräver för go-live ligger i en sen avgång.
Inga andras svar, inga antal, ingen analys; inget redigeringsläge och inga
exportlänkar.

## Backup (I4)

```bash
scripts/backup.sh /srv/teaball/data/teaball.db /mnt/backup/teaball
```

Tar en konsistent ögonblickskopia via SQLite:s backup-API (säker även under
drift), verifierar den med `PRAGMA integrity_check`, kontrollerar ledigt
utrymme på målet före skrivning och roterar: 30 dagliga + 12 månatliga kopior.
Målet ska vara en separat montering (t.ex. CIFS). Cron-exempel:

```
10 3 * * * /srv/teaball/scripts/backup.sh /srv/teaball/data/teaball.db /mnt/backup/teaball
```

Återställning: stoppa appen, kopiera in backupfilen som `data/teaball.db`,
starta igen.

Sökvägar för fristående drift står i [INSTALL.md](INSTALL.md#7-backup);
bibliotekarien-vps kör skriptet från en systemd-timer
([docs/drift-bibliotekarien-vps.md](docs/drift-bibliotekarien-vps.md#backup)).

## Utveckling

```bash
uv sync                       # beroenden (Python 3.12+)
uv run pytest -m "not slow"   # testsvit
uv run pytest                 # inkl. prestandatest (500 noder/50 medlemmar/10k svar)
uv run coverage run -m pytest -m "not slow" && uv run coverage report   # täckning
uv run uvicorn app.main:app --reload
python scripts/seed_demo.py   # deterministisk demodata till en tom databas
```

Täckningen mäts i CI (jobbet `coverage` i `.github/workflows/tests.yml`)
med grenmätning över `app/` och `scripts/`. Varje körning visar tabellen per
fil i sin sammanfattning, och jobbet failar under golvet `fail_under` i
`pyproject.toml`. Badgen ovan ritas av CI efter varje push till main och ligger
på grenen `badges`; ingen extern tjänst är inblandad.

CSS:en är förkompilerad Tailwind och incheckad (`static/css/app.css`) — ingen
build-kedja i drift. Efter template-ändringar, regenerera med standalone-CLI:t:

```bash
tailwindcss -i static/css/tailwind.in.css -o static/css/app.css --minify
```

### Arkitektur i korthet

- **Databaslogiken bor i databasen** (`db/views_triggers.sql`, återskapas vid
  varje uppstart): cykelskydd (D1) och bedömningshistorik (D2) som triggers,
  trädet i visningsordning som rekursiv vy (`funktion_trad`, D4), och
  arvsregeln (A1/A4) som vyparet `bedomning_direkt`/`bedomning_effektiv` med
  identisk kolumnform — analysens ”räkna med ärvda svar” byter bara FROM-vy.
- **Autentiseringen är en söm** (`app/auth/core.py`): routrar ser bara en
  `Principal`. Fas 3 (SAML/SWAMID) innebär en ny backend som returnerar samma
  `Principal` — vyerna ändras inte (S3).
- **htmx-mönstret:** varje osäker operation är ett riktigt formulär som
  fungerar utan JS (POST → redirect); htmx förbättrar samma endpoint med
  partiella svar (`HX-Request`-headern avgör).
- **Migrationer:** numrerade filer i `db/migrations/` (tabeller/index och
  datafixar), spårade i `schema_migration`, körda vid uppstart. Vyer/triggers
  behöver aldrig migration. Innan väntande migrationer körs mot en databas med
  data tas automatiskt en säkerhetskopia bredvid databasfilen
  (`<namn>.fore-<version>-<tidsstämpel>.db`, via SQLite:s backup-API) —
  återställning är stoppa appen + kopiera tillbaka filen. Kopian roteras
  inte: ta bort den när uppgraderingen är verifierad.

### Portanteckningar (D5)

SQL:en är dialektneutral med två kända undantag, båda i
`db/views_triggers.sql`/schemat: `printf('%04d…')` (blir `lpad()` i PostgreSQL)
och `datetime('now')` (blir `now()`). En framtida flytt är export/import, inte
omskrivning.
