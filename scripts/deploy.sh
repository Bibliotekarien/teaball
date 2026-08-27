#!/bin/bash
# Deploy för Teaball på bibliotekarien-vps (markrounding-mönstret).
#
# Kör som root (eller via sudo); växlar internt till service-användaren.
# Flöde: fetch → [ev. signaturkontroll] → ff-only merge → build → up -d → status.
#
# En komprometterad remote är root på en delad VPS, så fetch är skild från
# utcheckningen och målcommiten visas innan den appliceras (ff-only). Det här
# repot saknar ännu nyckelinfrastruktur och driftsätts osignerat
# (REQUIRE_SIGNED=0 som standard) — slå på signaturkravet så snart releaser
# taggas signerat (git tag -s + GIT_REF=v1.x + REQUIRE_SIGNED=1).
#
# Miljövariabler:
#   GIT_REMOTE       Remote att hämta från (default: origin)
#   GIT_REF          Tagg (helst signerad) eller gren att driftsätta (default: main)
#   REQUIRE_SIGNED   1 = kräv giltig GPG-signatur på commiten/taggen. Default 0
#                    för det här repot tills signerade releaser finns på plats.
#
# Flaggor:
#   --check / --dry-run   Hämta + ev. signaturkontroll, men applicera inget
#   -h / --help           Visa denna hjälptext
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/teaball/app}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
SERVICE_USER="${SERVICE_USER:-teaball}"
GIT_REMOTE="${GIT_REMOTE:-origin}"
GIT_REF="${GIT_REF:-main}"
REQUIRE_SIGNED="${REQUIRE_SIGNED:-0}"
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

if ! id "$SERVICE_USER" &>/dev/null; then
  echo "Service-användaren '$SERVICE_USER' finns inte. Skapa med:" >&2
  echo "  useradd --system --uid 1505 --home-dir /opt/teaball --shell /usr/sbin/nologin $SERVICE_USER" >&2
  echo "  usermod -aG docker $SERVICE_USER" >&2
  exit 1
fi

if [[ ! -f "$APP_DIR/.env" ]]; then
  echo "VARNING: $APP_DIR/.env saknas — compose kommer vägra starta utan secrets." >&2
fi

run_as() { sudo -u "$SERVICE_USER" -H bash -c "cd '$APP_DIR' && $*"; }

echo "==> Hämtar $GIT_REMOTE/$GIT_REF (utan att röra arbetskopian)"
run_as "git fetch --quiet --tags '$GIT_REMOTE'"

# En signerad tagg vinner över grenens spets; peela taggen till sin commit.
MAL="$(run_as "git rev-parse --verify --quiet 'refs/tags/$GIT_REF^{commit}' \
       || git rev-parse --verify '$GIT_REMOTE/$GIT_REF'")"
if [[ -z "$MAL" ]]; then
  echo "Hittar varken taggen eller grenen '$GIT_REF' på $GIT_REMOTE." >&2
  exit 1
fi
echo "    mål: $(run_as "git --no-pager log -1 --format='%h  %an  %s' '$MAL'")"

if [[ "$REQUIRE_SIGNED" == "1" ]]; then
  echo "==> Verifierar GPG-signatur"
  if ! run_as "git verify-tag '$GIT_REF'" &>/dev/null \
     && ! run_as "git verify-commit '$MAL'" &>/dev/null; then
    echo "AVBRYTER: '$GIT_REF' ($MAL) saknar giltig GPG-signatur." >&2
    echo "Signera releasen (git tag -s), importera driftnyckeln i $SERVICE_USER:s" >&2
    echo "nyckelring, eller sätt REQUIRE_SIGNED=0 om du medvetet litar på remoten." >&2
    exit 1
  fi
fi

if [[ $CHECK_ONLY -eq 1 ]]; then
  echo "==> Dry-run: validerar compose-konfigurationen"
  run_as "docker compose -f '$COMPOSE_FILE' config >/dev/null && echo 'compose config OK'"
  exit 0
fi

echo "==> Uppdaterar arbetskopian till $MAL (fast-forward)"
run_as "git merge --ff-only '$MAL'"

echo "==> Bygger imagen"
run_as "docker compose -f '$COMPOSE_FILE' build --pull"

echo "==> Startar stacken"
run_as "docker compose -f '$COMPOSE_FILE' up -d"

echo "==> Status"
run_as "docker compose -f '$COMPOSE_FILE' ps"

echo
echo "Klart. Första gången: kör även edge-recreate så Caddy joinar teaball_proxy:"
echo "  make -C /opt/bibliotekarien-platform edge-recreate"
