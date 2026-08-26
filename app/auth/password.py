"""Phase 1 backend: admin username/password with argon2 (spec S1)."""

import sqlite3

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.auth.core import Principal

_hasher = PasswordHasher()


def hash_losen(losenord: str) -> str:
    return _hasher.hash(losenord)


def verifiera(conn: sqlite3.Connection, anvandarnamn: str, losenord: str) -> Principal | None:
    rad = conn.execute(
        "SELECT id, anvandarnamn, losen_hash FROM forvaltare WHERE anvandarnamn = ?",
        (anvandarnamn,),
    ).fetchone()
    if rad is None:
        # Hash anyway so unknown and known usernames take similar time.
        _hasher.hash(losenord)
        return None
    try:
        _hasher.verify(rad["losen_hash"], losenord)
    except VerifyMismatchError:
        return None
    return Principal("forvaltare", rad["anvandarnamn"], forvaltare_id=rad["id"])
