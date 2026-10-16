"""Kravträdet (spec 5.1). All staff roles may read (extern only the externally
visible subset); every mutation and edit form requires the admin role. Every
unsafe operation is a plain form POST that works without JavaScript; htmx
enhances the same endpoints with partial swaps. Structural changes always respond with the whole tree container
(#trad-rot) — simple and always consistent with the database."""

import logging
import sqlite3

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from app.auth.core import Principal, krav_admin, krav_forvaltare
from app.auth.csrf import krav_csrf
from app.db import get_conn
from app.services import kommentarer
from app.services import trad as tjanst
from app.web import is_htmx, templates

router = APIRouter(prefix="/trad", dependencies=[Depends(krav_csrf)])
audit = logging.getLogger("teaball.audit")

TYPER = ["förmåga", "funktion", "krav"]
STATUSAR = ["driftsatt", "planerad", "idé", "utreds", "utgår"]


def _tradsvar(request, conn, principal, fel: str | None = None, filter: dict | None = None,
              aterstall_formular: bool = False, foralder_id: int | None = None):
    """Tree response: partial for htmx, full page (or redirect) otherwise.
    With aterstall_formular (after a successful create over htmx) the partial
    also carries a fresh, empty node form out-of-band — parent preserved — so
    sibling after sibling can be entered without re-opening the form.

    POST callers pass no filter; the last GET's filter (session) is reused so
    the swapped tree keeps matching the filter form, which lives outside
    #trad-rot and survives the swap. Without it an edit while filtering swaps
    in the whole unfiltered tree under an untouched filter form."""
    filter = filter or request.session.get("trad_filter") \
        or {"q": "", "typ": [], "status": [], "fas": "", "dolj_dolda": False}
    if not is_htmx(request) and fel is None and request.method == "POST":
        return RedirectResponse("/trad", status_code=303)
    rotter = tjanst.hamta_trad(
        conn, filter["q"] or None, filter["typ"] or None,
        filter["status"] or None, filter["fas"] or None,
        # "Dölj dolda" gives staff the member selection — including the
        # subtree counts, so the bars then show what members see.
        endast_synliga=principal.roll == "extern" or filter.get("dolj_dolda", False),
    )
    # Internal comments never reach the extern role: unmarked rows render
    # without the comment counter and block.
    if principal.roll != "extern":
        kommentarer.markera_antal(conn, rotter)
    ctx = {
        "principal": principal,
        "rotter": rotter,
        "fel": fel,
        "filter": filter,
        "skrivbar": principal.roll == "admin",
        # Compact/detailed toggle, sticky per session (set in visa_trad).
        "detaljerad": request.session.get("trad_vy") == "detaljerad",
    }
    mall = "trad/_innehall.html" if is_htmx(request) else "trad/index.html"
    if is_htmx(request) and aterstall_formular and fel is None:
        mall = "trad/_innehall_med_form.html"
        ctx |= {"nod": None, "foralder_id": foralder_id,
                "val": tjanst.hamta_val(conn), "typer": TYPER, "statusar": STATUSAR}
    status_code = 400 if fel and not is_htmx(request) else 200
    return templates.TemplateResponse(request, mall, ctx, status_code=status_code)


@router.get("")
def visa_trad(
    request: Request,
    q: str = "", fas: str = "", vy: str = "", dolj_dolda: str = "",
    typ: list[str] = Query([]), status: list[str] = Query([]),
    principal: Principal = Depends(krav_forvaltare),
    conn: sqlite3.Connection = Depends(get_conn),
):
    if vy in ("kompakt", "detaljerad"):
        request.session["trad_vy"] = vy
    filter = {"q": q, "typ": typ, "status": status, "fas": fas, "dolj_dolda": bool(dolj_dolda)}
    # Remembered for POST responses (see _tradsvar). A bare GET /trad clears
    # it — exactly what the then-empty filter form shows.
    request.session["trad_filter"] = filter
    return _tradsvar(request, conn, principal, filter=filter)


# --- create/edit forms ------------------------------------------------------

def _formsvar(request, conn, principal, nod=None, foralder_id=None):
    ctx = {
        "principal": principal,
        "nod": nod,
        "foralder_id": nod["foralder_id"] if nod else foralder_id,
        "val": tjanst.hamta_val(conn, exkludera_nod_id=nod["id"] if nod else None),
        "typer": TYPER,
        "statusar": STATUSAR,
    }
    mall = "trad/_nod_form.html" if is_htmx(request) else "trad/nod_sida.html"
    return templates.TemplateResponse(request, mall, ctx)


@router.get("/nod/ny")
def ny_nod_form(
    request: Request,
    foralder_id: str = "",
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    return _formsvar(request, conn, principal, foralder_id=tjanst.till_int(foralder_id))


@router.get("/nod/namnkoll")
def namnkoll_nodnamn(
    request: Request,
    namn: str = "",
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Rådgivande dubblettkoll medan namnet på en ny nod skrivs (htmx).
    Jämförelsen görs i Python med casefold() — SQLite:s NOCASE viker bara
    ASCII, så Å/Ä/Ö skulle annars missas. Trädet är litet (hundratals noder),
    så att läsa alla namn är billigt. Blockerar inget: samma namn kan vara
    legitimt i olika grenar, varningen är bara en knuff."""
    sokt = namn.strip().casefold()
    antal = 0
    if sokt:
        rader = conn.execute("SELECT namn FROM funktion").fetchall()
        antal = sum(1 for rad in rader if rad["namn"].strip().casefold() == sokt)
    return templates.TemplateResponse(request, "trad/_namnkoll.html", {"antal": antal})


@router.get("/nod/{nod_id}/redigera")
def redigera_form(
    request: Request,
    nod_id: int,
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    nod = conn.execute("SELECT * FROM funktion WHERE id = ?", (nod_id,)).fetchone()
    if nod is None:
        raise HTTPException(status_code=404, detail="Noden finns inte.")
    return _formsvar(request, conn, principal, nod=dict(nod))


@router.post("/nod")
def skapa_nod(
    request: Request,
    namn: str = Form(...),
    foralder_id: str = Form(""),
    typ: str = Form(...),
    status: str = Form(...),
    fas: str = Form(""),
    beskrivning: str = Form(""),
    lank_dokumentation: str = Form(""),
    lank_jira: str = Form(""),
    synlig_externt: str = Form(""),
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    try:
        dok = tjanst.validera_lank(lank_dokumentation, "Dokumentationslänken")
        jira = tjanst.validera_lank(lank_jira, "Jira-länken")
    except ValueError as fel:
        return _tradsvar(request, conn, principal, fel=str(fel))
    try:
        nod_id = tjanst.skapa_nod(
            conn, namn.strip()[:200], tjanst.till_int(foralder_id), typ, status,
            fas.strip()[:50] or None, beskrivning.strip()[:4000] or None,
            1 if synlig_externt else 0, dok, jira,
        )
    except sqlite3.IntegrityError as fel:
        conn.rollback()
        return _tradsvar(request, conn, principal, fel=tjanst.regeltext(fel))
    conn.commit()
    audit.info("forvaltare=%s op=skapa nod=%s namn=%r", principal.namn, nod_id, namn)
    return _tradsvar(request, conn, principal,
                     aterstall_formular=True, foralder_id=tjanst.till_int(foralder_id))


@router.post("/nod/{nod_id}")
def uppdatera_nod(
    request: Request,
    nod_id: int,
    namn: str = Form(...),
    foralder_id: str = Form(""),
    typ: str = Form(...),
    status: str = Form(...),
    fas: str = Form(""),
    beskrivning: str = Form(""),
    lank_dokumentation: str = Form(""),
    lank_jira: str = Form(""),
    synlig_externt: str = Form(""),
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    try:
        dok = tjanst.validera_lank(lank_dokumentation, "Dokumentationslänken")
        jira = tjanst.validera_lank(lank_jira, "Jira-länken")
    except ValueError as fel:
        return _tradsvar(request, conn, principal, fel=str(fel))
    try:
        tjanst.uppdatera_nod(
            conn, nod_id, namn.strip()[:200], tjanst.till_int(foralder_id), typ, status,
            fas.strip()[:50] or None, beskrivning.strip()[:4000] or None,
            1 if synlig_externt else 0, dok, jira,
        )
    except sqlite3.IntegrityError as fel:
        conn.rollback()
        return _tradsvar(request, conn, principal, fel=tjanst.regeltext(fel))
    conn.commit()
    audit.info("forvaltare=%s op=uppdatera nod=%s namn=%r", principal.namn, nod_id, namn)
    return _tradsvar(request, conn, principal)


# --- move / reorder (shared by no-JS forms and SortableJS) ------------------

@router.post("/nod/{nod_id}/flytta")
def flytta(
    request: Request,
    nod_id: int,
    foralder_id: str = Form(""),
    position: str = Form(""),
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    try:
        tjanst.flytta_nod(conn, nod_id, tjanst.till_int(foralder_id), tjanst.till_int(position))
    except sqlite3.IntegrityError as fel:
        conn.rollback()
        return _tradsvar(request, conn, principal, fel=tjanst.regeltext(fel))
    conn.commit()
    audit.info("forvaltare=%s op=flytta nod=%s foralder=%s", principal.namn, nod_id, foralder_id)
    return _tradsvar(request, conn, principal)


@router.post("/nod/{nod_id}/ordna")
def ordna(
    request: Request,
    nod_id: int,
    riktning: str = Form(...),
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    tjanst.ordna_nod(conn, nod_id, riktning)
    conn.commit()
    audit.info("forvaltare=%s op=ordna nod=%s riktning=%s", principal.namn, nod_id, riktning)
    return _tradsvar(request, conn, principal)


@router.post("/sortera")
def sortera(
    request: Request,
    foralder_id: str = Form(""),
    nod_id: list[str] = Form([]),
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    try:
        tjanst.sortera_syskon(conn, tjanst.till_int(foralder_id), [int(n) for n in nod_id])
    except sqlite3.IntegrityError as fel:
        conn.rollback()
        return _tradsvar(request, conn, principal, fel=tjanst.regeltext(fel))
    conn.commit()
    audit.info("forvaltare=%s op=sortera foralder=%s ordning=%s", principal.namn, foralder_id, nod_id)
    return _tradsvar(request, conn, principal)


# --- visibility & delete ----------------------------------------------------

@router.post("/nod/{nod_id}/synlighet")
def vaxla_synlighet(
    request: Request,
    nod_id: int,
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    conn.execute(
        "UPDATE funktion SET synlig_externt = 1 - synlig_externt WHERE id = ?", (nod_id,)
    )
    conn.commit()
    audit.info("forvaltare=%s op=synlighet nod=%s", principal.namn, nod_id)
    return _tradsvar(request, conn, principal)


@router.get("/nod/{nod_id}/ta-bort")
def ta_bort_bekrafta(
    request: Request,
    nod_id: int,
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    nod = conn.execute("SELECT * FROM funktion WHERE id = ?", (nod_id,)).fetchone()
    if nod is None:
        raise HTTPException(status_code=404, detail="Noden finns inte.")
    antal_barn, antal_bedomningar = tjanst.borttagskonsekvens(conn, nod_id)
    ctx = {
        "principal": principal,
        "nod": dict(nod),
        "antal_barn": antal_barn,
        "antal_bedomningar": antal_bedomningar,
    }
    mall = "trad/_ta_bort.html" if is_htmx(request) else "trad/ta_bort_sida.html"
    return templates.TemplateResponse(request, mall, ctx)


@router.post("/nod/{nod_id}/ta-bort")
def ta_bort(
    request: Request,
    nod_id: int,
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    tjanst.ta_bort_nod(conn, nod_id)
    conn.commit()
    audit.info("forvaltare=%s op=ta_bort nod=%s", principal.namn, nod_id)
    return _tradsvar(request, conn, principal)
