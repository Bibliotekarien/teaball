"""Assessment operations (spec 5.2). Used by both the admin proxy mode (B1)
and the member view (B2) — callers decide medlem_id and besvarat_av."""

import sqlite3

GILTIGA_SVAR = {"golive_krav", "kan_vanta", "behovs_ej"}

# Statuses that take a node out of the assessment: driftsatt is already
# delivered and utgår will never be built — an answer on either says nothing
# about go-live. The UI hides the buttons; this is the backstop for direct
# POSTs (and for stale forms rendered before a status change).
EJ_RANKBARA_STATUSAR = {"driftsatt", "utgår"}


def svarskarta(conn, medlem_id: int):
    """(direct answers by funktion_id, effective answers by funktion_id) for one
    member. Effective rows carry kalla_namn for the 'ärvt: … (från …)' label (A2)."""
    direkta = {
        r["funktion_id"]: dict(r)
        for r in conn.execute("SELECT * FROM bedomning WHERE medlem_id = ?", (medlem_id,))
    }
    effektiva = {}
    for r in conn.execute(
        """
        SELECT e.funktion_id, e.kalla_funktion_id, e.svar, e.arvd, f.namn AS kalla_namn
        FROM bedomning_effektiv e
        JOIN funktion f ON f.id = e.kalla_funktion_id
        WHERE e.medlem_id = ?
        """,
        (medlem_id,),
    ):
        effektiva[r["funktion_id"]] = dict(r)
    return direkta, effektiva


def delade_workarounds(conn, medlem_id: int):
    """Other members' shared workarounds per node, anonymously (B8):
    {funktion_id: [text, ...]} — never exposes who wrote them."""
    ut: dict[int, list[str]] = {}
    for r in conn.execute(
        """
        SELECT funktion_id, workaround FROM bedomning
        WHERE workaround_delas = 1 AND workaround IS NOT NULL AND TRIM(workaround) != ''
          AND medlem_id != ?
        ORDER BY funktion_id, besvarat
        """,
        (medlem_id,),
    ):
        ut.setdefault(r["funktion_id"], []).append(r["workaround"])
    return ut


def satt_svar(conn, medlem_id: int, funktion_id: int, svar: str, besvarat_av: str):
    """B3: clicking the already-selected answer removes it; otherwise upsert.
    Changing the answer keeps workaround/comment (the old row goes to history
    via the D2 trigger). Returns the resulting answer, or None if removed."""
    if svar not in GILTIGA_SVAR:
        raise ValueError("Ogiltigt svarsalternativ.")
    status = conn.execute(
        "SELECT status FROM funktion WHERE id = ?", (funktion_id,)
    ).fetchone()
    if status and status["status"] in EJ_RANKBARA_STATUSAR:
        raise ValueError(
            f"Noden är {status['status']} och kan inte bedömas."
        )
    rad = conn.execute(
        "SELECT svar FROM bedomning WHERE medlem_id = ? AND funktion_id = ?",
        (medlem_id, funktion_id),
    ).fetchone()
    if rad and rad["svar"] == svar:
        conn.execute(
            "DELETE FROM bedomning WHERE medlem_id = ? AND funktion_id = ?",
            (medlem_id, funktion_id),
        )
        return None
    if rad:
        conn.execute(
            "UPDATE bedomning SET svar = ?, besvarat_av = ?, besvarat = datetime('now')"
            " WHERE medlem_id = ? AND funktion_id = ?",
            (svar, besvarat_av, medlem_id, funktion_id),
        )
    else:
        conn.execute(
            "INSERT INTO bedomning (medlem_id, funktion_id, svar, besvarat_av)"
            " VALUES (?, ?, ?, ?)",
            (medlem_id, funktion_id, svar, besvarat_av),
        )
    return svar


def satt_workaround(conn, medlem_id: int, funktion_id: int, workaround: str, delas: bool):
    """B4: only meaningful on an existing direct answer; no-op otherwise."""
    conn.execute(
        "UPDATE bedomning SET workaround = ?, workaround_delas = ?"
        " WHERE medlem_id = ? AND funktion_id = ?",
        (workaround.strip()[:4000] or None, 1 if delas else 0, medlem_id, funktion_id),
    )


def satt_kommentar(conn, medlem_id: int, funktion_id: int, kommentar: str):
    """B5: always private; requires an existing direct answer (the data model
    has no answer-less rows)."""
    conn.execute(
        "UPDATE bedomning SET kommentar = ? WHERE medlem_id = ? AND funktion_id = ?",
        (kommentar.strip()[:4000] or None, medlem_id, funktion_id),
    )
