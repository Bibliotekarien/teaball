# Teaball

Kravdatabas och förmågekarta för ett system under omskrivning, med ca 50
medlemsorganisationer. Verktyget håller en hierarkisk funktions-/kravstruktur,
en roadmap och medlemmarnas bedömning av varje krav — så att gemensamma
nämnare, blockerare för go-live och migreringsordning blir synliga.
Kravspecifikationen finns i [`requirements.md`](requirements.md), designen
följer prototypen i `formagekarta-prototyp.jsx`. (I de dokumenten bär
tjänsten arbetsnamnet *Förmågekartan* — den heter numera Teaball; dokumenten
är bevarade oförändrade.)

**Stack:** Python/FastAPI + SQLite (all affärslogik som triggers/vyer i
databasen) + serverrenderad Jinja2 med htmx. Ingen SPA, ingen build-kedja.
Dra-och-släpp i kravträdet är en progressiv förbättring (SortableJS, vendorerad)
— allt fungerar även utan JavaScript.

## Installation (docker-compose, lokal/enkel drift)

```bash
cp .env.example .env          # fyll i SECRET_KEY och PUBLIC_BASE_URL
docker compose up -d --build
```

Appen lyssnar på `127.0.0.1:8000` och förutsätts stå bakom en befintlig
reverse proxy som terminerar TLS. Databasfilen hamnar i `./data/` (lokal disk —
**aldrig** CIFS-/nätverksmontering; endast backupkopior får ligga där).

## Drift på bibliotekarien-vps (produktion)

Produktion körs med **`docker-compose.prod.yml`** enligt plattformens mönster
(se `bibliotekarien-platform/SERVER_LAYOUT.md`, som är källa-av-sanning):
stack `/opt/teaball/app`, service-användare `teaball` (UID 1505),
inga host-portar — edge-Caddy joinar `teaball_proxy` och proxar
`teaball.bibliotekarien.se` genom **Anubis** (PoW-gate för all trafik;
htmx-anropen bär clearance-cookien). Databasen ligger i named-volymen
`teaball-data`.

Driftsättningschecklista (första gången):

1. DNS: `teaball.bibliotekarien.se` → serverns IP.
2. Skapa service-användare: `useradd --system --uid 1505 --home-dir /opt/teaball --shell /usr/sbin/nologin teaball && usermod -aG docker teaball`.
3. Klona repot till `/opt/teaball/app`, skapa `.env` från `.env.example`
   (SECRET_KEY, PUBLIC_BASE_URL, ANUBIS_COOKIE_DOMAIN; Matomo-värdena nedan).
4. **Matomo:** registrera sajten på `https://bibstats.bibliotekarien.se`
   (Administration → Websites → Manage → Add a new website, URL
   `https://teaball.bibliotekarien.se`) och sätt `MATOMO_SITE_ID` +
   `MATOMO_TOKEN` i `.env`. Trackingen sker **server-side** (Tracking HTTP API)
   — ingen matomo.js i klienten, DNT/GPC respekteras, `/svara/<token>` maskas.
5. `sudo /opt/teaball/app/scripts/deploy.sh` (skapar nätet), därefter
   `make -C /opt/bibliotekarien-platform edge-recreate` (Caddy joinar nätet).
6. Systemd: `sudo cp deploy/teaball.service deploy/teaball-backup.{service,timer} /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now teaball.service teaball-backup.timer`.
7. Skapa förvaltarkonton + läs in underlag (se nedan, med
   `docker compose -f docker-compose.prod.yml exec web ...`).
8. Observability: avkommentera `teaball.bibliotekarien.se`-proben i
   `observability-platform/stack/prometheus/prometheus.yml` (avsiktligt
   utkommenterad tills sajten är live — inga röda prober i förväg).

### Skapa förvaltarkonton

```bash
docker compose exec app python scripts/skapa_forvaltare.py anna
docker compose exec app python scripts/skapa_forvaltare.py bertil
```

Lösenordet frågas efter interaktivt och lagras argon2-hashat. Logga sedan in på
`/login`.

### Initial datainläsning

Läs in ett befintligt underlag som CSV eller JSON (kolumner/nycklar:
`namn, foralder, typ, status, fas` — `foralder` är förälderns *namn*, tomt för
rotnivå; filordningen blir syskonordningen):

```bash
docker compose exec app python scripts/importera_trad.py underlag.csv
```

Hela importen är en transaktion — valideringsfel lämnar databasen orörd.

Medlemslistan läses in på samma sätt (kolumner/nycklar: `namn, kategori`).
Utan filargument används det incheckade underlaget med DiVA-konsortiets
49 medlemmar (`data/diva_medlemmar.csv`, hämtat från
[info.diva-portal.org](https://www.info.diva-portal.org/w/diva/konsortiet/)):

```bash
docker compose exec app python scripts/importera_medlemmar.py            # DiVA:s medlemmar
docker compose exec app python scripts/importera_medlemmar.py egna.csv   # eget underlag
```

Medlemmar som redan finns (samma namn) hoppas över, så importen kan köras om
när medlemslistan ändras uppströms. Det finns även ett litet exempel-underlag
för själva förmågekartan, `data/diva_formagekarta_exempel.csv`, att läsa in
med `importera_trad.py` som startskelett.

### Medlemslänkar (fas 2)

Under **Medlemmar** i appen: lägg till medlemsorganisationer och klicka
”skapa länk”. Den personliga svarslänken (`/svara/<token>`) visas **en enda
gång** — kopiera och skicka den direkt. Endast en SHA-256-hash av token lagras;
”ny länk” eller ”återkalla” gör den gamla ogiltig omedelbart, även för pågående
sessioner. Medlemmen ser bara noder som är markerade synliga och bara sina egna
svar; delade workarounds från andra visas anonymt.

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

## Utveckling

```bash
uv sync                       # beroenden (Python 3.12+)
uv run pytest -m "not slow"   # testsvit
uv run pytest                 # inkl. prestandatest (500 noder/50 medlemmar/10k svar)
uv run uvicorn app.main:app --reload
python scripts/seed_demo.py   # deterministisk demodata till en tom databas
```

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
- **Migrationer:** numrerade filer i `db/migrations/` (bara tabeller/index),
  spårade i `schema_migration`, körda vid uppstart. Vyer/triggers behöver
  aldrig migration.

### Portanteckningar (D5)

SQL:en är dialektneutral med två kända undantag, båda i
`db/views_triggers.sql`/schemat: `printf('%04d…')` (blir `lpad()` i PostgreSQL)
och `datetime('now')` (blir `now()`). En framtida flytt är export/import, inte
omskrivning.
