"""Roadmap read view (R1) and the standalone static HTML export (R2)."""

import sqlite3
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.auth.core import Principal, krav_forvaltare
from app.db import get_conn
from app.services import roadmap as tjanst
from app.web import templates

router = APIRouter(prefix="/roadmap")


@router.get("")
def visa(
    request: Request,
    visa_krav: str = "",
    principal: Principal = Depends(krav_forvaltare),
    conn: sqlite3.Connection = Depends(get_conn),
):
    return templates.TemplateResponse(
        request,
        "roadmap/index.html",
        {
            "principal": principal,
            "visa_krav": visa_krav == "1",
            "grupper": tjanst.roadmap_data(conn, visa_krav == "1", endast_synliga=False),
        },
    )


@router.get("/export")
def exportera(
    request: Request,
    visa_krav: str = "",
    principal: Principal = Depends(krav_forvaltare),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """R2: self-contained HTML for styrgrupp mailouts — inline CSS, no scripts,
    respects synlig_externt (transitively)."""
    html = templates.get_template("roadmap/export.html").render(
        {
            "grupper": tjanst.roadmap_data(conn, visa_krav == "1", endast_synliga=True),
            "genererad": datetime.now(UTC).strftime("%Y-%m-%d"),
        }
    )
    filnamn = f"roadmap-{datetime.now(UTC).strftime('%Y%m%d')}.html"
    return HTMLResponse(
        html,
        headers={"Content-Disposition": f'attachment; filename="{filnamn}"'},
    )
