# Pinnad på digest (3.12-slim, hämtad 2026-08-25) — bumpa medvetet, inte via
# oannonserad :latest-glidning. Samma policy som Anubis-imagen i prod-composen.
FROM python:3.12-slim@sha256:7a8b475003c4fe15a2cd4e55e5cfc2f3560bdc9333d624f24cdd6d4340fd7a17

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/srv/teaball/.venv/bin:$PATH"

WORKDIR /srv/teaball

# WeasyPrint (PDF-exporten) renderar text via Pango; slim-imagen saknar både
# biblioteken och typsnitt. Liberation Sans ger rapporterna Arial-metrik.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Beroendena installeras exakt från uv.lock — samma versioner som CI provar
# (uv sync --locked i den delade python-tests.yml). --locked avbryter bygget
# om låsfilen inte stämmer med pyproject.toml i stället för att lösa om.
# uv är låst på version; bumpa medvetet. UV_PYTHON_DOWNLOADS=never håller
# imagens egen Python 3.12 som tolk. venv:en ligger först i PATH, så CMD:ns
# uvicorn, healthcheckens python3 och `docker compose exec web python
# scripts/...` alla kör med de låsta paketen.
RUN pip install --no-cache-dir uv==0.12.19

# Beroendelagret cachas tills pyproject.toml/uv.lock ändras.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY app ./app
COPY db ./db
COPY static ./static
COPY scripts ./scripts
# Bundled seed data (DiVA members etc.) so the import scripts work in the
# container. .dockerignore keeps local dev databases in data/ out of the image.
COPY data ./data

# Projektet självt (package = false i pyproject: inget att installera i dag,
# men steget kontrollerar låsfilen igen och följer plattformsmönstret).
RUN uv sync --locked --no-dev

# Service user per platform convention (SERVER_LAYOUT.md UID allocation).
RUN mkdir -p /data \
    && groupadd --gid 1505 appuser \
    && useradd --uid 1505 --gid 1505 --no-create-home appuser \
    && chown -R appuser:appuser /data /srv/teaball
USER appuser

EXPOSE 8000
# --proxy-headers: scheme/host from the edge (Secure cookies, Matomo URLs).
# --forwarded-allow-ips '*': the proxy hop is Anubis/Caddy on the compose
# network; the container publishes no host ports, so the header is trustworthy.
# The access log is on: members' tokens in GET /svara/<token> are masked by
# app/accesslog.py before the line is written (the platform pattern — mask,
# don't turn off; bibliotekarien-platform LOGGNING.md).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
