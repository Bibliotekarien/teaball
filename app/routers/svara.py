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
from app.services import roadmap as roadmap_tjanst
from app.services import trad as trad_tjanst
from app.web import is_htmx, templates

router = APIRouter(prefix="/svara", dependencies=[Depends(krav_csrf)])


def _starta_medlemssession(request: Request, conn, rad) -> RedirectResponse:
    # Stamped only when the link actually logs someone in — not on the switch
    # confirmation page, where the link was shown but not used. Data-minimal:
    # one timestamp, overwritten each time (see /integritet).
    conn.execute(
        "UPDATE medlem SET senast_anvand = datetime('now') WHERE id = ?", (rad["id"],)
    )
    conn.commit()
    request.session.clear()
    request.session[SESSION_MEDLEM] = rad["id"]
    request.session[SESSION_MEDLEM_HASH] = rad["token"]
    return RedirectResponse("/svara", status_code=303)


# Registreras FÖRE /{token}: FastAPI matchar i registreringsordning, annars
# tolkas "roadmap" som en ogiltig svarslänk. (Ett äkta token är 43 tecken
# base64 och kan aldrig vara ordet "roadmap", så ingen länk skuggas.)
@router.get("/roadmap")
def roadmap(
    request: Request,
    visa_krav: str = "",
    dolj_formagor: str = "",
    dolj_svar: str = "",
    principal: Principal = Depends(krav_medlem),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Medlemmens roadmap: samma urval som styrgruppens HTML-export och
    extern-rollen (endast synliga noder, transitivt), i medlemsvyns ram.
    Ingen bedömningsdata utom medlemmens egna effektiva svar, som visas per
    rad så att biblioteket ser om något de kallat go-live-krav ligger i en
    sen avgång. Inget redigeringsläge, inga exportlänkar."""
    _, effektiva = tjanst.svarskarta(conn, principal.medlem_id)
    return templates.TemplateResponse(
        request,
        "svara/roadmap.html",
        {
            "principal": principal,
            "grupper": roadmap_tjanst.roadmap_data(
                conn, visa_krav=visa_krav == "1", endast_synliga=True,
                dolj_formagor=dolj_formagor == "1"),
            "effektiva": effektiva,
            "ej_rankbara": tjanst.EJ_RANKBARA_STATUSAR,
            "visa_krav": visa_krav == "1",
            "dolj_formagor": dolj_formagor == "1",
            "dolj_svar": dolj_svar == "1",
        },
    )


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
    return _starta_medlemssession(request, conn, rad)


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
    return _starta_medlemssession(request, conn, rad)


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
    # Unfiltered on purpose — see the proxy view: the answered node must stay
    # visible for undo; the counter updates out-of-band.
    bedomda, kvar = tjanst.rakna_bedomt(rotter, effektiva)
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
            "bedomda": bedomda,
            "kvar": kvar,
        },
    )


@router.get("")
def visa(
    request: Request,
    dolj_bedomda: str = "",
    dolj_driftsatta: str = "",
    dolj_formagor: str = "",
    principal: Principal = Depends(krav_medlem),
    conn: sqlite3.Connection = Depends(get_conn),
):
    direkta, effektiva = tjanst.svarskarta(conn, principal.medlem_id)
    rotter = trad_tjanst.hamta_trad(conn, endast_synliga=True)
    # Counted before the filters — the counter must not shrink along with
    # what it measures.
    bedomda, kvar = tjanst.rakna_bedomt(rotter, effektiva)
    if dolj_formagor:
        rotter = tjanst.utan_formagor(rotter)
    if dolj_driftsatta:
        rotter = tjanst.utan_driftsatta(rotter)
    if dolj_bedomda:
        rotter = tjanst.utan_bedomda(rotter, effektiva)
    return templates.TemplateResponse(
        request,
        "svara/index.html",
        {
            "principal": principal,
            "rotter": rotter,
            "direkta": direkta,
            "effektiva": effektiva,
            "delade": tjanst.delade_workarounds(conn, principal.medlem_id),
            "bas": "/svara",
            "visa_dold": False,
            "bedomda": bedomda,
            "kvar": kvar,
            "dolj_bedomda": bool(dolj_bedomda),
            "dolj_driftsatta": bool(dolj_driftsatta),
            "dolj_formagor": bool(dolj_formagor),
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
    except ValueError as fel:
        raise HTTPException(status_code=400, detail=str(fel))
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
