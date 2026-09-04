"""Admin login/logout (spec S1). Member token entry lives in routers/svara.py (phase 2)."""

import sqlite3
import time

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app.auth import password
from app.auth.core import SESSION_FORVALTARE, SESSION_FORVALTARE_HASH, losen_digest
from app.auth.csrf import krav_csrf
from app.db import get_conn
from app.web import templates

router = APIRouter(dependencies=[Depends(krav_csrf)])

# Simple in-memory login throttle: after MAX_FORSOK failures for an
# (ip, username) pair, further attempts are rejected until the window passes.
# Single-process app, so a dict suffices; a restart resetting it is acceptable.
MAX_FORSOK = 5
SPARR_SEKUNDER = 300
_misslyckanden: dict[tuple[str, str], tuple[int, float]] = {}


def _sparrad(nyckel: tuple[str, str]) -> bool:
    antal, senast = _misslyckanden.get(nyckel, (0, 0.0))
    if antal >= MAX_FORSOK and time.monotonic() - senast < SPARR_SEKUNDER:
        return True
    if antal >= MAX_FORSOK:
        _misslyckanden.pop(nyckel, None)  # window passed — start over
    return False


def _registrera_misslyckande(nyckel: tuple[str, str]) -> None:
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
    nyckel = (request.client.host if request.client else "?", anvandarnamn.strip())
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
    request.session.clear()  # fresh session id state on login (no fixation)
    request.session[SESSION_FORVALTARE] = principal.forvaltare_id
    request.session[SESSION_FORVALTARE_HASH] = losen_digest(rad["losen_hash"])
    return RedirectResponse("/trad", status_code=303)


@router.post("/logout")
def logga_ut(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
