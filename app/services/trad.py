"""Tree operations (spec 5.1). Shared by the no-JS forms and the SortableJS
endpoints — the drag-and-drop enhancement posts to the same functions.

The D1 cycle trigger is the authoritative guard; callers catch
sqlite3.IntegrityError with the 'CYKEL:' prefix and show the message inline.
"""

import sqlite3


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


def hamta_trad(conn, q=None, typ=None, status=None, fas=None, endast_synliga=False):
    """The whole tree in display order as nested dicts. With filters (T4),
    matching nodes are kept together with their ancestors for context.
    typ and status accept several values — OR within a filter, AND between.
    endast_synliga=True gives the member view: only synlig_stig = 1 (B7/T5)."""
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
    noder = {r["id"]: {**dict(r), "barn": []} for r in rows}

    inkludera = None
    if q or typ or status or fas:
        traffar = set()
        for r in rows:
            if q and q.lower() not in r["namn"].lower():
                continue
            if typ and r["typ"] not in typ:
                continue
            if status and r["status"] not in status:
                continue
            if fas and (r["fas"] or "") != fas:
                continue
            traffar.add(r["id"])
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
