"""Interna kommentarer på noderna (migration 0006). Ingen författare lagras
— se migrationen. Bara intern personal ser dem; skrivande och statusbyten
kräver admin, som all annan ändring."""

import sqlite3

from app.services import trad

# Kommentarsvyns filter: etikett och vilka statusar det visar. Ordningen är
# flikordningen; "öppna" är arbetslistan och därmed standard.
VISNINGAR = {
    "öppna": ("Öppna", ("öppen",)),
    "behandlade": ("Behandlade", ("behandlad",)),
    "dolda": ("Dolda", ("dold",)),
    "alla": ("Alla", ("öppen", "behandlad", "dold")),
}
STATUSAR = ("öppen", "behandlad", "dold")
MAX_LANGD = 4000


def antal_per_nod(conn: sqlite3.Connection) -> dict[int, dict[str, int]]:
    """{nod_id: {status: antal}} för de kommentarer som visas under noderna
    (öppna och behandlade — dolda är undanlagda)."""
    rader = conn.execute(
        "SELECT funktion_id, status, COUNT(*) AS antal FROM kommentar"
        " WHERE status != 'dold' GROUP BY funktion_id, status"
    ).fetchall()
    antal: dict[int, dict[str, int]] = {}
    for r in rader:
        antal.setdefault(r["funktion_id"], {})[r["status"]] = r["antal"]
    return antal


def markera_antal(conn: sqlite3.Connection, noder: list[dict]) -> None:
    """Sätter "kommentarer" ({status: antal}) på varje nod, även nästlade
    barn i trädet. Rader utan fältet renderas utan kommentarsdel — så
    anropare som inte markerar (extern roll, exporterna) visar inget."""
    antal = antal_per_nod(conn)
    stack = list(noder)
    while stack:
        nod = stack.pop()
        nod["kommentarer"] = antal.get(nod["id"], {})
        stack.extend(nod.get("barn", ()))


def for_nod(conn: sqlite3.Connection, nod_id: int) -> list[dict]:
    """Nodens synliga kommentarer: öppna först, sedan behandlade, nyast först
    inom varje."""
    return [dict(r) for r in conn.execute(
        "SELECT * FROM kommentar WHERE funktion_id = ? AND status != 'dold'"
        " ORDER BY status = 'behandlad', skapad DESC, id DESC",
        (nod_id,),
    )]


def skapa(conn: sqlite3.Connection, nod_id: int, text: str) -> int:
    text = text.strip()[:MAX_LANGD]
    if not text:
        raise ValueError("Kommentaren är tom.")
    return conn.execute(
        "INSERT INTO kommentar (funktion_id, text) VALUES (?, ?)", (nod_id, text)
    ).lastrowid


def hamta(conn: sqlite3.Connection, kommentar_id: int) -> dict | None:
    rad = conn.execute("SELECT * FROM kommentar WHERE id = ?", (kommentar_id,)).fetchone()
    return dict(rad) if rad else None


def satt_status(conn: sqlite3.Connection, kommentar_id: int, status: str) -> None:
    if status not in STATUSAR:
        raise ValueError("Okänd status.")
    conn.execute(
        "UPDATE kommentar SET status = ?,"
        " hanterad = CASE WHEN ? = 'öppen' THEN NULL ELSE datetime('now') END"
        " WHERE id = ?",
        (status, status, kommentar_id),
    )


def antal_per_visning(conn: sqlite3.Connection) -> dict[str, int]:
    """Siffrorna i kommentarsvyns flikar."""
    per_status = dict(conn.execute(
        "SELECT status, COUNT(*) FROM kommentar GROUP BY status"
    ).fetchall())
    return {visa: sum(per_status.get(s, 0) for s in statusar)
            for visa, (_, statusar) in VISNINGAR.items()}


def grupperat(conn: sqlite3.Connection, visa: str) -> list[dict]:
    """Kommentarerna i visningen grupperade per nod, noderna i trädordning
    (funktion_trad.vag) så vyn läses som trädet. Varje grupp: nodens rad ur
    funktion_trad + förfäderna som "stig" + "kommentarer" (äldst först —
    arbetslistan beta av uppifrån)."""
    statusar = VISNINGAR.get(visa, VISNINGAR["öppna"])[1]
    platshallare = ",".join("?" * len(statusar))
    kommentarer = conn.execute(
        f"SELECT * FROM kommentar WHERE status IN ({platshallare})"
        " ORDER BY skapad, id",
        statusar,
    ).fetchall()
    per_nod: dict[int, list[dict]] = {}
    for k in kommentarer:
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
