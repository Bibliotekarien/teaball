"""Assessment operations (spec 5.2). Used by both the admin proxy mode (B1)
and the member view (B2) — callers decide medlem_id and besvarat_av."""

import sqlite3

GILTIGA_SVAR = {"golive_krav", "kan_vanta", "behovs_ej"}

# Statuses that take a node out of the assessment: driftsatt is already
# delivered and utgår will never be built — an answer on either says nothing
# about go-live. The UI hides the buttons; this is the backstop for direct
# POSTs (and for stale forms rendered before a status change).
EJ_RANKBARA_STATUSAR = {"driftsatt", "utgår"}


def ej_rankbar(nod) -> bool:
    """True when the node can't be assessed: a non-assessable status, or
    locked from ranking by a förvaltare (migration 0008). The lock is per
    node — like status it is not inherited by the children."""
    return nod["status"] in EJ_RANKBARA_STATUSAR or bool(nod["rankning_last"])


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


# Who sees an open comment (bedomning.oppen_delning, migration 0009), with
# the UI wording. Order is the picker's: least visible first, so the
# default is privat.
OPPEN_DELNING = {
    "privat": "bara förvaltarna",
    "anonym": "alla medlemmar, anonymt",
    "namn": "alla medlemmar, med organisationens namn",
}


def oppna_kommentarer(conn, medlem_id: int):
    """Other members' shared open comments per node (B8, migration 0009):
    {funktion_id: [{"text", "svar", "namn"}, ...]}. svar is the writer's
    current answer — the comment belongs to the answer row, so its colour
    follows when they change their mind. namn is the organisation only when
    the writer chose 'namn'; for 'anonym' the name is never even selected,
    so a template mistake can't leak it."""
    ut: dict[int, list[dict]] = {}
    for r in conn.execute(
        """
        SELECT b.funktion_id, b.oppen_kommentar AS text, b.svar,
               CASE WHEN b.oppen_delning = 'namn' THEN m.namn END AS namn
        FROM bedomning b
        JOIN medlem m ON m.id = b.medlem_id
        WHERE b.oppen_delning IN ('anonym', 'namn')
          AND b.oppen_kommentar IS NOT NULL AND TRIM(b.oppen_kommentar) != ''
          AND b.medlem_id != ?
        ORDER BY b.funktion_id, b.besvarat
        """,
        (medlem_id,),
    ):
        ut.setdefault(r["funktion_id"], []).append(dict(r))
    return ut


def rakna_bedomt(rotter, effektiva):
    """(bedömda, kvar) over the rendered tree's assessable nodes —
    driftsatt/utgår and locked nodes can't be answered and belong in neither
    column.
    An inherited answer counts as bedömd: the parent's answer holds until
    something more specific is given (A1/B6)."""
    bedomda = kvar = 0
    stack = list(rotter)
    while stack:
        n = stack.pop()
        stack.extend(n["barn"])
        if ej_rankbar(n):
            continue
        if n["id"] in effektiva:
            bedomda += 1
        else:
            kvar += 1
    return bedomda, kvar


def utan_bedomda(rotter, effektiva):
    """The 'dölj bedömda' filter: keep branches holding at least one assessable
    node without an effective answer; ancestors stay as context. An effective
    answer covers its whole subtree, so pruning an answered node never hides
    unanswered descendants — but a non-assessable node can have unanswered
    children, hence children are examined before the node's own state."""
    ut = []
    for n in rotter:
        barn = utan_bedomda(n["barn"], effektiva)
        kvar_har = not ej_rankbar(n) and n["id"] not in effektiva
        if barn or kvar_har:
            ut.append({**n, "barn": barn})
    return ut


def utan_formagor(rotter):
    """The 'dölj förmågor' filter: förmågor are hierarchy scaffolding in the
    assessment view, so hiding one lifts its children into its place instead
    of hiding the subtree. Inherited answers keep working — the källa label
    may name a hidden förmåga, which is the honest description."""
    ut = []
    for n in rotter:
        barn = utan_formagor(n["barn"])
        if n["typ"] == "förmåga":
            ut.extend(barn)
        else:
            ut.append({**n, "barn": barn})
    return ut


def utan_driftsatta(rotter):
    """The 'dölj driftsatta' filter: prune driftsatt nodes. Status is not
    inherited, so a driftsatt node can still hold assessable descendants —
    like in utan_bedomda it then stays as context instead of orphaning them."""
    ut = []
    for n in rotter:
        barn = utan_driftsatta(n["barn"])
        if barn or n["status"] != "driftsatt":
            ut.append({**n, "barn": barn})
    return ut


def satt_svar(conn, medlem_id: int, funktion_id: int, svar: str, besvarat_av: str):
    """B3: clicking the already-selected answer removes it; otherwise upsert.
    Changing the answer keeps both comments (the old row goes to history
    via the D2 trigger). Returns the resulting answer, or None if removed."""
    if svar not in GILTIGA_SVAR:
        raise ValueError("Ogiltigt svarsalternativ.")
    nod = conn.execute(
        "SELECT status, rankning_last FROM funktion WHERE id = ?", (funktion_id,)
    ).fetchone()
    if nod and nod["status"] in EJ_RANKBARA_STATUSAR:
        raise ValueError(
            f"Noden är {nod['status']} och kan inte bedömas."
        )
    if nod and nod["rankning_last"]:
        raise ValueError("Noden är låst från rankning och kan inte bedömas.")
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


def satt_oppen_kommentar(conn, medlem_id: int, funktion_id: int, text: str, delning: str):
    """B4 (migration 0009): the open comment and how it is shared — privat
    (förvaltarna only), anonym or namn (all members, with the organisation's
    name). Any answer may carry one. Only meaningful on an existing direct
    answer; no-op otherwise. An unknown delning falls back to privat, never
    to something more visible than the member asked for."""
    if delning not in OPPEN_DELNING:
        delning = "privat"
    conn.execute(
        "UPDATE bedomning SET oppen_kommentar = ?, oppen_delning = ?"
        " WHERE medlem_id = ? AND funktion_id = ?",
        (text.strip()[:4000] or None, delning, medlem_id, funktion_id),
    )


def satt_intern_kommentar(conn, medlem_id: int, funktion_id: int, text: str):
    """B5: always private to the member and förvaltarna; requires an
    existing direct answer (the data model has no answer-less rows)."""
    conn.execute(
        "UPDATE bedomning SET intern_kommentar = ? WHERE medlem_id = ? AND funktion_id = ?",
        (text.strip()[:4000] or None, medlem_id, funktion_id),
    )
