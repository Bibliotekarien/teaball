#!/bin/bash
# Deploy för Teaball på bibliotekarien-vps (markrounding-mönstret).
#
# Kör som root (eller via sudo). git och docker körs som root, och
# arbetskopian ska vara root-ägd och bara skrivbar för root.
# Flöde: ägarkontroll → fetch → [ev. signaturkontroll] → backup → ff-only
# merge → build → up -d → status.
#
# Varför root och inte service-användaren: root kör filer ur arbetskopian
# (det här skriptet, backup.sh via timern, compose-filen). Ägde teaball dem
# kunde den användaren skriva kod som root sedan körde. Därför ska teaball
# inte heller sitta i docker-gruppen, som är root i praktiken
# (SECURITY_REVIEW.md Risk 1 i bibliotekarien-platform; piloten var
# mark-rounding#47).
#
# En komprometterad remote är root på en delad VPS, så fetch är skild från
# utcheckningen och målcommiten visas innan den appliceras (ff-only). Det här
# repot saknar ännu nyckelinfrastruktur och driftsätts osignerat
# (REQUIRE_SIGNED=0 som standard) — slå på signaturkravet så snart releaser
# taggas signerat (git tag -s + GIT_REF=v1.x + REQUIRE_SIGNED=1).
#
# Ingen kod ändras i drift utan en färsk, verifierad databaskopia: innan
# arbetskopian rörs startas samma systemd-unit som nattens backup, så kopian
# hamnar där de andra ligger och roteras med dem. Databasen bär inrapporterad
# data som inte kan återskapas, och nattens kopia kan vara ett dygn gammal.
#
# Miljövariabler:
#   GIT_REMOTE       Remote att hämta från (default: origin)
#   GIT_REF          Tagg (helst signerad) eller gren att driftsätta (default: main)
#   REQUIRE_SIGNED   1 = kräv giltig GPG-signatur på commiten/taggen. Default 0
#                    för det här repot tills signerade releaser finns på plats.
#   BACKUP_UNIT      Systemd-unit som tar databaskopian (default:
#                    teaball-backup.service, se deploy/).
#   SKIP_BACKUP      1 = driftsätt utan kopia. Bara för första bring-up, när
#                    uniten inte är installerad och databasen ännu är tom.
#
# Flaggor:
#   --check / --dry-run   Hämta + ev. signaturkontroll + kolla att backup-uniten
#                         finns, men applicera inget
#   -h / --help           Visa denna hjälptext
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/teaball/app}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
GIT_REMOTE="${GIT_REMOTE:-origin}"
GIT_REF="${GIT_REF:-main}"
REQUIRE_SIGNED="${REQUIRE_SIGNED:-0}"
BACKUP_UNIT="${BACKUP_UNIT:-teaball-backup.service}"
SKIP_BACKUP="${SKIP_BACKUP:-0}"
CHECK_ONLY=0

for arg in "$@"; do
  case "$arg" in
    --check|--dry-run) CHECK_ONLY=1 ;;
    -h|--help) sed -n '2,/^set -e/p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *) echo "Okänd flagga: $arg" >&2; exit 2 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "Detta skript måste köras som root (eller via sudo)." >&2
  exit 1
fi

# Vägra köra om någon annan än root kan skriva i arbetskopian. Annars kör
# root kod som en mindre privilegierad användare har kunnat ändra.
# Symlänkar har alltid 777 och hoppas över; det som räknas är målet.
# `|| true`: när head slutar läsa får find SIGPIPE, och med pipefail hade
# skriptet då dött tyst här i stället för att säga vad som är fel.
osakra=$(find "$APP_DIR" ! -type l \( ! -user root -o -perm /022 \) -print | head -5 || true)
if [[ -n "$osakra" ]]; then
  echo "Arbetskopian $APP_DIR är inte root-ägd och skrivskyddad för andra, t.ex.:" >&2
  echo "$osakra" >&2
  echo "Rätta enligt README, \"Root-ägd arbetskopia\":" >&2
  echo "  chown -R root:root $APP_DIR && chmod -R go-w $APP_DIR" >&2
  exit 1
fi

if [[ ! -f "$APP_DIR/.env" ]]; then
  echo "VARNING: $APP_DIR/.env saknas — compose kommer vägra starta utan secrets." >&2
fi

cd "$APP_DIR"
compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

echo "==> Hämtar $GIT_REMOTE/$GIT_REF (utan att röra arbetskopian)"
git fetch --quiet --tags "$GIT_REMOTE"

# En signerad tagg vinner över grenens spets; peela taggen till sin commit.
MAL="$(git rev-parse --verify --quiet "refs/tags/$GIT_REF^{commit}" \
       || git rev-parse --verify "$GIT_REMOTE/$GIT_REF")"
if [[ -z "$MAL" ]]; then
  echo "Hittar varken taggen eller grenen '$GIT_REF' på $GIT_REMOTE." >&2
  exit 1
fi
echo "    mål: $(git --no-pager log -1 --format='%h  %an  %s' "$MAL")"

if [[ "$REQUIRE_SIGNED" == "1" ]]; then
  echo "==> Verifierar GPG-signatur"
  if ! git verify-tag "$GIT_REF" &>/dev/null \
     && ! git verify-commit "$MAL" &>/dev/null; then
    echo "AVBRYTER: '$GIT_REF' ($MAL) saknar giltig GPG-signatur." >&2
    echo "Signera releasen (git tag -s), importera driftnyckeln i roots" >&2
    echo "nyckelring, eller sätt REQUIRE_SIGNED=0 om du medvetet litar på remoten." >&2
    exit 1
  fi
fi

backup_unit_finns() { systemctl cat "$BACKUP_UNIT" &>/dev/null; }

if [[ $CHECK_ONLY -eq 1 ]]; then
  echo "==> Dry-run: validerar compose-konfigurationen"
  compose config >/dev/null && echo 'compose config OK'
  if backup_unit_finns; then
    echo "    backup-unit $BACKUP_UNIT: finns"
  else
    echo "    backup-unit $BACKUP_UNIT: SAKNAS — en skarp körning avbryts utan SKIP_BACKUP=1"
  fi
  exit 0
fi

# Samma unit som nattens backup: en enda sanning om databasens och kopiornas
# sökvägar, och journalen som logg. Skriptet bakom tar en konsistent kopia via
# backup-API:t, integritetskontrollerar den och skriver dagens fil — två
# deployer samma dag lämnar bara den senare kopian, men nattens ligger kvar
# under sitt eget datum. systemctl start på en oneshot väntar tills jobbet är
# klart och misslyckas om skriptet gör det, så ett fel stoppar deployen innan
# någon kod rörts.
if [[ "$SKIP_BACKUP" == "1" ]]; then
  echo "==> Hoppar över databaskopian (SKIP_BACKUP=1)"
elif ! backup_unit_finns; then
  echo "AVBRYTER: backup-uniten '$BACKUP_UNIT' finns inte — ingen kopia före deploy." >&2
  echo "Installera deploy/teaball-backup.{service,timer} (README, systemd-steget)," >&2
  echo "eller sätt SKIP_BACKUP=1 vid första bring-up medan databasen ännu är tom." >&2
  exit 1
else
  echo "==> Tar en verifierad databaskopia ($BACKUP_UNIT)"
  backup_start="$(date '+%Y-%m-%d %H:%M:%S')"
  if ! systemctl start "$BACKUP_UNIT"; then
    echo "AVBRYTER: databaskopian misslyckades — ingen kod ändras utan färsk kopia." >&2
    journalctl -u "$BACKUP_UNIT" --since "$backup_start" -o cat >&2 || true
    exit 1
  fi
  journalctl -u "$BACKUP_UNIT" --since "$backup_start" -o cat | sed 's/^/    /' || true
fi

echo "==> Uppdaterar arbetskopian till $MAL (fast-forward)"
git merge --ff-only "$MAL"

echo "==> Bygger imagen"
compose build --pull

echo "==> Startar stacken"
compose up -d

echo "==> Status"
compose ps

echo
echo "Klart. Första gången: kör även edge-recreate så Caddy joinar teaball_proxy:"
echo "  make -C /opt/bibliotekarien-platform edge-recreate"
