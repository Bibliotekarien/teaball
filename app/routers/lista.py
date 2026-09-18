"""Listvyn: alla noder som platt lista, sorterbar på skapande- och
uppdateringstid (migration 0005), med kravträdets filter (T4), en
snabbformulär-inbox högst upp och inline-redigering rad för rad med samma
formulär som kravträdet. Läsning kräver intern roll — vyn är ett
arbetsverktyg för förvaltare, extern har kravträdet; skapande och
redigering kräver admin. Standardsorteringen (skapad, fallande) gör att
nyskapade noder hamnar överst, direkt under formuläret."""

import logging
import sqlite3

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from app.auth.core import Principal, krav_admin, krav_intern
from app.auth.csrf import krav_csrf
from app.db import get_conn
from app.routers.trad import STATUSAR, TYPER
from app.services import trad as tjanst
from app.services.trad import LISTSORTERING
from app.web import is_htmx, templates

router = APIRouter(prefix="/lista", dependencies=[Depends(krav_csrf)])
audit = logging.getLogger("teaball.audit")

TOMT_FILTER = {"q": "", "typ": [], "status": [], "fas": "",
               "sortera": "skapad", "riktning": "fallande"}


def _listsvar(request, conn, principal, fel: str | None = None,
              filter: dict | None = None, aterstall_formular: bool = False):
    """List response: partial for htmx, full page (or redirect) otherwise.
    Same session-filter convention as kravträdet (_tradsvar): POST callers
    reuse the last GET's filter so the swapped list keeps matching the filter
    form, which lives outside #lista-rot and survives the swap."""
    filter = filter or request.session.get("lista_filter") or dict(TOMT_FILTER)
    if not is_htmx(request) and fel is None and request.method == "POST":
        return RedirectResponse("/lista", status_code=303)
    ctx = {
        "principal": principal,
        "rader": tjanst.hamta_lista(
            conn, filter["q"] or None, filter["typ"] or None,
            filter["status"] or None, filter["fas"] or None,
            sortera=filter["sortera"], stigande=filter["riktning"] == "stigande",
        ),
        "fel": fel,
        "filter": filter,
        "skrivbar": principal.roll == "admin",
        "detaljerad": request.session.get("lista_vy") == "detaljerad",
        "typer": TYPER,
        "statusar": STATUSAR,
        "val": tjanst.hamta_val(conn),
    }
    if is_htmx(request):
        mall = ("lista/_innehall_med_form.html"
                if aterstall_formular and fel is None else "lista/_innehall.html")
    else:
        mall = "lista/index.html"
    status_code = 400 if fel and not is_htmx(request) else 200
    return templates.TemplateResponse(request, mall, ctx, status_code=status_code)


@router.get("")
def visa_lista(
    request: Request,
    q: str = "", fas: str = "", vy: str = "",
    sortera: str = "", riktning: str = "",
    typ: list[str] = Query([]), status: list[str] = Query([]),
    principal: Principal = Depends(krav_intern),
    conn: sqlite3.Connection = Depends(get_conn),
):
    if vy in ("kompakt", "detaljerad"):
        request.session["lista_vy"] = vy
    filter = {
        "q": q, "typ": typ, "status": status, "fas": fas,
        "sortera": sortera if sortera in LISTSORTERING else "skapad",
        "riktning": "stigande" if riktning == "stigande" else "fallande",
    }
    request.session["lista_filter"] = filter
    return _listsvar(request, conn, principal, filter=filter)


@router.post("/nod")
def skapa_nod(
    request: Request,
    namn: str = Form(...),
    foralder_id: str = Form(""),
    typ: str = Form(...),
    status: str = Form(...),
    fas: str = Form(""),
    beskrivning: str = Form(""),
    synlig_externt: str = Form(""),
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Snabbformuläret: samma skapa-tjänst som kravträdet (nya noder hamnar
    först bland syskonen), men utan länkfälten — detaljer kompletteras med
    redigera på raden."""
    try:
        nod_id = tjanst.skapa_nod(
            conn, namn.strip()[:200],
            int(foralder_id) if foralder_id else None, typ, status,
            fas.strip()[:50] or None, beskrivning.strip()[:4000] or None,
            1 if synlig_externt else 0,
        )
    except sqlite3.IntegrityError as fel:
        conn.rollback()
        return _listsvar(request, conn, principal, fel=tjanst.regeltext(fel))
    conn.commit()
    audit.info("forvaltare=%s op=skapa nod=%s namn=%r via=lista",
               principal.namn, nod_id, namn)
    return _listsvar(request, conn, principal, aterstall_formular=True)


# --- inline-redigering ------------------------------------------------------

def _hamta_rad(conn, nod_id: int) -> dict:
    """The node as the list renders it (funktion_trad carries synlig_stig)."""
    rad = conn.execute("SELECT * FROM funktion_trad WHERE id = ?", (nod_id,)).fetchone()
    if rad is None:
        raise HTTPException(status_code=404, detail="Noden finns inte.")
    return dict(rad)


@router.get("/nod/{nod_id}/redigera")
def redigera_form(
    request: Request,
    nod_id: int,
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Kravträdets formulär (trad/_nod_form.html) riktat mot listan: sparandet
    postas hit, svaret swappar #lista-rot, och avbryt hämtar bara raden igen
    så sorteringen och filtret består. Utan htmx: helsidan, som i trädet."""
    nod = _hamta_rad(conn, nod_id)
    ctx = {
        "principal": principal,
        "nod": nod,
        "foralder_id": nod["foralder_id"],
        "val": tjanst.hamta_val(conn, exkludera_nod_id=nod_id),
        "typer": TYPER,
        "statusar": STATUSAR,
        "form_url": f"/lista/nod/{nod_id}",
        "form_mal": "#lista-rot",
        "avbryt_href": "/lista",
        "avbryt_hx": f"/lista/nod/{nod_id}/rad",
        "avbryt_mal": f"#rad-{nod_id}",
        "omslag": "li",
    }
    mall = "trad/_nod_form.html" if is_htmx(request) else "trad/nod_sida.html"
    return templates.TemplateResponse(request, mall, ctx)


@router.get("/nod/{nod_id}/rad")
def visa_rad(
    request: Request,
    nod_id: int,
    principal: Principal = Depends(krav_intern),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Avbryt i inline-redigeringen: bara raden, på formulärets plats."""
    if not is_htmx(request):
        return RedirectResponse("/lista", status_code=303)
    ctx = {
        "principal": principal,
        "n": _hamta_rad(conn, nod_id),
        "skrivbar": principal.roll == "admin",
        "detaljerad": request.session.get("lista_vy") == "detaljerad",
    }
    return templates.TemplateResponse(request, "lista/_rad.html", ctx)


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
    """Samma sparande som kravträdets, men svaret är listan (sessionens
    filter och sortering) — raden kan alltså byta plats, t.ex. hamna överst
    vid sortering på uppdaterad; lista.js scrollar dit."""
    _hamta_rad(conn, nod_id)
    try:
        dok = tjanst.validera_lank(lank_dokumentation, "Dokumentationslänken")
        jira = tjanst.validera_lank(lank_jira, "Jira-länken")
    except ValueError as fel:
        return _listsvar(request, conn, principal, fel=str(fel))
    try:
        tjanst.uppdatera_nod(
            conn, nod_id, namn.strip()[:200], tjanst.till_int(foralder_id), typ, status,
            fas.strip()[:50] or None, beskrivning.strip()[:4000] or None,
            1 if synlig_externt else 0, dok, jira,
        )
    except sqlite3.IntegrityError as fel:
        conn.rollback()
        return _listsvar(request, conn, principal, fel=tjanst.regeltext(fel))
    conn.commit()
    audit.info("forvaltare=%s op=uppdatera nod=%s namn=%r via=lista",
               principal.namn, nod_id, namn)
    return _listsvar(request, conn, principal)
