"""Server-side Matomo tracking via the Tracking HTTP API (the platform's
mark-rounding pattern).

Instead of a client-side JS tracker the backend reports page loads directly to
matomo.php: no third-party script, no CDN, cookie-free, and the edge CSP stays
strict. Trade-off: only full document loads are counted — htmx partial swaps
within a loaded page are deliberately not page views.

Privacy: DNT and Sec-GPC are honored, no cookies are set, and the member link
token in /svara/<token> is masked before any URL leaves the app. Tracking is
fire-and-forget — it must never slow down or fail a request."""

import asyncio
import logging
import re
import secrets
from urllib.parse import urlsplit, urlunsplit

import httpx

from app import config

_log = logging.getLogger("teaball.matomo")

_client: httpx.AsyncClient | None = None

# Strong references to in-flight fire-and-forget tasks. asyncio only keeps a
# weak reference to a bare create_task() result, so without this set the hit
# can be garbage-collected before it is ever sent — silently dropping tracking.
_tasks: set[asyncio.Task] = set()

# GET /svara/<token> is a 303 (never tracked), but mask defensively so the
# secret can never reach analytics via any status/path combination.
_TOKEN_RE = re.compile(r"^(/svara/)[^/]+$")


def sanitize_path(path: str) -> str:
    return _TOKEN_RE.sub(r"\1_token_", path)


def sanitize_referrer(referrer: str) -> str:
    """Mask the member token a same-origin referrer would otherwise carry into
    analytics as urlref. The /svara/<token> confirmation page renders with a
    200 (unlike the normal 303), so a click from it sends the raw token in the
    Referer header; sanitize_path masks only our own path, never the referrer.
    Only the path component is rewritten — scheme, host and query are kept."""
    if not referrer:
        return referrer
    delar = urlsplit(referrer)
    if not delar.path:
        return referrer
    return urlunsplit(delar._replace(path=sanitize_path(delar.path)))


def should_track(method: str, path: str, status_code: int, hx_request: bool) -> bool:
    """Track successful full HTML document loads only — not htmx partials
    (in-page swaps are not page views), assets, or health checks."""
    if method != "GET" or status_code != 200 or hx_request:
        return False
    if path.startswith(("/static", "/health")):
        return False
    if "." in path.rsplit("/", 1)[-1]:  # favicon.ico, robots.txt, …
        return False
    return True


def opted_out(headers) -> bool:
    return headers.get("dnt") == "1" or headers.get("sec-gpc") == "1"


def build_params(url: str, user_agent: str, lang: str, referrer: str, client_ip: str) -> dict:
    params = {
        "idsite": config.MATOMO_SITE_ID,
        "rec": "1",
        "apiv": "1",
        "url": url,
        "ua": user_agent,
        "lang": lang,
        "rand": secrets.token_hex(8),
        "send_image": "0",
    }
    if referrer:
        params["urlref"] = referrer
    if config.MATOMO_TOKEN and client_ip:
        # token_auth lets us pass the real visitor IP; without it Matomo would
        # log the proxy container's address for every hit.
        params["token_auth"] = config.MATOMO_TOKEN
        params["cip"] = client_ip
    return params


async def _send(params: dict) -> None:
    global _client
    try:
        if _client is None:
            _client = httpx.AsyncClient(timeout=5.0)
        resp = await _client.post(f"{config.MATOMO_URL}/matomo.php", data=params)
        # A successful tracking hit is 204 (send_image=0) or 200. Anything else
        # means Matomo rejected it — surface why instead of dropping it silently.
        if resp.status_code >= 400:
            _log.warning("Matomo avvisade träffen: HTTP %s %s",
                         resp.status_code, resp.text[:200])
    except Exception as exc:  # analytics must never break the app, but must be visible
        _log.warning("Matomo-tracking misslyckades: %s", exc)


def track_request(request, status_code: int) -> None:
    """Called from the middleware; schedules a fire-and-forget hit."""
    if not config.MATOMO_ENABLED:
        return
    if not should_track(
        request.method,
        request.url.path,
        status_code,
        request.headers.get("hx-request") == "true",
    ):
        return
    if opted_out(request.headers):
        return
    path = sanitize_path(request.url.path)
    # uvicorn runs with --proxy-headers, so scheme/host reflect the edge.
    url = f"{request.url.scheme}://{request.url.netloc}{path}"
    params = build_params(
        url=url,
        user_agent=request.headers.get("user-agent", ""),
        lang=request.headers.get("accept-language", ""),
        referrer=sanitize_referrer(request.headers.get("referer", "")),
        client_ip=request.client.host if request.client else "",
    )
    # Keep a strong reference until the task finishes; otherwise the event loop
    # may garbage-collect the fire-and-forget hit before it is sent.
    task = asyncio.get_running_loop().create_task(_send(params))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
