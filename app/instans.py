"""Instansens texter: organisationen, systemet som ersätts och integritetssidans
personuppgiftsansvarig och kontaktväg. De bor i tabellen instans (en rad) och
redigeras av admin på /installningar. Samma rad bär organisationens
Matomo-sajt, som bara operatören sätter (spara_matomo, migration 0011).

Texterna läses en gång per anrop av en middleware i main.py och läggs i en
ContextVar. Därifrån når även makron dem som importeras utan kontext (STATUS i
web.py används i många sådana), och varje anrop ser det som står i databasen
just då, oavsett hur många processer som kör. Utanför ett anrop (skript,
tester utan klient) gäller standardvärdena: neutral text, aldrig ett lånat
namn."""

import logging
import sqlite3
from contextvars import ContextVar
from dataclasses import dataclass, fields

from app import config, organisationer

logger = logging.getLogger("teaball")

NEUTRALT_SYSTEM = "det nuvarande systemet"

# Övre gränser för formuläret; texterna visas i löptext och tooltips.
# Nycklarna är också de fält admin får spara (spara). Övriga fält i Instans
# är operatörens och skrivs bara av egna funktioner; ett nytt adminfält ska
# alltså in här, ett nytt operatörsfält inte.
MAXLANGD = {
    "organisation": 200,
    "nuvarande_system": 200,
    "personuppgiftsansvarig": 300,
    "dataskydd_kontakt": 300,
}


@dataclass(frozen=True)
class Instans:
    organisation: str = ""
    nuvarande_system: str = ""
    personuppgiftsansvarig: str = ""
    dataskydd_kontakt: str = ""
    # Sätts av operatören (scripts/organisationer.py matomo), inte på
    # /installningar; se migration 0011.
    matomo_site_id: str = ""

    @property
    def systemnamn(self) -> str:
        """Namnet att skriva i löptext; neutralt när inget är angivet."""
        return self.nuvarande_system or NEUTRALT_SYSTEM


_FALT = [f.name for f in fields(Instans)]
_aktuell: ContextVar[Instans] = ContextVar("instans", default=Instans())


def aktuell() -> Instans:
    return _aktuell.get()


def satt_aktuell(instans: Instans):
    """Returnerar en token för ContextVar.reset."""
    return _aktuell.set(instans)


def aterstall(token) -> None:
    _aktuell.reset(token)


def las(conn: sqlite3.Connection) -> Instans:
    rad = conn.execute(f"SELECT {', '.join(_FALT)} FROM instans WHERE id = 1").fetchone()
    return Instans(**{f: rad[f] for f in _FALT}) if rad else Instans()


def spara(conn: sqlite3.Connection, **varden: str) -> Instans:
    """Sparar texterna som admin redigerar (MAXLANGD); fält som saknas blir
    tomma. Matomo-sajten rörs inte, den är operatörens (spara_matomo)."""
    okanda = set(varden) - set(MAXLANGD)
    if okanda:
        raise ValueError(f"Okända fält: {sorted(okanda)}")
    rensade = {f: (varden.get(f) or "").strip()[: MAXLANGD[f]] for f in MAXLANGD}
    conn.execute(
        f"UPDATE instans SET {', '.join(f'{f} = ?' for f in rensade)} WHERE id = 1",
        list(rensade.values()),
    )
    conn.commit()
    return las(conn)


def spara_matomo(conn: sqlite3.Connection, site_id: str) -> None:
    """Organisationens Matomo-sajt; tom sträng stänger av statistiken."""
    if site_id and not (site_id.isascii() and site_id.isdigit()
                        and len(site_id) <= 10 and int(site_id) >= 1):
        raise ValueError("Matomos site-id är ett positivt heltal.")
    conn.execute("UPDATE instans SET matomo_site_id = ? WHERE id = 1", (site_id,))
    conn.commit()


def fyll_fran_miljon(conn: sqlite3.Connection) -> None:
    """Uppgraderingsväg från .env: en databas som redan var i bruk när
    migration 0010 kom får ORGANISATION m.fl. kopierade från miljön, en gång,
    så att instansen behåller sina texter. En ny, tom databas fylls inte, och
    med flera organisationer fylls ingen: den skulle annars ärva serverns
    texter, t.ex. en annan organisations personuppgiftsansvarig. Därefter gäller
    databasen; satta variabler som inte används loggas som varning."""
    rad = conn.execute("SELECT fran_miljon FROM instans WHERE id = 1").fetchone()
    if rad is None:
        return
    fran_miljo = {
        "organisation": config.ORGANISATION,
        "nuvarande_system": config.NUVARANDE_SYSTEM,
        "personuppgiftsansvarig": config.PERSONUPPGIFTSANSVARIG,
        "dataskydd_kontakt": config.DATASKYDD_KONTAKT,
    }
    satta = [f.upper() for f, v in fran_miljo.items() if v]
    if rad["fran_miljon"]:
        if satta:
            logger.warning("Ignoreras, instansens texter ändras under Inställningar: %s",
                           ", ".join(satta))
        return
    if organisationer.flera():
        # Miljön är serverns, inte en viss organisations: en gammal databas som
        # flyttas in i katalogen ska inte få en annan organisations texter.
        if satta:
            logger.warning("Fylls inte från miljön med flera organisationer, ange "
                           "texterna under Inställningar: %s", ", ".join(satta))
        conn.execute("UPDATE instans SET fran_miljon = 1 WHERE id = 1")
        conn.commit()
        return
    i_bruk = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM forvaltare) OR EXISTS (SELECT 1 FROM funktion)"
    ).fetchone()[0]
    if i_bruk:
        spara(conn, **fran_miljo)
        if satta:
            logger.info("Instansens texter fyllda från miljön: %s", ", ".join(satta))
    elif satta:
        logger.warning("Ny databas fylls inte från miljön, ange texterna under "
                       "Inställningar: %s", ", ".join(satta))
    conn.execute("UPDATE instans SET fran_miljon = 1 WHERE id = 1")
    conn.commit()


class Instanstext:
    """En text som hämtar instansens värden när den skrivs ut, inte när den
    skapas. STATUS i web.py byggs en gång vid import, men "Finns i <system>"
    ska följa det som gäller för anropet."""

    def __init__(self, mall: str):
        self.mall = mall

    def __str__(self) -> str:
        return self.mall.format(system=aktuell().systemnamn)
