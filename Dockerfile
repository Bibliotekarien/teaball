# Pinnad på digest (3.12-slim, hämtad 2026-08-25) — bumpa medvetet, inte via
# oannonserad :latest-glidning. Samma policy som Anubis-imagen i prod-composen.
FROM python:3.12-slim@sha256:7a8b475003c4fe15a2cd4e55e5cfc2f3560bdc9333d624f24cdd6d4340fd7a17

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /srv/teaball

# WeasyPrint (PDF-exporten) renderar text via Pango; slim-imagen saknar både
# biblioteken och typsnitt. Liberation Sans ger rapporterna Arial-metrik.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Runtime dependencies mirror [project.dependencies] in pyproject.toml.
RUN pip install --no-cache-dir \
    "fastapi>=0.115" \
    "uvicorn[standard]>=0.30" \
    "jinja2>=3.1" \
    "python-multipart>=0.0.9" \
    "argon2-cffi>=23.1" \
    "itsdangerous>=2.2" \
    "openpyxl>=3.1.5" \
    "httpx>=0.27" \
    "weasyprint>=63"

COPY app ./app
COPY db ./db
COPY static ./static
COPY scripts ./scripts
# Bundled seed data (DiVA members etc.) so the import scripts work in the
# container. .dockerignore keeps local dev databases in data/ out of the image.
COPY data ./data

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
# --no-access-log: raw member tokens appear in GET /svara/<token> paths — the
# edge-Caddy access log covers request logging and masks that path.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-access-log"]
