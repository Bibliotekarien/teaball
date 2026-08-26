"""Create or update an admin account.

Usage:
    python scripts/skapa_forvaltare.py <anvandarnamn> [--losenord ...] [--db sökväg]

Without --losenord the password is prompted for (twice). In the container:
    docker compose exec app python scripts/skapa_forvaltare.py anna
"""

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402
from app.auth.password import hash_losen  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Skapa eller uppdatera ett förvaltarkonto.")
    parser.add_argument("anvandarnamn")
    parser.add_argument("--losenord", help="Anges helst inte på kommandoraden; utelämna för prompt.")
    parser.add_argument("--db", help="Sökväg till databasfilen (annars DB_PATH/standard).")
    args = parser.parse_args()

    losenord = args.losenord
    if not losenord:
        losenord = getpass.getpass("Lösenord: ")
        if losenord != getpass.getpass("Upprepa lösenord: "):
            print("Lösenorden skiljer sig åt.", file=sys.stderr)
            return 1
    if len(losenord) < 8:
        print("Lösenordet måste vara minst 8 tecken.", file=sys.stderr)
        return 1

    conn = db.connect(args.db)
    try:
        db.init_db(conn)
        conn.execute(
            "INSERT INTO forvaltare (anvandarnamn, losen_hash) VALUES (?, ?)"
            " ON CONFLICT (anvandarnamn) DO UPDATE SET losen_hash = excluded.losen_hash",
            (args.anvandarnamn, hash_losen(losenord)),
        )
        conn.commit()
    finally:
        conn.close()
    print(f"Förvaltarkontot '{args.anvandarnamn}' är skapat/uppdaterat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
