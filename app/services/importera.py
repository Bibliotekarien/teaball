"""Initial imports (spec E2): the function tree and the member list, both from
a flat CSV or JSON list.

Tree columns/keys: namn, foralder (parent's name, empty for root), typ, status,
fas, and optionally lank_dokumentation / lank_jira (absolute http(s) URLs).
Two passes: first create every node in file order (which becomes the
sibling order), then wire parents by name. A parent name must be unambiguous —
within the file, or failing that among pre-existing nodes in the database.

Member columns/keys: namn, kategori."""

import csv
import io
import json
import sqlite3

TILLATNA_TYPER = {"förmåga", "funktion", "krav"}
TILLATNA_STATUS = {"driftsatt", "planerad", "idé", "utreds", "utgår"}


def las_rader(innehall: str, filnamn: str) -> list[dict]:
    if filnamn.lower().endswith(".json"):
        data = json.loads(innehall)
        if not isinstance(data, list):
            raise ValueError("JSON-filen måste vara en lista av objekt.")
        return data
    return list(csv.DictReader(io.StringIO(innehall)))


def importera_medlemmar(conn: sqlite3.Connection, rader: list[dict]) -> tuple[int, int]:
    """Insert members from rows with namn (required) and kategori. A name that
    already exists in the database is skipped, so the import can be rerun when
    the upstream member list changes. Returns (inserted, skipped)."""
    sedda: set[str] = set()
    nya = hoppade = 0
    for i, rad in enumerate(rader):
        radnr = i + 2  # header is row 1 in the CSV
        namn = (rad.get("namn") or "").strip()
        if not namn:
            raise ValueError(f"Rad {radnr}: namn saknas.")
        if namn in sedda:
            raise ValueError(f"Rad {radnr}: {namn!r} förekommer flera gånger i filen.")
        sedda.add(namn)
        if conn.execute("SELECT 1 FROM medlem WHERE namn = ?", (namn,)).fetchone():
            hoppade += 1
            continue
        conn.execute(
            "INSERT INTO medlem (namn, kategori) VALUES (?, ?)",
            (namn, (rad.get("kategori") or "").strip() or None),
        )
        nya += 1
    return nya, hoppade


def importera_trad(conn: sqlite3.Connection, rader: list[dict]) -> int:
    namn_till_id: dict[str, int] = {}
    dubbletter: set[str] = set()
    nya_ider: list[tuple[int, str | None]] = []

    for i, rad in enumerate(rader):
        radnr = i + 2  # header is row 1 in the CSV
        namn = (rad.get("namn") or "").strip()
        if not namn:
            raise ValueError(f"Rad {radnr}: namn saknas.")
        typ = (rad.get("typ") or "krav").strip()
        status = (rad.get("status") or "planerad").strip()
        if typ not in TILLATNA_TYPER:
            raise ValueError(f"Rad {radnr}: okänd typ {typ!r}.")
        if status not in TILLATNA_STATUS:
            raise ValueError(f"Rad {radnr}: okänd status {status!r}.")
        lankar = {}
        for falt in ("lank_dokumentation", "lank_jira"):
            lank = (rad.get(falt) or "").strip() or None
            if lank and not lank.startswith(("http://", "https://")):
                raise ValueError(f"Rad {radnr}: {falt} måste börja med http:// eller https://.")
            lankar[falt] = lank
        cur = conn.execute(
            "INSERT INTO funktion (namn, typ, status, fas, sortering,"
            " lank_dokumentation, lank_jira) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (namn, typ, status, (rad.get("fas") or "").strip() or None, (i + 1) * 10,
             lankar["lank_dokumentation"], lankar["lank_jira"]),
        )
        if namn in namn_till_id:
            dubbletter.add(namn)
        else:
            namn_till_id[namn] = cur.lastrowid
        nya_ider.append((cur.lastrowid, (rad.get("foralder") or "").strip() or None))

    for i, (nod_id, foralder_namn) in enumerate(nya_ider):
        if foralder_namn is None:
            continue
        radnr = i + 2
        if foralder_namn in dubbletter:
            raise ValueError(
                f"Rad {radnr}: föräldernamnet {foralder_namn!r} är inte unikt i filen."
            )
        foralder_id = namn_till_id.get(foralder_namn)
        if foralder_id is None:
            traffar = conn.execute(
                "SELECT id FROM funktion WHERE namn = ?", (foralder_namn,)
            ).fetchall()
            if len(traffar) > 1:
                raise ValueError(
                    f"Rad {radnr}: föräldernamnet {foralder_namn!r} är inte unikt i databasen."
                )
            if not traffar:
                raise ValueError(
                    f"Rad {radnr}: föräldern {foralder_namn!r} finns varken i filen"
                    " eller i databasen."
                )
            foralder_id = traffar[0]["id"]
        conn.execute(
            "UPDATE funktion SET foralder_id = ? WHERE id = ?", (foralder_id, nod_id)
        )
    return len(nya_ider)
