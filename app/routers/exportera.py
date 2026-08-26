"""Export downloads (E1 + the all-views Excel workbook). Admin only."""

import sqlite3
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import PlainTextResponse

from app.auth.core import Principal, krav_forvaltare
from app.db import get_conn
from app.services import exportera as tjanst
from app.web import templates

router = APIRouter(prefix="/export")


def _datum() -> str:
    return datetime.now(UTC).strftime("%Y%m%d")


@router.get("")
def oversikt(request: Request, principal: Principal = Depends(krav_forvaltare)):
    return templates.TemplateResponse(
        request, "exportera/index.html", {"principal": principal}
    )


@router.get("/teaball.xlsx")
def xlsx(
    principal: Principal = Depends(krav_forvaltare),
    conn: sqlite3.Connection = Depends(get_conn),
):
    return Response(
        tjanst.xlsx_export(conn),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f'attachment; filename="teaball-{_datum()}.xlsx"'},
    )


@router.get("/json")
def json_export(
    principal: Principal = Depends(krav_forvaltare),
    conn: sqlite3.Connection = Depends(get_conn),
):
    return Response(
        tjanst.json_export(conn),
        media_type="application/json",
        headers={"Content-Disposition":
                 f'attachment; filename="teaball-{_datum()}.json"'},
    )


@router.get("/trad.csv")
def trad_csv(
    principal: Principal = Depends(krav_forvaltare),
    conn: sqlite3.Connection = Depends(get_conn),
):
    return PlainTextResponse(
        tjanst.trad_csv(conn),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="kravtrad-{_datum()}.csv"'},
    )


@router.get("/bedomningar.csv")
def bedomningar_csv(
    principal: Principal = Depends(krav_forvaltare),
    conn: sqlite3.Connection = Depends(get_conn),
):
    return PlainTextResponse(
        tjanst.bedomningar_csv(conn),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="bedomningar-{_datum()}.csv"'},
    )
