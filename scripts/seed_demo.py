"""Seed a performance/demo dataset per spec I3: ~500 nodes, 50 members,
10 000 assessments. Deterministic (fixed random seed).

Usage:
    python scripts/seed_demo.py [--db sökväg]

Intended for an empty database (refuses to run against one with data).
"""

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402

KATEGORIER = ["universitet", "högskola", "myndighet", "museum"]
FASER = ["Avgång 1", "senare"]
STATUSAR = ["driftsatt", "planerad", "idé", "utreds", "utgår"]
SVAR = ["golive_krav", "kan_vanta", "behovs_ej"]


def seed(conn, slump: random.Random | None = None) -> tuple[int, int]:
    """Fill an empty, migrated database. Returns (node count, assessment count).
    10 förmågor × (1 + 5 × (1 + 9)) = 510 nodes; 50 members × 200 = 10 000
    assessments."""
    slump = slump or random.Random(42)

    nod_ider = []
    for f in range(1, 11):
        formaga = conn.execute(
            "INSERT INTO funktion (namn, typ, status, fas, sortering)"
            " VALUES (?, 'förmåga', 'driftsatt', 'Avgång 1', ?)",
            (f"Förmåga {f}", f * 10),
        ).lastrowid
        nod_ider.append(formaga)
        for u in range(1, 6):
            funktion = conn.execute(
                "INSERT INTO funktion (namn, foralder_id, typ, status, fas, sortering)"
                " VALUES (?, ?, 'funktion', ?, ?, ?)",
                (f"Funktion {f}.{u}", formaga, slump.choice(STATUSAR),
                 slump.choice(FASER), u * 10),
            ).lastrowid
            nod_ider.append(funktion)
            for k in range(1, 10):
                krav = conn.execute(
                    "INSERT INTO funktion (namn, foralder_id, typ, status, fas, sortering)"
                    " VALUES (?, ?, 'krav', ?, ?, ?)",
                    (f"Krav {f}.{u}.{k}", funktion, slump.choice(STATUSAR),
                     slump.choice(FASER), k * 10),
                ).lastrowid
                nod_ider.append(krav)

    medlem_ider = [
        conn.execute(
            "INSERT INTO medlem (namn, kategori) VALUES (?, ?)",
            (f"Medlemsorganisation {m:02d}", slump.choice(KATEGORIER)),
        ).lastrowid
        for m in range(1, 51)
    ]

    for medlem_id in medlem_ider:
        for funktion_id in slump.sample(nod_ider, 200):
            svar = slump.choice(SVAR)
            oppen = (
                "Manuellt kringgående via exportfil."
                if svar == "kan_vanta" and slump.random() < 0.3 else None
            )
            conn.execute(
                "INSERT INTO bedomning (medlem_id, funktion_id, svar, oppen_kommentar,"
                " oppen_delning, intern_kommentar) VALUES (?, ?, ?, ?, ?, ?)",
                (medlem_id, funktion_id, svar, oppen,
                 "anonym" if oppen and slump.random() < 0.5 else "privat",
                 "Diskuterat på dialogmöte." if slump.random() < 0.1 else None),
            )
    conn.commit()
    return len(nod_ider), len(medlem_ider) * 200


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", help="Sökväg till databasfilen (annars DB_PATH/standard).")
    args = parser.parse_args()

    conn = db.connect(args.db)
    try:
        db.init_db(conn)
        if conn.execute("SELECT COUNT(*) FROM funktion").fetchone()[0]:
            print("Databasen är inte tom — avbryter.", file=sys.stderr)
            return 1
        noder, bedomningar = seed(conn)
        print(f"Seedat: {noder} noder, 50 medlemmar, {bedomningar} bedömningar.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
