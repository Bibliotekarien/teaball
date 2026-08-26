"""Session-bound CSRF protection (spec S1).

htmx requests send the token via the X-CSRF-Token header (hx-headers on <body>);
plain form posts carry a hidden csrf_token field. krav_csrf is attached as a
router-level dependency and skips safe methods.
"""

import hmac
import secrets

from fastapi import HTTPException, Request

SESSION_KEY = "csrf_token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def csrf_token(request: Request) -> str:
    token = request.session.get(SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[SESSION_KEY] = token
    return token


async def krav_csrf(request: Request) -> None:
    if request.method in SAFE_METHODS:
        return
    forvantad = request.session.get(SESSION_KEY)
    mottagen = request.headers.get("x-csrf-token")
    if mottagen is None:
        form = await request.form()
        varde = form.get("csrf_token")
        mottagen = varde if isinstance(varde, str) else None
    if not (forvantad and mottagen and hmac.compare_digest(forvantad, mottagen)):
        raise HTTPException(status_code=400, detail="Ogiltig eller saknad CSRF-token.")
