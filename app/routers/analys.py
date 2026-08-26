"""Analysis views (spec 5.3, admin only). Read-only GET pages with query
parameters — bookmarkable, JS-free; the A3 toggle is the ?arvda=1 parameter."""

import sqlite3

from fastapi import APIRouter, Depends, Query, Request

from app.auth.core import Principal, krav_forvaltare
from app.db import get_conn
from app.services import analys as tjanst
from app.web import templates

router = APIRouter(prefix="/analys")


@router.get("")
def rankning(
    request: Request,
    arvda: str = "",
    principal: Principal = Depends(krav_forvaltare),
    conn: sqlite3.Connection = Depends(get_conn),
):
    med_arvda = arvda == "1"
    return templates.TemplateResponse(
        request,
        "analys/index.html",
        {
            "principal": principal,
            "arvda": med_arvda,
            "rader": tjanst.rankning(conn, med_arvda),
            "workarounds": tjanst.workaround_bank(conn),
            "tackning": tjanst.tackning(conn),
        },
    )


@router.get("/medlemmar")
def medlemmar(
    request: Request,
    arvda: str = "",
    medlem_id: str = "",
    principal: Principal = Depends(krav_forvaltare),
    conn: sqlite3.Connection = Depends(get_conn),
):
    med_arvda = arvda == "1"
    alla = conn.execute("SELECT id, namn, kategori FROM medlem ORDER BY namn").fetchall()
    vald = int(medlem_id) if medlem_id.isdigit() else None
    svar, blockerare = ([], [])
    vald_namn = None
    if vald is not None:
        svar, blockerare = tjanst.medlemsprofil(conn, vald, med_arvda)
        rad = conn.execute("SELECT namn FROM medlem WHERE id = ?", (vald,)).fetchone()
        vald_namn = rad["namn"] if rad else None
    return templates.TemplateResponse(
        request,
        "analys/medlemmar.html",
        {
            "principal": principal,
            "arvda": med_arvda,
            "medlemmar": alla,
            "vald": vald,
            "vald_namn": vald_namn,
            "svar": svar,
            "blockerare": blockerare,
            "oversikt": tjanst.migreringsoversikt(conn, med_arvda),
            "tackning": tjanst.tackning(conn),
        },
    )


@router.get("/gemensamt")
def gemensamt(
    request: Request,
    arvda: str = "",
    funktion_id: str = "",
    medlem_id: list[str] = Query(default=[]),
    principal: Principal = Depends(krav_forvaltare),
    conn: sqlite3.Connection = Depends(get_conn),
):
    med_arvda = arvda == "1"
    valda_medlemmar = [int(m) for m in (medlem_id or []) if m.isdigit()]
    vald_funktion = int(funktion_id) if funktion_id.isdigit() else None

    noder = conn.execute("SELECT id, djup, namn FROM funktion_trad ORDER BY vag").fetchall()
    alla_medlemmar = conn.execute("SELECT id, namn, kategori FROM medlem ORDER BY namn").fetchall()

    kraver = tjanst.kraver_noden(conn, vald_funktion, med_arvda) if vald_funktion else []
    delade = tjanst.gemensamma_krav(conn, valda_medlemmar, med_arvda)
    vald_funktion_namn = None
    if vald_funktion:
        rad = conn.execute("SELECT namn FROM funktion WHERE id = ?", (vald_funktion,)).fetchone()
        vald_funktion_namn = rad["namn"] if rad else None

    return templates.TemplateResponse(
        request,
        "analys/gemensamt.html",
        {
            "principal": principal,
            "arvda": med_arvda,
            "noder": noder,
            "medlemmar": alla_medlemmar,
            "vald_funktion": vald_funktion,
            "vald_funktion_namn": vald_funktion_namn,
            "valda_medlemmar": valda_medlemmar,
            "kraver": kraver,
            "delade": delade,
        },
    )
