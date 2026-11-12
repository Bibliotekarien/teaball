"""Configuration from environment variables, with paths anchored at the repo root."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DB_PATH = Path(os.environ.get("DB_PATH", str(BASE_DIR / "data" / "teaball.db")))

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

# Instance texts. Teaball is a generic tool for an organisation (often a
# consortium) moving from a current system to a new one; these name both on
# the privacy page and in the status explanations. Empty values give neutral
# wording, never a borrowed name.
ORGANISATION = os.environ.get("ORGANISATION", "").strip()
NUVARANDE_SYSTEM = os.environ.get("NUVARANDE_SYSTEM", "").strip() or "det nuvarande systemet"

# Privacy page (/integritet): the data controller and how to reach them.
# Unset, the page says so with a visible "fill in before go-live" marker.
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
