"""Vilken organisations databas ett anrop gäller.

Utan ORGANISATIONER_DIR är installationen en organisation med databasen i
DB_PATH, precis som tidigare. Med ORGANISATIONER_DIR satt har varje
organisation en egen SQLite-fil där, döpt efter sitt hostnamn
(teaball.example.org → teaball.example.org.db), och anropets Host-header
avgör vilken som används. Ett okänt hostnamn får 404: organisationer skapas
på servern, aldrig av ett anrop.

Det här är det enda stället som väljer databas. Middlewaren i main.py sätter
den en gång per anrop, och db.connect(), get_conn och instansens texter läser
den härifrån. Data, konton och texter kan därför inte komma från olika
organisationer i samma anrop."""

import logging
import re
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from app import config

# Ett vanligt DNS-namn i gemener: etiketter på högst 63 tecken av a–z, 0–9 och
# bindestreck, åtskilda av punkt, högst 253 tecken totalt. Utesluter allt som
# kan bli en annan sökväg (/, .., \), och längdgränsen håller filnamnet inom
# vad filsystemet tar emot (annars OSError och 500 i stället för 404).
_ETIKETT = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_HOSTNAMN = re.compile(rf"^{_ETIKETT}(?:\.{_ETIKETT})*$")
_MAX_HOSTNAMN = 253
# Kopior före migration (db.py): <namn>.fore-NNNN-<UTC-tid>.db i samma katalog.
_KOPIA = re.compile(r"\.fore-\d{4}-\d{8}T\d{6}Z\.db$")


@dataclass(frozen=True)
class Organisation:
    nyckel: str      # hostnamnet; "" när installationen har en organisation
    databas: Path


_aktuell: ContextVar[Organisation | None] = ContextVar("organisation", default=None)


def flera() -> bool:
    return config.ORGANISATIONER_DIR is not None


def giltigt_hostnamn(namn: str) -> bool:
    return len(namn) <= _MAX_HOSTNAMN and bool(_HOSTNAMN.match(namn))


def kopior_fore_migration(hostnamn: str) -> list[Path]:
    """Organisationens kopior före migration (db.py), som ligger bredvid den."""
    return sorted(
        fil for fil in config.ORGANISATIONER_DIR.glob(f"{hostnamn}.fore-*.db")
        if _KOPIA.search(fil.name)
    )


def _ar_organisationsfil(fil: Path) -> bool:
    # Kopiorna före migration är aldrig en organisation. (Deras versaler T och Z
    # stoppas redan av _HOSTNAMN; det explicita mönstret gör avsikten synlig.)
    return fil.suffix == ".db" and not _KOPIA.search(fil.name) and giltigt_hostnamn(fil.stem)


def for_vard(host: str) -> Organisation | None:
    """Organisationen för en Host-header, eller None om den inte finns."""
    if not flera():
        return Organisation("", config.DB_PATH)
    namn = host.strip().lower().rsplit(":", 1)[0].rstrip(".")
    if not giltigt_hostnamn(namn):
        return None
    fil = config.ORGANISATIONER_DIR / f"{namn}.db"
    if not _ar_organisationsfil(fil) or not fil.is_file():
        return None
    return Organisation(namn, fil)


def alla() -> list[Organisation]:
    """Alla organisationers databaser, för migrering vid start."""
    if not flera():
        return [Organisation("", config.DB_PATH)]
    return [
        Organisation(fil.stem, fil)
        for fil in sorted(config.ORGANISATIONER_DIR.glob("*.db"))
        if _ar_organisationsfil(fil)
    ]


def aktuell() -> Organisation:
    """Anropets organisation. Utanför ett anrop (skript, start) finns ingen
    med flera organisationer; då är det ett fel att fråga, aldrig en gissning."""
    organisation = _aktuell.get()
    if organisation is not None:
        return organisation
    if flera():
        raise RuntimeError(
            "Ingen organisation vald. ORGANISATIONER_DIR är satt, så skript "
            "måste få databasfilen med --db."
        )
    return Organisation("", config.DB_PATH)


class AuditOrganisation(logging.Filter):
    """Prefixar auditraderna med org=<hostnamn> när det finns flera
    organisationer: id och användarnamn upprepas mellan databaserna, så en rad
    utan organisation går inte att knyta till rätt organisation efteråt."""

    def filter(self, record: logging.LogRecord) -> bool:
        organisation = _aktuell.get()
        if flera() and organisation is not None:
            # Nyckeln är ett validerat hostnamn utan %, så den kan stå i
            # formatsträngen.
            record.msg = f"org={organisation.nyckel} {record.msg}"
        return True


def satt_aktuell(organisation: Organisation):
    """Returnerar en token för ContextVar.reset."""
    return _aktuell.set(organisation)


def aterstall(token) -> None:
    _aktuell.reset(token)
