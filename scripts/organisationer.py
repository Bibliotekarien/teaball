"""Skapa, lista och ta bort organisationer på en installation med flera
organisationer (INSTALL.md avsnitt 10). Kräver ORGANISATIONER_DIR.

    python scripts/organisationer.py skapa teaball.exempel.se stilla-lax
    python scripts/organisationer.py lista
    python scripts/organisationer.py ta-bort teaball.exempel.se --bekrafta teaball.exempel.se
    python scripts/organisationer.py matomo teaball.exempel.se 12

I containern:
    docker compose exec web python scripts/organisationer.py lista

skapa gör databasen <hostnamn>.db med organisationens första admin. Den byggs
under ett tillfälligt namn och får sitt riktiga namn först när den är klar,
så appen ser aldrig en organisation utan admin. Hostnamnet behöver sedan DNS
och TLS i proxyn.

ta-bort raderar aldrig direkt: databasen och dess kopior före migration flyttas
till borttagna/ i samma katalog, och sedan svarar adressen 404. Ta bort
hostnamnet ur proxyn först, så att inget anrop hinner skriva under tiden.
Kopiorna innehåller organisationens data och ska raderas när de inte längre
behövs, liksom organisationens katalog i backupmålet.
"""

import argparse
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, db, instans, organisationer  # noqa: E402
from app.auth.password import hash_losen  # noqa: E402
from app.services.konton import giltigt_anvandarnamn  # noqa: E402
from scripts.skapa_forvaltare import las_losenord  # noqa: E402

BORTTAGNA = "borttagna"


def _fil(hostnamn: str) -> Path:
    return config.ORGANISATIONER_DIR / f"{hostnamn}.db"


def _med_sidofiler(fil: Path) -> list[Path]:
    return [fil, fil.with_name(fil.name + "-wal"), fil.with_name(fil.name + "-shm")]


def skapa(hostnamn: str, anvandarnamn: str, losenord: str | None) -> int:
    if not organisationer.giltigt_hostnamn(hostnamn):
        tips = (f" Menade du {hostnamn.lower()}?"
                if organisationer.giltigt_hostnamn(hostnamn.lower()) else "")
        print(f"'{hostnamn}' är inget giltigt hostnamn (gemener, a–z, 0–9, - och .).{tips}",
              file=sys.stderr)
        return 1
    if not giltigt_anvandarnamn(anvandarnamn):
        print(f"'{anvandarnamn}' är inget giltigt användarnamn (2–50 tecken: bokstäver, "
              "siffror, punkt, bindestreck, understreck).", file=sys.stderr)
        return 1
    fil = _fil(hostnamn)
    if fil.exists():
        print(f"Organisationen {hostnamn} finns redan ({fil}).", file=sys.stderr)
        return 1
    losenord = las_losenord(losenord)
    if losenord is None:
        return 1

    # Byggs under ett namn som aldrig är en organisation (suffix .ny).
    tillfallig = config.ORGANISATIONER_DIR / f".{hostnamn}.ny"
    try:
        conn = db.connect(tillfallig)
        try:
            db.init_db(conn)
            conn.execute(
                "INSERT INTO forvaltare (anvandarnamn, losen_hash, roll) VALUES (?, ?, 'admin')",
                (anvandarnamn, hash_losen(losenord)))
            conn.commit()
        finally:
            conn.close()     # sista anslutningen: WAL checkpointas och tas bort
        # link misslyckas om målet finns, så två samtidiga skapa kan inte
        # skriva över varandra.
        os.link(tillfallig, fil)
    except FileExistsError:
        print(f"Organisationen {hostnamn} skapades samtidigt av någon annan.", file=sys.stderr)
        return 1
    finally:
        for del_ in _med_sidofiler(tillfallig):
            del_.unlink(missing_ok=True)

    print(f"Organisationen {hostnamn} är skapad med admin '{anvandarnamn}'.")
    print(f"""
Ge hostnamnet DNS och TLS i proxyn. Skicka sedan till organisationens admin:
  1. Logga in på https://{hostnamn}/login som '{anvandarnamn}'.
  2. Byt lösenord (https://{hostnamn}/losenord); det här känner operatören till.
  3. Fyll i organisationen, personuppgiftsansvarig och kontakt under Inställningar.
  4. Läs https://{hostnamn}/integritet före skarp drift.""")
    return 0


def _rad(organisation: organisationer.Organisation, senaste: int) -> str:
    namn = f"{organisation.nyckel:<40}"
    try:
        # Skrivskyddat: listningen ska aldrig ändra en databas.
        conn = sqlite3.connect(f"{organisation.databas.resolve().as_uri()}?mode=ro", uri=True)
        try:
            version = conn.execute("SELECT max(version) FROM schema_migration").fetchone()[0]
            if version is None:
                return f"{namn}  (tom schema_migration, inte en Teaball-databas?)"
            if version < senaste:
                # Äldre scheman saknar kolumner som räknas nedan.
                return f"{namn}  (schema {version:04d}, migreras vid nästa start)"
            if version > senaste:
                return f"{namn}  (schema {version:04d} är nyare än koden, {senaste:04d})"
            konton, inloggad = conn.execute(
                "SELECT count(*), max(senast_inloggad) FROM forvaltare").fetchone()
            medlemmar = conn.execute("SELECT count(*) FROM medlem").fetchone()[0]
            noder = conn.execute("SELECT count(*) FROM funktion").fetchone()[0]
            site_id = conn.execute("SELECT matomo_site_id FROM instans").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.DatabaseError as fel:
        return f"{namn}  (kan inte läsas: {fel})"
    return (f"{namn} {konton:>6} {medlemmar:>9} {noder:>6}  {inloggad or 'aldrig':<19}"
            f"  {site_id or '-'}")


def lista() -> int:
    alla = organisationer.alla()
    if not alla:
        print(f"Inga organisationer i {config.ORGANISATIONER_DIR}.")
    else:
        senaste = db.senaste_migration()
        print(f"{'hostnamn':<40} {'konton':>6} {'medlemmar':>9} {'noder':>6}"
              f"  {'senast inloggad':<19}  matomo")
        for organisation in alla:
            print(_rad(organisation, senaste))
    borttagna = sorted((config.ORGANISATIONER_DIR / BORTTAGNA).glob("*.db"))
    if borttagna:
        print(f"\n{BORTTAGNA}/: {len(borttagna)} kopior av borttagna organisationer, "
              "med personuppgifter. Radera dem när de inte längre behövs.")
    return 0


def ta_bort(hostnamn: str, bekraftelse: str | None) -> int:
    fil = _fil(hostnamn)
    if not organisationer.giltigt_hostnamn(hostnamn) or not fil.is_file():
        print(f"Organisationen {hostnamn} finns inte (se lista).", file=sys.stderr)
        return 1
    if bekraftelse != hostnamn:
        print(f"Bekräfta med --bekrafta {hostnamn}. Organisationens adress slutar "
              "fungera; dess konton och svar flyttas till en kopia i "
              f"{BORTTAGNA}/. Ta bort hostnamnet ur proxyn först.", file=sys.stderr)
        return 1
    katalog = config.ORGANISATIONER_DIR / BORTTAGNA
    katalog.mkdir(mode=0o700, exist_ok=True)
    stampel = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    kopia = katalog / f"{hostnamn}.{stampel}.db"
    # Backup-API:t ger en konsistent kopia även om appen skriver just nu.
    kalla = sqlite3.connect(f"{fil.resolve().as_uri()}?mode=ro", uri=True)
    mal = sqlite3.connect(kopia)
    try:
        kalla.backup(mal)
        kontroll = mal.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        mal.close()
        kalla.close()
    if kontroll != "ok":
        # Kopian är det enda som blir kvar; utan en hel kopia raderas inget.
        kopia.unlink()
        print(f"Kopian klarade inte integritetskontrollen ({kontroll}); inget är "
              "borttaget.", file=sys.stderr)
        return 1
    for kopia_fore in organisationer.kopior_fore_migration(hostnamn):
        kopia_fore.rename(katalog / kopia_fore.name)
    for del_ in _med_sidofiler(fil):
        del_.unlink(missing_ok=True)
    print(f"Organisationen {hostnamn} är borttagen; adressen ger nu 404.")
    print(f"Kopia: {kopia} (och eventuella kopior före migration i samma katalog).")
    print("Radera kopiorna när de inte längre behövs, liksom organisationens katalog i "
          f"backupmålet (<mål>/{hostnamn}/), som inte längre roteras. Ta bort "
          "hostnamnet ur DNS.")
    return 0


def satt_matomo(hostnamn: str, site_id: str | None) -> int:
    """Organisationens sajt i operatörens Matomo; utan site-id stängs
    statistiken av för organisationen."""
    fil = _fil(hostnamn)
    if not organisationer.giltigt_hostnamn(hostnamn) or not fil.is_file():
        print(f"Organisationen {hostnamn} finns inte (se lista).", file=sys.stderr)
        return 1
    conn = db.connect(fil)
    try:
        instans.spara_matomo(conn, site_id or "")
    except ValueError as fel:
        print(str(fel), file=sys.stderr)
        return 1
    finally:
        conn.close()
    if not site_id:
        print(f"Ingen besöksstatistik för {hostnamn}.")
    elif not config.MATOMO_URL:
        print(f"{hostnamn} har site-id {site_id}, men MATOMO_URL är inte satt, så "
              "ingen statistik skickas.")
    else:
        print(f"{hostnamn} rapporterar till site-id {site_id} i {config.MATOMO_URL}. "
              "Integritetssidan nämner nu besöksstatistiken.")
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
    p_matomo = under.add_parser("matomo", help="Sätt organisationens Matomo-sajt.")
    p_matomo.add_argument("hostnamn")
    p_matomo.add_argument("site_id", nargs="?",
                          help="Sajtens id i MATOMO_URL. Utelämnat: ingen statistik.")
    args = parser.parse_args(argv)

    if not organisationer.flera():
        print("ORGANISATIONER_DIR är inte satt; installationen har en organisation.",
              file=sys.stderr)
        return 1
    if args.kommando == "skapa":
        return skapa(args.hostnamn, args.anvandarnamn, args.losenord)
    if args.kommando == "lista":
        return lista()
    if args.kommando == "matomo":
        return satt_matomo(args.hostnamn, args.site_id)
    return ta_bort(args.hostnamn, args.bekrafta)


if __name__ == "__main__":
    raise SystemExit(main())
