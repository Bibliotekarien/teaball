"""Roadmap: the read view (R1), an explicit edit mode — phase moves via
drag-and-drop or a per-row select, both against the same endpoint — and the
standalone static HTML export (R2)."""

import logging
import sqlite3
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth.core import Principal, krav_admin, krav_forvaltare
from app.auth.csrf import krav_csrf
from app.db import get_conn
from app.services import roadmap as tjanst
from app.services.roadmap import FASTA_FASER, SISTA_FASER, UTAN_FAS
from app.services.trad import regeltext
from app.web import is_htmx, templates

router = APIRouter(prefix="/roadmap")
audit = logging.getLogger("teaball.audit")


def _ctx(request: Request, conn, principal, visa_krav: bool, redigera: bool,
         fel: str | None = None):
    grupper = tjanst.roadmap_data(
        conn, visa_krav, endast_synliga=principal.roll == "extern"
    )
    if redigera:
        # In edit mode the empty named phases (and "utan avgång") must render too,
        # as drop targets.
        per_fas = dict(grupper)
        ordning = list(dict.fromkeys(
            [*FASTA_FASER, *[f for f, _ in grupper if f != UTAN_FAS],
             *SISTA_FASER, UTAN_FAS]))
        grupper = [(f, per_fas.get(f, [])) for f in ordning]
    fas_alternativ = list(dict.fromkeys(
        [*FASTA_FASER, *[f for f, _ in grupper if f != UTAN_FAS], *SISTA_FASER]))
    return {
        "principal": principal,
        "visa_krav": visa_krav,
        "redigera": redigera,
        "skrivbar": principal.roll == "admin",
        "grupper": grupper,
        "fas_alternativ": fas_alternativ,
        "fel": fel,
    }


@router.get("")
def visa(
    request: Request,
    visa_krav: str = "",
    redigera: str = "",
    principal: Principal = Depends(krav_forvaltare),
    conn: sqlite3.Connection = Depends(get_conn),
):
    # ?redigera=1 is neutralized here for read-only roles, so neither the
    # template chain nor roadmap.js needs any role awareness.
    return templates.TemplateResponse(
        request,
        "roadmap/index.html",
        _ctx(request, conn, principal, visa_krav == "1",
             redigera == "1" and principal.roll == "admin"),
    )


@router.post("/flytta", dependencies=[Depends(krav_csrf)])
def flytta(
    request: Request,
    nod_id: int = Form(...),
    fas: str = Form(""),
    visa_krav: str = Form(""),
    principal: Principal = Depends(krav_admin),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Move one node to another phase. Deliberately only the node itself —
    children keep their own fas, exactly as in the tree editor."""
    if conn.execute("SELECT 1 FROM funktion WHERE id = ?", (nod_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="Noden finns inte.")
    ny_fas = fas.strip()[:50] or None
    try:
        conn.execute("UPDATE funktion SET fas = ? WHERE id = ?", (ny_fas, nod_id))
    except sqlite3.IntegrityError as fel_db:
        # Avgångstriggern: t.ex. en planerad nod dragen till "utan avgång".
        # Rollback FÖRE _ctx så grupperna renderas från oförändrad databas —
        # helhets-swappen av #roadmap-grupper återställer även SortableJS
        # optimistiska DOM-flytt. htmx-svaret måste vara 200 (htmx swappar
        # inte icke-2xx), helsidan får 400 som i trädet.
        conn.rollback()
        ctx = _ctx(request, conn, principal, visa_krav == "1", True,
                   fel=regeltext(fel_db))
        if is_htmx(request):
            return templates.TemplateResponse(request, "roadmap/_grupper.html", ctx)
        return templates.TemplateResponse(
            request, "roadmap/index.html", ctx, status_code=400
        )
    conn.commit()
    audit.info("forvaltare=%s op=roadmap_flytta nod=%s fas=%r", principal.namn, nod_id, ny_fas)
    if is_htmx(request):
        return templates.TemplateResponse(
            request,
            "roadmap/_grupper.html",
            _ctx(request, conn, principal, visa_krav == "1", True),
        )
    mal = "/roadmap?redigera=1" + ("&visa_krav=1" if visa_krav == "1" else "")
    return RedirectResponse(mal, status_code=303)


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
