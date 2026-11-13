"""Create or update a staff account.

Usage:
    python scripts/skapa_forvaltare.py <anvandarnamn> [--roll admin|intern|extern]
                                       [--losenord ...] [--db sökväg]

Without --losenord the password is prompted for (twice). Without --roll a new
account becomes admin (the column default) and an existing account keeps its
role — a password reset must never silently change permissions. In the
container:
    docker compose exec app python scripts/skapa_forvaltare.py anna
"""

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402
from app.auth.password import hash_losen  # noqa: E402


def las_losenord(losenord: str | None) -> str | None:
    """The password from the argument or a double prompt; None (with the
    reason printed) when it does not match or is too short."""
    if not losenord:
        losenord = getpass.getpass("Lösenord: ")
        if losenord != getpass.getpass("Upprepa lösenord: "):
            print("Lösenorden skiljer sig åt.", file=sys.stderr)
            return None
    if len(losenord) < 8:
        print("Lösenordet måste vara minst 8 tecken.", file=sys.stderr)
        return None
    return losenord


def main() -> int:
    parser = argparse.ArgumentParser(description="Skapa eller uppdatera ett förvaltarkonto.")
    parser.add_argument("anvandarnamn")
    parser.add_argument("--roll", choices=["admin", "intern", "extern"],
                        help="Roll för kontot. Utelämnad: nya konton blir admin,"
                             " befintliga behåller sin roll.")
    parser.add_argument("--losenord", help="Anges helst inte på kommandoraden; utelämna för prompt.")
    parser.add_argument("--db", help="Sökväg till databasfilen (annars DB_PATH)."
                             " Krävs när ORGANISATIONER_DIR är satt:"
                             " <ORGANISATIONER_DIR>/<hostnamn>.db.")
    args = parser.parse_args()

    losenord = las_losenord(args.losenord)
    if losenord is None:
        return 1

    conn = db.connect(args.db)
    try:
        db.init_db(conn)
        if args.roll:
            conn.execute(
                "INSERT INTO forvaltare (anvandarnamn, losen_hash, roll) VALUES (?, ?, ?)"
                " ON CONFLICT (anvandarnamn) DO UPDATE SET"
                " losen_hash = excluded.losen_hash, roll = excluded.roll",
                (args.anvandarnamn, hash_losen(losenord), args.roll),
            )
        else:
            # No --roll: leave an existing account's role untouched (a password
            # reset must never silently promote or demote); new rows fall back
            # to the column default 'admin'.
            conn.execute(
                "INSERT INTO forvaltare (anvandarnamn, losen_hash) VALUES (?, ?)"
                " ON CONFLICT (anvandarnamn) DO UPDATE SET losen_hash = excluded.losen_hash",
                (args.anvandarnamn, hash_losen(losenord)),
            )
        conn.commit()
        roll = conn.execute(
            "SELECT roll FROM forvaltare WHERE anvandarnamn = ?", (args.anvandarnamn,)
        ).fetchone()["roll"]
    finally:
        conn.close()
    print(f"Kontot '{args.anvandarnamn}' är skapat/uppdaterat med rollen {roll}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
