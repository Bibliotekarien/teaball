"""Instansens texter i databasen (app/instans.py): engångsfyllningen från
miljön, adminsidan /installningar och att texterna följer databasen per
anrop."""

from app import config, db as appdb, instans
from tests.conftest import csrf_fran, logga_in, seed_trad, skapa_forvaltare


def _ny_databas(tmp_path, namn="ny.db"):
    conn = appdb.connect(tmp_path / namn)
    appdb.init_db(conn)
    return conn


def _som_fore_0010(conn):
    """En databas i bruk när migration 0010 kommer: ett konto finns och
    tabellen instans är nyss skapad."""
    skapa_forvaltare(conn)
    conn.execute("UPDATE instans SET fran_miljon = 0 WHERE id = 1")
    conn.commit()


def test_fylls_fran_miljon_en_gang_vid_uppgradering(tmp_path, monkeypatch, caplog):
    """En instans som konfigurerats med .env behåller sina texter vid
    uppgraderingen. Därefter gäller databasen: ändrad miljö påverkar inte,
    men den ignorerade variabeln loggas."""
    conn = _ny_databas(tmp_path)
    _som_fore_0010(conn)
    monkeypatch.setattr(config, "ORGANISATION", "DiVA-konsortiet")
    monkeypatch.setattr(config, "NUVARANDE_SYSTEM", "DiVA Classic")
    appdb.init_db(conn)                       # första start efter 0010
    assert instans.las(conn) == instans.Instans(
        organisation="DiVA-konsortiet", nuvarande_system="DiVA Classic")

    monkeypatch.setattr(config, "ORGANISATION", "Något annat")
    caplog.clear()
    appdb.init_db(conn)                       # nästa start
    assert instans.las(conn).organisation == "DiVA-konsortiet"
    assert "Ignoreras" in caplog.text and "ORGANISATION" in caplog.text
    conn.close()


def test_ny_databas_arver_inte_miljon(tmp_path, monkeypatch, caplog):
    """Med en databasfil per organisation får en ny organisation aldrig
    serverns texter, t.ex. en annan organisations personuppgiftsansvarig."""
    monkeypatch.setattr(config, "ORGANISATION", "DiVA-konsortiet")
    monkeypatch.setattr(config, "PERSONUPPGIFTSANSVARIG", "Någon annans universitet")
    conn = _ny_databas(tmp_path)
    assert instans.las(conn) == instans.Instans()
    assert "Ny databas fylls inte" in caplog.text
    conn.close()


def test_tom_miljo_ger_tomma_texter(tmp_path):
    conn = _ny_databas(tmp_path)
    assert instans.las(conn) == instans.Instans()
    assert instans.las(conn).systemnamn == "det nuvarande systemet"
    conn.close()


def test_spara_trimmar_och_kapar(app_db):
    sparad = instans.spara(app_db, organisation="  Konsortiet  ", nuvarande_system="x" * 500)
    assert sparad.organisation == "Konsortiet"
    assert len(sparad.nuvarande_system) == instans.MAXLANGD["nuvarande_system"]
    assert instans.las(app_db) == sparad


def test_installningar_sparas_och_syns_direkt(client, app_db):
    seed_trad(app_db)
    logga_in(client, app_db)
    sida = client.get("/installningar").text
    assert "Saknas: personuppgiftsansvarig och kontakt för dataskydd." in sida
    assert "Ändringar gäller direkt." in sida

    svar = client.post("/installningar", data={
        "organisation": "Exempelkonsortiet",
        "nuvarande_system": "Gamla systemet",
        "personuppgiftsansvarig": "Exempeluniversitetet",
        "dataskydd_kontakt": "dpo@example.org",
        "csrf_token": csrf_fran(sida),
    }, follow_redirects=False)

    assert svar.status_code == 303
    sida = client.get("/installningar").text
    assert "Sparat." in sida
    assert 'value="Exempelkonsortiet"' in sida
    assert "Saknas:" not in sida
    # Statusförklaringen och integritetssidan läser det nya utan omstart.
    assert "Finns i Gamla systemet; identifierad" in client.get("/trad").text
    assert "Personuppgiftsansvarig är Exempeluniversitetet." in client.get("/integritet").text


def test_varningen_foljer_integritetssidan(client, app_db):
    """Bara kontaktvägen saknas: integritetssidan markerar den, så ska
    Inställningar också göra."""
    instans.spara(app_db, personuppgiftsansvarig="Exempeluniversitetet")
    logga_in(client, app_db)
    assert "Saknas: kontakt för dataskydd." in client.get("/installningar").text
    assert "dataskyddsfrågor fylls i här" in client.get("/integritet").text


def test_lasfel_ger_neutral_text(client, app_db, monkeypatch, caplog):
    """En databas som inte går att läsa ger neutral text, inte 500."""
    import sqlite3

    def trasig(conn):
        raise sqlite3.OperationalError("database is locked")

    instans.spara(app_db, organisation="Exempelkonsortiet")
    monkeypatch.setattr(instans, "las", trasig)
    svar = client.get("/integritet")
    assert svar.status_code == 200
    assert "Exempelkonsortiet" not in svar.text
    assert "den organisation som driver" in svar.text
    assert "Kunde inte läsa instansens texter" in caplog.text


def test_utreds_ar_neutral_utan_system(client, app_db):
    seed_trad(app_db)
    logga_in(client, app_db)
    assert "Finns i det nuvarande systemet; identifierad" in client.get("/trad").text


def test_installningar_kraver_admin(client, app_db):
    logga_in(client, app_db, namn="ivar", roll="intern")
    assert client.get("/installningar", follow_redirects=False).status_code == 403
    token = csrf_fran(client.get("/trad").text)
    svar = client.post("/installningar", data={"organisation": "x", "csrf_token": token},
                       follow_redirects=False)
    assert svar.status_code == 403
    assert instans.las(app_db).organisation == ""


def test_installningar_kraver_csrf(client, app_db):
    logga_in(client, app_db)
    svar = client.post("/installningar", data={"organisation": "x"}, follow_redirects=False)
    assert svar.status_code in (400, 403)
    assert instans.las(app_db).organisation == ""


def test_fliken_syns_bara_for_admin(client, app_db, klient_fabrik):
    seed_trad(app_db)
    logga_in(client, app_db)
    assert 'href="/installningar"' in client.get("/trad").text
    intern = klient_fabrik()
    logga_in(intern, app_db, namn="ivar", roll="intern")
    assert 'href="/installningar"' not in intern.get("/trad").text


def test_texterna_escapas_i_tooltip(client, app_db):
    seed_trad(app_db)
    instans.spara(app_db, nuvarande_system='"><script>x</script>')
    logga_in(client, app_db)
    sida = client.get("/trad").text
    assert "<script>x</script>" not in sida
    assert "Finns i &#34;&gt;&lt;script&gt;" in sida
