"""Medlemmarnas kommentarer — den öppna och den interna kommentaren på varje
svar (bedomning, migration 0009) — sedda från förvaltningen. Vyn
medlemskommentar ger en rad per icke-tom kommentar; en kommentar
identifieras av (medlem_id, funktion_id, falt).

Förvaltarna hanterar dem (migration 0013): läst eller arkiverad. Det gäller
bara förvaltningens vyer — medlemmens kommentar rörs aldrig."""

import sqlite3

from app.services import trad

# Kommentarsvyns filter: etikett och SQL-villkor på hanteringen. Ordningen
# är flikordningen; "olästa" är arbetslistan och därmed standard. Villkoren
# är hårdkodade — visningsnyckeln från URL:en väljer bara bland dem.
VISNINGAR = {
    "olästa": ("Olästa", "k.hantering IS NULL"),
    "lästa": ("Lästa", "k.hantering = 'läst'"),
    "arkiverade": ("Arkiverade", "k.hantering = 'arkiverad'"),
    "alla": ("Alla", "1"),
}
# Statusbyten från knapparna; "oläst" tar bort hanteringen.
STATUSAR = ("oläst", "läst", "arkiverad")
FALT = ("oppen", "intern")

# Ordningen inom en nod: olästa först, sedan medlemsordning, och den öppna
# kommentaren före den interna (CASE i stället för att lita på alfabetet).
_ORDNING = "m.namn, CASE k.falt WHEN 'oppen' THEN 0 ELSE 1 END"
_URVAL = (
    "SELECT k.*, m.namn AS medlem_namn FROM medlemskommentar k"
    " JOIN medlem m ON m.id = k.medlem_id"
)


def antal_per_nod(conn: sqlite3.Connection) -> dict[int, dict[str, int]]:
    """{nod_id: {"totalt": n, "olasta": n}} för de kommentarer som visas
    under noderna (olästa och lästa — arkiverade är undanlagda)."""
    return {
        r["funktion_id"]: {"totalt": r["totalt"], "olasta": r["olasta"]}
        for r in conn.execute(
            "SELECT funktion_id, COUNT(*) AS totalt,"
            " SUM(hantering IS NULL) AS olasta"
            " FROM medlemskommentar WHERE hantering IS NOT 'arkiverad'"
            " GROUP BY funktion_id"
        )
    }


def markera_antal(conn: sqlite3.Connection, noder: list[dict]) -> None:
    """Sätter "medlemskommentarer" på varje nod, även nästlade barn. Rader
    utan fältet renderas utan medlemskommentarer — så extern roll och
    exporterna aldrig visar dem."""
    antal = antal_per_nod(conn)
    stack = list(noder)
    while stack:
        nod = stack.pop()
        nod["medlemskommentarer"] = antal.get(nod["id"], {"totalt": 0, "olasta": 0})
        stack.extend(nod.get("barn", ()))


def for_nod(conn: sqlite3.Connection, nod_id: int) -> list[dict]:
    """Nodens synliga kommentarer (inte arkiverade), olästa först."""
    return [dict(r) for r in conn.execute(
        _URVAL + " WHERE k.funktion_id = ? AND k.hantering IS NOT 'arkiverad'"
        f" ORDER BY k.hantering IS NOT NULL, {_ORDNING}",
        (nod_id,),
    )]


def hamta(conn, medlem_id: int, funktion_id: int, falt: str) -> dict | None:
    rad = conn.execute(
        _URVAL + " WHERE k.medlem_id = ? AND k.funktion_id = ? AND k.falt = ?",
        (medlem_id, funktion_id, falt),
    ).fetchone()
    return dict(rad) if rad else None


def satt_status(conn, medlem_id: int, funktion_id: int, falt: str, status: str) -> None:
    """Oläst, läst eller arkiverad. hanterad stämplas vid varje byte."""
    if status not in STATUSAR:
        raise ValueError("Okänd status.")
    if status == "oläst":
        conn.execute(
            "DELETE FROM medlemskommentar_hantering"
            " WHERE medlem_id = ? AND funktion_id = ? AND falt = ?",
            (medlem_id, funktion_id, falt),
        )
        return
    conn.execute(
        "INSERT INTO medlemskommentar_hantering (medlem_id, funktion_id, falt, status)"
        " VALUES (?, ?, ?, ?) ON CONFLICT (medlem_id, funktion_id, falt) DO UPDATE SET"
        " status = excluded.status, hanterad = datetime('now')",
        (medlem_id, funktion_id, falt, status),
    )


def antal_per_visning(conn: sqlite3.Connection) -> dict[str, int]:
    """Siffrorna i kommentarsvyns flikar."""
    per_status = {"olästa": 0, "lästa": 0, "arkiverade": 0}
    for hantering, antal in conn.execute(
        "SELECT hantering, COUNT(*) FROM medlemskommentar GROUP BY hantering"
    ):
        per_status[{None: "olästa", "läst": "lästa", "arkiverad": "arkiverade"}[hantering]] = antal
    return per_status | {"alla": sum(per_status.values())}


def grupperat(conn: sqlite3.Connection, visa: str) -> list[dict]:
    """Kommentarerna i visningen grupperade per nod i trädordning, som de
    interna kommentarernas vy."""
    villkor = VISNINGAR.get(visa, VISNINGAR["olästa"])[1]
    per_nod: dict[int, list[dict]] = {}
    for k in conn.execute(_URVAL + f" WHERE {villkor} ORDER BY {_ORDNING}"):
        per_nod.setdefault(k["funktion_id"], []).append(dict(k))
    return trad.grupperat_per_nod(conn, per_nod)
