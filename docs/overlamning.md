# Överlämning till en mottagande organisation

Så lämnas Teaball över från drift på bibliotekarien-vps till en annan
organisation, som sedan driver tjänsten på egen server. Dokumentet gäller
själva överlämningen: vad som måste vara klart innan, hur datan flyttas,
vad som försvinner med plattformen, vem som ansvarar för vad efteråt och
hur vi städar.

Hur man sätter upp en installation står i [INSTALL.md](../INSTALL.md). Hur
vår drift fungerar står i [drift-bibliotekarien-vps.md](drift-bibliotekarien-vps.md).
Här hänvisas till båda i stället för att upprepa dem.

**Ord som används:**
- *Vi* är den som driftar i dag, på bibliotekarien-vps.
- *Mottagaren* är den organisation som tar över driften.
- *Organisation (databas)* är en databasfil på installationen (INSTALL.md
  avsnitt 10). I dag finns en: `teaball.bibliotekarien.se`.

**Förutsättning:** stegen nedan gäller en installation med en enda
organisation (databas), som vår. Har den fler när överlämningen görs:
`web` får inte stoppas, eftersom det tar ner alla. Ta i stället bort
hostnamnet ur edge, ta en backup och kör `organisationer.py ta-bort` medan
`web` kör (INSTALL.md avsnitt 10, *Ta bort en organisation*). Hoppa över
de steg i städningen som gäller hela stacken.

## 1. Blockerare och beslut

Inget av detta är kod. Det ska vara klart innan datan flyttas.

- **Avtal.** Det ska vara klart vem som är personuppgiftsansvarig efter
  flytten. Fortsätter vi att drifta någon organisation (databas) åt någon
  annan, även tillfälligt, är vi deras personuppgiftsbiträde. Då krävs ett
  biträdesavtal. Avtalet ska också omfatta generalrepetitionen, eftersom
  den skickar riktiga personuppgifter till mottagaren.
- **Integritetssidan.** Personuppgiftsansvarig, kontaktväg, rättslig grund,
  var uppgifterna lagras och gallring ligger i databasen och följer med
  (#115). Mottagaren går igenom dem under **Inställningar** och ändrar det
  som inte stämmer, särskilt lagringsplatsen, som beskriver vår drift. Två
  meningar står fast i sidans mall och går inte att ändra där:
  - att säkerhetskopior lagras med rullande gallring
  - beskrivningen av vilka uppgifter som behandlas

  Stämmer de inte för mottagaren får de ändra mallen. Har mottagaren fler
  än en organisation (databas) ska `DRIFTARE` och `DRIFTARE_KONTAKT` sättas
  i deras `.env`, annars visar sidan en gul markering.
- **Medlemmarnas kontaktuppgifter.** Teaball lagrar bara medlemsorganisationens
  namn, inte vem som ska ha länken. Kontaktlistan lämnas över separat, eller
  finns redan hos mottagaren. Den behövs för att meddela tidpunkten och, om
  hostnamnet byts, för att skicka nya länkar.
- **Beslut som ska fattas, och skrivas ned:**
  - **Adressen** (avsnitt 2): följer `teaball.bibliotekarien.se` med, byts
    den, eller omdirigerar vi den under en period?
  - **DNS-posten:** följer namnet med ligger posten kvar i vår zon. Vi är
    då ansvariga för den, och mottagaren ska meddela oss före ett byte av
    IP-adress. Bestäm ett datum då mottagaren byter till ett eget namn,
    så att ett namn under vår domän inte pekar på någon annans server på
    obestämd tid.
  - **Hur länge vi behåller kopior** efter flytten innan de raderas.
  - **Backuphistoriken:** följer de 30 dagliga och 12 månatliga kopiorna
    med, eller bara den senaste?
  - **Repot:** flyttas eller forkas (avsnitt 4).
  - **Hur ofta mottagaren provar en återläsning.**

## 2. Flytt mellan servrar

En organisation (databas) flyttas som en fil. INSTALL.md avsnitt 6
beskriver det generellt. Här är stegen från bibliotekarien-vps. Gör gärna
en generalrepetition med en färsk kopia först och kasta sedan provdatabasen.

**Versioner.** Mottagaren kör samma eller nyare commit av koden. Nyare kod
migrerar databasen vid start, men äldre kod mot en nyare databas stöds inte.

**Före.**
- Välj en tid utan pågående svarsomgång och säg till förvaltare och
  medlemmar i förväg. Driftdokumentets *Flytt till en databas per
  organisation*, punkt 3 under *Före*, har ett förslag till meddelande.
- Säg till den som tar emot larmen, och till dem som kan köra plattformens
  `deploy-all`, att låta bli under flytten.
- Ta bort våra egna förvaltarkonton under **Konton**, utom mottagarens
  admin. Konton följer annars med i databasen, med användarnamn och
  lösenordshash.
- Skapa ett admin-konto åt mottagaren och lämna lösenordet i en annan
  kanal än filen. Mottagaren byter det vid första inloggningen.
- Skapa en mellanplats för filen som bara du kan läsa:
  `sudo install -d -m 700 -o "$USER" ~/overlamning`.

**Hos oss** (bibliotekarien-vps):

```bash
cd /opt/teaball/app
sudo systemctl disable teaball.service                       # en omstart ska inte starta appen igen
sudo docker compose -f docker-compose.prod.yml stop web      # inga fler skrivningar
sudo systemctl start teaball-backup.service                  # verifierad kopia efter stoppet
sudo ls -l /opt/teaball/backups/teaball.bibliotekarien.se/dagliga/
sudo install -m 600 -o "$USER" /opt/teaball/backups/teaball.bibliotekarien.se/dagliga/teaball-<datum>.db ~/overlamning/
sha256sum ~/overlamning/teaball-<datum>.db
```

Kör inte `deploy.sh` och starta inte `web` igen förrän städningen. Annars
kan medlemmar som fortfarande når oss skriva svar som aldrig följer med.
Backup-uniten fungerar med `web` stoppad.

För över filen direkt till mottagarens server, krypterat (scp eller sftp).
Använd aldrig e-post eller en öppen delningstjänst. Går den via någon
annans dator är det ytterligare en kopia att radera, och den ska skrivas
ned.

**Hos mottagaren.** Installation enligt INSTALL.md avsnitt 2, 3, 7 och 9,
med en **egen** `SECRET_KEY`. Kopiera aldrig vår `.env`: den innehåller vår
nyckel och vår Matomo-token. Hoppa över avsnitt 4, eftersom kontona finns i
databasen.

En organisation på servern, med appen stoppad:

```bash
sudo docker compose -f docker-compose.standalone.yml stop web
sha256sum teaball-<datum>.db                                  # jämför med vår summa
sudo rm -f teaball-data/teaball.db teaball-data/teaball.db-wal teaball-data/teaball.db-shm   # en provdatabas
sudo install -o 1505 -g 1505 -m 600 teaball-<datum>.db teaball-data/teaball.db
ls -Z teaball-data teaball-data/teaball.db                    # med SELinux: samma etikett
sudo docker compose -f docker-compose.standalone.yml start web
rm teaball-<datum>.db
```

- **Fler organisationer (databaser) hos mottagaren:** lägg filen som
  `teaball-data/organisationer/<hostnamn>.db`, där `<hostnamn>` är det namn
  den ska ha hos mottagaren. Följ INSTALL.md avsnitt 10, som skapar
  katalogen och startar med `up -d`.
- **Matomo:** sajtens id följer med i databasen, och med flera
  organisationer (databaser) används det. Koppla mottagarens egen sajt med
  `organisationer.py matomo <hostnamn> <site-id>`, eller stäng av med
  `organisationer.py matomo <hostnamn>`. Annars rapporterar den till den
  sajt hos mottagaren som råkar ha vårt id. Med en organisation används
  `MATOMO_SITE_ID` i `.env`, och då spelar det ingen roll.
- **SELinux:** visar `ls -Z` olika etiketter kan containern inte läsa
  filen. Rätta med `sudo chcon --reference teaball-data teaball-data/teaball.db`.

Starten migrerar databasen om den har ett äldre schema och tar då en kopia
först (`teaball.fore-*.db`). Radera den när allt är kontrollerat.

**Adress och svarslänkar.** Token i länken hashas utan `SECRET_KEY` och
fungerar på vilken adress som helst där samma databas finns. Det som
slutar fungera är adressen. Det finns tre fall:

- **Hostnamnet följer med** (DNS för `teaball.bibliotekarien.se` pekas om
  till mottagaren):
  - Länkarna fungerar som förut.
  - Sänk DNS-postens TTL några dagar före flytten.
  - Mottagarens Caddy hämtar certifikatet när namnet pekar dit.
  - Vi tar bort namnet ur vår edge först när DNS har bytts.
- **Vi omdirigerar under en period** till mottagarens adress, med sökvägen
  kvar:
  - Länkarna fungerar via omdirigeringen.
  - Vi behåller DNS-posten och en rad i edge under perioden. Edge-loggarna
    maskar token.
  - Under tiden skickar mottagaren ut nya länkar i lugn takt.
- **Ett nytt hostnamn utan omdirigering:**
  - Länkarna slutar fungera.
  - Skapa en **ny länk** för varje medlem under **Medlemmar** och skicka ut
    den (INSTALL.md avsnitt 6, "Efter övertagandet").
  - Svaren finns kvar, bara länken byts.

I alla fallen slutar sessionerna gälla, eftersom mottagaren har en egen
`SECRET_KEY`. Förvaltare loggar in igen. Medlemmar öppnar sin länk igen, och
inloggningssidan säger åt dem att göra det.

**Kontroll hos mottagaren.** Före DNS-bytet svarar namnet fortfarande hos
oss, och Caddy hos mottagaren har inget certifikat. Testa därför direkt mot
mottagarens server, till exempel med en rad i `/etc/hosts` på den egna
datorn och en tillfällig adress, eller `curl --resolve <hostnamn>:443:<ip>`.
Med flera organisationer (databaser) väljer `Host` vilken databas som
används, så testet måste skicka rätt namn. Alternativet är att kontrollera
direkt efter DNS-bytet och räkna med att tjänsten är nere tills dess.

Kontrollera:
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
| **Maskning i edge-loggarna** | `/svara/<token>` maskas i accessloggarna | Proxyns egen logg maskar inte token av sig själv. Maska, stäng av, eller behandla loggen som lika känslig som databasen (INSTALL.md, "Proxyloggarna innehåller hemliga länkar"). |
| **Matomo på bibstats** | Server-side besöksstatistik | Egen Matomo med IP-anonymisering (INSTALL.md avsnitt 9 och 10), eller ingen alls. Utan `MATOMO_URL` säger integritetssidan att ingen statistik samlas in. |
| **Blackbox-prober** (observability-platform) | Larm när `/login` slutar svara | Egen övervakning mot `https://<hostnamn>/login`. `/health` räcker inte: den svarar för alla hostnamn, även när databasen saknas. |
| **Loki och Grafana** | Samlade loggar och larm | `docker compose logs web` och journalen, eller mottagarens egen loggplattform. |
| **`deploy.sh`** | Ägarkontroll, backup före deploy och fast-forward | Uppgradering enligt INSTALL.md avsnitt 8. `deploy.sh` är skriven för vår server (`/opt/teaball`, root-ägd arbetskopia) och kan användas som förlaga. |
| **Backup-uniten** (`deploy/teaball-backup.*`) | Nattlig, verifierad kopia och kopia före varje deploy | Cron enligt INSTALL.md avsnitt 7, eller avsnitt 10 med flera organisationer (databaser), mot ett mål på en annan disk eller server. |

## 4. Ansvar efter överlämningen

| Område | Ansvarig efter överlämningen |
|---|---|
| Drift: server, Docker, proxy och TLS | Mottagaren |
| DNS-posten, om namnet under bibliotekarien.se följer med | Vi, fram till det överenskomna datumet. Mottagaren meddelar oss före ett IP-byte. |
| Säkerhetsuppdateringar av OS och Docker | Mottagaren |
| Uppgraderingar av Teaball (`git pull`, ombyggd image) | Mottagaren |
| Backup, övervakning av att den körs, och återläsningsprov | Mottagaren |
| Personuppgiftsansvar och integritetssidan | Mottagarens personuppgiftsansvarige |
| Konton, medlemmar och svarslänkar | Mottagarens förvaltare (admin i appen) |
| Repot, CI och Dependabot | Enligt beslutet i avsnitt 1 (se nedan) |
| Kopior och loggar hos oss efter flytten | Vi, tills de raderats enligt avsnitt 5 |

**Repot.** `Bibliotekarien/teaball` är publikt och har sin CI i repot:
tester, coverage, hemlighetssökning, beroendegranskning, SBOM och
Dependabot. Det finns två vägar:

- **Repot flyttas** (GitHub: Settings → Transfer) till mottagarens
  organisation. CI, issues och historik följer med. Deploy-nycklar och
  webhooks följer också med. Ta därför bort vår deploy-nyckel (Settings →
  Deploy keys) och granska webhooks **före** flytten. Flytta repot först
  när vår server är städad (avsnitt 5): efter flytten pekar
  `Bibliotekarien/teaball` på ett repo som någon annan styr, och `deploy.sh`
  kör som root.
- **Mottagaren forkar** och driver sin kopia, med Dependabot och Actions
  påslagna i forken. Vi arkiverar vårt repo när servern är städad.

Oavsett väg ska mottagaren ha minst en person som granskar och mergar
Dependabot-PR:er. Bilderna i `Dockerfile` är pinnade på digest och uppdateras
bara genom dem.

## 5. Checklista

| # | Steg | Vem |
|---|---|---|
| 1 | Avtal och besluten i avsnitt 1, nedskrivna | Båda |
| 2 | Installation hos mottagaren (avsnitt 2, *Hos mottagaren*), backup och övervakning | Mottagaren |
| 3 | Kontaktlistan för medlemmarna finns hos mottagaren | Båda |
| 4 | Ta bort våra förvaltarkonton och skapa mottagarens admin (avsnitt 2, *Före*) | Vi |
| 5 | Generalrepetition med en färsk kopia och kontroll, sedan kastas provdatabasen | Båda |
| 6 | Meddela förvaltare och medlemmar tidpunkten | Mottagaren |
| 7 | Sänk DNS-postens TTL, om namnet följer med | Vi |
| 8 | Stoppa, ta kopia, checksumma, för över krypterat (avsnitt 2) | Vi |
| 9 | Lägg in filen, starta, kontrollera direkt mot servern (avsnitt 2) | Mottagaren |
| 10 | Peka om DNS, sätt upp omdirigeringen, eller skapa och skicka nya svarslänkar | Vi respektive mottagaren |
| 11 | Inställningar, integritetssidan och Matomo-sajten hos mottagaren; radera överförd fil och `teaball.fore-*.db` | Mottagaren |
| 12 | Städning hos oss (nedan), när mottagaren bekräftat att allt fungerar | Vi |
| 13 | Repot: ta bort deploy-nyckeln, flytta eller forka, slå på Dependabot och Actions | Båda |

**Städning hos oss** (steg 12), i den här ordningen. Skriv ned datum för
varje punkt som rör data.

1. **Edge.** Plattformen har ingen avvecklingsrutin för en app. Att bara ta
   bort hostnamnet räcker inte: med ett enda namn blir site-raden tom och
   Caddyfilen ogiltig. Edge refererar till Teaball på flera ställen:
   - teaball-blocket i `edge/caddy/Caddyfile`
   - loggarna `http.log.access.teaball` och `http.log.error.teaball` i de
     globala inställningarna
   - `import chatbot teaball`
   - nätet `teaball_proxy` som externt nät i `edge/docker-compose.yml`
   - `teaball.service` i `Wants=` och `After=` i `systemd/edge.service`

   Tas stacken och nätet bort före edge startar inte edge-Caddy vid nästa
   `edge-recreate` eller omstart av servern, och då går alla sajter ner.
   Ta bort alla referenserna, kör `edge-validate` och sedan
   `edge-recreate`, inte bara `edge-reload`. Följer namnet med görs det när
   DNS har bytts. Vid omdirigering görs det när perioden är slut. Ett
   issue i bibliotekarien-platform om en avvecklingsrutin vore bättre än
   att ha stegen här.
2. **Prob:** ta bort blackbox-proben i observability-platform.
3. **Matomo:** ta bort sajten på bibstats och raden i `CHATBOT_SITES` i
   plattformens `matomo/.env`. Spärra `MATOMO_TOKEN` om ingen annan app
   använder den användaren. Bestäm om sajtens historik ska exporteras till
   mottagaren eller raderas.
4. **Data:**
   - Stoppa och ta bort stacken och volymen
     (`sudo docker compose -f docker-compose.prod.yml down -v`). Det tar
     också bort `teaball.fore-*.db` i volymen.
   - Radera hela `/opt/teaball/backups`, inklusive `fore-flytt.db` från
     flytten till en databas per organisation, om den finns kvar. Vänta
     med det tills den överenskomna tiden har gått.
   - Ta bort imagen `teaball:fore-flytt`, om den finns kvar.
   - Radera `~/overlamning` och varje annan mellanplats filen passerat.
   - Kontrollera att inget är kvar:
     `sudo find /opt /var/lib/docker/volumes /home /root /tmp -name '*teaball*.db*'`.
5. **Loggar:**
   - Appens audit-logg (kontonamn och medlemsnamn) och accessloggar med
     IP-adresser finns i Loki tills de roteras bort.
   - Edge-säkerhetsloggen med klient-IP sparas i 365 dygn i
     `/var/log/edge-sakerhet/`, med kopia på Storage Box (plattformens
     `SERVER_LAYOUT.md` och `LOGGNING.md`).

   Antingen låter vi dem åldras ut och skriver ned när det sker, eller så
   raderar vi Teaballs rader. Det beslutet hör till överenskommelsen i steg
   1. Audit-historiken följer inte med till mottagaren.
6. **Hemligheter och konton på servern:**
   - Radera `/opt/teaball`, med `.env` (`SECRET_KEY`, `MATOMO_TOKEN`) och
     deploy-nyckeln.
   - Ta bort `teaball.service` och `teaball-backup.{service,timer}` ur
     `/etc/systemd/system/` och kör `daemon-reload`.
   - `sudo userdel teaball`.
   - Ta bort Teaball och uid 1505 ur plattformens `SERVER_LAYOUT.md`.
7. **DNS:** ta bort namnet om det inte följde med. Följde det med tas det
   bort det överenskomna datumet.

Skriv ned när varje del av datan raderades. Det är underlaget om någon
frågar vart deras uppgifter tog vägen.
