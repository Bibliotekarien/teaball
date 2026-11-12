# Installera Teaball på egen server

Den här guiden är för en organisation som vill driva en egen Teaball-instans.
Den förutsätter ingen särskild plattform: en Linuxserver med Docker och en
reverse proxy som terminerar TLS räcker. (Hur instansen på
bibliotekarien-vps drivs står i [`docs/drift-bibliotekarien-vps.md`](docs/drift-bibliotekarien-vps.md)
— den bygger på en delad plattform och är inte en mall att följa.)

En instans består av **en container och en SQLite-fil**. All data — behovsträd,
roadmap, bedömningar, medlemmar och konton — ligger i den filen. Det finns
ingen separat databasserver, ingen e-post och inga externa beroenden i drift.

## 1. Krav

- Linux med Docker Engine och Compose-pluginen (`docker compose`).
- Ett DNS-namn för tjänsten, t.ex. `teaball.example.org`.
- En reverse proxy med TLS (Caddy, nginx, Apache, Traefik …) på samma server.
- **Lokal disk** för databasen. SQLite på nätverksmontering (CIFS/NFS) ger
  korrupta databaser — dit får bara backupkopior skrivas.
- Ett separat backupmål (annan disk, montering eller server).

Resursbehovet är litet: compose-filen begränsar containern till 1 CPU och
512 MB minne, vilket räcker med god marginal för ett konsortium på ~50
medlemmar.

## 2. Installera

```bash
sudo git clone https://github.com/Bibliotekarien/teaball.git /srv/teaball
cd /srv/teaball
sudo cp .env.example .env
sudo chmod 600 .env
```

Fyll i `.env`:

| Variabel | Värde |
|---|---|
| `SECRET_KEY` | Slumpad nyckel som signerar sessionscookies. Generera med `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`. Appen vägrar starta utan. |
| `PUBLIC_BASE_URL` | Den publika adressen, t.ex. `https://teaball.example.org`. Används i medlemmarnas svarslänkar. |
| `ORGANISATION` | Namnet på er organisation eller ert samarbete, t.ex. `Exempelkonsortiet`. Visas på integritetssidan. Tomt ger neutral text. |
| `NUVARANDE_SYSTEM` | Systemet som ska ersättas, t.ex. `Gamla Systemet`. Används i förklaringen av statusen *utreds* ("Finns i …"). Tomt ger "det nuvarande systemet". |
| `PERSONUPPGIFTSANSVARIG` | Vem som är personuppgiftsansvarig, t.ex. `Exempeluniversitetet`. Visas på `/integritet`. |
| `DATASKYDD_KONTAKT` | Kontaktväg för dataskyddsfrågor, t.ex. en funktionsadress. Visas på `/integritet`. |
| `MATOMO_*` | Lämna tomma om ni inte har en egen Matomo — då är statistiken avstängd, och integritetssidan säger det. |
| `ANUBIS_COOKIE_DOMAIN` | Används inte av den fristående compose-filen; lämna som den är. |

Så länge `PERSONUPPGIFTSANSVARIG` och `DATASKYDD_KONTAKT` saknas visar
integritetssidan en gul markering om att de ska fyllas i före skarp drift.
Läs igenom sidan (`/integritet`) innan ni öppnar tjänsten. Den säger till
exempel att tjänsten och säkerhetskopiorna driftas inom EU, och det måste
stämma för er.

Skapa datakatalogen. Containern kör som uid/gid 1505, som måste äga den:

```bash
sudo mkdir teaball-data
sudo chown 1505:1505 teaball-data
sudo chmod 700 teaball-data
```

Vill ni ha databasen någon annanstans, sätt `TEABALL_DATA_DIR=/sökväg` i
`.env`. Porten (`127.0.0.1:8000`) ändras med `TEABALL_PORT`.

Bygg och starta:

```bash
sudo docker compose -f docker-compose.standalone.yml up -d --build
curl -s http://127.0.0.1:8000/health      # {"status":"ok"}
```

Databasen skapas och migreras automatiskt vid första starten.

## 3. Reverse proxy

Appen lyssnar **bara** på `127.0.0.1` och ska alltid nås via proxyn. Den litar
på proxyns `X-Forwarded-For` för klientens IP (inloggningsspärren räknar per
IP) — publicera aldrig porten utåt, då kan klienter förfalska sin adress.

Appen sätter själv sina säkerhetsheadrar (Content-Security-Policy,
X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Cache-Control på
sidor med bedömningar). Proxyn behöver bara lägga till **HSTS** och
**ersätta**, inte förlänga, `X-Forwarded-For`.

**Caddy** (hämtar och förnyar certifikat själv; skriver över
`X-Forwarded-For` som standard):

```caddy
teaball.example.org {
    reverse_proxy 127.0.0.1:8000
    header Strict-Transport-Security "max-age=63072000; includeSubDomains"
}
```

**nginx** (certifikat via t.ex. certbot):

```nginx
server {
    listen 443 ssl;
    server_name teaball.example.org;
    # ssl_certificate / ssl_certificate_key …

    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $remote_addr;   # inte $proxy_add_x_forwarded_for
    }
}
```

### Proxyloggarna innehåller hemliga länkar

Medlemmarnas svarslänkar har formen `/svara/<token>`, där token *är*
inloggningen. Appens egen accesslogg maskar dem, men proxyns logg gör det
inte av sig själv — token syns i request-URI:n och i `Referer` på anrop från
svarssidan. Maska dem (mönster: `/svara/[A-Za-z0-9_-]{32,}`), stäng av
accessloggen för tjänsten, eller behandla proxyloggen som lika känslig som
databasen.

## 4. Första administratören

```bash
sudo docker compose -f docker-compose.standalone.yml exec web \
    python scripts/skapa_forvaltare.py stilla-lax
```

Lösenordet frågas efter interaktivt. Logga in på `/login`; resten av kontona
sköts under **Konton** i appen. Roller och kontohantering beskrivs i
[README](README.md#skapa-förvaltarkonton).

Har ni migrerat en databas från en annan instans (avsnitt 6) finns kontona
redan — hoppa över det här steget.

## 5. Börja med tom databas

Läs in medlemmar och ett startskelett för behovsträdet enligt
[README, Initial datainläsning](README.md#initial-datainläsning). Med den
fristående compose-filen blir kommandona:

```bash
sudo docker compose -f docker-compose.standalone.yml cp medlemmar.csv web:/tmp/medlemmar.csv
sudo docker compose -f docker-compose.standalone.yml exec web python scripts/importera_medlemmar.py /tmp/medlemmar.csv
```

Formatet framgår av exemplen i `data/` (från DiVA-konsortiet, där Teaball
började). Vill ni börja behovsträdet från exemplets skelett:

```bash
sudo docker compose -f docker-compose.standalone.yml exec web python scripts/importera_trad.py data/diva_formagekarta_exempel.csv
```

## 6. Ta över en databas från en annan instans

Hela instansen flyttas som en fil. Gör gärna en generalrepetition med en
färsk kopia först — den visar att allt fungerar och hur lång tid det tar —
och kasta sedan provdatabasen.

**Versioner:** den nya instansen måste köra **samma eller nyare** version av
koden än den gamla. Nyare kod migrerar databasen automatiskt vid start (och
tar en säkerhetskopia först); äldre kod mot en nyare databas stöds inte.

**Hos den gamla instansen:**

1. Stoppa appen, så att ingen skriver något som sedan går förlorat.
2. Ta en konsistent kopia med SQLite:s backup-API, t.ex.
   `scripts/backup.sh <dbfil> <målkatalog>` (ger
   `<målkatalog>/dagliga/teaball-<datum>.db`, integritetskontrollerad).
3. Räkna checksumma: `sha256sum teaball-<datum>.db`.
4. För över filen krypterat (scp/sftp) — den innehåller bedömningar och
   kommentarer. Inte e-post, inte okrypterade delningstjänster.

**Hos den nya instansen:**

```bash
sudo docker compose -f docker-compose.standalone.yml stop web
sha256sum teaball-<datum>.db                     # jämför med avsändarens
sudo install -o 1505 -g 1505 -m 600 teaball-<datum>.db teaball-data/teaball.db
sudo docker compose -f docker-compose.standalone.yml start web
```

Ligger det redan en provdatabas i `teaball-data/`, ta bort `teaball.db` och
eventuella `teaball.db-wal`/`teaball.db-shm` innan den nya filen läggs dit.

Verifiera därefter: inloggning, behovsträdet, bedömningarna, analysen,
exporterna (inklusive PDF-rapporten) och roadmapen. Radera den överförda
filen och eventuella mellanlagrade kopior när allt stämmer.

**Efter övertagandet:**

- **Konton:** databasen innehåller den gamla instansens förvaltarkonton.
  Logga in med ett admin-konto som skapats åt er före flytten, och ta bort
  de konton som inte ska följa med under **Konton**.
- **Medlemslänkar:** länkarna innehåller den gamla adressen och slutar
  fungera när den instansen stängs. Skapa **ny länk** för varje medlem under
  **Medlemmar** och skicka ut dem. Länken visas en gång; den gamla blir
  ogiltig samtidigt. Medlemmarnas svar och kommentarer finns kvar — bara
  länken byts.
- **Integritetssidan:** sätt `ORGANISATION`, `PERSONUPPGIFTSANSVARIG` och
  `DATASKYDD_KONTAKT` i `.env` (avsnitt 2), så att `/integritet` beskriver
  er och inte den gamla instansens ägare.

## 7. Backup

`scripts/backup.sh` tar en konsistent kopia även under drift, verifierar den
med `PRAGMA integrity_check`, kontrollerar ledigt utrymme och roterar (30
dagliga + 12 månatliga). Den behöver `sqlite3` eller `python3` på servern och
körs som root (datakatalogen ägs av 1505). Cron-exempel:

```
10 3 * * * /srv/teaball/scripts/backup.sh /srv/teaball/teaball-data/teaball.db /mnt/backup/teaball
```

Målet ska ligga på en annan disk eller server. Övervaka att kopiorna faktiskt
skrivs, och prova en återställning någon gång.

**Återställning:** stoppa appen, ta bort `teaball.db-wal`/`-shm` om de finns,
kopiera in backupfilen som `teaball-data/teaball.db` (ägare 1505, läge 600),
starta igen.

## 8. Uppgradera

```bash
cd /srv/teaball
sudo scripts/backup.sh teaball-data/teaball.db /mnt/backup/teaball
sudo git pull --ff-only
sudo docker compose -f docker-compose.standalone.yml up -d --build
```

Väntande databasmigrationer körs vid start. Före dem tas automatiskt en
säkerhetskopia bredvid databasen (`teaball.fore-<version>-<tid>.db` i
`teaball-data/`); den roteras inte — ta bort den när uppgraderingen är
verifierad.

## 9. Valfritt

- **Statistik:** Teaball kan rapportera sidvisningar server-side till en
  Matomo-instans (Tracking HTTP API — inget skript i webbläsaren, DNT/GPC
  respekteras, svarslänkarnas token maskas). Sätt `MATOMO_URL`,
  `MATOMO_SITE_ID` och `MATOMO_TOKEN`.
- **Botskydd:** instansen på bibliotekarien-vps står bakom
  [Anubis](https://github.com/TecharoHQ/anubis); se
  `docker-compose.prod.yml` för hur. Tjänsten är stängd för sökmotorer
  (`/robots.txt` säger `Disallow: /`) och allt utom inloggningen kräver
  konto, så det är inget krav. Lägger ni Anubis framför appen måste
  CSP:n tillåta dess PoW-worker (`'wasm-unsafe-eval'`, `worker-src blob:`),
  och proxyn då sätta CSP:n i stället för appen. Sätt också `ROBOTSKYDD=1`
  i `.env` och för in den i compose-filens `environment`, så att
  integritetssidan nämner Anubis kaka.
