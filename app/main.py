"""Application factory. Routers are registered here as they are implemented."""

import logging
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import accesslog, config, db, instans, matomo, organisationer
from app.web import templates
from app.routers import (
    analys, bedomning, exportera, inloggning, installningar, kommentarer, konton, lista,
    medlemmar, roadmap, svara, trad,
)

logger = logging.getLogger("teaball")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logging.getLogger("teaball.audit").addFilter(organisationer.AuditOrganisation())


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
    if organisationer.flera() and config.MATOMO_SITE_ID:
        # Typically an instance that was just moved in (INSTALL.md avsnitt
        # 10): its statistics stop until the site is connected per organisation.
        logger.warning("MATOMO_SITE_ID=%s används inte med flera organisationer; koppla "
                       "sajten med scripts/organisationer.py matomo <hostnamn> %s.",
                       config.MATOMO_SITE_ID, config.MATOMO_SITE_ID)
    if not organisationer.flera() and config.COOKIE_SECURE and not config.PUBLIC_BASE_URL:
        logger.warning("PUBLIC_BASE_URL saknas: svarslänkarna byggs på anropets adress, "
                       "kontrollera att de börjar med https://.")
    # Every organisation's database is migrated before the first request; a
    # failure stops the start-up, as with a single database.
    alla = organisationer.alla()
    if organisationer.flera():
        logger.info("Flera organisationer i %s: %s", config.ORGANISATIONER_DIR,
                    ", ".join(o.nyckel for o in alla) or "inga ännu")
    for organisation in alla:
        conn = db.connect(organisation.databas)
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
            "matomo": matomo.aktiv(),
            # With several organisations the Matomo is the operator's, not the
            # organisation's own; the notice must say so.
            "matomo_hos_operatoren": organisationer.flera(),
            "robotskydd": config.ROBOTSKYDD,
        })

    @app.middleware("http")
    async def organisation_och_texter(request, call_next):
        """Chooses the request's organisation from the Host header
        (app/organisationer.py) and reads its instance texts (app/instans.py),
        once per request: everything downstream — get_conn, the session check,
        the templates — sees the same organisation. Texts are read per request,
        not at start-up, so a change on /installningar shows at once even with
        several processes. Static files and the health check need neither."""
        if request.url.path.startswith("/static") or request.url.path == "/health":
            return await call_next(request)
        host = request.headers.get("host", "")
        organisation = organisationer.for_vard(host)
        if organisation is None:
            # Logged so a misspelt database file or a proxy that rewrites Host
            # can be found; the edge only forwards configured hostnames.
            logger.warning("Okänt hostnamn, ingen organisationsdatabas: %r", host[:100])
            return PlainTextResponse(
                "Okänd adress. Kontrollera att länken är rätt, eller kontakta den "
                "som skickade den.", status_code=404)
        org_token = organisationer.satt_aktuell(organisation)
        try:
            texter = await run_in_threadpool(_las_instans)
            token = instans.satt_aktuell(texter)
            try:
                svar = await call_next(request)
                # Here, not in an outer middleware: the Matomo site belongs to
                # the organisation, which is only set inside this block.
                matomo.track_request(request, svar.status_code)
                return svar
            finally:
                instans.aterstall(token)
        finally:
            organisationer.aterstall(org_token)

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
        return svar

    return app


app = create_app()
