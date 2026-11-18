"""Medlemmarnas kommentarer (den öppna och den interna på varje svar), sedda
från förvaltningen. Två ytor, som de interna kommentarerna:

* /kommentarer/medlemmar — arbetslistan: kommentarerna grupperade per nod i
  trädordning, filtrerade på läst/oläst (olästa som standard), där varje
  kommentar läskvitteras eller raderas för sig.
* nodblocket — under en rad i behovsträdet: nodens kommentarer, utfällda på
  begäran (htmx) från pillret på raden.

Läsa får alla interna — samma data visas redan i analysen. Att kvittera och
radera kräver admin. Extern roll når aldrig kommentarerna."""

import logging
import sqlite3

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.auth.core import Principal, krav_admin, krav_intern
from app.auth.csrf import krav_csrf
from app.db import get_conn
from app.services import medlemskommentarer as tjanst
from app.services import trad
from app.web import is_htmx, templates

router = APIRouter(prefix="/kommentarer/medlemmar", dependencies=[Depends(krav_csrf)])
audit = logging.getLogger("teaball.audit")


def _visning(request: Request, visa: str | None = None) -> str:
    """Senaste valda fliken (sessionen), så kvitteringens svar visar samma urval."""
    if visa in tjanst.VISNINGAR:
        request.session["medlemskommentar_visa"] = visa
        return visa
    sparad = request.session.get("medlemskommentar_visa")
    return sparad if sparad in tjanst.VISNINGAR else "olästa"


def _vysvar(request, conn, principal, visa: str):
    ctx = {
        "principal": principal,
        "visa": visa,
        "visningar": tjanst.VISNINGAR,
        "antal": tjanst.antal_per_visning(conn),
        "grupper": tjanst.grupperat(conn, visa),
        "skrivbar": principal.roll == "admin",
    }
    mall = ("kommentarer/_medlemmar_innehall.html" if is_htmx(request)
            else "kommentarer/medlemmar.html")
    return templates.TemplateResponse(request, mall, ctx)


def _nod(conn, nod_id: int) -> dict:
    rad = conn.execute("SELECT * FROM funktion_trad WHERE id = ?", (nod_id,)).fetchone()
    if rad is None:
        raise HTTPException(status_code=404, detail="Noden finns inte.")
    rad = dict(rad)
    rad["stig"] = trad.foraldrastig(conn, rad["foralder_id"])
    return rad


def _blocksvar(request, conn, principal, nod_id: int, oppen: bool):
    """Nodblocket. htmx: blocket plus radens pill out-of-band, så antalet
    följer med kvitteringar och raderingar. Utan JS: en egen sida för noden
    med blocket utfällt."""
    nod = _nod(conn, nod_id)
    oppen = oppen or not is_htmx(request)
    ctx = {
        "principal": principal,
        "nod": nod,
        "antal": tjanst.antal_per_nod(conn).get(nod_id, {"totalt": 0, "olasta": 0}),
        "kommentarer": tjanst.for_nod(conn, nod_id) if oppen else [],
        "oppen": oppen,
        "skrivbar": principal.roll == "admin",
    }
    mall = ("kommentarer/_medlemmar_nod_svar.html" if is_htmx(request)
            else "kommentarer/medlemmar_nod_sida.html")
    return templates.TemplateResponse(request, mall, ctx)


def _efter_andring(request, conn, principal, funktion_id: int, fran: str):
    """Rita om ytan ändringen gjordes från: nodblocket eller vyn."""
    if fran == "nod":
        if not is_htmx(request):
            return RedirectResponse(f"/kommentarer/medlemmar/nod/{funktion_id}",
                                    status_code=303)
        return _blocksvar(request, conn, principal, funktion_id, True)
    if not is_htmx(request):
        return RedirectResponse(f"/kommentarer/medlemmar#grupp-{funktion_id}",
                                status_code=303)
    return _vysvar(request, conn, principal, _visning(request))


def _kommentar(conn, medlem_id: int, funktion_id: int, falt: str) -> dict:
    kommentar = (tjanst.hamta(conn, medlem_id, funktion_id, falt)
                 if falt in tjanst.FALT else None)
    if kommentar is None:
        raise HTTPException(status_code=404, detail="Kommentaren finns inte.")
    return kommentar


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


@router.post("/{medlem_id}/{funktion_id}/{falt}/kvittera")
def kvittera(
    request: Request,
    medlem_id: int,
    funktion_id: int,
    falt: str,
    last: str = Form("1"),
    fran: str = Form("vy"),
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Markera läst (last=1) eller oläst igen (last=0)."""
    _kommentar(conn, medlem_id, funktion_id, falt)
    tjanst.kvittera(conn, medlem_id, funktion_id, falt, last == "1")
    conn.commit()
    return _efter_andring(request, conn, principal, funktion_id, fran)


@router.post("/{medlem_id}/{funktion_id}/{falt}/radera")
def radera(
    request: Request,
    medlem_id: int,
    funktion_id: int,
    falt: str,
    fran: str = Form("vy"),
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Tömmer kommentaren på medlemmens svar (svaret står kvar). Texten
    loggas inte — den finns i bedomning_historik."""
    _kommentar(conn, medlem_id, funktion_id, falt)
    tjanst.radera(conn, medlem_id, funktion_id, falt)
    conn.commit()
    audit.info("forvaltare=%s op=radera_medlemskommentar medlem=%s nod=%s falt=%s",
               principal.namn, medlem_id, funktion_id, falt)
    return _efter_andring(request, conn, principal, funktion_id, fran)
