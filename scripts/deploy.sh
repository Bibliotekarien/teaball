#!/bin/bash
# Deploy för Teaball på bibliotekarien-vps (markrounding-mönstret).
#
# Kör som root (eller via sudo); växlar internt till service-användaren.
# Flöde: git pull --ff-only → docker compose build → up -d → status.
#
# Flaggor:
#   --check / --dry-run   Validera utan att applicera något
#   -h / --help           Visa denna hjälptext
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/teaball/app}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
SERVICE_USER="${SERVICE_USER:-teaball}"
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

echo "==> Hämtar senaste koden"
run_as "git pull --ff-only"

if [[ $CHECK_ONLY -eq 1 ]]; then
  echo "==> Dry-run: validerar compose-konfigurationen"
  run_as "docker compose -f '$COMPOSE_FILE' config >/dev/null && echo 'compose config OK'"
  exit 0
fi

echo "==> Bygger imagen"
run_as "docker compose -f '$COMPOSE_FILE' build --pull"

echo "==> Startar stacken"
run_as "docker compose -f '$COMPOSE_FILE' up -d"

echo "==> Status"
run_as "docker compose -f '$COMPOSE_FILE' ps"

echo
echo "Klart. Första gången: kör även edge-recreate så Caddy joinar teaball_proxy:"
echo "  make -C /opt/bibliotekarien-platform edge-recreate"
