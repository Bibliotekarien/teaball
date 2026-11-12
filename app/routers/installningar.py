"""Admin-only: instansens texter — organisationen, systemet som ersätts och
integritetssidans personuppgiftsansvarig och kontaktväg (app/instans.py)."""

import logging
import sqlite3

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app import instans
from app.auth.core import Principal, krav_admin
from app.auth.csrf import krav_csrf
from app.db import get_conn
from app.web import templates

router = APIRouter(prefix="/installningar", dependencies=[Depends(krav_csrf)])
audit = logging.getLogger("teaball.audit")

FLASH_SPARAT = "installningar_sparat"


@router.get("")
def visa(
    request: Request,
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    return templates.TemplateResponse(request, "installningar/index.html", {
        "principal": principal,
        "instans": instans.las(conn),
        "maxlangd": instans.MAXLANGD,
        "neutralt_system": instans.NEUTRALT_SYSTEM,
        "sparat": request.session.pop(FLASH_SPARAT, False),
    })


@router.post("")
def spara(
    request: Request,
    organisation: str = Form(""),
    nuvarande_system: str = Form(""),
    personuppgiftsansvarig: str = Form(""),
    dataskydd_kontakt: str = Form(""),
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    instans.spara(
        conn,
        organisation=organisation,
        nuvarande_system=nuvarande_system,
        personuppgiftsansvarig=personuppgiftsansvarig,
        dataskydd_kontakt=dataskydd_kontakt,
    )
    audit.info("forvaltare=%s op=installningar_spara", principal.namn)
    request.session[FLASH_SPARAT] = True
    return RedirectResponse("/installningar", status_code=303)
