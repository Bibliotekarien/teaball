"""Initial load of the function tree from CSV or JSON (spec E2).

Usage:
    python scripts/importera_trad.py underlag.csv [--db sökväg]

CSV columns / JSON keys: namn, foralder (parent's name, empty for root),
typ (förmåga|funktion|krav, default krav), status (default planerad), fas
(required when status is planerad/driftsatt — the avgång rule).
The file order becomes the sibling order. The whole import is one transaction —
a validation error leaves the database untouched."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402
from app.services.importera import importera_trad, las_rader  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Läs in funktionsträdet från CSV/JSON.")
    parser.add_argument("fil", type=Path)
    parser.add_argument("--db", help="Sökväg till databasfilen (annars DB_PATH)."
                             " Krävs när ORGANISATIONER_DIR är satt:"
                             " <ORGANISATIONER_DIR>/<hostnamn>.db.")
    args = parser.parse_args()

    rader = las_rader(args.fil.read_text(encoding="utf-8"), args.fil.name)
    conn = db.connect(args.db)
    try:
        db.init_db(conn)
        antal = importera_trad(conn, rader)
        conn.commit()
    except ValueError as fel:
        conn.rollback()
        print(f"Importen avbröts: {fel}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    print(f"{antal} noder inlästa.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
