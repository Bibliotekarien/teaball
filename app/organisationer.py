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

import re
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from app import config

# Ett vanligt DNS-namn i gemener: etiketter av a–z, 0–9 och bindestreck,
# åtskilda av punkt. Utesluter allt som kan bli en annan sökväg (/, .., \).
_HOSTNAMN = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*$")


@dataclass(frozen=True)
class Organisation:
    nyckel: str      # hostnamnet; "" när installationen har en organisation
    databas: Path


_aktuell: ContextVar[Organisation | None] = ContextVar("organisation", default=None)


def flera() -> bool:
    return config.ORGANISATIONER_DIR is not None


def _ar_organisationsfil(fil: Path) -> bool:
    # Kopior före migration (db.py) heter <namn>.fore-NNNN-<tid>.db och ligger
    # i samma katalog; de är aldrig en organisation.
    return fil.suffix == ".db" and ".fore-" not in fil.name and bool(_HOSTNAMN.match(fil.stem))


def for_vard(host: str) -> Organisation | None:
    """Organisationen för en Host-header, eller None om den inte finns."""
    if not flera():
        return Organisation("", config.DB_PATH)
    namn = host.strip().lower().rsplit(":", 1)[0].rstrip(".")
    if not _HOSTNAMN.match(namn):
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


def satt_aktuell(organisation: Organisation):
    """Returnerar en token för ContextVar.reset."""
    return _aktuell.set(organisation)


def aterstall(token) -> None:
    _aktuell.reset(token)
