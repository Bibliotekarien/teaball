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
har egen spärr (bakgrund i plattformens `edge/ANUBIS.md`). Databasen ligger i named-volymen
`teaball-data`. Teaball är **stängd för sökmotorer** — `/robots.txt`
(serveras av appen) säger `Disallow: /`, eftersom allt utom inloggningen
kräver konto. uvicorns accesslogg är på, med medlemmarnas token maskade
(`app/accesslog.py`). Instansens texter ligger i databasen och ändras under
Inställningar i appen. `docker-compose.prod.yml` har `ORGANISATION=DiVA-konsortiet`
och `NUVARANDE_SYSTEM=DiVA Classic` som standard; de fyller databasen en gång,
vid första start efter migration 0010, och läses sedan inte. **Ta bort dem ur
`docker-compose.prod.yml` efter den deployen** — tills dess loggar appen vid
varje start att de ignoreras.

Driftsättningschecklista (första gången):

1. DNS: `teaball.bibliotekarien.se` → serverns IP.
2. Skapa service-användare: `useradd --system --uid 1505 --home-dir /opt/teaball --shell /usr/sbin/nologin teaball`.
   Den läggs **inte** i docker-gruppen (se "Root-ägd arbetskopia" nedan).
3. Klona repot till `/opt/teaball/app` som root (`sudo git clone`), med
   deploy-nyckeln via `core.sshCommand` i repots `.git/config`. Skapa `.env`
   från `.env.example` med `sudo install -m 600` (SECRET_KEY,
   PUBLIC_BASE_URL; Matomo-värdena nedan). Kör
   `sudo chmod -R go-w /opt/teaball/app` och `sudo restorecon -R
   /opt/teaball/app`.
4. **Matomo:** registrera sajten på `https://bibstats.bibliotekarien.se`
   (Administration → Websites → Manage → Add a new website, URL
   `https://teaball.bibliotekarien.se`) och sätt
   `MATOMO_URL=https://bibstats.bibliotekarien.se`, `MATOMO_SITE_ID` och
   `MATOMO_TOKEN` i `.env`. Trackingen sker **server-side** (Tracking HTTP API)
   — ingen matomo.js i klienten, DNT/GPC respekteras, `/svara/<token>` maskas.
5. `sudo SKIP_BACKUP=1 /opt/teaball/app/scripts/deploy.sh` (skapar nätet;
   `SKIP_BACKUP=1` bara denna första gång — backup-uniten kommer i steg 6 och
   databasen är ännu tom), därefter
   `make -C /opt/bibliotekarien-platform edge-recreate` (Caddy joinar nätet).
6. Systemd: `sudo cp deploy/teaball.service deploy/teaball-backup.{service,timer} /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now teaball.service teaball-backup.timer`.
7. Skapa förvaltarkonton + läs in underlag (se
   [README](../README.md#skapa-förvaltarkonton), med
   `docker compose -f docker-compose.prod.yml exec web ...`).
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

## Backup

`teaball-backup.timer` kör `scripts/backup.sh` varje natt (unit + timer i
`deploy/`) mot volymen under `/var/lib/docker/volumes/`, till
`/opt/teaball/backups`. Jobbet kör som `teaball` (uid 1505), inte root,
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
