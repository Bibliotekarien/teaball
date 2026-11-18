#!/usr/bin/env python3
"""Kopierar containerns ögonblickskopior (scripts/ogonblick.py) till
backupmålet, på värden (#108).

Jobbet kör med CAP_DAC_READ_SEARCH och kan alltså läsa allt, men katalogen
det läser är skrivbar för containern. Därför öppnar det ingen SQLite-fil
där och följer inga symlänkar: katalogen och varje fil öppnas med
O_NOFOLLOW, relativt den redan öppnade katalogen, och fstat på den öppna
filen avgör att det är en vanlig fil som containerns användare äger. Det
som kontrolleras är alltså exakt det som läses, inte ett namn som kan
bytas ut däremellan.

Kopian skrivs i målet som en temporärfil och integritetskontrolleras där,
i en katalog som containern inte når, innan den döps om och gamla kopior
roteras bort (30 dagliga, 12 månatliga, som scripts/backup.sh).

Användning (körs av deploy/teaball-backup.service, som teaball):
    python3 -I scripts/backup_kopiera.py <ögonblickskatalog> <målkatalog>
"""

import datetime
import os
import re
import shutil
import sqlite3
import stat
import sys

# Tecken som kan stå i ett hostnamn; ett ' eller / i namnet släpps inte
# vidare till målsökvägen.
NAMN = re.compile(r"[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?")
AGARE = 1505          # containerns användare (Dockerfile)
DAGLIGA, MANATLIGA = 30, 12
MINSTA_FRIA_MB = int(os.environ.get("MINSTA_FRIA_MB", "200"))
BLOCK = 1 << 20


def oppna_katalog(sokvag: str) -> int:
    return os.open(sokvag, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def oppna_kopia(katalog_fd: int, filnamn: str) -> int:
    """Öppnar filen utan att följa en symlänk, och utan att blockera på en
    FIFO. Kastar ValueError om det inte är en vanlig fil som ägs av
    containerns användare och har en enda länk."""
    fd = os.open(filnamn, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=katalog_fd)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ValueError("inte en vanlig fil")
        if st.st_uid != AGARE:
            raise ValueError(f"ägs av uid {st.st_uid}, inte {AGARE}")
        if st.st_nlink != 1:
            raise ValueError(f"har {st.st_nlink} hårda länkar")
    except BaseException:
        os.close(fd)
        raise
    return fd


def integritet(fil: str) -> str:
    # immutable=1: SQLite skapar ingen -journal eller -shm och läser bara.
    conn = sqlite3.connect(f"file:{fil}?mode=ro&immutable=1", uri=True)
    try:
        conn.execute("PRAGMA trusted_schema=OFF")
        return conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()


def rotera(katalog: str, behall: int) -> None:
    filer = sorted((f for f in os.listdir(katalog)
                    if f.startswith("teaball-") and f.endswith(".db")), reverse=True)
    for f in filer[behall:]:
        os.unlink(os.path.join(katalog, f))


def kopiera(katalog_fd: int, filnamn: str, mal: str, idag: datetime.date) -> str:
    namn = filnamn.removesuffix(".db")
    dagliga = os.path.join(mal, namn, "dagliga")
    manatliga = os.path.join(mal, namn, "manatliga")
    fil = os.path.join(dagliga, f"teaball-{idag.isoformat()}.db")
    tmp = fil + ".tmp"

    # Öppna först: ett namn som inte leder till en godkänd fil ska inte
    # lämna någon katalog efter sig i målet.
    kalla = oppna_kopia(katalog_fd, filnamn)
    try:
        os.makedirs(dagliga, mode=0o700, exist_ok=True)
        os.makedirs(manatliga, mode=0o700, exist_ok=True)
        with os.fdopen(kalla, "rb", closefd=False) as r, \
                open(tmp, "wb", opener=lambda p, f: os.open(p, f | os.O_NOFOLLOW, 0o600)) as w:
            shutil.copyfileobj(r, w, BLOCK)
            w.flush()
            os.fsync(w.fileno())
    finally:
        os.close(kalla)

    try:
        kontroll = integritet(tmp)
        if kontroll != "ok":
            raise ValueError(f"integritetskontrollen misslyckades: {kontroll}")
    except BaseException:
        os.unlink(tmp)
        raise
    os.replace(tmp, fil)
    if idag.day == 1:
        shutil.copyfile(fil, os.path.join(manatliga, f"teaball-{idag:%Y-%m}.db"))
    rotera(dagliga, DAGLIGA)
    rotera(manatliga, MANATLIGA)
    return fil


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("Användning: backup_kopiera.py <ögonblickskatalog> <målkatalog>", file=sys.stderr)
        return 2
    kallkatalog, mal = argv[1], argv[2]
    if not os.path.isdir(mal):
        print(f"Målkatalogen {mal} finns inte.", file=sys.stderr)
        return 1
    fria_mb = shutil.disk_usage(mal).free // BLOCK
    if fria_mb < MINSTA_FRIA_MB:
        print(f"För lite ledigt utrymme på {mal} ({fria_mb} MB < {MINSTA_FRIA_MB} MB) "
              "— ingen backup skriven.", file=sys.stderr)
        return 1
    try:
        katalog_fd = oppna_katalog(kallkatalog)
    except OSError as fel:
        print(f"Kan inte öppna {kallkatalog}: {fel}", file=sys.stderr)
        return 1

    idag = datetime.date.today()
    antal, misslyckade = 0, []
    try:
        for filnamn in sorted(os.listdir(katalog_fd)):
            namn = filnamn.removesuffix(".db")
            if filnamn.endswith(".tmp"):
                continue        # en ögonblickskopia som skrivs just nu
            if not filnamn.endswith(".db") or not NAMN.fullmatch(namn):
                print(f"Hoppar över {filnamn!r}: namnet är inget hostnamn.", file=sys.stderr)
                misslyckade.append(repr(filnamn))
                continue
            try:
                fil = kopiera(katalog_fd, filnamn, mal, idag)
            except (OSError, ValueError, sqlite3.Error) as fel:
                print(f"{namn}: {fel}", file=sys.stderr)
                misslyckade.append(namn)
                continue
            antal += 1
            print(f"Backup klar: {fil}")
    finally:
        os.close(katalog_fd)

    if antal == 0 and not misslyckade:
        print(f"Inga ögonblickskopior i {kallkatalog} — ingen backup tagen.", file=sys.stderr)
        return 1
    if misslyckade:
        print(f"Backup misslyckades för: {' '.join(misslyckade)}", file=sys.stderr)
        return 1
    print(f"Backup klar för {antal} organisationer.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
