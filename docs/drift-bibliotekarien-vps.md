# Drift på bibliotekarien-vps

Så drivs instansen på `teaball.bibliotekarien.se`. Den bygger på den delade
plattformen i `bibliotekarien-platform` (edge-Caddy, Anubis, Matomo,
övervakning) och är **inte** en installationsmall — för egen server, se
[INSTALL.md](../INSTALL.md).

Produktion körs med **`docker-compose.prod.yml`** enligt plattformens mönster
(se `bibliotekarien-platform/SERVER_LAYOUT.md`, som är källa-av-sanning):
stack `/opt/teaball/app`, service-användare `teaball` (UID 1505),
inga host-portar — edge-Caddy joinar `teaball_proxy` och proxar
`teaball.bibliotekarien.se` genom **Anubis** (PoW-gate för all trafik;
htmx-anropen bär clearance-cookien; Anubis standardpolicy enligt
plattformens `edge/ANUBIS.md`). Instansen körs med en databas per
organisation (`ORGANISATIONER_DIR`, INSTALL.md avsnitt 10), än så länge med
en enda: `organisationer/teaball.bibliotekarien.se.db` i named-volymen
`teaball-data`. Både edge-Caddy och Anubis skickar vidare anropets
`Host`-header oförändrad, och det är den som väljer databas. (Sätt aldrig
`TARGET_HOST` på Anubis: då får alla anrop samma hostnamn och svarar 404.)
Teaball är **stängd för sökmotorer** — `/robots.txt`
(serveras av appen) säger `Disallow: /`, eftersom allt utom inloggningen
kräver konto. uvicorns accesslogg är på, med medlemmarnas token maskade
(`app/accesslog.py`). Instansens texter ligger i databasen och ändras under
Inställningar i appen. `ROBOTSKYDD=1` står i `docker-compose.prod.yml`.

Driftsättningschecklista (första gången):

1. DNS: `teaball.bibliotekarien.se` → serverns IP.
2. Skapa service-användare: `useradd --system --uid 1505 --home-dir /opt/teaball --shell /usr/sbin/nologin teaball`.
   Den läggs **inte** i docker-gruppen (se "Root-ägd arbetskopia" nedan).
3. Klona repot till `/opt/teaball/app` som root (`sudo git clone`), med
   deploy-nyckeln via `core.sshCommand` i repots `.git/config`. Skapa `.env`
   från `.env.example` med `sudo install -m 600` (SECRET_KEY,
   ANUBIS_COOKIE_DOMAIN; Matomo-värdena nedan). Kör
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

## Flytt till en databas per organisation (en gång)

Fram till den deploy som för in `ORGANISATIONER_DIR` i
`docker-compose.prod.yml` låg databasen i `/data/teaball.db`. Den nya
compose-filen letar i `/data/organisationer/`, så filen ska flyttas dit
**innan** den nya koden startar. Annars svarar adressen 404 tills den
flyttats. Den nya backup-uniten kräver också att filen redan ligger där.

**Före:** deployen med instansinställningarna (migration 0010) ska redan
vara gjord i det gamla läget, så att Inställningar visar DiVA-texterna.
Med flera organisationer fylls texterna aldrig från miljön. Har den deployen
inte gjorts: fyll i Inställningar för hand efter flytten. Säg till
förvaltarna i förväg att de loggas ut. Medlemmarna klickar på sin länk igen.

```bash
cd /opt/teaball/app
D=/var/lib/docker/volumes/teaball_teaball-data/_data
sudo grep MATOMO_SITE_ID .env                    # anteckna site-id:t
sudo systemctl start teaball-backup.service      # färsk kopia, med den gamla uniten
sudo docker compose -f docker-compose.prod.yml stop web
sudo ls -l $D                                    # se nedan om -wal
sudo install -d -o teaball -g teaball -m 700 $D/organisationer
sudo mv $D/teaball.db $D/organisationer/teaball.bibliotekarien.se.db
sudo SKIP_BACKUP=1 /opt/teaball/app/scripts/deploy.sh
```

Efter en normal stängning finns ingen `teaball.db-wal`. Finns den ändå,
flytta den till `$D/organisationer/teaball.bibliotekarien.se.db-wal`: den
kan innehålla skrivningar som ännu inte nått databasfilen. En `-shm` kan
tas bort. `SKIP_BACKUP=1` behövs eftersom den gamla uniten pekar på den
flyttade filen; kopian togs två rader tidigare. Avbryts deploy.sh innan
`compose up` står appen stoppad. Flytta då tillbaka filen och kör
`sudo docker compose -f docker-compose.prod.yml start web`.

Byt sedan backup-uniten. De gamla kopiorna flyttas in under organisationen,
så att de fortsätter roteras:

```bash
sudo install -d -o teaball -g teaball -m 700 /opt/teaball/backups/teaball.bibliotekarien.se
sudo mv /opt/teaball/backups/dagliga /opt/teaball/backups/manatliga /opt/teaball/backups/teaball.bibliotekarien.se/
sudo cp /opt/teaball/app/deploy/teaball-backup.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start teaball-backup.service
journalctl -u teaball-backup.service -n 20       # "Backup klar för 1 organisationer."
```

Koppla Matomo-sajten (compose skickar inte längre `MATOMO_SITE_ID`, så
statistiken står still tills detta är gjort):

```bash
sudo docker compose -f docker-compose.prod.yml exec web python scripts/organisationer.py matomo teaball.bibliotekarien.se <site-id>
sudo docker compose -f docker-compose.prod.yml exec web python scripts/organisationer.py lista
```

**Kontrollera:**

- `https://teaball.bibliotekarien.se/login` visar inloggningen, inte
  ”Okänd adress”.
- Inloggningen fungerar, och Inställningar visar texterna och
  besöksstatistiken.
- En ny svarslänk börjar med `https://teaball.bibliotekarien.se/`.
- Nästa sidvisning syns i Matomo.

`MATOMO_SITE_ID` och `PUBLIC_BASE_URL` i `.env` läses inte längre och kan
tas bort. Kopiorna före migration (`$D/teaball.fore-*.db`) ligger kvar i
volymens rot. Appen hittar dem inte längre, och de raderas när de inte
längre behövs.

**Backa:** stoppa web, flytta tillbaka filen till `$D/teaball.db`, kör
`sudo git -C /opt/teaball/app reset --hard <commiten före>` och
`sudo docker compose -f docker-compose.prod.yml up -d --build`. Har uniten
bytts: lägg tillbaka den gamla med
`sudo git -C /opt/teaball/app show <commiten före>:deploy/teaball-backup.service`
till `/etc/systemd/system/`, kör `daemon-reload` och flytta tillbaka
backupkatalogerna.

**Fler organisationer på den här servern** kräver mer än ett nytt
hostnamn i edge-Caddy: Anubis `COOKIE_DOMAIN` gäller ett hostnamn, så
varje organisation behöver en egen Anubis-instans eller en gemensam
föräldradomän. Det är inte gjort.

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
