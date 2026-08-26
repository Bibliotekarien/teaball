"""Analysis queries (spec 5.3). Every function takes `arvda` — the A3 toggle —
and switches between the two column-compatible views bedomning_direkt (default)
and bedomning_effektiv. The view name is chosen from a hardcoded pair, never
from user input (S5)."""

import sqlite3


def _kalla(arvda: bool) -> str:
    return "bedomning_effektiv" if arvda else "bedomning_direkt"


def rankning(conn, arvda: bool = False):
    """N1: per node golive/kan_vanta/behovs_ej counts, sorted by blockers,
    with the N2 warning flag precomputed."""
    rows = conn.execute(
        f"""
        SELECT f.id, f.namn, f.status, f.fas,
               SUM(CASE WHEN b.svar = 'golive_krav' THEN 1 ELSE 0 END) AS golive,
               SUM(CASE WHEN b.svar = 'kan_vanta' THEN 1 ELSE 0 END) AS kan_vanta,
               SUM(CASE WHEN b.svar = 'behovs_ej' THEN 1 ELSE 0 END) AS behovs_ej
        FROM {_kalla(arvda)} b
        JOIN funktion f ON f.id = b.funktion_id
        GROUP BY f.id
        ORDER BY golive DESC, kan_vanta DESC, f.namn
        """
    ).fetchall()
    rader = []
    for r in rows:
        rad = dict(r)
        rad["totalt"] = r["golive"] + r["kan_vanta"] + r["behovs_ej"]
        # N2: someone blocks go-live on this, but it is only an idea or lies in 'senare'.
        rad["varning"] = r["golive"] > 0 and (r["status"] == "idé" or r["fas"] == "senare")
        rader.append(rad)
    max_totalt = max((r["totalt"] for r in rader), default=1)
    for rad in rader:
        rad["golive_pct"] = 100 * rad["golive"] / max_totalt
        rad["kan_vanta_pct"] = 100 * rad["kan_vanta"] / max_totalt
        rad["behovs_ej_pct"] = 100 * rad["behovs_ej"] / max_totalt
    return rader


def workaround_bank(conn):
    """N4: all workarounds per node — admins see everything, including unshared
    ones, with member names."""
    ut: dict[int, list[dict]] = {}
    for r in conn.execute(
        """
        SELECT b.funktion_id, b.workaround, b.workaround_delas, m.namn AS medlem_namn
        FROM bedomning b
        JOIN medlem m ON m.id = b.medlem_id
        WHERE b.workaround IS NOT NULL AND TRIM(b.workaround) != ''
        ORDER BY m.namn
        """
    ):
        ut.setdefault(r["funktion_id"], []).append(dict(r))
    return ut


def tackning(conn):
    """N3: coverage is always based on direct answers — silence must never be
    presented as 'behövs ej'."""
    totalt = conn.execute("SELECT COUNT(*) FROM medlem").fetchone()[0]
    svarande = conn.execute("SELECT COUNT(DISTINCT medlem_id) FROM bedomning").fetchone()[0]
    utan_svar = conn.execute(
        "SELECT namn FROM medlem WHERE id NOT IN (SELECT DISTINCT medlem_id FROM bedomning)"
        " ORDER BY namn"
    ).fetchall()
    return {"svarande": svarande, "totalt": totalt, "utan_svar": [r["namn"] for r in utan_svar]}


def medlemsprofil(conn, medlem_id: int, arvda: bool = False):
    """N5: all of the member's direct answers, plus outstanding blockers —
    their golive_krav nodes whose status is not 'befintlig'."""
    svar = conn.execute(
        """
        SELECT b.*, f.namn AS funktion_namn, f.status, f.fas
        FROM bedomning b
        JOIN funktion f ON f.id = b.funktion_id
        WHERE b.medlem_id = ?
        ORDER BY f.namn
        """,
        (medlem_id,),
    ).fetchall()
    blockerare = conn.execute(
        f"""
        SELECT f.id, f.namn, f.status, f.fas, b.arvd
        FROM {_kalla(arvda)} b
        JOIN funktion f ON f.id = b.funktion_id
        WHERE b.medlem_id = ? AND b.svar = 'golive_krav' AND f.status != 'befintlig'
        ORDER BY f.namn
        """,
        (medlem_id,),
    ).fetchall()
    return [dict(r) for r in svar], [dict(r) for r in blockerare]


def migreringsoversikt(conn, arvda: bool = False):
    """N6: members sorted by outstanding blockers ascending — those at the top
    can migrate first. Members without any answer sort last and are flagged,
    never presented as ready (N3)."""
    rows = conn.execute(
        f"""
        SELECT m.id, m.namn, m.kategori,
               (SELECT COUNT(*) FROM {_kalla(arvda)} b
                JOIN funktion f ON f.id = b.funktion_id
                WHERE b.medlem_id = m.id AND b.svar = 'golive_krav'
                  AND f.status != 'befintlig') AS blockerare,
               EXISTS (SELECT 1 FROM bedomning WHERE medlem_id = m.id) AS har_svarat
        FROM medlem m
        ORDER BY har_svarat DESC, blockerare ASC, m.namn
        """
    ).fetchall()
    return [dict(r) for r in rows]


def kraver_noden(conn, funktion_id: int, arvda: bool = False):
    """N7 (forward): which members — and categories — require the node for go-live."""
    rows = conn.execute(
        f"""
        SELECT m.id, m.namn, m.kategori, b.arvd
        FROM {_kalla(arvda)} b
        JOIN medlem m ON m.id = b.medlem_id
        WHERE b.funktion_id = ? AND b.svar = 'golive_krav'
        ORDER BY m.namn
        """,
        (funktion_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def gemensamma_krav(conn, medlem_ids: list[int], arvda: bool = False):
    """N7 (reverse): the go-live requirements every member in the subset shares."""
    if not medlem_ids:
        return []
    platshallare = ",".join("?" * len(medlem_ids))
    rows = conn.execute(
        f"""
        SELECT f.id, f.namn, f.status, f.fas
        FROM {_kalla(arvda)} b
        JOIN funktion f ON f.id = b.funktion_id
        WHERE b.svar = 'golive_krav' AND b.medlem_id IN ({platshallare})
        GROUP BY f.id
        HAVING COUNT(DISTINCT b.medlem_id) = ?
        ORDER BY f.namn
        """,
        (*medlem_ids, len(medlem_ids)),
    ).fetchall()
    return [dict(r) for r in rows]
