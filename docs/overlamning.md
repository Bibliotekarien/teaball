# Överlämning till en mottagande organisation

Så lämnas Teaball över från drift på bibliotekarien-vps till en annan
organisation, som sedan driver tjänsten på egen server. Dokumentet gäller
själva överlämningen: vad som måste vara klart innan, hur datan flyttas,
vad som försvinner med plattformen och vem som ansvarar för vad efteråt.

Hur man sätter upp en installation står i [INSTALL.md](../INSTALL.md). Hur
vår drift fungerar står i [drift-bibliotekarien-vps.md](drift-bibliotekarien-vps.md).
Här hänvisas till båda i stället för att upprepa dem.

**Ord som används:** *vi* är den som driftar i dag (bibliotekarien-vps).
*Mottagaren* är organisationen som tar över driften. En *organisation* är en
databas på installationen (INSTALL.md avsnitt 10), i dag bara
`teaball.bibliotekarien.se`.

## 1. Blockerare

Inget av detta är kod. Det ska vara klart innan datan flyttas.

- **Biträdesavtal.** Fortsätter vi att drifta någon organisation åt någon
  annan, även tillfälligt under flytten, är vi deras personuppgiftsbiträde.
  Det kräver ett biträdesavtal med var och en. Driftar mottagaren bara sin
  egen organisation behövs inget avtal mellan oss efter flytten. Däremot
  behövs en överenskommelse om hur länge vi behåller kopior (avsnitt 5).
- **Driftaren på integritetssidan.** Med fler än en organisation på samma
  installation nämner integritetssidan driftaren som personuppgiftsbiträde,
  och `DRIFTARE`/`DRIFTARE_KONTAKT` i `.env` måste vara satta (#105). Så
  länge de saknas visar sidan en gul markering. Mottagaren sätter sina egna
  värden, eller lämnar dem tomma om installationen bara har en organisation.
- **Integritetssidans texter.** Personuppgiftsansvarig, kontaktväg,
  rättslig grund, var uppgifterna lagras och gallring ligger i databasen och
  följer med. Mottagaren går igenom dem under **Inställningar** och ändrar
  det som inte stämmer för dem, särskilt lagringsplatsen, som beskriver vår
  drift.
- **Personuppgiftsansvar.** Det ska vara klart vem som är
  personuppgiftsansvarig efter flytten och att medlemmarna får veta det.
  Integritetssidan ska säga det från första dagen på den nya servern.

## 2. Flytt mellan servrar

En organisation flyttas som en fil. INSTALL.md avsnitt 6 beskriver det
generellt. Här är stegen för en flytt från bibliotekarien-vps. Gör gärna en
generalrepetition med en färsk kopia först och kasta sedan provdatabasen.

**Versioner.** Mottagaren kör samma eller nyare commit av koden. Nyare kod
migrerar databasen vid start, men äldre kod mot en nyare databas stöds inte.

**Hos oss** (bibliotekarien-vps):

```bash
cd /opt/teaball/app
sudo systemctl start teaball-backup.service                  # färsk, verifierad kopia före stoppet
sudo docker compose -f docker-compose.prod.yml stop web      # inga fler skrivningar
sudo systemctl start teaball-backup.service                  # kopian efter stoppet är den som flyttas
ls -l /opt/teaball/backups/teaball.bibliotekarien.se/dagliga/
sha256sum /opt/teaball/backups/teaball.bibliotekarien.se/dagliga/teaball-<datum>.db
```

Backup-uniten fungerar även när `web` är stoppad. Den andra körningen skriver
över dagens kopia med en som tagits efter stoppet. Filen innehåller
bedömningar och kommentarer: för över den krypterat (scp eller sftp), aldrig
med e-post eller en öppen delningstjänst.

**Hos mottagaren** (installation enligt INSTALL.md avsnitt 2–4, appen stoppad):

- **En organisation på servern:** lägg filen som `teaball-data/teaball.db`
  (INSTALL.md avsnitt 6).
- **Flera organisationer:** lägg den som
  `teaball-data/organisationer/<hostnamn>.db` (INSTALL.md avsnitt 10).

```bash
sha256sum teaball-<datum>.db                                  # jämför med vår summa
sudo install -o 1505 -g 1505 -m 600 teaball-<datum>.db teaball-data/teaball.db
sudo docker compose -f docker-compose.standalone.yml start web
```

Ta bort eventuella `-wal`/`-shm` från en provdatabas innan filen läggs dit.
Starten migrerar databasen om den har ett äldre schema och tar då en kopia
först.

**Adress och svarslänkar.** Det finns två fall.

- **Hostnamnet följer med** (DNS för `teaball.bibliotekarien.se` pekas om
  till mottagarens server): medlemmarnas länkar fungerar som förut. Sänk
  DNS-postens TTL några dagar före flytten. Caddy hos mottagaren hämtar
  certifikatet när namnet pekar dit. Vi tar bort namnet ur vår edge (avsnitt
  5) först när DNS har bytts, så att ingen träffar en tom adress hos oss.
- **Mottagaren använder ett eget hostnamn:** länkarna innehåller den gamla
  adressen och slutar fungera. Skapa **ny länk** för varje medlem under
  **Medlemmar** och skicka ut dem (INSTALL.md avsnitt 6, "Efter
  övertagandet"). Svaren finns kvar, bara länken byts.

**I båda fallen:**
- Alla sessioner slutar gälla, eftersom mottagaren har en egen `SECRET_KEY`.
  Förvaltare loggar in igen, och medlemmar öppnar sin länk igen.
- Förvaltarkontona följer med i databasen. Mottagaren loggar in med ett
  admin-konto som skapats åt dem före flytten och tar bort de konton som
  inte ska följa med, under **Konton**.

**Kontroll hos mottagaren:**
- inloggning, behovsträdet, bedömningarna, analysen och svarsläget
- exporterna, inklusive PDF-rapporten, och roadmapen
- en svarslänk med en tillfällig testmedlem, som tas bort efteråt

## 3. Det som försvinner med plattformen

På bibliotekarien-vps lutar Teaball sig mot den delade plattformen
(`bibliotekarien-platform` och `observability-platform`). Inget av det
följer med. Mottagaren behöver något i stället:

| Hos oss | Vad det gör | Hos mottagaren |
|---|---|---|
| **Edge-Caddy** | TLS, HSTS och proxy till `teaball-web:8000` | Egen proxy, INSTALL.md avsnitt 3. Appen sätter sina övriga säkerhetsheadrar själv. |
| **Edge-loggarna och säkerhetsloggen** | Accessloggar med `/svara/<token>` maskat | Proxyns egen logg maskar inte token av sig själv. Maska, stäng av, eller behandla loggen som lika känslig som databasen (INSTALL.md, "Proxyloggarna innehåller hemliga länkar"). |
| **Matomo på bibstats** | Server-side besöksstatistik per organisation | Egen Matomo med IP-anonymisering (INSTALL.md avsnitt 9 och 10), eller ingen alls. Utan `MATOMO_URL` säger integritetssidan att ingen statistik samlas in. |
| **Blackbox-prober** (observability-platform) | Larm när `/login` slutar svara | Egen övervakning mot `https://<hostnamn>/login`, inte `/health`, som svarar även när proxyn är fel. |
| **Loki och Grafana** | Samlade loggar och larm | `docker compose logs web` och journalen, eller mottagarens egen loggplattform. |
| **`deploy.sh`** | Ägarkontroll, backup före deploy och fast-forward | Uppgradering enligt INSTALL.md avsnitt 8. `deploy.sh` är skriven för vår server (`/opt/teaball`, root-ägd arbetskopia) och kan användas som förlaga. |
| **Backup-uniten** (`deploy/teaball-backup.*`) | Nattlig, verifierad kopia och kopia före varje deploy | Cron enligt INSTALL.md avsnitt 7, mot ett mål på en annan disk eller server. |

## 4. Ansvar efter överlämningen

| Område | Ansvarig efter överlämningen |
|---|---|
| Drift: server, Docker, proxy, TLS, DNS | Mottagaren |
| Säkerhetsuppdateringar av OS och Docker | Mottagaren |
| Uppgraderingar av Teaball (`git pull`, ombyggd image) | Mottagaren |
| Backup, övervakning av att den körs, och återläsningsprov minst en gång per halvår | Mottagaren |
| Personuppgiftsansvar och integritetssidan | Mottagarens personuppgiftsansvarige |
| Konton, medlemmar och svarslänkar | Mottagarens förvaltare (admin i appen) |
| Repot, CI och Dependabot | Överenskommes (se nedan) |
| Kopior hos oss efter flytten | Vi, tills de raderats enligt avsnitt 5 |

**Repot.** `Bibliotekarien/teaball` är publikt och har sin CI i repot:
tester, coverage, hemlighetssökning, beroendegranskning, SBOM och
Dependabot. Det finns två vägar:

- **Repot flyttas** (GitHub: Settings → Transfer) till mottagarens
  organisation. CI, issues och historik följer med. Dependabot-PR:er går
  då till mottagaren.
- **Mottagaren forkar** och driver sin kopia. Vi slutar då ta emot PR:er
  i vårt repo eller arkiverar det, och mottagaren slår på Dependabot och
  Actions i sin fork.

Oavsett väg ska mottagaren ha minst en person som granskar och mergar
Dependabot-PR:er. Bilderna i `Dockerfile` är pinnade på digest och uppdateras
bara genom dem.

## 5. Checklista

| # | Steg | Vem |
|---|---|---|
| 1 | Överenskommelse om personuppgiftsansvar, eventuella biträdesavtal och hur länge vi behåller kopior (avsnitt 1) | Båda |
| 2 | Bestäm om hostnamnet följer med eller byts, och om repot flyttas eller forkas | Båda |
| 3 | Installation hos mottagaren enligt INSTALL.md avsnitt 2–4: server, proxy, `.env`, backup, övervakning | Mottagaren |
| 4 | Admin-konto åt mottagaren i den befintliga organisationen | Vi |
| 5 | Generalrepetition med en färsk kopia, sedan kastas provdatabasen | Båda |
| 6 | Meddela förvaltare och medlemmar tidpunkten, och att alla loggar in igen | Mottagaren |
| 7 | Sänk DNS-postens TTL, om hostnamnet följer med | Vi |
| 8 | Stoppa, ta kopia, checksumma, överför krypterat (avsnitt 2) | Vi |
| 9 | Lägg in filen, starta, kontrollera (avsnitt 2) | Mottagaren |
| 10 | Peka om DNS, eller skapa nya svarslänkar och skicka ut dem | Vi respektive mottagaren |
| 11 | Gå igenom Inställningar och integritetssidan, och ta bort konton som inte ska följa med | Mottagaren |
| 12 | Repot: flytta eller forka, och slå på Dependabot och Actions | Båda |
| 13 | Städning hos oss (nedan), när mottagaren bekräftat att allt fungerar | Vi |

**Städning hos oss** (steg 13), i den här ordningen:

1. **Edge:** ta bort hostnamnet ur teaball-blockets site-rad i plattformens
   `edge/caddy/Caddyfile`, sedan `edge-validate` och `edge-reload`. Görs
   när DNS har bytts, om namnet följer med.
2. **Prob:** ta bort blackbox-proben i observability-platform, så att den
   inte larmar.
3. **Matomo:** ta bort sajten på bibstats och raden i `CHATBOT_SITES` i
   plattformens `matomo/.env`.
4. **Data:**
   - Stoppa stacken.
   - Radera organisationens databas och kopiorna före migration ur volymen
     (`organisationer.py ta-bort` flyttar dem till `borttagna/`, som sedan
     raderas).
   - Radera `/opt/teaball/backups/<hostnamn>/`.
   - Radera eventuella överförda filer. Vänta med det sista tills den tid
     som överenskommits i steg 1 har gått.
5. **Stacken:**
   - Är det den sista organisationen: stäng av `teaball-backup.timer` och
     `teaball.service`, ta bort stacken och volymen.
   - Ta bort Teaball ur plattformens `SERVER_LAYOUT.md` och uid 1505 ur
     tilldelningen.
6. **DNS:** ta bort namnet om det inte följde med.

Skriv ned när varje del av datan raderades. Det är underlaget om någon
frågar vart deras uppgifter tog vägen.
