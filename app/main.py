"""Application factory. Routers are registered here as they are implemented."""

import logging
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import accesslog, config, db, instans, matomo
from app.web import templates
from app.routers import (
    analys, bedomning, exportera, inloggning, installningar, kommentarer, konton, lista,
    medlemmar, roadmap, svara, trad,
)

logger = logging.getLogger("teaball")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if config.SECRET_KEY == config.DEV_SECRET_KEY:
        if config.COOKIE_SECURE:
            # Production (behind TLS): a forgeable session cookie is full
            # account takeover — refuse to start rather than warn.
            raise RuntimeError(
                "SECRET_KEY saknas. Generera en med "
                "python3 -c \"import secrets; print(secrets.token_urlsafe(48))\" "
                "och sätt den i .env."
            )
        logger.warning("SECRET_KEY is unset — using the insecure development key.")
    conn = db.connect()
    try:
        db.init_db(conn)
    finally:
        conn.close()
    yield


def _las_instans() -> instans.Instans:
    """Neutral text hellre än en trasig sida: misslyckas läsningen (t.ex. en
    låst databas) visas standardvärdena och felet loggas."""
    try:
        conn = db.connect()
        try:
            return instans.las(conn)
        finally:
            conn.close()
    except sqlite3.Error:
        logger.exception("Kunde inte läsa instansens texter; visar neutral text")
        return instans.Instans()


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    accesslog.install()
    app.add_middleware(
        SessionMiddleware,
        secret_key=config.SECRET_KEY,
        session_cookie="teaball_session",
        same_site="lax",
        https_only=config.COOKIE_SECURE,
    )
    app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
    app.include_router(inloggning.router)
    app.include_router(trad.router)
    app.include_router(lista.router)
    app.include_router(kommentarer.router)
    app.include_router(bedomning.router)
    app.include_router(analys.router)
    app.include_router(roadmap.router)
    app.include_router(exportera.router)
    app.include_router(medlemmar.router)
    app.include_router(konton.router)
    app.include_router(installningar.router)
    app.include_router(svara.router)

    @app.get("/")
    def start():
        return RedirectResponse("/trad", status_code=303)

    @app.get("/robots.txt", include_in_schema=False)
    def robots():
        """Teaball is closed to search engines — decided, not by accident:
        everything but the login needs an account, and /svara/<token> are
        members' secret links. Served by the app, not Anubis (whose robots.txt
        is the same Disallow, but only by default; bibliotekarien-platform
        edge/ANUBIS.md). Anubis lets /robots.txt through unchallenged."""
        return PlainTextResponse(
            "# Teaball är ett slutet verktyg: allt utom inloggningen kräver\n"
            "# konto, och /svara/<token> är medlemmarnas hemliga länkar.\n"
            "# Inget att indexera.\n"
            "User-agent: *\n"
            "Disallow: /\n"
        )

    @app.get("/health")
    def health():
        """Container healthcheck + external uptime probe target. No auth."""
        return {"status": "ok"}

    @app.get("/integritet")
    def integritet(request: Request):
        """Public privacy notice, linked from the footer. Standalone template
        (no CSRF/htmx) so an anonymous reader is not handed a session cookie."""
        return templates.TemplateResponse(request, "integritet.html", {
            "principal": None,
            "organisation": instans.aktuell().organisation,
            "personuppgiftsansvarig": instans.aktuell().personuppgiftsansvarig,
            "dataskydd_kontakt": instans.aktuell().dataskydd_kontakt,
            "matomo": config.MATOMO_ENABLED,
            "robotskydd": config.ROBOTSKYDD,
        })

    @app.middleware("http")
    async def instansens_texter(request, call_next):
        """The instance texts for this request (app/instans.py). Read per
        request, not once at start-up, so a change on /installningar shows at
        once even with several processes. One row from a tiny table; static
        files and the health check skip it."""
        if request.url.path.startswith("/static") or request.url.path == "/health":
            return await call_next(request)
        token = instans.satt_aktuell(await run_in_threadpool(_las_instans))
        try:
            return await call_next(request)
        finally:
            instans.aterstall(token)

    @app.middleware("http")
    async def sakerhetsheaders(request, call_next):
        svar = await call_next(request)
        # Behind edge-Caddy these are replaced by the site block's headers;
        # they carry the app's own baseline when it runs stand-alone.
        # No 'unsafe-inline' in script-src: all JS is external files with
        # data-attribute hooks (htmx attributes are not inline scripts).
        # style-src needs 'unsafe-inline' for style="" attributes (tree indent,
        # analysis bar widths).
        svar.headers.setdefault("X-Content-Type-Options", "nosniff")
        svar.headers.setdefault("X-Frame-Options", "DENY")
        svar.headers.setdefault("Referrer-Policy", "same-origin")
        svar.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        svar.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self';"
            " style-src 'self' 'unsafe-inline'; img-src 'self' data:;"
            " base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
        )
        if not request.url.path.startswith("/static"):
            # Assessment pages carry private comments — keep them out of
            # shared-computer caches. Static assets may cache freely.
            svar.headers.setdefault("Cache-Control", "no-store")
        matomo.track_request(request, svar.status_code)
        return svar

    return app


app = create_app()
