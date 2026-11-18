"""Medlemmarnas kommentarer — den öppna och den interna kommentaren på varje
svar (bedomning, migration 0009) — sedda från förvaltningen. Vyn
medlemskommentar ger en rad per icke-tom kommentar; en kommentar
identifieras av (medlem_id, funktion_id, falt).

Förvaltarna läskvitterar dem (migration 0013) och raderar dem när de
justerat formuleringarna. Att radera tömmer kommentaren på medlemmens svar —
den försvinner alltså även för medlemmen, men den gamla texten ligger kvar i
bedomning_historik (D2-triggern)."""

import sqlite3

from app.services import trad

# Kommentarsvyns filter: etikett och SQL-villkor på kvittensen. Ordningen är
# flikordningen; "olästa" är arbetslistan och därmed standard. Villkoren är
# hårdkodade — visningsnyckeln från URL:en väljer bara bland dem.
VISNINGAR = {
    "olästa": ("Olästa", "kvitterad IS NULL"),
    "lästa": ("Lästa", "kvitterad IS NOT NULL"),
    "alla": ("Alla", "1"),
}
FALT = {"oppen": "Öppen kommentar", "intern": "Intern kommentar"}
KOLUMN = {"oppen": "oppen_kommentar", "intern": "intern_kommentar"}

_URVAL = (
    "SELECT k.*, m.namn AS medlem_namn FROM medlemskommentar k"
    " JOIN medlem m ON m.id = k.medlem_id"
)


def antal_per_nod(conn: sqlite3.Connection) -> dict[int, dict[str, int]]:
    """{nod_id: {"totalt": n, "olasta": n}}."""
    return {
        r["funktion_id"]: {"totalt": r["totalt"], "olasta": r["olasta"]}
        for r in conn.execute(
            "SELECT funktion_id, COUNT(*) AS totalt,"
            " SUM(kvitterad IS NULL) AS olasta"
            " FROM medlemskommentar GROUP BY funktion_id"
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
    """Nodens kommentarer: olästa först, sedan i medlemsordning."""
    return [dict(r) for r in conn.execute(
        _URVAL + " WHERE k.funktion_id = ?"
        " ORDER BY k.kvitterad IS NOT NULL, m.namn, k.falt DESC",
        (nod_id,),
    )]


def hamta(conn, medlem_id: int, funktion_id: int, falt: str) -> dict | None:
    rad = conn.execute(
        _URVAL + " WHERE k.medlem_id = ? AND k.funktion_id = ? AND k.falt = ?",
        (medlem_id, funktion_id, falt),
    ).fetchone()
    return dict(rad) if rad else None


def kvittera(conn, medlem_id: int, funktion_id: int, falt: str, last: bool) -> None:
    """Markera läst (last=True) eller oläst igen."""
    if last:
        conn.execute(
            "INSERT INTO medlemskommentar_kvittens (medlem_id, funktion_id, falt)"
            " VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
            (medlem_id, funktion_id, falt),
        )
    else:
        conn.execute(
            "DELETE FROM medlemskommentar_kvittens"
            " WHERE medlem_id = ? AND funktion_id = ? AND falt = ?",
            (medlem_id, funktion_id, falt),
        )


def radera(conn, medlem_id: int, funktion_id: int, falt: str) -> None:
    """Tömmer kommentaren på svaret. Kvittensen rensas av triggern och den
    gamla texten hamnar i historiken. Svaret och den andra kommentaren
    står kvar."""
    if falt not in KOLUMN:
        raise ValueError("Okänd kommentar.")
    conn.execute(
        f"UPDATE bedomning SET {KOLUMN[falt]} = NULL"
        " WHERE medlem_id = ? AND funktion_id = ?",
        (medlem_id, funktion_id),
    )


def antal_per_visning(conn: sqlite3.Connection) -> dict[str, int]:
    """Siffrorna i kommentarsvyns flikar."""
    rad = conn.execute(
        "SELECT COUNT(*) AS alla, SUM(kvitterad IS NULL) AS olasta"
        " FROM medlemskommentar"
    ).fetchone()
    alla, olasta = rad["alla"], rad["olasta"] or 0
    return {"olästa": olasta, "lästa": alla - olasta, "alla": alla}


def grupperat(conn: sqlite3.Connection, visa: str) -> list[dict]:
    """Kommentarerna i visningen grupperade per nod i trädordning, som de
    interna kommentarernas vy: nodens rad ur funktion_trad + "stig" +
    "kommentarer" (medlemsordning)."""
    villkor = VISNINGAR.get(visa, VISNINGAR["olästa"])[1]
    per_nod: dict[int, list[dict]] = {}
    for k in conn.execute(
        _URVAL + f" WHERE {villkor} ORDER BY m.namn, k.falt DESC"
    ):
        per_nod.setdefault(k["funktion_id"], []).append(dict(k))
    if not per_nod:
        return []
    karta = trad._foralderkarta(conn)
    grupper = []
    for nod in conn.execute(
        f"SELECT * FROM funktion_trad WHERE id IN ({','.join('?' * len(per_nod))})"
        " ORDER BY vag",
        tuple(per_nod),
    ):
        nod = dict(nod)
        nod["stig"] = trad._stig(karta, nod["foralder_id"])
        grupper.append({"nod": nod, "kommentarer": per_nod[nod["id"]]})
    return grupper
