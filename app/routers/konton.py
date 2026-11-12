"""Admin-only accounts view: list staff accounts and manage them — create
(with a random password shown once), change role, issue a new random
password, delete. The rules that stop an admin from locking everyone out
live in services/konton.py; this router only renders their messages.

The one-time password is rendered straight into the POST response, never
put in the session: Starlette's session cookie is signed but not encrypted,
so a flashed password would sit base64-readable in the cookie until the next
page view. Same for the member answer link in medlemmar.py. Error messages
are not secret and still travel as a flash across the redirect."""

import logging
import sqlite3

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app.auth.core import Principal, krav_admin
from app.auth.csrf import krav_csrf
from app.db import get_conn
from app.services import konton as tjanst
from app.web import templates

router = APIRouter(prefix="/konton", dependencies=[Depends(krav_csrf)])
audit = logging.getLogger("teaball.audit")

FLASH_FEL = "konton_fel"


def _ctx(request: Request, conn, principal, fel: str | None = None,
         forslag_namn: str | None = None, nytt_losenord: dict | None = None):
    konton = conn.execute(
        "SELECT id, anvandarnamn, roll, senast_inloggad FROM forvaltare"
        " ORDER BY anvandarnamn"
    ).fetchall()
    return {
        "principal": principal,
        "konton": konton,
        "roller": tjanst.ROLLER,
        "forslag_namn": forslag_namn or tjanst.slumpa_anvandarnamn(conn),
        "nytt_losenord": nytt_losenord,
        "fel": fel or request.session.pop(FLASH_FEL, None),
    }


def _fel_och_tillbaka(request: Request, fel: tjanst.Kontofel) -> RedirectResponse:
    request.session[FLASH_FEL] = str(fel)
    return RedirectResponse("/konton", status_code=303)


@router.get("")
def lista(
    request: Request,
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    return templates.TemplateResponse(
        request, "konton/index.html", _ctx(request, conn, principal)
    )


@router.post("")
def skapa(
    request: Request,
    anvandarnamn: str = Form(""),
    roll: str = Form(...),
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Empty username → a random two-word one. The password is always random."""
    try:
        namn, losenord = tjanst.skapa(conn, anvandarnamn, roll)
    except tjanst.Kontofel as fel:
        # Keep what the admin typed so a typo is a one-character fix.
        return templates.TemplateResponse(
            request, "konton/index.html",
            _ctx(request, conn, principal, fel=str(fel),
                 forslag_namn=anvandarnamn.strip() or None),
            status_code=400,
        )
    conn.commit()
    audit.info("forvaltare=%s op=konto_skapa konto=%r roll=%s", principal.namn, namn, roll)
    return templates.TemplateResponse(
        request, "konton/index.html",
        _ctx(request, conn, principal, nytt_losenord={
            "anvandarnamn": namn, "losenord": losenord, "nytt_konto": True}),
    )


@router.post("/{konto_id}/roll")
def byt_roll(
    request: Request,
    konto_id: int,
    roll: str = Form(...),
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    try:
        namn = tjanst.byt_roll(conn, konto_id, roll, principal.forvaltare_id)
    except tjanst.Kontofel as fel:
        return _fel_och_tillbaka(request, fel)
    conn.commit()
    audit.info("forvaltare=%s op=konto_roll konto=%r roll=%s", principal.namn, namn, roll)
    return RedirectResponse("/konton", status_code=303)


@router.post("/{konto_id}/losenord")
def nytt_losenord(
    request: Request,
    konto_id: int,
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    try:
        namn, losenord = tjanst.nytt_losenord(conn, konto_id, principal.forvaltare_id)
    except tjanst.Kontofel as fel:
        return _fel_och_tillbaka(request, fel)
    conn.commit()
    audit.info("forvaltare=%s op=konto_nytt_losenord konto=%r", principal.namn, namn)
    return templates.TemplateResponse(
        request, "konton/index.html",
        _ctx(request, conn, principal, nytt_losenord={
            "anvandarnamn": namn, "losenord": losenord, "nytt_konto": False}),
    )


@router.get("/{konto_id}/ta-bort")
def ta_bort_bekrafta(
    request: Request,
    konto_id: int,
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Server-rendered confirmation, works without JS (same as medlemmar)."""
    rad = conn.execute(
        "SELECT anvandarnamn, roll FROM forvaltare WHERE id = ?", (konto_id,)
    ).fetchone()
    if rad is None:
        return RedirectResponse("/konton", status_code=303)
    return templates.TemplateResponse(
        request, "konton/ta_bort.html",
        {"principal": principal, "konto_id": konto_id,
         "anvandarnamn": rad["anvandarnamn"], "roll": rad["roll"]},
    )


@router.post("/{konto_id}/ta-bort")
def ta_bort(
    request: Request,
    konto_id: int,
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    try:
        namn = tjanst.ta_bort(conn, konto_id, principal.forvaltare_id)
    except tjanst.Kontofel as fel:
        return _fel_och_tillbaka(request, fel)
    conn.commit()
    audit.info("forvaltare=%s op=konto_ta_bort konto=%r", principal.namn, namn)
    return RedirectResponse("/konton", status_code=303)
