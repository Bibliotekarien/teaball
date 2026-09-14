"""Tree operations (spec 5.1). Shared by the no-JS forms and the SortableJS
endpoints — the drag-and-drop enhancement posts to the same functions.

The database triggers are the authoritative guards (D1 cycles, avgångskravet);
callers catch sqlite3.IntegrityError and show regeltext() inline.
"""

import sqlite3

# Trigger error prefixes (db/views_triggers.sql). The Swedish tail after the
# prefix is written to be shown to the user as-is.
REGELPREFIX = ("CYKEL: ", "AVGÅNG: ")


def regeltext(fel: sqlite3.IntegrityError) -> str:
    """The user-facing message from a rule trigger's RAISE, or a generic
    fallback for IntegrityErrors that aren't ours (FK violations etc.)."""
    text = str(fel)
    for prefix in REGELPREFIX:
        if prefix in text:
            return text.split(prefix, 1)[1]
    return "Ändringen bröt mot en databasregel och avvisades."


def undergren_ids(conn: sqlite3.Connection, nod_id: int) -> set[int]:
    """The node itself and all its descendants."""
    rows = conn.execute(
        """
        WITH RECURSIVE undergren(id) AS (
            SELECT ?
            UNION ALL
            SELECT f.id FROM funktion f JOIN undergren u ON f.foralder_id = u.id
        )
        SELECT id FROM undergren
        """,
        (nod_id,),
    ).fetchall()
    return {r["id"] for r in rows}


def _traff(rad, q, typ, status, fas) -> bool:
    """The T4 filter predicate, shared by the tree and the list view so
    "same filters" stays literally true: OR within a filter, AND between."""
    if q and q.lower() not in rad["namn"].lower():
        return False
    if typ and rad["typ"] not in typ:
        return False
    if status and rad["status"] not in status:
        return False
    if fas and (rad["fas"] or "") != fas:
        return False
    return True


def hamta_trad(conn, q=None, typ=None, status=None, fas=None, endast_synliga=False):
    """The whole tree in display order as nested dicts. With filters (T4),
    matching nodes are kept together with their ancestors for context.
    typ and status accept several values — OR within a filter, AND between.
    endast_synliga=True gives the member view: only synlig_stig = 1 (B7/T5).

    Every node also carries its subtree summary: status_under (status →
    count of leaf descendants) and antal_under (all leaf descendants). Only
    leaves count — a node with children is structure, not content — which
    makes the figures structure-neutral (same content ⇒ same numbers however
    deeply it is grouped) and exactly additive: a parent's counts are the sum
    of its children's. Deliberately counted over the unfiltered rows — a
    status filter must not make the level-0/1 distribution bars lie about the
    branch's real state — but inside the endast_synliga selection, so members
    are never shown counts of hidden nodes."""
    if isinstance(typ, str):
        typ = [typ]
    if isinstance(status, str):
        status = [status]
    if endast_synliga:
        rows = conn.execute(
            "SELECT * FROM funktion_trad WHERE synlig_stig = 1 ORDER BY vag"
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM funktion_trad ORDER BY vag").fetchall()
    noder = {r["id"]: {**dict(r), "barn": [], "status_under": {}} for r in rows}

    # Leafness is judged within the selected rows: in the member view a node
    # whose children are all hidden IS a leaf in the tree the member sees.
    # Ancestor walk per leaf: O(noder × djup) — fine at this scale (hundreds).
    # A hidden node never has a visible descendant (synlig_stig is transitive),
    # so with endast_synliga every foralder_id still resolves inside noder.
    foraldrar = {r["foralder_id"] for r in rows if r["foralder_id"] is not None}
    for r in rows:
        if r["id"] in foraldrar:
            continue
        foralder_id = r["foralder_id"]
        while foralder_id is not None:
            fordelning = noder[foralder_id]["status_under"]
            fordelning[r["status"]] = fordelning.get(r["status"], 0) + 1
            foralder_id = noder[foralder_id]["foralder_id"]
    for nod in noder.values():
        nod["antal_under"] = sum(nod["status_under"].values())

    inkludera = None
    if q or typ or status or fas:
        traffar = {r["id"] for r in rows if _traff(r, q, typ, status, fas)}
        inkludera = set()
        for nod_id in traffar:
            aktuell = nod_id
            while aktuell is not None and aktuell not in inkludera:
                inkludera.add(aktuell)
                aktuell = noder[aktuell]["foralder_id"]

    rotter = []
    for r in rows:
        if inkludera is not None and r["id"] not in inkludera:
            continue
        nod = noder[r["id"]]
        if r["foralder_id"] is None:
            rotter.append(nod)
        else:
            noder[r["foralder_id"]]["barn"].append(nod)
    return rotter


LISTSORTERING = ("skapad", "uppdaterad")


def hamta_lista(conn, q=None, typ=None, status=None, fas=None,
                endast_synliga=False, sortera="skapad", stigande=False):
    """All nodes as a flat list for the list view: same filter semantics as
    hamta_trad (T4) but no ancestor context — the rows stand on their own.
    Sorted on skapad or uppdaterad; rows from before the stamps (NULL,
    migration 0005) always come last, whichever direction is chosen."""
    if isinstance(typ, str):
        typ = [typ]
    if isinstance(status, str):
        status = [status]
    kolumn = sortera if sortera in LISTSORTERING else "skapad"
    riktning = "ASC" if stigande else "DESC"
    synlighet = "WHERE synlig_stig = 1" if endast_synliga else ""
    rows = conn.execute(
        f"""
        SELECT * FROM funktion_trad {synlighet}
        ORDER BY {kolumn} IS NULL, {kolumn} {riktning}, id {riktning}
        """
    ).fetchall()
    return [dict(r) for r in rows if _traff(r, q, typ, status, fas)]


def hitta_nod(rotter: list[dict], nod_id: int) -> dict | None:
    """Locate a node (with its nested barn) in a tree built by hamta_trad."""
    for nod in rotter:
        if nod["id"] == nod_id:
            return nod
        traff = hitta_nod(nod["barn"], nod_id)
        if traff:
            return traff
    return None


def hamta_val(conn, exkludera_nod_id: int | None = None):
    """Parent-<select> options in display order, names indented by depth.
    When editing a node, its own subtree is excluded (would be a cycle)."""
    exkludera = undergren_ids(conn, exkludera_nod_id) if exkludera_nod_id else set()
    rows = conn.execute("SELECT id, namn, djup FROM funktion_trad ORDER BY vag").fetchall()
    return [
        {"id": r["id"], "etikett": ("   " * r["djup"]) + r["namn"]}
        for r in rows
        if r["id"] not in exkludera
    ]


def _syskon_ordning(conn, foralder_id):
    if foralder_id is None:
        rows = conn.execute(
            "SELECT id FROM funktion WHERE foralder_id IS NULL ORDER BY sortering, id"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id FROM funktion WHERE foralder_id = ? ORDER BY sortering, id",
            (foralder_id,),
        ).fetchall()
    return [r["id"] for r in rows]


def _normalisera(conn, ordning: list[int]):
    for i, nod_id in enumerate(ordning):
        conn.execute("UPDATE funktion SET sortering = ? WHERE id = ?", ((i + 1) * 10, nod_id))


def skapa_nod(conn, namn, foralder_id, typ, status, fas, beskrivning, synlig_externt,
              lank_dokumentation=None, lank_jira=None) -> int:
    cur = conn.execute(
        "INSERT INTO funktion (namn, foralder_id, typ, status, fas, beskrivning,"
        " synlig_externt, sortering, lank_dokumentation, lank_jira)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
        (namn, foralder_id, typ, status, fas, beskrivning, synlig_externt,
         lank_dokumentation, lank_jira),
    )
    nytt = cur.lastrowid
    # New nodes land first among their siblings (top of the root list when
    # parentless); sorting afterwards still wins — prepend and renormalize.
    ordning = [nytt] + [i for i in _syskon_ordning(conn, foralder_id) if i != nytt]
    _normalisera(conn, ordning)
    return nytt


def flytta_nod(conn, nod_id: int, ny_foralder_id: int | None, position: int | None = None):
    """Reparent (cycle-guarded by the D1 trigger) and place among the new siblings."""
    conn.execute("UPDATE funktion SET foralder_id = ? WHERE id = ?", (ny_foralder_id, nod_id))
    ordning = [i for i in _syskon_ordning(conn, ny_foralder_id) if i != nod_id]
    if position is None or position > len(ordning):
        position = len(ordning)
    ordning.insert(position, nod_id)
    _normalisera(conn, ordning)


def ordna_nod(conn, nod_id: int, riktning: str):
    """Move one step up or down within the sibling group (T3 no-JS path)."""
    rad = conn.execute("SELECT foralder_id FROM funktion WHERE id = ?", (nod_id,)).fetchone()
    if rad is None:
        return
    ordning = _syskon_ordning(conn, rad["foralder_id"])
    i = ordning.index(nod_id)
    j = i - 1 if riktning == "upp" else i + 1
    if 0 <= j < len(ordning):
        ordning[i], ordning[j] = ordning[j], ordning[i]
        _normalisera(conn, ordning)


def sortera_syskon(conn, foralder_id: int | None, nod_ids: list[int]):
    """SortableJS drop: the receiving sibling group's new order. Nodes dragged in
    from another parent are reparented here (cycle-guarded by the trigger)."""
    for nod_id in nod_ids:
        conn.execute(
            "UPDATE funktion SET foralder_id = ? WHERE id = ?", (foralder_id, nod_id)
        )
    _normalisera(conn, nod_ids)


def borttagskonsekvens(conn, nod_id: int) -> tuple[int, int]:
    """(descendant count, assessment count in the subtree) for the T2 confirmation."""
    ids = undergren_ids(conn, nod_id)
    platshallare = ",".join("?" * len(ids))
    antal_bedomningar = conn.execute(
        f"SELECT COUNT(*) FROM bedomning WHERE funktion_id IN ({platshallare})",
        tuple(ids),
    ).fetchone()[0]
    return len(ids) - 1, antal_bedomningar


def ta_bort_nod(conn, nod_id: int):
    """Delete the subtree bottom-up. Assessments are deleted explicitly first so
    the D2 trigger writes them to bedomning_historik (FK cascade would bypass
    nothing here — explicit delete makes the history guarantee unambiguous)."""
    rows = conn.execute(
        """
        WITH RECURSIVE undergren(id, djup) AS (
            SELECT ?, 0
            UNION ALL
            SELECT f.id, u.djup + 1 FROM funktion f JOIN undergren u ON f.foralder_id = u.id
        )
        SELECT id FROM undergren ORDER BY djup DESC
        """,
        (nod_id,),
    ).fetchall()
    for r in rows:
        conn.execute("DELETE FROM bedomning WHERE funktion_id = ?", (r["id"],))
        conn.execute("DELETE FROM funktion WHERE id = ?", (r["id"],))
