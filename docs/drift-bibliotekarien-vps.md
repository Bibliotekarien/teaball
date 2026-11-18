# Drift på bibliotekarien-vps

Så drivs instansen på `teaball.bibliotekarien.se`. Den bygger på den delade
plattformen i `bibliotekarien-platform` (edge-Caddy, Matomo,
övervakning) och är **inte** en installationsmall — för egen server, se
[INSTALL.md](../INSTALL.md).

Produktion körs med **`docker-compose.prod.yml`** enligt plattformens mönster
(se `bibliotekarien-platform/SERVER_LAYOUT.md`, som är källa-av-sanning):
stack `/opt/teaball/app`, service-användare `teaball` (UID 1505),
inga host-portar — edge-Caddy joinar `teaball_proxy` och proxar
`teaball.bibliotekarien.se` direkt till `teaball-web:8000`. Ingen Anubis,
med avsikt: det finns inget publikt innehåll att skydda, och inloggningen
har egen spärr (bakgrund i plattformens `edge/ANUBIS.md`). Instansen körs
med en databas per organisation (`ORGANISATIONER_DIR`, INSTALL.md avsnitt
10), än så länge med en enda: `organisationer/teaball.bibliotekarien.se.db`
i named-volymen `teaball-data`. Edge-Caddy skickar vidare anropets
`Host`-header oförändrad, och det är den som väljer databas.
Teaball är **stängd för sökmotorer** — `/robots.txt`
(serveras av appen) säger `Disallow: /`, eftersom allt utom inloggningen
kräver konto. uvicorns accesslogg är på, med medlemmarnas token maskade
(`app/accesslog.py`). Instansens texter ligger i databasen och ändras under
Inställningar i appen.

Driftsättningschecklista (första gången):

1. DNS: `teaball.bibliotekarien.se` → serverns IP.
2. Skapa service-användare: `useradd --system --uid 1505 --home-dir /opt/teaball --shell /usr/sbin/nologin teaball`.
   Den läggs **inte** i docker-gruppen (se "Root-ägd arbetskopia" nedan).
3. Klona repot till `/opt/teaball/app` som root (`sudo git clone`), med
   deploy-nyckeln via `core.sshCommand` i repots `.git/config`. Skapa `.env`
   från `.env.example` med `sudo install -m 600` (SECRET_KEY,
   Matomo-värdena nedan). Kör
   `sudo chmod -R go-w /opt/teaball/app` och `sudo restorecon -R
   /opt/teaball/app`.
4. **Matomo:** registrera sajten på `https://bibstats.bibliotekarien.se`
   (Administration → Websites → Manage → Add a new website, URL
   `https://teaball.bibliotekarien.se`) och sätt
   `MATOMO_URL=https://bibstats.bibliotekarien.se` och `MATOMO_TOKEN` i
   `.env`. Sajtens id kopplas till organisationen i steg 7. Trackingen sker
   **server-side** (Tracking HTTP API) — ingen matomo.js i klienten, DNT/GPC
   respekteras, `/svara/<token>` maskas.
5. `sudo SKIP_BACKUP=1 /opt/teaball/app/scripts/deploy.sh` (skapar nätet;
   `SKIP_BACKUP=1` bara denna första gång — backup-uniten kommer i steg 6 och
   databasen är ännu tom), därefter
   `make -C /opt/bibliotekarien-platform edge-recreate` (Caddy joinar nätet).
6. Systemd: `sudo cp deploy/teaball.service deploy/teaball-backup.{service,timer} /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now teaball.service teaball-backup.timer`.
7. Skapa organisationen med sin första admin och koppla Matomo-sajten
   (`docker compose -f docker-compose.prod.yml exec web python
   scripts/organisationer.py skapa teaball.bibliotekarien.se <användarnamn>`,
   sedan `... matomo teaball.bibliotekarien.se <site-id>`; INSTALL.md avsnitt
   10). Läs in underlag med `--db
   /data/organisationer/teaball.bibliotekarien.se.db` (se
   [README](../README.md#skapa-förvaltarkonton)).
8. Observability: avkommentera `teaball.bibliotekarien.se`-proben i
   `observability-platform/stack/prometheus/prometheus.yml` (avsiktligt
   utkommenterad tills sajten är live — inga röda prober i förväg).

## Byte till drift utan Anubis (en gång, 2026-11)

Edge måste sluta peka på `teaball-anubis` **innan** containern försvinner,
annars svarar sajten 502 tills edge laddats om. Ordning:

1. Merga Bibliotekarien/bibliotekarien-platform#95 (edge pekar på
   `teaball-web:8000`), dra hem den i `/opt/bibliotekarien-platform`, kopiera
   `SERVER_LAYOUT.md` till `/opt` enligt filens huvud och kör
   `make -C /opt/bibliotekarien-platform edge-validate`, sedan `edge-reload`.
   Nu går trafiken förbi Anubis fast containern kör kvar.
2. Kontrollera i en webbläsare att sajten svarar utan utmaningssida och att
   inloggning och en svarslänk fungerar.
3. Merga teaball#100 och kör `sudo /opt/teaball/app/scripts/deploy.sh`.
4. Kontrollera att `teaball-anubis` är borta: `sudo docker ps -a --filter
   name=teaball-anubis`. Den här första gången finns den troligen kvar.
   Skriptet uppdaterar sig självt med `git merge` medan det kör, och bash
   läser vidare i den gamla versionen, som saknar `--remove-orphans`. Kör då
   `sudo docker rm -f teaball-anubis`, eller deploya en gång till.
5. Ta bort `ANUBIS_COOKIE_DOMAIN` ur `/opt/teaball/app/.env`. Den läses inte
   längre, så det brådskar inte.

Backa i omvänd ordning, annars pekar edge på en container som inte finns
och sajten svarar 502:

1. Revertera teaball#100 och lägg tillbaka `ANUBIS_COOKIE_DOMAIN` i `.env`
   om steg 5 är gjort. Den gamla compose-filen vägrar starta utan den.
2. Deploya. Anubis-imagen hämtas igen.
3. Revertera Bibliotekarien/bibliotekarien-platform#95, `edge-validate`,
   `edge-reload`.

## Flytt till en databas per organisation (en gång)

Fram till den deploy som för in `ORGANISATIONER_DIR` i
`docker-compose.prod.yml` låg databasen i `/data/teaball.db`. Den nya
compose-filen letar i `/data/organisationer/`, så filen ska flyttas dit
**innan** den nya koden startar. Den nya backup-uniten kräver också att
filen redan ligger där. Imagen byggs medan den gamla appen kör, så
tjänsten är bara nere medan filen flyttas: 1–2 minuter. Gör hela
körplanen i ett pass, dagtid: nattens backup (02:50 UTC) misslyckas om den
hamnar mitt i.

Adressen, datan, svarslänkarna och Inställningar är desamma efteråt. Det
enda användarna märker är att inloggade förvaltare får logga in en gång
till, och att medlemmar som har sidan öppen öppnar sin länk igen. Sessionen
binds nu till organisationen, och gamla sessioner saknar den bindningen.

**Före**

0. **Bytet till drift utan Anubis är genomfört** (avsnittet ovan): edge
   pekar på `teaball-web:8000` och `teaball-anubis` är borta. teaball#100
   ligger redan på main, så den första deployen i steg 1 tar bort Anubis
   oavsett. Är edge inte omladdad då svarar sajten 502.
1. **#90–#93 är deployade och kontrollerade.** Merga och deploya dem som
   vanligt, i det gamla läget. Öppna sedan Inställningar och **fyll i det
   som saknas nu, före flytten**. Organisation (DiVA-konsortiet) och
   nuvarande system (DiVA Classic) har fyllts från compose-filen vid första
   starten. Personuppgiftsansvarig och dataskyddskontakt är tomma i
   produktion och ska fyllas i för hand. Kontrollera att `/integritet` visar
   dem utan gul markering. Efter flytten fylls texterna aldrig från miljön,
   så det som står i Inställningar då är det som gäller.
2. **Merga #94 först när körplanen ska köras direkt efteråt.** Kör inte
   `deploy.sh` eller plattformens `deploy-all` däremellan, och säg till dem
   som kan köra `deploy-all` att låta bli under flytten. Den nya koden
   hittar ingen fil, och alla sidor svarar 404 (”Okänd adress”). `/health`
   och Prometheus-proben förblir ändå gröna, så inget larmar.
3. **Säg till i förväg.** Välj en tid utan pågående svarsomgång. Tjänsten
   är nere 1–2 minuter. Förslag till förvaltare och medlemmar:

   > Teaball är nere en kort stund [datum, tid]. Efteråt behöver förvaltare
   > logga in igen, och medlemmar öppnar sin personliga länk igen. Länken är
   > densamma. Spara text du håller på att skriva innan dess.

   Integritetssidans text om besöksstatistik ändras till ”hos den som
   driftar tjänsten, i en egen sajt”. Meddela den personuppgiftsansvarige.

**Förbered, medan den gamla appen kör.** Hämta den nya koden och bygg
imagen. Den körande containern påverkas inte: den har sin konfiguration
och sin image sedan den startades. Den gamla backup-uniten i
`/etc/systemd/system` fungerar också, eftersom `backup.sh` är oförändrad.
Den gamla imagen sparas under ett eget namn, så att det går fort att backa:

```bash
cd /opt/teaball/app
D=/var/lib/docker/volumes/teaball_teaball-data/_data
sudo git rev-parse HEAD                          # anteckna: commiten att backa till
sudo grep '^MATOMO_SITE_ID=' .env                # anteckna: kopplas till organisationen nedan
sudo docker tag teaball:latest teaball:fore-flytt
sudo git fetch origin
sudo git log -1 --format='%h %s' origin/main     # ska vara mergen av #94
sudo git merge --ff-only origin/main
sudo docker compose -f docker-compose.prod.yml build --pull
```

Från och med `git merge` ligger den nya compose-filen i arbetskopian. Kör
inget `compose up`, `deploy.sh` eller `systemctl restart teaball` förrän
filen är flyttad, och starta inte om servern: då startar den nya koden utan
fil, och alla sidor svarar 404.

**Flytten (nedtid, 1–2 minuter).** Stoppa appen och ta en kopia av exakt
den fil som ska flyttas, med den gamla uniten. Kopian sparas också under
ett eget namn, eftersom nästa backup samma dag skriver över dagens fil:

```bash
sudo docker compose -f docker-compose.prod.yml stop web
sudo systemctl start teaball-backup.service
sudo cp -p /opt/teaball/backups/dagliga/teaball-$(date +%F).db /opt/teaball/backups/fore-flytt.db
```

Flytta filen. Efter en normal stängning finns ingen `teaball.db-wal`. Finns
den ändå, flyttas den med av tredje raden, eftersom den kan innehålla
skrivningar som inte nått databasfilen. En `-shm` återskapas av SQLite:

```bash
sudo install -d -o teaball -g teaball -m 700 $D/organisationer
sudo mv $D/teaball.db $D/organisationer/teaball.bibliotekarien.se.db
sudo test ! -e $D/teaball.db-wal || sudo mv $D/teaball.db-wal $D/organisationer/teaball.bibliotekarien.se.db-wal
sudo rm -f $D/teaball.db-shm
sudo ls -lZ $D $D/organisationer                 # samma ägare och SELinux-etikett som förut
```

Har `organisationer/` en annan SELinux-etikett än `$D`, ge den samma:
`sudo chcon -R --reference=$D $D/organisationer`. Annars kan containern
inte läsa filen och alla sidor ger fel.

Koppla Matomo-sajten med site-id:t som `grep` skrev ut, innan appen
startar. Compose skickar inte längre `MATOMO_SITE_ID`, så annars går
sidvisningarna förlorade tills det är gjort. Starta sedan appen, utan att
bygga:

```bash
sudo docker compose -f docker-compose.prod.yml run --rm --no-deps web python scripts/organisationer.py matomo teaball.bibliotekarien.se <site-id>
sudo docker compose -f docker-compose.prod.yml up -d --remove-orphans
sudo docker compose -f docker-compose.prod.yml ps   # web ska bli healthy
```

Nu är tjänsten uppe igen. Går något fel i det här steget: följ *Backa*
nedan.

**Byt backup-uniten**, medan appen kör. De gamla kopiorna flyttas in under
organisationen, så att de fortsätter att roteras:

```bash
sudo install -d -o teaball -g teaball -m 700 /opt/teaball/backups/teaball.bibliotekarien.se
sudo mv /opt/teaball/backups/dagliga /opt/teaball/backups/manatliga /opt/teaball/backups/teaball.bibliotekarien.se/
sudo cp /opt/teaball/app/deploy/teaball-backup.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start teaball-backup.service
journalctl -u teaball-backup.service -n 20       # "Backup klar för 1 organisationer."
sudo docker compose -f docker-compose.prod.yml exec web python scripts/organisationer.py lista
```

**Kontrollera:**

- `https://teaball.bibliotekarien.se/login` visar inloggningen, inte
  ”Okänd adress”.
- Inloggningen fungerar, och Inställningar visar texterna och
  besöksstatistiken.
- `/integritet` beskriver statistiken som insamlad hos den som driftar
  tjänsten.
- En ny svarslänk börjar med `https://teaball.bibliotekarien.se/`. Att
  skapa en ny länk gör medlemmens gamla länk ogiltig, så prova med en
  tillfällig testmedlem (lägg till under Medlemmar, skapa länken, öppna den,
  ta bort medlemmen), aldrig med en riktig medlem.
- Nästa sidvisning syns i Matomo.

**Efteråt**, när ni har bestämt att inte backa (senast efter 30 dagar,
samma tid som de dagliga kopiorna sparas):

- Ta bort `MATOMO_SITE_ID`, `PUBLIC_BASE_URL` och eventuella textvariabler
  ur `.env`. De läses inte längre, men den gamla compose-filen kräver
  `PUBLIC_BASE_URL`, så de ska stå kvar så länge man kan behöva backa.
- Radera kopiorna med personuppgifter som appen och backupen inte längre
  ser, och den gamla imagen (i ett nytt skal finns inte `D` kvar):

  ```bash
  D=/var/lib/docker/volumes/teaball_teaball-data/_data
  sudo rm $D/teaball.fore-*.db /opt/teaball/backups/fore-flytt.db
  sudo docker image rm teaball:fore-flytt
  ```

**Backa.** Ersätt `<commit>` med den som antecknades. Den gamla imagen
läggs tillbaka under sitt vanliga namn, så inget behöver byggas:

```bash
cd /opt/teaball/app
D=/var/lib/docker/volumes/teaball_teaball-data/_data
sudo docker compose -f docker-compose.prod.yml stop web
sudo test ! -e $D/organisationer/teaball.bibliotekarien.se.db || sudo mv $D/organisationer/teaball.bibliotekarien.se.db $D/teaball.db
sudo test ! -e $D/organisationer/teaball.bibliotekarien.se.db-wal || sudo mv $D/organisationer/teaball.bibliotekarien.se.db-wal $D/teaball.db-wal
sudo rm -f $D/organisationer/teaball.bibliotekarien.se.db-shm
sudo git reset --hard <commit>
sudo docker tag teaball:fore-flytt teaball:latest
sudo docker compose -f docker-compose.prod.yml up -d
```

Backar man efter att appen har kört i det nya läget går inget förlorat:
filen flyttas tillbaka med det som skrivits sedan dess. Förvaltarna får
logga in en gång till.

Har backup-uniten redan bytts, lägg tillbaka den gamla (arbetskopian har
den efter `reset`) och backupkatalogerna:

```bash
sudo cp /opt/teaball/app/deploy/teaball-backup.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo mv /opt/teaball/backups/teaball.bibliotekarien.se/dagliga /opt/teaball/backups/teaball.bibliotekarien.se/manatliga /opt/teaball/backups/
```

Kör sedan inte `deploy.sh` eller `deploy-all` förrän #94 är revertad på
main eller felet är rättat. Annars drar nästa deploy in den nya
compose-filen igen, utan att filen flyttats. Revertera också
Bibliotekarien/bibliotekarien-platform#92 (`SERVER_LAYOUT.md`) och kopiera
filen till `/opt` igen, så att den beskriver det gamla läget.

## Fler organisationer på den här servern

1. DNS för hostnamnet till serverns IP.
2. Hostnamnet på teaball-blockets site-rad i plattformens
   `edge/caddy/Caddyfile`, sedan `edge-validate` och `edge-reload`.
3. `organisationer.py skapa <hostnamn> <användarnamn>` och vid behov
   `organisationer.py matomo <hostnamn> <site-id>` (INSTALL.md avsnitt 10).
4. En rad i `CHATBOT_SITES` i plattformens `matomo/.env`.
5. En blackbox-prob i observability-platform mot `https://<hostnamn>/login`,
   inte `/health`: `/health` svarar för alla hostnamn och är grön även när
   organisationens databas saknas.

Ingen Anubis att ordna (se ovan).

## Backup

`teaball-backup.timer` kör `scripts/backup_alla.sh` varje natt (unit + timer i
`deploy/`) mot organisationskatalogen i volymen under
`/var/lib/docker/volumes/`, till `/opt/teaball/backups/<hostnamn>/`. Jobbet kör som `teaball` (uid 1505), inte root,
med `CAP_DAC_READ_SEARCH` för att nå in i `/var/lib/docker` och skrivrätt
bara till målet och datakatalogen (se kommentaren i uniten).
`/opt/teaball/backups` måste därför ägas av `teaball`.

**En gång, när uniten byts från root till teaball.** deploy.sh installerar
inga units, så den deploy som för in den nya uniten går igenom med den gamla
(root-)uniten som redan ligger i `/etc/systemd/system`. Gör stegen nedan
direkt efter den deployen. Ägarbytet måste komma före kopieringen av uniten,
annars fallerar nattens backup och nästa deploy avbryts:

```bash
sudo install -d -o teaball -g teaball -m 700 /opt/teaball/backups
sudo chown -R teaball:teaball /opt/teaball/backups
sudo cp /opt/teaball/app/deploy/teaball-backup.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start teaball-backup.service
journalctl -u teaball-backup.service -n 20    # "Backup klar: …"
``` `scripts/deploy.sh` startar samma unit innan den rör
arbetskopian — ingen kodändring driftsätts utan en färsk, verifierad kopia.
Misslyckas kopian avbryts deployen. Kontrollera läget med
`systemctl list-timers teaball-backup.timer` och
`journalctl -u teaball-backup.service -n 20`.

## Root-ägd arbetskopia

Arbetskopian `/opt/teaball/app` ägs av root, och `scripts/deploy.sh` kör
git och compose som root. `teaball` är bara ett namn på uid 1505 och
sitter inte i docker-gruppen. Tidigare ägde `teaball` kopian och satt i
gruppen, och då fanns två vägar till root:

- **docker-gruppen är root.** Den som kan prata med docker-socketen kan
  starta en container som monterar `/`.
- **root körde filer som teaball kunde skriva:** deploy.sh (via sudo) och
  backup.sh (`teaball-backup.service` kör som root).
- **teaball ägde `/opt/teaball`** och kunde därmed byta ut hela arbetskopian
  (`mv app x; mkdir app`), skript och allt.

deploy.sh vägrar köra om `/opt/teaball` inte är root-ägd och skrivskyddad,
om `app` är en symlänk, eller om något i kopian ägs av någon annan än root
eller är skrivbart för grupp eller andra. Samma ändring gjordes först i
mark-rounding (#47); se Risk 1 i bibliotekarien-platform
`SECURITY_REVIEW.md`.

**Flytta en befintlig server** (en gång; den nya deploy.sh vägrar köra
innan). Första raden ska skriva ut ett `ssh -i …deploy_key`-kommando; är den
tom, stanna. `-f` läser filen direkt — git som root ignorerar annars repots
config så länge någon annan äger det, och svarar då tomt fast nyckeln finns.

```bash
sudo git config -f /opt/teaball/app/.git/config --get core.sshCommand
sudo chown root:root /opt/teaball    # inte -R: bara katalogen själv
sudo chmod 755 /opt/teaball
sudo chown -R root:root /opt/teaball/app /opt/teaball/.ssh
sudo git -C /opt/teaball/app pull --ff-only
sudo chmod -R go-w /opt/teaball/app
sudo chmod 600 /opt/teaball/app/.env
sudo restorecon -R /opt/teaball/app
sudo gpasswd -d teaball docker
sudo cp /opt/teaball/app/deploy/teaball.service /etc/systemd/system/
sudo systemctl daemon-reload
```

Kontrollera sedan med `id teaball` (ingen docker) och en vanlig deploy.
