"""Phase 2 backend: member access via unique link tokens (spec S2, B2).

The raw token (256 bits, secrets.token_urlsafe) is shown to the admin exactly
once at generation; only its SHA-256 hex digest is stored in medlem.token.
/svara/<token> exchanges the link for a session and redirects, so the token
never lingers in htmx request URLs or Referer headers. The member session
stores the hash — regenerating or revoking the token invalidates existing
sessions immediately (see auth.core.aktuell_principal)."""

import hashlib
import hmac
import secrets
import sqlite3


def generera() -> tuple[str, str]:
    """(raw token for the link, hash for storage)."""
    token = secrets.token_urlsafe(32)  # 256 bits of randomness (S2: >= 128)
    return token, hasha(token)


def hasha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def verifiera(conn: sqlite3.Connection, token: str):
    """The medlem row for a presented raw token, or None. The indexed lookup is
    already the comparison; compare_digest is belt and braces on top (S2)."""
    kandidat = hasha(token)
    rad = conn.execute(
        "SELECT id, namn, token FROM medlem WHERE token = ?", (kandidat,)
    ).fetchone()
    if rad is None or not hmac.compare_digest(rad["token"], kandidat):
        return None
    return rad
