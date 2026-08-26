"""Tests for roadmap (R1/R2), exports (E1 + xlsx) and the import script (E2),
including the roadmap half of acceptance test §9.4."""

import io
import json
from pathlib import Path

from openpyxl import load_workbook

from app.services.importera import importera_medlemmar, importera_trad, las_rader
from tests.conftest import logga_in, satt_svar, seed_trad, skapa_medlem


def test_roadmap_r1_typfilter(client, app_db):
    seed_trad(app_db)
    logga_in(client, app_db)
    sida = client.get("/roadmap").text
    assert "Publicering" in sida and "Import från Web of Science" in sida
    assert "Dubblettdetektering" not in sida          # krav hidden by default
    med_krav = client.get("/roadmap", params={"visa_krav": "1"}).text
    assert "Dubblettdetektering" in med_krav


def test_acceptance_9_4_roadmap_export(client, app_db):
    ids = seed_trad(app_db)
    app_db.execute("UPDATE funktion SET synlig_externt = 0 WHERE id = ?",
                   (ids["publicering"],))
    app_db.commit()
    logga_in(client, app_db)

    export = client.get("/roadmap/export")
    assert export.status_code == 200
    assert 'attachment; filename="roadmap-' in export.headers["content-disposition"]
    # The hidden capability's whole subtree is gone from the export ...
    assert "Publicering" not in export.text
    assert "Import från Web of Science" not in export.text
    assert "Export &amp; spridning" in export.text
    # ... and the export is script-free (R2).
    assert "<script" not in export.text
    # ... but admins still see the branch in the roadmap view.
    assert "Publicering" in client.get("/roadmap").text


def test_json_export_utan_token(client, app_db):
    seed_trad(app_db)
    medlem = skapa_medlem(app_db, "Uppsala universitet")
    app_db.execute("UPDATE medlem SET token = 'hemlig-hash' WHERE id = ?", (medlem,))
    satt_svar(app_db, medlem, seed := 1, "golive_krav")
    app_db.commit()
    logga_in(client, app_db)

    svar = client.get("/export/json")
    data = json.loads(svar.text)
    assert set(data) == {"funktion", "medlem", "bedomning", "bedomning_historik"}
    assert len(data["funktion"]) == 6
    assert data["bedomning"][0]["svar"] == "golive_krav"
    assert all("token" not in rad for rad in data["medlem"])
    assert "hemlig-hash" not in svar.text


def test_csv_exporter(client, app_db):
    ids = seed_trad(app_db)
    medlem = skapa_medlem(app_db, "Uppsala universitet")
    satt_svar(app_db, medlem, ids["wos"], "kan_vanta", workaround="Cron-skript.")
    app_db.commit()
    logga_in(client, app_db)

    trad = client.get("/export/trad.csv").text
    assert trad.splitlines()[0].startswith("id,namn,foralder_id,foralder_namn")
    assert "Dubblettdetektering" in trad

    bed = client.get("/export/bedomningar.csv").text
    assert "Uppsala universitet" in bed and "Cron-skript." in bed


def test_xlsx_export_alla_vyer(client, app_db):
    ids = seed_trad(app_db)
    medlem = skapa_medlem(app_db, "Uppsala universitet")
    satt_svar(app_db, medlem, ids["dubblett"], "golive_krav")
    app_db.commit()
    logga_in(client, app_db)

    svar = client.get("/export/teaball.xlsx")
    assert svar.status_code == 200
    wb = load_workbook(io.BytesIO(svar.content))
    assert wb.sheetnames == ["Kravträd", "Bedömningar", "Analys", "Migrering", "Roadmap"]

    trad_blad = wb["Kravträd"]
    namn = [rad[0] for rad in trad_blad.iter_rows(min_row=2, values_only=True)]
    assert namn[0] == "Publicering"                       # tree order, roots unindented
    assert any(n.lstrip() == "Dubblettdetektering" and n.startswith("    ") for n in namn)

    bed_blad = wb["Bedömningar"]
    rad = next(bed_blad.iter_rows(min_row=2, values_only=True))
    assert rad[0] == "Uppsala universitet" and rad[3] == "Go-live"

    analys_blad = wb["Analys"]
    assert "1 av 1" in analys_blad.cell(row=1, column=1).value


def test_import_fran_csv(conn):
    csv_text = (
        "namn,foralder,typ,status,fas\n"
        "Publicering,,förmåga,befintlig,nu\n"
        "Registrera avhandling,Publicering,funktion,befintlig,nu\n"
        "Spikblad genereras,Registrera avhandling,krav,planerad,nästa\n"
        "Import,Publicering,funktion,befintlig,nu\n"
    )
    antal = importera_trad(conn, las_rader(csv_text, "underlag.csv"))
    conn.commit()
    assert antal == 4
    rows = {r["namn"]: dict(r) for r in conn.execute("SELECT * FROM funktion")}
    assert rows["Registrera avhandling"]["foralder_id"] == rows["Publicering"]["id"]
    assert rows["Spikblad genereras"]["foralder_id"] == rows["Registrera avhandling"]["id"]
    # File order becomes sibling order.
    ordning = [r["namn"] for r in conn.execute(
        "SELECT namn FROM funktion WHERE foralder_id = ? ORDER BY sortering",
        (rows["Publicering"]["id"],))]
    assert ordning == ["Registrera avhandling", "Import"]


def test_import_fel_avvisas(conn):
    import pytest

    with pytest.raises(ValueError, match="finns varken"):
        importera_trad(conn, las_rader("namn,foralder\nA,Saknas\n", "x.csv"))
    with pytest.raises(ValueError, match="inte unikt i filen"):
        importera_trad(conn, las_rader(
            "namn,foralder\nDubbel,\nDubbel,\nBarn,Dubbel\n", "x.csv"))
    with pytest.raises(ValueError, match="okänd typ"):
        importera_trad(conn, las_rader("namn,foralder,typ\nA,,fel\n", "x.csv"))


def test_import_fran_json(conn):
    data = json.dumps([
        {"namn": "Publicering", "typ": "förmåga", "status": "befintlig"},
        {"namn": "Import", "foralder": "Publicering", "typ": "funktion"},
    ])
    assert importera_trad(conn, las_rader(data, "underlag.json")) == 2


def test_importera_medlemmar_fran_csv(conn):
    csv_text = "namn,kategori\nUppsala universitet,universitet\nRiksarkivet,\n"
    assert importera_medlemmar(conn, las_rader(csv_text, "medlemmar.csv")) == (2, 0)
    conn.commit()
    rader = {r["namn"]: r["kategori"]
             for r in conn.execute("SELECT namn, kategori FROM medlem")}
    assert rader == {"Uppsala universitet": "universitet", "Riksarkivet": None}


def test_importera_medlemmar_hoppar_befintliga(conn):
    skapa_medlem(conn, "Uppsala universitet")
    csv_text = ("namn,kategori\nUppsala universitet,universitet\n"
                "Umeå universitet,universitet\n")
    assert importera_medlemmar(conn, las_rader(csv_text, "m.csv")) == (1, 1)
    # Rerunning the same file is a no-op.
    assert importera_medlemmar(conn, las_rader(csv_text, "m.csv")) == (0, 2)


def test_importera_medlemmar_fel_avvisas(conn):
    import pytest

    with pytest.raises(ValueError, match="namn saknas"):
        importera_medlemmar(conn, las_rader("namn,kategori\n,museum\n", "m.csv"))
    with pytest.raises(ValueError, match="flera gånger"):
        importera_medlemmar(conn, las_rader("namn\nDubbel\nDubbel\n", "m.csv"))


def test_diva_underlagen_importerar(conn):
    """The bundled data files must stay importable and internally consistent."""
    rot = Path(__file__).resolve().parent.parent
    fil = rot / "data" / "diva_medlemmar.csv"
    nya, hoppade = importera_medlemmar(
        conn, las_rader(fil.read_text("utf-8"), fil.name))
    assert (nya, hoppade) == (49, 0)
    rad = conn.execute(
        "SELECT kategori FROM medlem WHERE namn = 'Uppsala universitet'").fetchone()
    assert rad["kategori"] == "universitet"

    trad = rot / "data" / "diva_formagekarta_exempel.csv"
    assert importera_trad(conn, las_rader(trad.read_text("utf-8"), trad.name)) == 16
