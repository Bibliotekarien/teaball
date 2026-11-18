"""Configuration from environment variables, with paths anchored at the repo root."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DB_PATH = Path(os.environ.get("DB_PATH", str(BASE_DIR / "data" / "teaball.db")))

# Several organisations on one installation: one SQLite file per organisation
# in this directory, named after its hostname (<host>.db), chosen per request
# by the Host header. Unset = one organisation in DB_PATH. See
# app/organisationer.py.
ORGANISATIONER_DIR = (
    Path(os.environ["ORGANISATIONER_DIR"]) if os.environ.get("ORGANISATIONER_DIR") else None
)

# Signs session cookies. The default is for local development only;
# main.py logs a loud warning when it is in use.
DEV_SECRET_KEY = "dev-only-insecure-key"
SECRET_KEY = os.environ.get("SECRET_KEY") or DEV_SECRET_KEY

# Set to 1 behind the TLS-terminating reverse proxy (docker-compose does);
# off by default so local development over plain http works.
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"

# Public URL used when composing member answer links (falls back to the
# request's own base URL, which behind a proxy is usually wrong).
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "")

# Server-side Matomo tracking (Tracking HTTP API). Off unless both URL and
# site id are set — local development tracks nothing.
MATOMO_URL = os.environ.get("MATOMO_URL", "").strip().rstrip("/")
MATOMO_SITE_ID = os.environ.get("MATOMO_SITE_ID", "").strip()
MATOMO_TOKEN = os.environ.get("MATOMO_TOKEN", "").strip()
MATOMO_ENABLED = bool(MATOMO_URL and MATOMO_SITE_ID)

# Instance texts: the organisation, the system being replaced, and the privacy
# page's data controller and contact. They live in the database (table
# instans, edited by admins on /installningar). These variables are only an
# upgrade path: a database already in use when migration 0010 arrives is
# seeded from them ONCE, so an instance configured through .env keeps its
# texts. New databases are never seeded, and changing the variables later has
# no effect (a warning is logged). Do not read them elsewhere; use
# instans.aktuell(). See app/instans.py.
ORGANISATION = os.environ.get("ORGANISATION", "").strip()
NUVARANDE_SYSTEM = os.environ.get("NUVARANDE_SYSTEM", "").strip()
PERSONUPPGIFTSANSVARIG = os.environ.get("PERSONUPPGIFTSANSVARIG", "").strip()
DATASKYDD_KONTAKT = os.environ.get("DATASKYDD_KONTAKT", "").strip()

# Set to 1 when a bot gate that sets its own cookie (Anubis) sits in front of
# the app — the privacy page must then mention that cookie. The app cannot
# see the gate itself.
ROBOTSKYDD = os.environ.get("ROBOTSKYDD", "0") == "1"

MIGRATIONS_DIR = BASE_DIR / "db" / "migrations"
VIEWS_TRIGGERS_SQL = BASE_DIR / "db" / "views_triggers.sql"
TEMPLATES_DIR = BASE_DIR / "app" / "templates"
STATIC_DIR = BASE_DIR / "static"
