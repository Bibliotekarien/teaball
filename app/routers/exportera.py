"""Export downloads: E1, the all-views Excel workbook, the standalone tree
HTML and the combined PDF report (tree + ranking). Admin + intern only: the
default outputs dump private comments and unshared workarounds, and the
"safe" variants are opt-in query params — a blanket rule is the only
auditable one. The extern role's sole export is /roadmap/export."""

import sqlite3
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse

from app.auth.core import Principal, krav_intern
from app.db import get_conn
from app.services import analys as analys_tjanst
from app.services import confluence as confluence_tjanst
from app.services import exportera as tjanst
from app.web import templates

router = APIRouter(prefix="/export")


def _datum() -> str:
    return datetime.now(UTC).strftime("%Y%m%d")


@router.get("")
def oversikt(request: Request, principal: Principal = Depends(krav_intern)):
    return templates.TemplateResponse(
        request, "exportera/index.html", {"principal": principal}
    )


@router.get("/teaball.xlsx")
def xlsx(
    principal: Principal = Depends(krav_intern),
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
    principal: Principal = Depends(krav_intern),
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
    principal: Principal = Depends(krav_intern),
    conn: sqlite3.Connection = Depends(get_conn),
):
    return PlainTextResponse(
        tjanst.trad_csv(conn),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="kravtrad-{_datum()}.csv"'},
    )


@router.get("/bedomningar.csv")
def bedomningar_csv(
    principal: Principal = Depends(krav_intern),
    conn: sqlite3.Connection = Depends(get_conn),
):
    return PlainTextResponse(
        tjanst.bedomningar_csv(conn),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="bedomningar-{_datum()}.csv"'},
    )


@router.get("/kravtrad.html")
def kravtrad_html(
    endast_synliga: str = "",
    principal: Principal = Depends(krav_intern),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Standalone HTML of the tree, same pattern as the R2 roadmap export:
    inline CSS, no scripts. ?endast_synliga=1 restricts to externally visible
    nodes — the filename gets an -extern suffix so the two variants are
    distinguishable in a mail attachment."""
    filtrera = endast_synliga == "1"
    html = templates.get_template("exportera/kravtrad.html").render({
        "noder": tjanst.kravtrad_rader(conn, filtrera),
        "endast_synliga": filtrera,
        "genererad": datetime.now(UTC).strftime("%Y-%m-%d"),
    })
    suffix = "-extern" if filtrera else ""
    return HTMLResponse(
        html,
        headers={"Content-Disposition":
                 f'attachment; filename="kravtrad-{_datum()}{suffix}.html"'},
    )


@router.get("/rapport.pdf")
def rapport_pdf(
    endast_synliga: str = "",
    principal: Principal = Depends(krav_intern),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Tree + blockerar-rankning as one PDF (styrgrupp mailouts), rendered by
    WeasyPrint from the same templates as the HTML export."""
    # Lazy import: WeasyPrint loads Pango system libraries and is missing on
    # dev machines without them — the rest of the app must not depend on it.
    try:
        from weasyprint import HTML
    except (ImportError, OSError) as fel:
        raise HTTPException(
            status_code=503,
            detail="PDF-motorn (WeasyPrint/Pango) är inte installerad i den här miljön.",
        ) from fel
    filtrera = endast_synliga == "1"
    html = templates.get_template("exportera/rapport.html").render({
        "noder": tjanst.kravtrad_rader(conn, filtrera),
        "rankning": analys_tjanst.rankning(conn, arvda=False, endast_synliga=filtrera),
        "tackning": analys_tjanst.tackning(conn),
        "endast_synliga": filtrera,
        "genererad": datetime.now(UTC).strftime("%Y-%m-%d"),
    })
    suffix = "-extern" if filtrera else ""
    return Response(
        HTML(string=html).write_pdf(),
        media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="teaball-rapport-{_datum()}{suffix}.pdf"'},
    )


# Confluence wiki-markup of a view, served inline as plain text so the browser
# shows the raw markup to select, copy and paste into Confluence.
CONFLUENCE_VYER = {"kravtrad": "Kravträd", "analys": "Analys",
                   "roadmap": "Roadmap", "medlemmar": "Medlemmar"}


@router.get("/confluence/{vy}", response_class=PlainTextResponse)
def confluence(
    vy: str,
    request: Request,
    principal: Principal = Depends(krav_intern),
    conn: sqlite3.Connection = Depends(get_conn),
):
    if vy not in CONFLUENCE_VYER:
        raise HTTPException(status_code=404)
    datum = datetime.now(UTC).strftime("%Y-%m-%d")
    if vy == "kravtrad":
        text = confluence_tjanst.kravtrad(conn, datum)
    elif vy == "analys":
        text = confluence_tjanst.analys(conn, request.query_params.get("arvda") == "1", datum)
    elif vy == "roadmap":
        text = confluence_tjanst.roadmap(
            conn, request.query_params.get("visa_krav") == "1", datum,
            dolj_formagor=request.query_params.get("dolj_formagor") == "1")
    else:
        text = confluence_tjanst.medlemmar(conn, datum)
    return PlainTextResponse(text, media_type="text/plain; charset=utf-8")
