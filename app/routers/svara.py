"""Member assessment view (spec B2, B7): /svara/<token> exchanges the link for
a session; /svara is the same assessment UI as the proxy mode, locked to the
member's own answers and to externally visible nodes. medlem_id comes ONLY from
the Principal — never from the request (I5)."""

import sqlite3

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from app.auth import token as token_backend
from app.auth.core import (
    SESSION_MEDLEM,
    SESSION_MEDLEM_HASH,
    Principal,
    aktuell_principal,
    krav_medlem,
)
from app.auth.csrf import krav_csrf
from app.db import get_conn
from app.services import bedomning as tjanst
from app.services import trad as trad_tjanst
from app.web import is_htmx, templates

router = APIRouter(prefix="/svara", dependencies=[Depends(krav_csrf)])


def _starta_medlemssession(request: Request, rad) -> RedirectResponse:
    request.session.clear()
    request.session[SESSION_MEDLEM] = rad["id"]
    request.session[SESSION_MEDLEM_HASH] = rad["token"]
    return RedirectResponse("/svara", status_code=303)


@router.get("/{token}")
def logga_in_med_token(
    request: Request,
    token: str,
    conn: sqlite3.Connection = Depends(get_conn),
):
    rad = token_backend.verifiera(conn, token)
    if rad is None:
        return templates.TemplateResponse(
            request,
            "svara/ogiltig.html",
            {"principal": None},
            status_code=404,
        )
    # Login CSRF guard: a GET must not silently replace an existing session
    # (logging an admin out, or capturing the victim's answers in the link
    # owner's account). Ask for a POST-confirmed switch instead.
    if aktuell_principal(request, conn) is not None:
        # This is the only page served with a 200 on the token URL, so it is
        # the one place a click could leak the raw token in the Referer header.
        # no-referrer stops that at the source (Matomo masking is defence in
        # depth); the site-wide same-origin policy is deliberately overridden.
        return templates.TemplateResponse(
            request,
            "svara/vaxla.html",
            {"principal": None, "medlem_namn": rad["namn"], "token": token},
            headers={"Referrer-Policy": "no-referrer"},
        )
    return _starta_medlemssession(request, rad)


@router.post("/vaxla")
def vaxla_session(
    request: Request,
    token: str = Form(...),
    conn: sqlite3.Connection = Depends(get_conn),
):
    rad = token_backend.verifiera(conn, token)
    if rad is None:
        return templates.TemplateResponse(
            request, "svara/ogiltig.html", {"principal": None}, status_code=404
        )
    return _starta_medlemssession(request, rad)


def _kontrollera_synlig(conn, funktion_id: int) -> None:
    rad = conn.execute(
        "SELECT synlig_stig FROM funktion_trad WHERE id = ?", (funktion_id,)
    ).fetchone()
    if rad is None or not rad["synlig_stig"]:
        raise HTTPException(status_code=404)


def _gren_eller_redirect(request, conn, principal: Principal, funktion_id: int):
    if not is_htmx(request):
        return RedirectResponse(f"/svara#gren-{funktion_id}", status_code=303)
    rotter = trad_tjanst.hamta_trad(conn, endast_synliga=True)
    nod = trad_tjanst.hitta_nod(rotter, funktion_id)
    if nod is None:
        return Response(status_code=204)
    direkta, effektiva = tjanst.svarskarta(conn, principal.medlem_id)
    return templates.TemplateResponse(
        request,
        "bedomning/_gren.html",
        {
            "n": nod,
            "direkta": direkta,
            "effektiva": effektiva,
            "delade": tjanst.delade_workarounds(conn, principal.medlem_id),
            "bas": "/svara",
            "visa_dold": False,
        },
    )


@router.get("")
def visa(
    request: Request,
    principal: Principal = Depends(krav_medlem),
    conn: sqlite3.Connection = Depends(get_conn),
):
    direkta, effektiva = tjanst.svarskarta(conn, principal.medlem_id)
    return templates.TemplateResponse(
        request,
        "svara/index.html",
        {
            "principal": principal,
            "rotter": trad_tjanst.hamta_trad(conn, endast_synliga=True),
            "direkta": direkta,
            "effektiva": effektiva,
            "delade": tjanst.delade_workarounds(conn, principal.medlem_id),
            "bas": "/svara",
            "visa_dold": False,
        },
    )


@router.post("/{funktion_id}/svar")
def spara_svar(
    request: Request,
    funktion_id: int,
    svar: str = Form(...),
    principal: Principal = Depends(krav_medlem),
    conn: sqlite3.Connection = Depends(get_conn),
):
    _kontrollera_synlig(conn, funktion_id)
    try:
        tjanst.satt_svar(conn, principal.medlem_id, funktion_id, svar, principal.namn)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ogiltigt svarsalternativ.")
    conn.commit()
    return _gren_eller_redirect(request, conn, principal, funktion_id)


@router.post("/{funktion_id}/workaround")
def spara_workaround(
    request: Request,
    funktion_id: int,
    workaround: str = Form(""),
    workaround_delas: str = Form(""),
    principal: Principal = Depends(krav_medlem),
    conn: sqlite3.Connection = Depends(get_conn),
):
    _kontrollera_synlig(conn, funktion_id)
    tjanst.satt_workaround(
        conn, principal.medlem_id, funktion_id, workaround, bool(workaround_delas)
    )
    conn.commit()
    if is_htmx(request):
        return Response(status_code=204)
    return RedirectResponse(f"/svara#gren-{funktion_id}", status_code=303)


@router.post("/{funktion_id}/kommentar")
def spara_kommentar(
    request: Request,
    funktion_id: int,
    kommentar: str = Form(""),
    principal: Principal = Depends(krav_medlem),
    conn: sqlite3.Connection = Depends(get_conn),
):
    _kontrollera_synlig(conn, funktion_id)
    tjanst.satt_kommentar(conn, principal.medlem_id, funktion_id, kommentar)
    conn.commit()
    if is_htmx(request):
        return Response(status_code=204)
    return RedirectResponse(f"/svara#gren-{funktion_id}", status_code=303)
