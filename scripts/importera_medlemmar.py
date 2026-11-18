"""Load the member list from CSV or JSON (columns/keys: namn, kategori).

Usage:
    python scripts/importera_medlemmar.py <fil> [--db sökväg]

The file is required: every instance has its own members. The DiVA
consortium list in data/diva_medlemmar.csv is an example of the format.
Members whose name already exists are skipped, so the import can be rerun
when the upstream list changes."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402
from app.services.importera import importera_medlemmar, las_rader  # noqa: E402

def main() -> int:
    parser = argparse.ArgumentParser(description="Läs in medlemslistan från CSV/JSON.")
    parser.add_argument("fil", type=Path)
    parser.add_argument("--db", help="Sökväg till databasfilen (annars DB_PATH)."
                             " Krävs när ORGANISATIONER_DIR är satt:"
                             " <ORGANISATIONER_DIR>/<hostnamn>.db.")
    args = parser.parse_args()

    rader = las_rader(args.fil.read_text(encoding="utf-8"), args.fil.name)
    conn = db.connect(args.db)
    try:
        db.init_db(conn)
        nya, hoppade = importera_medlemmar(conn, rader)
        conn.commit()
    except ValueError as fel:
        conn.rollback()
        print(f"Importen avbröts: {fel}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    print(f"{nya} medlemmar inlästa, {hoppade} fanns redan.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
