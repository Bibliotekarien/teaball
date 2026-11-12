"""Member management: CRUD plus generating, regenerating and revoking the
personal answer-link tokens (spec B2). The raw link is shown exactly once,
rendered straight into the POST response — never via the session, whose
cookie is signed but not encrypted. The list is readable for the intern
role (names and link status only — never tokens); every mutation and the
delete confirmation require admin."""

import logging
import sqlite3

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app.auth import token as token_backend
from app.auth.core import Principal, krav_admin, krav_intern
from app.auth.csrf import krav_csrf
from app import config
from app.db import get_conn
from app.web import templates

router = APIRouter(prefix="/medlemmar", dependencies=[Depends(krav_csrf)])
audit = logging.getLogger("teaball.audit")


def _svarslank(request: Request, token: str) -> str:
    bas = config.PUBLIC_BASE_URL.rstrip("/") or str(request.base_url).rstrip("/")
    return f"{bas}/svara/{token}"


@router.get("")
def lista(
    request: Request,
    principal: Principal = Depends(krav_intern),
    conn: sqlite3.Connection = Depends(get_conn),
):
    return _listsida(request, conn, principal)


def _listsida(request: Request, conn, principal, ny_lank: dict | None = None):
    medlemmar = conn.execute(
        """
        SELECT m.id, m.namn, m.kategori, m.token IS NOT NULL AS har_token,
               m.senast_anvand,
               (SELECT COUNT(*) FROM bedomning b WHERE b.medlem_id = m.id) AS antal_svar
        FROM medlem m ORDER BY m.namn
        """
    ).fetchall()
    return templates.TemplateResponse(
        request,
        "medlemmar/index.html",
        {
            "principal": principal,
            "medlemmar": medlemmar,
            "skrivbar": principal.roll == "admin",
            "ny_lank": ny_lank,
        },
    )


@router.post("")
def skapa(
    request: Request,
    namn: str = Form(...),
    kategori: str = Form(""),
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    conn.execute(
        "INSERT INTO medlem (namn, kategori) VALUES (?, ?)",
        (namn.strip(), kategori.strip() or None),
    )
    conn.commit()
    audit.info("forvaltare=%s op=medlem_skapa namn=%r", principal.namn, namn)
    return RedirectResponse("/medlemmar", status_code=303)


@router.post("/{medlem_id}")
def uppdatera(
    request: Request,
    medlem_id: int,
    namn: str = Form(...),
    kategori: str = Form(""),
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    conn.execute(
        "UPDATE medlem SET namn = ?, kategori = ? WHERE id = ?",
        (namn.strip()[:200], kategori.strip()[:100] or None, medlem_id),
    )
    conn.commit()
    audit.info("forvaltare=%s op=medlem_uppdatera medlem=%s namn=%r",
               principal.namn, medlem_id, namn)
    return RedirectResponse("/medlemmar", status_code=303)


@router.get("/{medlem_id}/ta-bort")
def ta_bort_bekrafta(
    request: Request,
    medlem_id: int,
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """T2-style server-rendered confirmation — works without JS."""
    rad = conn.execute("SELECT namn FROM medlem WHERE id = ?", (medlem_id,)).fetchone()
    if rad is None:
        return RedirectResponse("/medlemmar", status_code=303)
    antal_svar = conn.execute(
        "SELECT COUNT(*) FROM bedomning WHERE medlem_id = ?", (medlem_id,)
    ).fetchone()[0]
    return templates.TemplateResponse(
        request,
        "medlemmar/ta_bort.html",
        {"principal": principal, "medlem_id": medlem_id,
         "namn": rad["namn"], "antal_svar": antal_svar},
    )


@router.post("/{medlem_id}/ta-bort")
def ta_bort(
    request: Request,
    medlem_id: int,
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    # Delete answers explicitly so the D2 trigger writes them to the history
    # before the member row (and its FK cascade) goes away.
    conn.execute("DELETE FROM bedomning WHERE medlem_id = ?", (medlem_id,))
    conn.execute("DELETE FROM medlem WHERE id = ?", (medlem_id,))
    conn.commit()
    audit.info("forvaltare=%s op=medlem_ta_bort medlem=%s", principal.namn, medlem_id)
    return RedirectResponse("/medlemmar", status_code=303)


@router.post("/{medlem_id}/token")
def generera_token(
    request: Request,
    medlem_id: int,
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Generate or regenerate — the old link (and any active session) dies."""
    token, tokenhash = token_backend.generera()
    conn.execute("UPDATE medlem SET token = ? WHERE id = ?", (tokenhash, medlem_id))
    conn.commit()
    rad = conn.execute("SELECT namn FROM medlem WHERE id = ?", (medlem_id,)).fetchone()
    audit.info("forvaltare=%s op=token_generera medlem=%s", principal.namn, medlem_id)
    return _listsida(request, conn, principal, ny_lank={
        "namn": rad["namn"] if rad else "?",
        "lank": _svarslank(request, token),
    })


@router.post("/{medlem_id}/token/ta-bort")
def revokera_token(
    request: Request,
    medlem_id: int,
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    conn.execute("UPDATE medlem SET token = NULL WHERE id = ?", (medlem_id,))
    conn.commit()
    audit.info("forvaltare=%s op=token_revokera medlem=%s", principal.namn, medlem_id)
    return RedirectResponse("/medlemmar", status_code=303)
