"""Assessment view, admin proxy mode (spec B1, B3–B6). The member-facing
variant (/svara, phase 2) reuses the same templates and service functions with
medlem_id taken from the member Principal instead of the URL."""

import sqlite3

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from app.auth.core import Principal, krav_forvaltare
from app.auth.csrf import krav_csrf
from app.db import get_conn
from app.services import bedomning as tjanst
from app.services import trad as trad_tjanst
from app.web import is_htmx, templates

router = APIRouter(prefix="/bedomning", dependencies=[Depends(krav_csrf)])


def _kontrollera_finns(conn, medlem_id: int, funktion_id: int) -> None:
    if not conn.execute("SELECT 1 FROM medlem WHERE id = ?", (medlem_id,)).fetchone():
        raise HTTPException(status_code=404, detail="Medlemmen finns inte.")
    if not conn.execute("SELECT 1 FROM funktion WHERE id = ?", (funktion_id,)).fetchone():
        raise HTTPException(status_code=404, detail="Noden finns inte.")


def _gren_eller_redirect(request, conn, medlem_id: int, funktion_id: int):
    """After a save: htmx gets the node's whole subtree re-rendered (an answer
    change flips descendants' 'ärvt' labels — A2/B6); no-JS gets a redirect
    back to the anchor."""
    if not is_htmx(request):
        return RedirectResponse(
            f"/bedomning?medlem_id={medlem_id}#gren-{funktion_id}", status_code=303
        )
    rotter = trad_tjanst.hamta_trad(conn)
    nod = trad_tjanst.hitta_nod(rotter, funktion_id)
    if nod is None:
        return Response(status_code=204)
    direkta, effektiva = tjanst.svarskarta(conn, medlem_id)
    return templates.TemplateResponse(
        request,
        "bedomning/_gren.html",
        {
            "n": nod,
            "direkta": direkta,
            "effektiva": effektiva,
            "delade": tjanst.delade_workarounds(conn, medlem_id),
            "bas": f"/bedomning/{medlem_id}",
            "visa_dold": True,
        },
    )


@router.get("")
def visa(
    request: Request,
    medlem_id: str = "",
    principal: Principal = Depends(krav_forvaltare),
    conn: sqlite3.Connection = Depends(get_conn),
):
    medlemmar = conn.execute("SELECT id, namn, kategori FROM medlem ORDER BY namn").fetchall()
    kanda = {m["id"] for m in medlemmar}
    vald = None
    if medlem_id.isdigit() and int(medlem_id) in kanda:
        vald = int(medlem_id)
    elif medlemmar:
        vald = medlemmar[0]["id"]

    ctx = {
        "principal": principal,
        "medlemmar": medlemmar,
        "vald": vald,
        "rotter": trad_tjanst.hamta_trad(conn) if vald else [],
        "bas": f"/bedomning/{vald}",
        "visa_dold": True,
    }
    if vald:
        ctx["direkta"], ctx["effektiva"] = tjanst.svarskarta(conn, vald)
        ctx["delade"] = tjanst.delade_workarounds(conn, vald)
    else:
        ctx["direkta"], ctx["effektiva"], ctx["delade"] = {}, {}, {}
    return templates.TemplateResponse(request, "bedomning/index.html", ctx)


@router.post("/{medlem_id}/{funktion_id}/svar")
def spara_svar(
    request: Request,
    medlem_id: int,
    funktion_id: int,
    svar: str = Form(...),
    principal: Principal = Depends(krav_forvaltare),
    conn: sqlite3.Connection = Depends(get_conn),
):
    _kontrollera_finns(conn, medlem_id, funktion_id)
    try:
        tjanst.satt_svar(conn, medlem_id, funktion_id, svar, f"proxy: {principal.namn}")
    except ValueError as fel:
        raise HTTPException(status_code=400, detail=str(fel))
    conn.commit()
    return _gren_eller_redirect(request, conn, medlem_id, funktion_id)


@router.post("/{medlem_id}/{funktion_id}/workaround")
def spara_workaround(
    request: Request,
    medlem_id: int,
    funktion_id: int,
    workaround: str = Form(""),
    workaround_delas: str = Form(""),
    principal: Principal = Depends(krav_forvaltare),
    conn: sqlite3.Connection = Depends(get_conn),
):
    tjanst.satt_workaround(conn, medlem_id, funktion_id, workaround, bool(workaround_delas))
    conn.commit()
    if is_htmx(request):
        return Response(status_code=204)  # autosave: nothing else changes visually
    return RedirectResponse(
        f"/bedomning?medlem_id={medlem_id}#gren-{funktion_id}", status_code=303
    )


@router.post("/{medlem_id}/{funktion_id}/kommentar")
def spara_kommentar(
    request: Request,
    medlem_id: int,
    funktion_id: int,
    kommentar: str = Form(""),
    principal: Principal = Depends(krav_forvaltare),
    conn: sqlite3.Connection = Depends(get_conn),
):
    tjanst.satt_kommentar(conn, medlem_id, funktion_id, kommentar)
    conn.commit()
    if is_htmx(request):
        return Response(status_code=204)
    return RedirectResponse(
        f"/bedomning?medlem_id={medlem_id}#gren-{funktion_id}", status_code=303
    )
