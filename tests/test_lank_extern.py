"""Länk till extern dokumentation per nod (migration 0012): den enda nodlänken
som medlemmarna och kontorollen extern ser. Det interna kravdokumentet och
Jira-länken är bara för förvaltarna."""

import pytest

from app import config, db
from app.services.exportera import trad_csv
from app.services.importera import importera_trad, las_rader
from tests.conftest import csrf_fran, ge_token, logga_in, skapa_funktion, skapa_medlem

EXTERN = "https://docs.example/publicering"
INTERN_DOK = "https://wiki.intern.example/behov"
JIRA = "https://jira.intern.example/DIVA-7"


def _nod(conn):
    nod_id = skapa_funktion(conn, "Publicering", typ="förmåga",
                            lank_dokumentation=INTERN_DOK, lank_jira=JIRA,
                            lank_extern=EXTERN)
    conn.commit()
    return nod_id


def test_medlemmen_ser_bara_den_externa_lanken(client, app_db):
    _nod(app_db)
    token = ge_token(app_db, skapa_medlem(app_db, "KTH"))
    client.get(f"/svara/{token}")
    sida = client.get("/svara").text
    assert f'href="{EXTERN}"' in sida
    assert INTERN_DOK not in sida
    assert JIRA not in sida


def test_forvaltaren_ser_alla_lankar(client, app_db):
    _nod(app_db)
    logga_in(client, app_db)
    # The compact/detailed choice is kept in the session; the second request
    # is a plain page load in the chosen view.
    client.get("/trad", params={"vy": "detaljerad"})
    sida = client.get("/trad").text
    for lank in (EXTERN, INTERN_DOK, JIRA):
        assert f'href="{lank}"' in sida


def test_extern_roll_ser_bara_den_externa_lanken(client, app_db):
    """Kontorollen extern ser samma sak som medlemmarna (README)."""
    _nod(app_db)
    logga_in(client, app_db, namn="extern-konto", roll="extern")
    sida = client.get("/trad", params={"vy": "detaljerad"}).text
    assert f'href="{EXTERN}"' in sida
    assert INTERN_DOK not in sida
    assert JIRA not in sida


def test_lankarna_har_text_for_skarmlasare(client, app_db):
    """Länktexten upprepas på varje nod; skärmläsaren får veta vilken nod och
    att länken öppnas i ny flik, och pilen läses inte upp."""
    _nod(app_db)
    token = ge_token(app_db, skapa_medlem(app_db, "KTH"))
    client.get(f"/svara/{token}")
    sida = client.get("/svara").text
    assert '<span class="sr-only"> för Publicering (öppnas i ny flik)</span>' in sida
    assert '<span aria-hidden="true">↗</span>' in sida


def test_formularet_sparar_och_validerar_lanken(client, app_db):
    nod_id = _nod(app_db)
    logga_in(client, app_db)
    token = csrf_fran(client.get("/trad").text)
    falt = {"namn": "Publicering", "typ": "förmåga", "status": "planerad",
            "fas": "Avgång 1", "synlig_externt": "1", "csrf_token": token}

    client.post(f"/trad/nod/{nod_id}", data={**falt, "lank_extern": "https://docs.example/ny"})
    rad = app_db.execute("SELECT lank_extern FROM funktion WHERE id = ?", (nod_id,)).fetchone()
    assert rad["lank_extern"] == "https://docs.example/ny"

    svar = client.post(f"/trad/nod/{nod_id}", data={**falt, "lank_extern": "javascript:alert(1)"})
    assert "Länken till extern dokumentation måste börja med http" in svar.text
    rad = app_db.execute("SELECT lank_extern FROM funktion WHERE id = ?", (nod_id,)).fetchone()
    assert rad["lank_extern"] == "https://docs.example/ny"


@pytest.mark.parametrize("adress", ["/lista/nod/{id}", "/kommentarer/nod/{id}/redigera"])
def test_lista_och_kommentarsvyn_sparar_lanken(client, app_db, adress):
    """Samma formulär sparas från listan och kommentarsvyn; båda vägarna ska
    skriva länken, inte bara låta bli att krascha."""
    nod_id = _nod(app_db)
    logga_in(client, app_db)
    token = csrf_fran(client.get("/trad").text)
    client.post(adress.format(id=nod_id), data={
        "namn": "Publicering", "typ": "förmåga", "status": "planerad", "fas": "Avgång 1",
        "synlig_externt": "1", "lank_extern": "https://docs.example/via", "csrf_token": token})
    rad = app_db.execute("SELECT lank_extern FROM funktion WHERE id = ?", (nod_id,)).fetchone()
    assert rad["lank_extern"] == "https://docs.example/via"


def test_ny_nod_far_lanken(client, app_db):
    logga_in(client, app_db)
    token = csrf_fran(client.get("/trad").text)
    client.post("/trad/nod", data={
        "namn": "Ny förmåga", "typ": "förmåga", "status": "planerad", "fas": "Avgång 1",
        "synlig_externt": "1", "lank_extern": "https://docs.example/ny", "csrf_token": token})
    rad = app_db.execute("SELECT lank_extern FROM funktion WHERE namn = 'Ny förmåga'").fetchone()
    assert rad["lank_extern"] == "https://docs.example/ny"


def test_andrad_lank_uppdaterar_stampeln(app_db):
    nod_id = _nod(app_db)
    app_db.execute("UPDATE funktion SET uppdaterad = '2000-01-01 00:00:00' WHERE id = ?", (nod_id,))
    app_db.execute("UPDATE funktion SET lank_extern = 'https://docs.example/ny' WHERE id = ?",
                   (nod_id,))
    rad = app_db.execute("SELECT uppdaterad FROM funktion WHERE id = ?", (nod_id,)).fetchone()
    assert rad["uppdaterad"] > "2000-01-01 00:00:00"


def test_externt_urval_av_exporten_har_bara_den_externa_lanken(client, app_db):
    """Urvalet "endast synligt externt" är det som delas med medlemmarna."""
    _nod(app_db)
    logga_in(client, app_db)
    externt = client.get("/export/kravtrad.html", params={"endast_synliga": "1"}).text
    assert f'href="{EXTERN}"' in externt
    assert INTERN_DOK not in externt and JIRA not in externt
    allt = client.get("/export/kravtrad.html").text
    for lank in (EXTERN, INTERN_DOK, JIRA):
        assert f'href="{lank}"' in allt


def test_csv_export_och_import_tar_med_lanken(conn):
    _nod(conn)
    ut = trad_csv(conn)
    assert "lank_extern" in ut.splitlines()[0] and EXTERN in ut
    importera_trad(conn, las_rader(
        "namn,foralder,typ,status,fas,lank_extern\n"
        "Ny nod,,krav,planerad,Avgång 1,https://docs.example/ny\n", "x.csv"))
    rad = conn.execute("SELECT lank_extern FROM funktion WHERE namn = 'Ny nod'").fetchone()
    assert rad["lank_extern"] == "https://docs.example/ny"


def test_importen_validerar_som_formularen(conn):
    """Samma regel som formulären: http/https, högst 500 tecken, och ett
    JSON-värde som inte är en sträng ger ett radnumrerat fel."""
    with pytest.raises(ValueError, match="Rad 2: lank_extern måste börja med http"):
        importera_trad(conn, las_rader(
            "namn,foralder,typ,status,fas,lank_extern\n"
            "A,,krav,planerad,Avgång 1,javascript:alert(1)\n", "x.csv"))
    with pytest.raises(ValueError, match="Rad 2: lank_jira måste börja med http"):
        importera_trad(conn, las_rader(
            '[{"namn": "B", "typ": "krav", "status": "planerad", "fas": "Avgång 1",'
            ' "lank_jira": 5}]', "x.json"))
    lang = "https://docs.example/" + "x" * 600
    importera_trad(conn, las_rader(
        f"namn,foralder,typ,status,fas,lank_extern\nC,,krav,planerad,Avgång 1,{lang}\n", "x.csv"))
    rad = conn.execute("SELECT lank_extern FROM funktion WHERE namn = 'C'").fetchone()
    assert len(rad["lank_extern"]) == 500


def test_lagre_migration_som_kommer_senare_kors_anda(tmp_path, monkeypatch):
    """0012 driftsätts före 0010 och 0011 (flera organisationer). migrate()
    kör varje fil vars nummer saknas, så de körs när de väl kommer."""
    # Egna migrationsfiler, så att testet inte beror på vilka nummer som
    # redan finns i db/migrations.
    katalog = tmp_path / "migrationer"
    katalog.mkdir()
    (katalog / "0001_forsta.sql").write_text("CREATE TABLE forsta (id INTEGER);\n", "utf-8")
    (katalog / "0003_tredje.sql").write_text("CREATE TABLE tredje (id INTEGER);\n", "utf-8")
    monkeypatch.setattr(config, "MIGRATIONS_DIR", katalog)
    conn = db.connect(tmp_path / "x.db")
    db.migrate(conn)

    (katalog / "0002_senare.sql").write_text("CREATE TABLE senare (id INTEGER);\n", "utf-8")
    db.migrate(conn)
    versioner = {r[0] for r in conn.execute("SELECT version FROM schema_migration")}
    assert versioner == {1, 2, 3}
    assert conn.execute("SELECT count(*) FROM senare").fetchone()[0] == 0
    conn.close()
