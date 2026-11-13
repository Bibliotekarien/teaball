#!/usr/bin/env bash
# Backup av alla organisationer på en installation med flera organisationer
# (INSTALL.md avsnitt 10). Kör backup.sh för varje <hostnamn>.db i
# organisationskatalogen, med en egen målkatalog per organisation: backup.sh
# döper alltid kopian till teaball-<datum>.db, så en gemensam målkatalog hade
# fått organisationerna att skriva över varandra.
#
# Användning:
#   scripts/backup_alla.sh <organisationskatalog> <målkatalog>
#
# Kör som uid 1505, som backup.sh. Målkatalogen ska ägas av 1505; underkatalogerna
# skapas av skriptet. Cron-exempel (dagligen 03:10, i roots crontab):
#   10 3 * * * setpriv --reuid=1505 --regid=1505 --clear-groups /srv/teaball/scripts/backup_alla.sh /srv/teaball/teaball-data/organisationer /mnt/backup/teaball
#
# En organisation som misslyckas stoppar inte de andra; skriptet avslutas
# ändå med fel så att cron/övervakningen märker det.
set -uo pipefail

KATALOG="${1:?Användning: backup_alla.sh <organisationskatalog> <målkatalog>}"
MAL="${2:?Användning: backup_alla.sh <organisationskatalog> <målkatalog>}"
BACKUP="$(dirname "$0")/backup.sh"

[ -d "$KATALOG" ] || { echo "Katalogen $KATALOG finns inte." >&2; exit 1; }
shopt -s nullglob

antal=0
misslyckade=()
for fil in "$KATALOG"/*.db; do
  namn="$(basename "$fil" .db)"
  # Kopiorna före migration (app/db.py) är inga organisationer.
  case "$namn" in
    *.fore-[0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z) continue ;;
  esac
  antal=$((antal + 1))
  "$BACKUP" "$fil" "$MAL/$namn" || misslyckade+=("$namn")
done

if [ "$antal" -eq 0 ]; then
  echo "Inga organisationer i $KATALOG — ingen backup tagen." >&2
  exit 1
fi
if [ "${#misslyckade[@]}" -gt 0 ]; then
  echo "Backup misslyckades för: ${misslyckade[*]}" >&2
  exit 1
fi
echo "Backup klar för $antal organisationer."
