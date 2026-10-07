"""Kontohantering för förvaltare: skapa, byta roll, nytt lösenord, ta bort,
samt byte av eget lösenord. Reglerna som skyddar mot att låsa ute sig själv
bor här, inte i routern, så att de är testbara utan HTTP.

Tjänsten har ingen e-post och ska inte få någon. Lösenord slumpas därför fram
och visas för administratören en enda gång (samma mönster som medlemslänkarna);
den som fått ett byter själv på /losenord. Användarnamn föreslås också
slumpade — två vardagliga svenska ord — så att kontolistan inte behöver
innehålla några personuppgifter alls."""

import re
import secrets
import sqlite3

from app.auth.password import hash_losen, verifiera_losen

ROLLER = ("admin", "intern", "extern")
MINSTA_LOSENORD = 8
# Bokstäver, siffror, punkt, bindestreck, understreck; 2–50 tecken. Svenska
# bokstäver tillåts så att den som vill döpa kontot efter en funktion kan
# skriva "styrgrupp-sö" — men förslagen håller sig till ASCII.
_ANVANDARNAMN = re.compile(r"^[\w.-]{2,50}$")

# Ordlistorna är medvetet ASCII och lätta att läsa upp i telefon. 24 × 24 ger
# 576 kombinationer — gott och väl för ett tiotal konton; slumpa_anvandarnamn
# slumpar om vid kollision.
ADJEKTIV = (
    "stilla", "snabb", "tyst", "ljus", "varm", "kall", "klar", "djup",
    "fin", "rund", "rak", "mild", "tunn", "lugn", "vaken", "glad",
    "stark", "tidig", "sen", "vild", "tam", "torr", "blank", "brant",
)
SUBSTANTIV = (
    "lax", "ek", "lind", "asp", "mossa", "sten", "holme", "vik",
    "fors", "dal", "udde", "kulle", "tall", "gran", "hassel", "pil",
    "vass", "strand", "klippa", "lo", "uggla", "trana", "orre", "hare",
)


class Kontofel(ValueError):
    """Ett regelbrott som ska visas för användaren, inte en programbugg."""


def giltigt_anvandarnamn(namn: str) -> bool:
    return bool(_ANVANDARNAMN.match(namn))


def slumpa_anvandarnamn(conn: sqlite3.Connection) -> str:
    """Två slumpade ord, garanterat lediga."""
    for _ in range(50):
        forslag = f"{secrets.choice(ADJEKTIV)}-{secrets.choice(SUBSTANTIV)}"
        if not _finns_namn(conn, forslag):
            return forslag
    # Ordlistorna nästan uttömda — osannolikt, men fall tillbaka på ett suffix.
    return f"{secrets.choice(ADJEKTIV)}-{secrets.choice(SUBSTANTIV)}-{secrets.randbelow(900) + 100}"


def slumpa_losenord() -> str:
    """16 tecken ur URL-säkert alfabet: ~96 bitar, går att skriva av."""
    return secrets.token_urlsafe(12)


def _finns_namn(conn, namn: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM forvaltare WHERE anvandarnamn = ?", (namn,)
    ).fetchone() is not None


def _hamta(conn, konto_id: int):
    rad = conn.execute(
        "SELECT id, anvandarnamn, roll FROM forvaltare WHERE id = ?", (konto_id,)
    ).fetchone()
    if rad is None:
        raise Kontofel("Kontot finns inte.")
    return rad


def _antal_admin(conn) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM forvaltare WHERE roll = 'admin'"
    ).fetchone()[0]


def _inte_sig_sjalv(konto_id: int, aktor_id: int, vad: str) -> None:
    if konto_id == aktor_id:
        raise Kontofel(f"Du kan inte {vad} ditt eget konto. "
                       "Byt eget lösenord under ”Byt lösenord”; be en annan "
                       "administratör om resten.")


def _inte_sista_admin(conn, rad, vad: str) -> None:
    if rad["roll"] == "admin" and _antal_admin(conn) <= 1:
        raise Kontofel(f"Det går inte att {vad} den sista administratören — "
                       "då finns ingen som kan hantera konton.")


def skapa(conn: sqlite3.Connection, anvandarnamn: str, roll: str) -> tuple[str, str]:
    """Skapar kontot med ett slumpat lösenord. Returnerar (användarnamn,
    lösenord i klartext) — det senare visas en gång och lagras aldrig."""
    namn = anvandarnamn.strip() or slumpa_anvandarnamn(conn)
    if not giltigt_anvandarnamn(namn):
        raise Kontofel("Användarnamnet får bara innehålla bokstäver, siffror, "
                       "punkt, bindestreck och understreck (2–50 tecken).")
    if roll not in ROLLER:
        raise Kontofel("Okänd roll.")
    if _finns_namn(conn, namn):
        raise Kontofel(f"Det finns redan ett konto som heter ”{namn}”.")
    losenord = slumpa_losenord()
    conn.execute(
        "INSERT INTO forvaltare (anvandarnamn, losen_hash, roll) VALUES (?, ?, ?)",
        (namn, hash_losen(losenord), roll),
    )
    return namn, losenord


def byt_roll(conn: sqlite3.Connection, konto_id: int, roll: str, aktor_id: int) -> str:
    """Returnerar kontots användarnamn för auditloggen. Slår igenom på
    kontots nästa request — rollen läses från databasen varje gång."""
    if roll not in ROLLER:
        raise Kontofel("Okänd roll.")
    _inte_sig_sjalv(konto_id, aktor_id, "ändra rollen på")
    rad = _hamta(conn, konto_id)
    if roll != "admin":
        _inte_sista_admin(conn, rad, "nedgradera")
    conn.execute("UPDATE forvaltare SET roll = ? WHERE id = ?", (roll, konto_id))
    return rad["anvandarnamn"]


def nytt_losenord(conn: sqlite3.Connection, konto_id: int, aktor_id: int) -> tuple[str, str]:
    """Slumpar ett nytt lösenord åt någon annan. Kontots alla sessioner dör
    direkt, eftersom sessionen bär en digest av lösenordshashen."""
    _inte_sig_sjalv(konto_id, aktor_id, "slumpa nytt lösenord åt")
    rad = _hamta(conn, konto_id)
    losenord = slumpa_losenord()
    conn.execute("UPDATE forvaltare SET losen_hash = ? WHERE id = ?",
                 (hash_losen(losenord), konto_id))
    return rad["anvandarnamn"], losenord


def ta_bort(conn: sqlite3.Connection, konto_id: int, aktor_id: int) -> str:
    _inte_sig_sjalv(konto_id, aktor_id, "ta bort")
    rad = _hamta(conn, konto_id)
    _inte_sista_admin(conn, rad, "ta bort")
    conn.execute("DELETE FROM forvaltare WHERE id = ?", (konto_id,))
    return rad["anvandarnamn"]


def byt_eget_losenord(conn: sqlite3.Connection, konto_id: int,
                      nuvarande: str, nytt: str, upprepat: str) -> str:
    """Returnerar den nya hashen så att routern kan uppdatera sessionens
    digest och den inloggade slipper loggas ut av sitt eget byte."""
    if nytt != upprepat:
        raise Kontofel("De två nya lösenorden skiljer sig åt.")
    if len(nytt) < MINSTA_LOSENORD:
        raise Kontofel(f"Det nya lösenordet måste vara minst {MINSTA_LOSENORD} tecken.")
    rad = conn.execute(
        "SELECT losen_hash FROM forvaltare WHERE id = ?", (konto_id,)
    ).fetchone()
    if rad is None or not verifiera_losen(rad["losen_hash"], nuvarande):
        raise Kontofel("Det nuvarande lösenordet stämmer inte.")
    ny_hash = hash_losen(nytt)
    conn.execute("UPDATE forvaltare SET losen_hash = ? WHERE id = ?", (ny_hash, konto_id))
    return ny_hash
