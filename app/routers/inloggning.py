"""Admin login/logout (spec S1). Member token entry lives in routers/svara.py (phase 2)."""

import logging
import sqlite3
import time

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app import organisationer
from app.auth import password
from app.auth.core import (
    SESSION_FORVALTARE,
    SESSION_FORVALTARE_HASH,
    Principal,
    krav_forvaltare,
    losen_digest,
    starta_session,
)
from app.auth.csrf import krav_csrf
from app.db import get_conn
from app.services import konton as konton_tjanst
from app.web import templates

router = APIRouter(dependencies=[Depends(krav_csrf)])
audit = logging.getLogger("teaball.audit")

# Simple in-memory login throttle: after MAX_FORSOK failures for an
# (ip, organisation, username) key, further attempts are rejected until the window passes.
# Single-process app, so a dict suffices; a restart resetting it is acceptable.
MAX_FORSOK = 5
SPARR_SEKUNDER = 300
# (ip, organisation, username): the same username in another organisation is
# another account and must not share its lockout.
Nyckel = tuple[str, str, str]
_misslyckanden: dict[Nyckel, tuple[int, float]] = {}


def _nyckel(request: Request, anvandarnamn: str) -> Nyckel:
    return (request.client.host if request.client else "?",
            organisationer.aktuell().nyckel, anvandarnamn)


def _sparrad(nyckel: Nyckel) -> bool:
    antal, senast = _misslyckanden.get(nyckel, (0, 0.0))
    if antal >= MAX_FORSOK and time.monotonic() - senast < SPARR_SEKUNDER:
        return True
    if antal >= MAX_FORSOK:
        _misslyckanden.pop(nyckel, None)  # window passed — start over
    return False


def _registrera_misslyckande(nyckel: Nyckel) -> None:
    antal, _ = _misslyckanden.get(nyckel, (0, 0.0))
    _misslyckanden[nyckel] = (antal + 1, time.monotonic())


@router.get("/login")
def login_sida(request: Request):
    return templates.TemplateResponse(
        request, "auth/login.html", {"principal": None, "fel": None}
    )


@router.post("/login")
def logga_in(
    request: Request,
    anvandarnamn: str = Form(...),
    losenord: str = Form(...),
    conn: sqlite3.Connection = Depends(get_conn),
):
    nyckel = _nyckel(request, anvandarnamn.strip())
    if _sparrad(nyckel):
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"principal": None,
             "fel": "För många misslyckade försök — vänta några minuter och försök igen."},
            status_code=429,
        )
    principal = password.verifiera(conn, anvandarnamn.strip(), losenord)
    if principal is None:
        _registrera_misslyckande(nyckel)
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"principal": None, "fel": "Fel användarnamn eller lösenord."},
            status_code=401,
        )
    _misslyckanden.pop(nyckel, None)
    # Data-minimal activity stamp for /konton: a single timestamp overwritten
    # on each login — no history (see /integritet).
    conn.execute(
        "UPDATE forvaltare SET senast_inloggad = datetime('now') WHERE id = ?",
        (principal.forvaltare_id,),
    )
    conn.commit()
    rad = conn.execute(
        "SELECT losen_hash FROM forvaltare WHERE id = ?", (principal.forvaltare_id,)
    ).fetchone()
    starta_session(request, **{
        SESSION_FORVALTARE: principal.forvaltare_id,
        SESSION_FORVALTARE_HASH: losen_digest(rad["losen_hash"]),
    })
    return RedirectResponse("/trad", status_code=303)


@router.post("/logout")
def logga_ut(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# Byte av eget lösenord — alla förvaltarroller, även extern. Ligger här och
# inte under /konton eftersom /konton är admin-only.
@router.get("/losenord")
def losenord_sida(
    request: Request,
    principal: Principal = Depends(krav_forvaltare),
):
    return templates.TemplateResponse(
        request, "auth/losenord.html",
        {"principal": principal, "fel": None, "klart": False,
         "minsta": konton_tjanst.MINSTA_LOSENORD},
    )


@router.post("/losenord")
def byt_losenord(
    request: Request,
    nuvarande: str = Form(...),
    nytt: str = Form(...),
    upprepat: str = Form(...),
    principal: Principal = Depends(krav_forvaltare),
    conn: sqlite3.Connection = Depends(get_conn),
):
    # Samma throttle som /login: den som kommit över en öppen session ska
    # inte kunna gissa sig fram till det nuvarande lösenordet och låsa ute
    # ägaren. Nyckeln delas med /login så båda vägarna räknas ihop.
    nyckel = _nyckel(request, principal.namn)
    sida = {"principal": principal, "klart": False,
            "minsta": konton_tjanst.MINSTA_LOSENORD}
    if _sparrad(nyckel):
        return templates.TemplateResponse(
            request, "auth/losenord.html",
            {**sida, "fel": "För många misslyckade försök — vänta några minuter "
                            "och försök igen."},
            status_code=429,
        )
    try:
        ny_hash = konton_tjanst.byt_eget_losenord(
            conn, principal.forvaltare_id, nuvarande, nytt, upprepat)
    except konton_tjanst.FelLosenord as fel:
        _registrera_misslyckande(nyckel)
        return templates.TemplateResponse(
            request, "auth/losenord.html", {**sida, "fel": str(fel)}, status_code=400)
    except konton_tjanst.Kontofel as fel:
        return templates.TemplateResponse(
            request, "auth/losenord.html", {**sida, "fel": str(fel)}, status_code=400)
    _misslyckanden.pop(nyckel, None)
    conn.commit()
    # Sessionen bär en digest av hashen: uppdatera den här sessionen så den
    # överlever bytet, medan kontots övriga sessioner loggas ut.
    request.session[SESSION_FORVALTARE_HASH] = losen_digest(ny_hash)
    audit.info("forvaltare=%s op=eget_losenord", principal.namn)
    return templates.TemplateResponse(
        request, "auth/losenord.html",
        {"principal": principal, "fel": None, "klart": True,
         "minsta": konton_tjanst.MINSTA_LOSENORD},
    )
