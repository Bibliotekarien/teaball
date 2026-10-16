"""Interna kommentarer på noderna. Två ytor:

* /kommentarer — arbetslistan: kommentarerna grupperade per nod i
  trädordning, filtrerade på status (öppna som standard), där varje
  kommentar bockas av för sig som behandlad eller döljs.
  Admin kan dessutom redigera noden inline från gruppens rubrik, med
  behovsträdets formulär.
* nodblocket — under en rad i listvyn och behovsträdet: nodens öppna och
  behandlade kommentarer, utfällda på begäran (htmx), med skrivfält.

Läsa och skriva kommentarer får alla interna (intern och admin; extern ser
aldrig kommentarerna). Att hantera dem — statusbyten och att redigera noden
härifrån — kräver admin. Ingen författare lagras eller visas."""

import logging
import sqlite3

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.auth.core import Principal, krav_admin, krav_intern
from app.auth.csrf import krav_csrf
from app.db import get_conn
from app.routers.trad import STATUSAR, TYPER
from app.services import kommentarer as tjanst
from app.services import trad
from app.web import is_htmx, templates

router = APIRouter(prefix="/kommentarer", dependencies=[Depends(krav_csrf)])
audit = logging.getLogger("teaball.audit")


def _visning(request: Request, visa: str | None = None) -> str:
    """Senaste valda fliken (sessionen), så statusbytens svar visar samma urval."""
    if visa in tjanst.VISNINGAR:
        request.session["kommentar_visa"] = visa
        return visa
    sparad = request.session.get("kommentar_visa")
    return sparad if sparad in tjanst.VISNINGAR else "öppna"


def _vysvar(request, conn, principal, visa: str, fel: str | None = None):
    ctx = {
        "fel": fel,
        "principal": principal,
        "visa": visa,
        "visningar": tjanst.VISNINGAR,
        "antal": tjanst.antal_per_visning(conn),
        "grupper": tjanst.grupperat(conn, visa),
        "skrivbar": principal.roll == "admin",
    }
    mall = "kommentarer/_innehall.html" if is_htmx(request) else "kommentarer/index.html"
    status_code = 400 if fel and not is_htmx(request) else 200
    return templates.TemplateResponse(request, mall, ctx, status_code=status_code)


def _nod(conn, nod_id: int) -> dict:
    rad = conn.execute("SELECT * FROM funktion_trad WHERE id = ?", (nod_id,)).fetchone()
    if rad is None:
        raise HTTPException(status_code=404, detail="Noden finns inte.")
    rad = dict(rad)
    rad["stig"] = trad.foraldrastig(conn, rad["foralder_id"])
    return rad


def _blocksvar(request, conn, principal, nod_id: int, oppen: bool, fel: str | None = None):
    """Nodblocket. htmx: bara blocket (utfällt eller hopfällt) plus nodradens
    räknare out-of-band, så siffran följer med nya kommentarer och statusbyten.
    Utan JS: en egen sida för noden med samma block utfällt."""
    nod = _nod(conn, nod_id)
    antal = tjanst.antal_per_nod(conn).get(nod_id, {})
    ctx = {
        "principal": principal,
        "nod": nod,
        "antal": antal,
        "kommentarer": tjanst.for_nod(conn, nod_id) if oppen or not is_htmx(request) else [],
        "oppen": oppen or not is_htmx(request),
        "fel": fel,
        "skrivbar": principal.roll == "admin",
    }
    mall = "kommentarer/_nod_svar.html" if is_htmx(request) else "kommentarer/nod_sida.html"
    status_code = 400 if fel and not is_htmx(request) else 200
    return templates.TemplateResponse(request, mall, ctx, status_code=status_code)


@router.get("")
def visa_kommentarer(
    request: Request,
    visa: str = "",
    principal: Principal = Depends(krav_intern),
    conn: sqlite3.Connection = Depends(get_conn),
):
    return _vysvar(request, conn, principal, _visning(request, visa))


@router.get("/nod/{nod_id}")
def visa_nod(
    request: Request,
    nod_id: int,
    oppen: int = 1,
    principal: Principal = Depends(krav_intern),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Fäll ut (oppen=1) eller ihop (oppen=0) nodblocket."""
    return _blocksvar(request, conn, principal, nod_id, bool(oppen))


@router.post("/nod/{nod_id}")
def skapa_kommentar(
    request: Request,
    nod_id: int,
    text: str = Form(""),
    principal: Principal = Depends(krav_intern),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Alla interna får skriva — det är att hantera kommentarerna som är admins."""
    _nod(conn, nod_id)
    try:
        kommentar_id = tjanst.skapa(conn, nod_id, text)
    except ValueError as fel:
        return _blocksvar(request, conn, principal, nod_id, True, fel=str(fel))
    conn.commit()
    # Varken text eller förvaltare loggas: kommentarerna ska inte gå att
    # knyta till någon ("inga namn"), och loggen ska inte bära innehållet.
    audit.info("op=kommentera nod=%s kommentar=%s", nod_id, kommentar_id)
    if not is_htmx(request):
        return RedirectResponse(f"/kommentarer/nod/{nod_id}", status_code=303)
    return _blocksvar(request, conn, principal, nod_id, True)


@router.post("/{kommentar_id}/status")
def byt_status(
    request: Request,
    kommentar_id: int,
    status: str = Form(...),
    fran: str = Form("vy"),
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Bocka av (behandlad), dölj eller öppna igen. fran säger vilken yta
    som ska ritas om: kommentarsvyn (standard) eller nodblocket."""
    kommentar = tjanst.hamta(conn, kommentar_id)
    if kommentar is None:
        raise HTTPException(status_code=404, detail="Kommentaren finns inte.")
    try:
        tjanst.satt_status(conn, kommentar_id, status)
    except ValueError:
        raise HTTPException(status_code=400, detail="Okänd status.")
    conn.commit()
    audit.info("op=kommentar_status kommentar=%s status=%s", kommentar_id, status)
    nod_id = kommentar["funktion_id"]
    if fran == "nod":
        if not is_htmx(request):
            return RedirectResponse(f"/kommentarer/nod/{nod_id}", status_code=303)
        return _blocksvar(request, conn, principal, nod_id, True)
    if not is_htmx(request):
        return RedirectResponse(f"/kommentarer#rad-{nod_id}", status_code=303)
    return _vysvar(request, conn, principal, _visning(request))


# --- redigera noden inline i kommentarsvyn ------------------------------------

@router.get("/nod/{nod_id}/redigera")
def redigera_form(
    request: Request,
    nod_id: int,
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Behovsträdets formulär (trad/_nod_form.html) i gruppens rubrik: det
    ersätter rubriken (#rad-<id>), sparandet swappar hela vyn och avbryt
    hämtar bara rubriken igen. Utan htmx: helsidan, som i trädet och listan."""
    nod = _nod(conn, nod_id)
    ctx = {
        "principal": principal,
        "nod": nod,
        "foralder_id": nod["foralder_id"],
        "val": trad.hamta_val(conn, exkludera_nod_id=nod_id),
        "typer": TYPER,
        "statusar": STATUSAR,
        "form_url": f"/kommentarer/nod/{nod_id}/redigera",
        "form_mal": "#kommentarer-rot",
        "avbryt_href": f"/kommentarer#rad-{nod_id}",
        "avbryt_hx": f"/kommentarer/nod/{nod_id}/rubrik",
        "avbryt_mal": f"#rad-{nod_id}",
        "omslag": "header",
    }
    mall = "trad/_nod_form.html" if is_htmx(request) else "trad/nod_sida.html"
    return templates.TemplateResponse(request, mall, ctx)


@router.get("/nod/{nod_id}/rubrik")
def visa_rubrik(
    request: Request,
    nod_id: int,
    principal: Principal = Depends(krav_intern),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Avbryt i inline-redigeringen: bara rubriken, på formulärets plats."""
    if not is_htmx(request):
        return RedirectResponse(f"/kommentarer#rad-{nod_id}", status_code=303)
    ctx = {"principal": principal, "n": _nod(conn, nod_id),
           "skrivbar": principal.roll == "admin"}
    return templates.TemplateResponse(request, "kommentarer/_rubrik.html", ctx)


@router.post("/nod/{nod_id}/redigera")
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
    """Samma sparande som behovsträdets och listans; svaret är kommentarsvyn
    med sessionens flik, så gruppen visar nodens nya namn och status."""
    _nod(conn, nod_id)
    visa = _visning(request)
    try:
        dok = trad.validera_lank(lank_dokumentation, "Dokumentationslänken")
        jira = trad.validera_lank(lank_jira, "Jira-länken")
    except ValueError as fel:
        return _vysvar(request, conn, principal, visa, fel=str(fel))
    try:
        trad.uppdatera_nod(
            conn, nod_id, namn.strip()[:200], trad.till_int(foralder_id), typ, status,
            fas.strip()[:50] or None, beskrivning.strip()[:4000] or None,
            1 if synlig_externt else 0, dok, jira,
        )
    except sqlite3.IntegrityError as fel:
        conn.rollback()
        return _vysvar(request, conn, principal, visa, fel=trad.regeltext(fel))
    conn.commit()
    audit.info("forvaltare=%s op=uppdatera nod=%s namn=%r via=kommentarer",
               principal.namn, nod_id, namn)
    if not is_htmx(request):
        return RedirectResponse(f"/kommentarer#rad-{nod_id}", status_code=303)
    return _vysvar(request, conn, principal, visa)
