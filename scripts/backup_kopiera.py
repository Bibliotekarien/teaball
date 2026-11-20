#!/usr/bin/env python3
"""Kopierar containerns ögonblickskopior (scripts/ogonblick.py) till
backupmålet, på värden (#108).

Jobbet kör med CAP_DAC_READ_SEARCH och kan alltså läsa allt, men katalogen
det läser är skrivbar för containern. Därför öppnar det ingen SQLite-fil
där och följer inga symlänkar. Katalogen öppnas med O_NOFOLLOW och varje
fil med O_PATH|O_NOFOLLOW relativt den, så att inget innehåll läses och
ingen enhet öppnas förrän fstat på den öppna filen har visat en vanlig fil
som containerns användare äger, med en enda länk och rimlig storlek och
ålder. Först då öppnas samma fil för läsning, via /proc/self/fd. Det som
kontrolleras är alltså exakt det som läses, inte ett namn som kan bytas
ut däremellan.

Kopian skrivs i målet som en temporärfil, där containern inte når, och
integritetskontrolleras av en underprocess utan förmågor: innehållet är
containerns, och SQLite ska inte tolka det i en process som kan läsa allt.
Sedan döps den om och gamla kopior roteras bort (30 dagliga, 12 månatliga,
som scripts/backup.sh).

En <namn>.misslyckad från ogonblick.py betyder att den organisationens
kopia inte gick att ta. De övriga kopieras ändå, men jobbet avslutas med
fel, så att deploy.sh stoppas och övervakningen märker det.

Användning (körs av deploy/teaball-backup.service, som teaball):
    python3 -I scripts/backup_kopiera.py <ögonblickskatalog> <målkatalog>
"""

import datetime
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import time

# Medveten kopia av hostnamnsregeln i app/organisationer.py: skriptet körs på
# värden, utan appens Python-miljö. Ett ' eller / i namnet når aldrig
# målsökvägen.
NAMN = re.compile(r"[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?")
MISSLYCKAD = ".misslyckad"   # som i ogonblick.py
AGARE = 1505          # containerns användare (Dockerfile)
DAGLIGA, MANATLIGA = 30, 12
MINSTA_FRIA_MB = int(os.environ.get("MINSTA_FRIA_MB", "200"))
# Tak mot en container som lägger in en gles fil på hundratals GB, eller
# tusentals "organisationer", för att fylla backupmålets disk.
STORSTA_MB = int(os.environ.get("STORSTA_MB", "2048"))
STORSTA_ANTAL = int(os.environ.get("STORSTA_ANTAL", "200"))
# ogonblick.py körs strax före; en äldre fil är en kvarlämnad kopia, och
# den ska inte sparas som dagens.
STORSTA_ALDER_S = 6 * 3600
BLOCK = 1 << 20


def oppna_katalog(sokvag: str) -> int:
    return os.open(sokvag, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def oppna_kopia(katalog_fd: int, filnamn: str, fria: int) -> int:
    """Returnerar en läsbar fd för filen, eller kastar ValueError om det inte
    är en vanlig fil som ägs av containerns användare, har en enda länk,
    får plats och är färsk."""
    sti = os.open(filnamn, os.O_PATH | os.O_NOFOLLOW, dir_fd=katalog_fd)
    try:
        st = os.fstat(sti)
        if not stat.S_ISREG(st.st_mode):
            raise ValueError("inte en vanlig fil")
        if st.st_uid != AGARE:
            raise ValueError(f"ägs av uid {st.st_uid}, inte {AGARE}")
        if st.st_nlink != 1:
            raise ValueError(f"har {st.st_nlink} hårda länkar")
        if st.st_size > STORSTA_MB * BLOCK:
            raise ValueError(f"större än {STORSTA_MB} MB ({st.st_size // BLOCK} MB)")
        if st.st_size + MINSTA_FRIA_MB * BLOCK > fria:
            raise ValueError("får inte plats i målet")
        if time.time() - st.st_mtime > STORSTA_ALDER_S:
            raise ValueError("ögonblickskopian är äldre än sex timmar")
        # Samma inod som kontrollerades, nu för läsning.
        return os.open(f"/proc/self/fd/{sti}", os.O_RDONLY)
    finally:
        os.close(sti)


def kontrollera(fil: str) -> str:
    # immutable=1: SQLite skapar ingen -journal eller -shm och läser bara.
    conn = sqlite3.connect(f"file:{fil}?mode=ro&immutable=1", uri=True)
    try:
        conn.execute("PRAGMA trusted_schema=OFF")
        return conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()


def integritet(fil: str) -> str:
    """kontrollera() i en underprocess utan förmågor. Ambient och
    ärvbara förmågor kan sänkas utan privilegier, och utan dem har den nya
    processen inga alls."""
    setpriv = shutil.which("setpriv")
    if setpriv is None:
        raise ValueError("setpriv saknas; integritetskontrollen körs inte med förmågan")
    svar = subprocess.run(
        [setpriv, "--inh-caps=-all", "--ambient-caps=-all", "--",
         sys.executable, "-I", os.path.abspath(__file__), "--kontrollera", fil],
        capture_output=True, text=True, timeout=1800,
    )
    if svar.returncode != 0:
        return (svar.stderr.strip().splitlines() or ["okänt fel"])[-1]
    return svar.stdout.strip()


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
    kalla = oppna_kopia(katalog_fd, filnamn, shutil.disk_usage(mal).free)
    try:
        os.makedirs(dagliga, mode=0o700, exist_ok=True)
        os.makedirs(manatliga, mode=0o700, exist_ok=True)
        with os.fdopen(kalla, "rb", closefd=False) as r, \
                open(tmp, "wb", opener=lambda p, f: os.open(p, f | os.O_NOFOLLOW, 0o600)) as w:
            # Taket gäller också det som faktiskt läses: filen kan växa
            # efter fstat.
            kvar = STORSTA_MB * BLOCK
            while block := r.read(min(BLOCK, kvar + 1)):
                kvar -= len(block)
                if kvar < 0:
                    raise ValueError(f"växte över {STORSTA_MB} MB under kopieringen")
                w.write(block)
            w.flush()
            os.fsync(w.fileno())
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
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
    if len(argv) == 3 and argv[1] == "--kontrollera":
        print(kontrollera(argv[2]))
        return 0
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
        filnamn_alla = sorted(os.listdir(katalog_fd))
        if len(filnamn_alla) > STORSTA_ANTAL:
            print(f"{len(filnamn_alla)} filer i {kallkatalog}, fler än {STORSTA_ANTAL} "
                  "— ingen backup skriven.", file=sys.stderr)
            return 1
        for filnamn in filnamn_alla:
            if filnamn.endswith(MISSLYCKAD) and NAMN.fullmatch(filnamn.removesuffix(MISSLYCKAD)):
                print(f"{filnamn.removesuffix(MISSLYCKAD)}: ögonblickskopian gick inte att ta "
                      "(se ogonblick.py ovan i journalen).", file=sys.stderr)
                misslyckade.append(filnamn.removesuffix(MISSLYCKAD))
                continue
            namn = filnamn.removesuffix(".db")
            if not filnamn.endswith(".db") or not NAMN.fullmatch(namn):
                print(f"Hoppar över {filnamn!r}: namnet är inget hostnamn.", file=sys.stderr)
                misslyckade.append(repr(filnamn))
                continue
            try:
                fil = kopiera(katalog_fd, filnamn, mal, idag)
            except (OSError, ValueError, sqlite3.Error, subprocess.SubprocessError) as fel:
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
