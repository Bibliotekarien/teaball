"""The auth seam (spec S3).

Routers only ever import the dependencies below and receive a Principal —
they never see passwords, tokens, or (future) SAML details. Phase 3 SAML
support means adding a backend that resolves a Principal from SAML session
data; no view changes.
"""

import hashlib
import hmac
import sqlite3
from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, HTTPException, Request

from app.db import get_conn

SESSION_FORVALTARE = "forvaltare_id"
# The admin session stores a digest of the password hash so a password change
# (skapa_forvaltare.py) invalidates existing sessions server-side — signed
# cookies cannot otherwise be revoked.
SESSION_FORVALTARE_HASH = "forvaltare_losen_digest"
SESSION_MEDLEM = "medlem_id"
# The member session stores the token *hash* so revoking/regenerating the token
# (which replaces the stored hash) immediately invalidates existing sessions.
SESSION_MEDLEM_HASH = "medlem_token_hash"


def losen_digest(losen_hash: str) -> str:
    return hashlib.sha256(losen_hash.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class Principal:
    kind: Literal["forvaltare", "medlem"]
    namn: str
    forvaltare_id: int | None = None
    medlem_id: int | None = None


def aktuell_principal(request: Request, conn: sqlite3.Connection) -> Principal | None:
    forvaltare_id = request.session.get(SESSION_FORVALTARE)
    sessionsdigest = request.session.get(SESSION_FORVALTARE_HASH)
    if forvaltare_id is not None and sessionsdigest:
        rad = conn.execute(
            "SELECT id, anvandarnamn, losen_hash FROM forvaltare WHERE id = ?",
            (forvaltare_id,),
        ).fetchone()
        if rad and hmac.compare_digest(losen_digest(rad["losen_hash"]), sessionsdigest):
            return Principal("forvaltare", rad["anvandarnamn"], forvaltare_id=rad["id"])

    medlem_id = request.session.get(SESSION_MEDLEM)
    sessionshash = request.session.get(SESSION_MEDLEM_HASH)
    if medlem_id is not None and sessionshash:
        rad = conn.execute(
            "SELECT id, namn, token FROM medlem WHERE id = ?", (medlem_id,)
        ).fetchone()
        if rad and rad["token"] and hmac.compare_digest(rad["token"], sessionshash):
            return Principal("medlem", rad["namn"], medlem_id=rad["id"])

    return None


def krav_forvaltare(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> Principal:
    principal = aktuell_principal(request, conn)
    if principal is None or principal.kind != "forvaltare":
        # htmx must not swap the login page into a fragment — HX-Redirect
        # makes the browser do a full navigation instead.
        if request.headers.get("hx-request") == "true":
            raise HTTPException(status_code=401, headers={"HX-Redirect": "/login"})
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return principal


def krav_medlem(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> Principal:
    """Member OR admin-in-proxy-mode never passes here — this is strictly the
    member session. medlem_id is ALWAYS taken from the Principal, never from
    request parameters (the I5 isolation rule)."""
    principal = aktuell_principal(request, conn)
    if principal is None or principal.kind != "medlem":
        # A full-page reload surfaces the 403 properly when a token is revoked
        # while a tab is open; a silent htmx 4xx would just do nothing.
        huvuden = (
            {"HX-Refresh": "true"}
            if request.headers.get("hx-request") == "true"
            else None
        )
        raise HTTPException(
            status_code=403,
            detail="Denna sida nås via din personliga svarslänk.",
            headers=huvuden,
        )
    return principal
