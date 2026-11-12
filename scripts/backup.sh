#!/usr/bin/env bash
# Säker ögonblickskopia av SQLite-databasen, även under drift (spec I4).
# ".backup" tar en konsistent kopia via SQLite:s backup-API.
#
# Användning:
#   scripts/backup.sh <dbfil> <målkatalog>
#
# Målkatalogen förutsätts vara en separat montering (t.ex. CIFS) — aldrig samma
# katalog som databasfilen. Rotation: 30 dagliga + 12 månatliga kopior behålls.
#
# Kör som databasens ägare (uid 1505 i containeruppsättningarna), inte som
# root. Cron-exempel (dagligen 03:10, i roots crontab):
#   10 3 * * * setpriv --reuid=1505 --regid=1505 --clear-groups /srv/teaball/scripts/backup.sh /srv/teaball/teaball-data/teaball.db /mnt/backup/teaball
set -euo pipefail

DBFIL="${1:?Användning: backup.sh <dbfil> <målkatalog>}"
MAL="${2:?Användning: backup.sh <dbfil> <målkatalog>}"
MINSTA_FRIA_MB="${MINSTA_FRIA_MB:-200}"

[ -f "$DBFIL" ] || { echo "Databasfilen $DBFIL finns inte." >&2; exit 1; }
mkdir -p "$MAL/dagliga" "$MAL/manatliga"

# Kontrollera ledigt utrymme på målet innan skrivning.
fria_mb=$(df -Pm "$MAL" | awk 'NR==2 {print $4}')
if [ "$fria_mb" -lt "$MINSTA_FRIA_MB" ]; then
  echo "För lite ledigt utrymme på $MAL (${fria_mb} MB < ${MINSTA_FRIA_MB} MB) — ingen backup skriven." >&2
  exit 1
fi

datum=$(date +%F)
fil="$MAL/dagliga/teaball-$datum.db"

# sqlite3-CLI:t om det finns, annars Pythons inbyggda sqlite3 — båda använder
# SQLite:s backup-API och ger en konsistent kopia även under drift. Källan
# öppnas skrivskyddad i båda grenarna: backupen ska aldrig kunna ändra den.
if command -v sqlite3 >/dev/null; then
  sqlite3 -readonly "$DBFIL" ".backup '$fil'"
  kontroll=$(sqlite3 "$fil" "PRAGMA integrity_check;")
else
  kontroll=$(python3 - "$DBFIL" "$fil" <<'PYEOF'
import sqlite3, sys
kalla = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
mal = sqlite3.connect(sys.argv[2])
kalla.backup(mal)
print(mal.execute("PRAGMA integrity_check").fetchone()[0])
PYEOF
)
fi

# Verifiera kopian innan gamla backuper roteras bort.
[ "$kontroll" = "ok" ] \
  || { echo "Integritetskontrollen misslyckades för $fil: $kontroll" >&2; exit 1; }

# Första dagen i månaden sparas kopian även som månatlig.
if [ "$(date +%d)" = "01" ]; then
  cp "$fil" "$MAL/manatliga/teaball-$(date +%Y-%m).db"
fi

# Rotation: behåll 30 dagliga och 12 månatliga. find, inte ls + glob: i en tom
# katalog (manatliga/ ända till första månadsskiftet) förblir globben oexpanderad
# och ls dör med exit 2, som pipefail gör till hela skriptets — tyst, eftersom
# stderr var bortdirigerad. Filnamnen bär ISO-datum, så omvänd namnsortering
# är nyast-först.
find "$MAL/dagliga" -maxdepth 1 -name 'teaball-*.db' | sort -r | tail -n +31 | xargs -r rm --
find "$MAL/manatliga" -maxdepth 1 -name 'teaball-*.db' | sort -r | tail -n +13 | xargs -r rm --

echo "Backup klar: $fil"
