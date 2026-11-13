"""Skapa, lista och ta bort organisationer på en installation med flera
organisationer (INSTALL.md avsnitt 10). Kräver ORGANISATIONER_DIR.

    python scripts/organisationer.py skapa teaball.exempel.se stilla-lax
    python scripts/organisationer.py lista
    python scripts/organisationer.py ta-bort teaball.exempel.se --bekrafta teaball.exempel.se

I containern:
    docker compose exec web python scripts/organisationer.py lista

skapa gör databasen <hostnamn>.db med organisationens första admin. Appen
hittar den direkt; hostnamnet behöver sedan DNS och TLS i proxyn.

ta-bort raderar aldrig direkt: databasen kopieras först till
borttagna/<hostnamn>.<tid>.db i samma katalog, och sedan svarar adressen 404.
Kopian innehåller organisationens data och ska raderas när den inte längre
behövs.
"""

import argparse
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, db, organisationer  # noqa: E402
from app.auth.password import hash_losen  # noqa: E402
from scripts.skapa_forvaltare import las_losenord  # noqa: E402

BORTTAGNA = "borttagna"


def _fil(hostnamn: str) -> Path:
    return config.ORGANISATIONER_DIR / f"{hostnamn}.db"


def skapa(hostnamn: str, anvandarnamn: str, losenord: str | None) -> int:
    if not organisationer.giltigt_hostnamn(hostnamn):
        print(f"'{hostnamn}' är inget giltigt hostnamn (gemener, a–z, 0–9, - och .).",
              file=sys.stderr)
        return 1
    fil = _fil(hostnamn)
    if fil.exists():
        print(f"Organisationen {hostnamn} finns redan ({fil}).", file=sys.stderr)
        return 1
    losenord = las_losenord(losenord)
    if losenord is None:
        return 1
    conn = db.connect(fil)
    try:
        db.init_db(conn)
        conn.execute("INSERT INTO forvaltare (anvandarnamn, losen_hash, roll) VALUES (?, ?, 'admin')",
                     (anvandarnamn, hash_losen(losenord)))
        conn.commit()
    finally:
        conn.close()
    print(f"Organisationen {hostnamn} är skapad med admin '{anvandarnamn}'.")
    print(f"Ge hostnamnet DNS och TLS i proxyn; den nås sedan på https://{hostnamn}/login.")
    return 0


def _senaste_migration() -> int:
    return max(int(p.name.split("_", 1)[0]) for p in config.MIGRATIONS_DIR.glob("[0-9]*.sql"))


def lista() -> int:
    alla = organisationer.alla()
    if not alla:
        print(f"Inga organisationer i {config.ORGANISATIONER_DIR}.")
        return 0
    senaste = _senaste_migration()
    print(f"{'hostnamn':<40} {'konton':>6} {'medlemmar':>9} {'noder':>6}  senast inloggad")
    for organisation in alla:
        # Skrivskyddat: listningen ska aldrig ändra en databas.
        conn = sqlite3.connect(f"file:{organisation.databas}?mode=ro", uri=True)
        try:
            konton, inloggad = conn.execute(
                "SELECT count(*), max(senast_inloggad) FROM forvaltare").fetchone()
            medlemmar = conn.execute("SELECT count(*) FROM medlem").fetchone()[0]
            noder = conn.execute("SELECT count(*) FROM funktion").fetchone()[0]
            version = conn.execute("SELECT max(version) FROM schema_migration").fetchone()[0]
        finally:
            conn.close()
        rad = (f"{organisation.nyckel:<40} {konton:>6} {medlemmar:>9} {noder:>6}"
               f"  {inloggad or 'aldrig'}")
        if version != senaste:
            rad += f"  (schema {version:04d}, migreras vid nästa start)"
        print(rad)
    return 0


def ta_bort(hostnamn: str, bekraftelse: str | None) -> int:
    fil = _fil(hostnamn)
    if not organisationer.giltigt_hostnamn(hostnamn) or not fil.is_file():
        print(f"Organisationen {hostnamn} finns inte.", file=sys.stderr)
        return 1
    if bekraftelse != hostnamn:
        print(f"Bekräfta med --bekrafta {hostnamn}. Organisationens adress slutar "
              "fungera, och alla dess konton och svar följer med.", file=sys.stderr)
        return 1
    katalog = config.ORGANISATIONER_DIR / BORTTAGNA
    katalog.mkdir(mode=0o700, exist_ok=True)
    stampel = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    kopia = katalog / f"{hostnamn}.{stampel}.db"
    # Backup-API:t ger en konsistent kopia även om appen skriver just nu.
    kalla = sqlite3.connect(f"file:{fil}?mode=ro", uri=True)
    mal = sqlite3.connect(kopia)
    try:
        kalla.backup(mal)
    finally:
        mal.close()
        kalla.close()
    for del_ in (fil, fil.with_name(fil.name + "-wal"), fil.with_name(fil.name + "-shm")):
        del_.unlink(missing_ok=True)
    print(f"Organisationen {hostnamn} är borttagen; adressen ger nu 404.")
    print(f"Kopia: {kopia}. Radera den när den inte längre behövs, och ta bort "
          "hostnamnet ur proxyn och DNS.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hantera organisationerna i ORGANISATIONER_DIR.")
    under = parser.add_subparsers(dest="kommando", required=True)
    p_skapa = under.add_parser("skapa", help="Skapa en organisation med sin första admin.")
    p_skapa.add_argument("hostnamn")
    p_skapa.add_argument("anvandarnamn", help="Den första adminens användarnamn.")
    p_skapa.add_argument("--losenord", help="Anges helst inte på kommandoraden; utelämna för prompt.")
    under.add_parser("lista", help="Lista organisationerna.")
    p_bort = under.add_parser("ta-bort", help="Ta bort en organisation (kopia sparas).")
    p_bort.add_argument("hostnamn")
    p_bort.add_argument("--bekrafta", metavar="HOSTNAMN", help="Samma hostnamn igen.")
    args = parser.parse_args(argv)

    if not organisationer.flera():
        print("ORGANISATIONER_DIR är inte satt; installationen har en organisation.",
              file=sys.stderr)
        return 1
    if args.kommando == "skapa":
        return skapa(args.hostnamn, args.anvandarnamn, args.losenord)
    if args.kommando == "lista":
        return lista()
    return ta_bort(args.hostnamn, args.bekrafta)


if __name__ == "__main__":
    raise SystemExit(main())
