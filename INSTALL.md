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
| `MATOMO_*` | Lämna tomma om ni inte har en egen Matomo — då är statistiken avstängd, och integritetssidan säger det. |
| `ANUBIS_COOKIE_DOMAIN` | Används inte av den fristående compose-filen; lämna som den är. |

Skapa datakatalogen. Containern kör som uid/gid 1505, som måste äga den:

```bash
sudo mkdir teaball-data
sudo chown 1505:1505 teaball-data
sudo chmod 700 teaball-data
```

Vill ni ha databasen någon annanstans, sätt `TEABALL_DATA_DIR=/sökväg` i
`.env`. Porten (`127.0.0.1:8000`) ändras med `TEABALL_PORT`, och vilka
avsändare som får ange klientens IP med `FORWARDED_ALLOW_IPS` (se avsnitt 3).

Bygg och starta:

```bash
sudo docker compose -f docker-compose.standalone.yml up -d --build
curl -s http://127.0.0.1:8000/health      # {"status":"ok"}
```

Databasen skapas och migreras automatiskt vid första starten.

## 3. Reverse proxy

Appen lyssnar **bara** på `127.0.0.1` och ska alltid nås via proxyn —
publicera aldrig porten utåt.

Klientens IP (inloggningsspärren räknar per IP) läses ur proxyns
`X-Forwarded-For`. Appen litar bara på headern när den kommer från Dockers
interna nät, dit proxyn ansluter via port-vidarebefordran, och läser den
högerifrån. Det fungerar oavsett om proxyn skriver över headern eller lägger
till i den. Om accessloggen (`docker compose logs web`) visar samma
172.x-/192.168.x-adress för alla besökare använder er Docker andra nät; sätt
då `FORWARDED_ALLOW_IPS` i `.env` till nätets gateway, som
`docker network inspect teaball_default` visar.

Appen sätter själv sina säkerhetsheadrar (Content-Security-Policy,
X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Cache-Control på
sidor med bedömningar). Proxyn behöver bara lägga till **HSTS**.

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

Med flera organisationer på samma installation: hoppa över avsnitt 4 och 5
och följ avsnitt 10, där varje organisation skapas med sin första admin.

```bash
sudo docker compose -f docker-compose.standalone.yml exec web \
    python scripts/skapa_forvaltare.py stilla-lax
```

Lösenordet frågas efter interaktivt. Logga in på `/login`; resten av kontona
sköts under **Konton** i appen.

Fyll sedan i instansens texter under **Inställningar**: organisationen,
systemet som ersätts (används i förklaringen av statusen *utreds*, "Finns i
…"), personuppgiftsansvarig och kontaktväg för dataskyddsfrågor. Tomma fält
ger neutral text. Så länge personuppgiftsansvarig och kontaktväg saknas visar
integritetssidan en gul markering om att de ska fyllas i före skarp drift.
Läs igenom sidan (`/integritet`) innan ni öppnar tjänsten. Den säger till
exempel att tjänsten och säkerhetskopiorna driftas inom EU, och det måste
stämma för er. Roller och kontohantering beskrivs i
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
- **Instansens texter:** de ligger i databasen och följer med från den
  gamla instansen. Ändra organisation, nuvarande system,
  personuppgiftsansvarig och kontaktväg under **Inställningar**, så att
  `/integritet` och statusförklaringarna beskriver er och inte den gamla
  instansens ägare.

## 7. Backup

`scripts/backup.sh` tar en konsistent kopia även under drift, verifierar den
med `PRAGMA integrity_check`, kontrollerar ledigt utrymme och roterar (30
dagliga + 12 månatliga). Den behöver `sqlite3` eller `python3` på servern.

Kör den som uid 1505, samma användare som containern och ägaren till
datakatalogen — **inte som root**. Datakatalogen är skrivbar för containern,
och root ska inte öppna en databas som en komprometterad container har
kunnat preparera. Backupmålet ska därför ägas av 1505:

```bash
sudo install -d -o 1505 -g 1505 -m 700 /mnt/backup/teaball
```

Cron-exempel, i roots crontab (`setpriv` byter till uid 1505 före körningen):

```
10 3 * * * setpriv --reuid=1505 --regid=1505 --clear-groups /srv/teaball/scripts/backup.sh /srv/teaball/teaball-data/teaball.db /mnt/backup/teaball
```

Målet ska ligga på en annan disk eller server. Övervaka att kopiorna faktiskt
skrivs, och prova en återställning någon gång.

**Återställning:** stoppa appen, ta bort `teaball.db-wal`/`-shm` om de finns,
kopiera in backupfilen som `teaball-data/teaball.db` (ägare 1505, läge 600),
starta igen.

## 8. Uppgradera

```bash
cd /srv/teaball
sudo setpriv --reuid=1505 --regid=1505 --clear-groups scripts/backup.sh teaball-data/teaball.db /mnt/backup/teaball
sudo git pull --ff-only
sudo docker compose -f docker-compose.standalone.yml up -d --build
```

Väntande databasmigrationer körs vid start. Före dem tas automatiskt en
säkerhetskopia bredvid databasen (`teaball.fore-<version>-<tid>.db` i
`teaball-data/`); den roteras inte — ta bort den när uppgraderingen är
verifierad.

Med flera organisationer (avsnitt 10): kör `scripts/backup_alla.sh
teaball-data/organisationer /mnt/backup/teaball` i stället för `backup.sh`
på första raden. Kopiorna före migration hamnar då i
`teaball-data/organisationer/`, en per organisation.

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

## 10. Flera organisationer (förhandsversion)

En installation kan rymma flera organisationer med varsin databasfil. De
delar inga konton, medlemmar eller data, och var och en har sin egen admin
och sina egna texter under **Inställningar**.

Förhandsversion betyder: **ännu inte för skarp drift med flera
organisationer.** Se *Inte klart än* nedan.

- Sätt `ORGANISATIONER_DIR=/data/organisationer` i `.env` och starta om. Då
  används inte `DB_PATH`, och `PUBLIC_BASE_URL` behövs inte: svarslänkarna
  byggs på varje organisations egen adress. Kontrollera att en ny svarslänk
  börjar med `https://` (schemat kommer från proxyns `X-Forwarded-Proto`).
- Varje organisation är en fil `<hostnamn>.db` i katalogen, t.ex.
  `teaball.exempel.se.db`, med hostnamnet i gemener. Anropets `Host`-header
  avgör vilken som används, så proxyn måste skicka vidare det ursprungliga
  hostnamnet. Caddy gör det utan inställning; nginx behöver
  `proxy_set_header Host $host`. Ett okänt hostnamn får 404 och loggas som
  varning (`Okänt hostnamn`), så ett felstavat filnamn syns i loggen.
- En organisation har exakt ett hostnamn. Ska `www.`-varianten också
  fungera, låt proxyn omdirigera den. Byter en organisation hostnamn:
  byt namn på filen och skicka nya svarslänkar (som i avsnitt 6).
- Organisationerna hanteras med `scripts/organisationer.py` (lösenordet
  frågas efter interaktivt):

  ```bash
  sudo docker compose -f docker-compose.standalone.yml exec web \
      python scripts/organisationer.py skapa teaball.exempel.se stilla-lax
  sudo docker compose -f docker-compose.standalone.yml exec web \
      python scripts/organisationer.py lista
  sudo docker compose -f docker-compose.standalone.yml exec web \
      python scripts/organisationer.py ta-bort teaball.exempel.se --bekrafta teaball.exempel.se
  ```

  `skapa` gör databasen med organisationens första admin, och appen hittar
  den direkt utan omstart. Ge sedan hostnamnet DNS och TLS i proxyn. `lista`
  visar konton, medlemmar, noder och senaste inloggning per organisation.
  `skapa` skriver också ut en checklista att skicka till organisationens
  admin (byt lösenord, fyll i Inställningar, läs `/integritet`).

  **Ta bort en organisation:** ta först bort hostnamnet ur proxyn, så att
  inget anrop hinner skriva under tiden, och kör sedan `ta-bort`. Databasen
  och dess kopior före migration flyttas till `organisationer/borttagna/`,
  och adressen ger 404. Kvar finns då organisationens data på två ställen,
  som ska raderas när de inte längre behövs (t.ex. när data har lämnats
  tillbaka enligt biträdesavtalet): kopiorna i `borttagna/`, och
  organisationens katalog i backupmålet (`/mnt/backup/teaball/<hostnamn>/`),
  som inte längre roteras. `lista` påminner om kopiorna i `borttagna/`.
  Ångra en borttagning: kopiera tillbaka kopian som
  `organisationer/<hostnamn>.db` (ägare 1505, läge 600) och lägg tillbaka
  hostnamnet i proxyn.

  Övriga skript behöver `--db` med flera organisationer, även importen:
  `python scripts/importera_medlemmar.py medlemmar.csv --db /data/organisationer/teaball.exempel.se.db`.
- Instansens texter fylls aldrig från `.env` med flera organisationer; varje
  organisations admin anger dem under **Inställningar**.

**Flytta in en befintlig instans.** Slår du på `ORGANISATIONER_DIR` utan att
flytta databasen får den egna adressen 404. Stoppa appen, flytta filen och
starta igen:

```bash
sudo docker compose -f docker-compose.standalone.yml down
sudo install -d -o 1505 -g 1505 -m 700 teaball-data/organisationer
sudo mv teaball-data/teaball.db teaball-data/organisationer/teaball.exempel.se.db
sudo rm -f teaball-data/teaball.db-wal teaball-data/teaball.db-shm
sudo docker compose -f docker-compose.standalone.yml up -d
```

Ta en backup först (avsnitt 7). Medlemmarnas länkar fungerar som förut om
hostnamnet är detsamma, men alla som är inloggade får logga in igen.

**Backup:** `scripts/backup_alla.sh` kör `backup.sh` (avsnitt 7) för varje
organisation, med en egen underkatalog per organisation i målet. (Kör inte
`backup.sh` själv mot samma målkatalog för flera organisationer: kopiorna
heter alltid `teaball-<datum>.db` och skriver över varandra.) En
organisation som misslyckas stoppar inte de andra, men skriptet avslutas med
fel. Cron-exempel, med målet ägt av 1505 som i avsnitt 7:

```
10 3 * * * setpriv --reuid=1505 --regid=1505 --clear-groups /srv/teaball/scripts/backup_alla.sh /srv/teaball/teaball-data/organisationer /mnt/backup/teaball
```

**Återställning av en organisation.** Backuperna ligger i
`/mnt/backup/teaball/<hostnamn>/dagliga/teaball-<datum>.db` (och
`manatliga/`). Appen måste stoppas medan filen byts, och det tar ner alla
organisationer en kort stund:

```bash
sudo docker compose -f docker-compose.standalone.yml stop web
sudo rm -f teaball-data/organisationer/teaball.exempel.se.db-wal teaball-data/organisationer/teaball.exempel.se.db-shm
sudo install -o 1505 -g 1505 -m 600 /mnt/backup/teaball/teaball.exempel.se/dagliga/teaball-2026-11-12.db \
    teaball-data/organisationer/teaball.exempel.se.db
sudo docker compose -f docker-compose.standalone.yml start web
```

Starten migrerar filen om backupen har ett äldre schema.

**Inte klart än:**
- **Matomo:** statistiken är gemensam för alla organisationer, och
  integritetssidan beskriver den som organisationens egen. Lämna Matomo
  avstängt med flera organisationer.
- **Personuppgiftsbiträde:** driver ni Teaball åt andra organisationer är ni
  deras personuppgiftsbiträde och behöver ett biträdesavtal med var och en.
  Integritetssidan nämner ännu inte operatören.
- **Anubis:** en Anubis-instans tar ett hostnamn (`COOKIE_DOMAIN`), så flera
  organisationer bakom Anubis kräver en instans per hostnamn. Det är inte
  provat.
- En databasfil som kopieras in för hand (t.ex. en återställd backup med
  äldre schema) migreras först vid nästa omstart, så starta om efter en
  sådan. `lista` visar om någon väntar på migrering.
