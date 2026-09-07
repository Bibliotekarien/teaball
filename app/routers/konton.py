"""Admin-only accounts view: which staff accounts exist, their role and last
login. Read-only GET, no CSRF (same pattern as analys.py). The stamp itself is
written at login (inloggning.py); this view only presents it."""

import sqlite3

from fastapi import APIRouter, Depends, Request

from app.auth.core import Principal, krav_admin
from app.db import get_conn
from app.web import templates

router = APIRouter(prefix="/konton")


@router.get("")
def lista(
    request: Request,
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    konton = conn.execute(
        "SELECT anvandarnamn, roll, senast_inloggad FROM forvaltare"
        " ORDER BY anvandarnamn"
    ).fetchall()
    return templates.TemplateResponse(
        request, "konton/index.html", {"principal": principal, "konton": konton}
    )
