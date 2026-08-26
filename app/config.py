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

MIGRATIONS_DIR = BASE_DIR / "db" / "migrations"
VIEWS_TRIGGERS_SQL = BASE_DIR / "db" / "views_triggers.sql"
TEMPLATES_DIR = BASE_DIR / "app" / "templates"
STATIC_DIR = BASE_DIR / "static"
