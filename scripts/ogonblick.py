"""Ögonblickskopior av organisationernas databaser, tagna inne i containern
(#108). Värdens backupjobb (scripts/backup_kopiera.py) kopierar dem sedan
som vanliga filer, utan att öppna någon SQLite-fil som containern kan
skriva i.

Varför här: datakatalogen är skrivbar för containern. Öppnade värdens jobb
databaserna själv, med sina extra rättigheter, kunde en komprometterad
container byta ut en fil mot en symlänk mellan kontroll och öppning. Här
inne har containern inget att vinna på en symlänk: processen har samma
rättigheter som containern redan har.

Kopiorna skrivs till <datakatalog>/ogonblick/<namn>.db: först en
temporärfil, sedan integritetskontroll, fsync och rename, så att värden
aldrig ser en halvskriven kopia. Kopior av organisationer som inte längre
finns tas bort, så att de inte följer med som färska backuper.

Körs av backup-uniten före kopieringen:
    docker compose -f docker-compose.prod.yml run --rm --no-deps -T web \\
        python scripts/ogonblick.py
"""

import os
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, organisationer  # noqa: E402

KATALOGNAMN = "ogonblick"


def katalog() -> Path:
    bas = config.ORGANISATIONER_DIR.parent if organisationer.flera() else config.DB_PATH.parent
    return bas / KATALOGNAMN


def namn_for(org: organisationer.Organisation) -> str:
    # Med en organisation saknas hostnamn; filen heter som databasen.
    return org.nyckel or org.databas.stem


def ta(kalla: Path, mal: Path) -> None:
    tmp = mal.with_name(mal.name + ".tmp")
    tmp.unlink(missing_ok=True)
    src = sqlite3.connect(f"file:{kalla}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
            # En enda fil utan -wal: värden kopierar bara <namn>.db.
            dst.execute("PRAGMA journal_mode=DELETE")
            kontroll = dst.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            dst.close()
    finally:
        src.close()
    if kontroll != "ok":
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Integritetskontrollen misslyckades för {kalla}: {kontroll}")
    with open(tmp, "rb") as f:
        os.fsync(f.fileno())
    os.replace(tmp, mal)


def main() -> int:
    mal = katalog()
    mal.mkdir(mode=0o700, exist_ok=True)
    orgs = organisationer.alla()
    if not orgs:
        print("Inga organisationer — ingen ögonblickskopia tagen.", file=sys.stderr)
        return 1
    tagna, misslyckade = set(), []
    for org in orgs:
        namn = namn_for(org)
        try:
            ta(org.databas, mal / f"{namn}.db")
            tagna.add(f"{namn}.db")
        except (sqlite3.Error, OSError, RuntimeError) as fel:
            print(f"{namn}: {fel}", file=sys.stderr)
            misslyckade.append(namn)
    # Allt annat bort: kopior av borttagna organisationer, misslyckade
    # kopior och sådant som inte hör hemma här. Värdens jobb kopierar varje
    # <namn>.db i katalogen, så det som ligger kvar blir en backup.
    for fil in mal.iterdir():
        if fil.name not in tagna:
            if fil.is_dir() and not fil.is_symlink():
                shutil.rmtree(fil)
            else:
                fil.unlink()
    if misslyckade:
        print(f"Ögonblickskopian misslyckades för: {' '.join(misslyckade)}", file=sys.stderr)
        return 1
    print(f"Ögonblickskopior klara för {len(tagna)} organisationer i {mal}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
