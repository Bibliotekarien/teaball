"""The public privacy notice and its footer link."""

from app import config
from tests.conftest import ge_token, logga_in, seed_trad, skapa_medlem


def test_integritetssidan_ar_publik_och_kakfri(client):
    svar = client.get("/integritet")
    assert svar.status_code == 200
    # Key sections are present.
    assert "Personuppgiftsansvarig" in svar.text
    assert "Dina rättigheter" in svar.text
    assert "IMY" in svar.text
    # An anonymous reader of the privacy notice is not handed any cookie.
    assert "set-cookie" not in {k.lower() for k in svar.headers}


def test_integritetssidan_utan_instanstexter(client, monkeypatch):
    """Unconfigured: neutral wording, the fill-in marker, and no claims about
    statistics or a bot-gate cookie the instance may not have."""
    for namn in ("ORGANISATION", "PERSONUPPGIFTSANSVARIG", "DATASKYDD_KONTAKT"):
        monkeypatch.setattr(config, namn, "")
    monkeypatch.setattr(config, "MATOMO_ENABLED", False)
    monkeypatch.setattr(config, "ROBOTSKYDD", False)
    sida = client.get("/integritet").text
    assert "DiVA" not in sida and "konsorti" not in sida
    assert "den organisation som driver" in sida
    assert "fastställs och fylls i här" in sida
    assert "Ingen besöksstatistik samlas in" in sida
    assert "Matomo" not in sida and "Teknisk statistik" not in sida
    assert "robotskyddet" not in sida


def test_integritetssidan_med_instanstexter(client, monkeypatch):
    monkeypatch.setattr(config, "ORGANISATION", "Exempelkonsortiet")
    monkeypatch.setattr(config, "PERSONUPPGIFTSANSVARIG", "Exempeluniversitetet")
    monkeypatch.setattr(config, "DATASKYDD_KONTAKT", "dataskydd@example.org")
    monkeypatch.setattr(config, "MATOMO_ENABLED", True)
    monkeypatch.setattr(config, "ROBOTSKYDD", True)
    sida = client.get("/integritet").text
    assert "behovsarbetet inom Exempelkonsortiet inför" in sida
    assert "Personuppgiftsansvarig är Exempeluniversitetet." in sida
    assert "Frågor om dataskydd: dataskydd@example.org." in sida
    assert "fylls i här" not in sida
    assert "Matomo" in sida and "Teknisk statistik" in sida
    assert "robotskyddet" in sida


def test_integritetssidan_saknad_kontaktvag_markeras(client, monkeypatch):
    monkeypatch.setattr(config, "PERSONUPPGIFTSANSVARIG", "Exempeluniversitetet")
    monkeypatch.setattr(config, "DATASKYDD_KONTAKT", "")
    sida = client.get("/integritet").text
    assert "Personuppgiftsansvarig är Exempeluniversitetet." in sida
    assert "dataskyddsfrågor fylls i här innan" in sida
    assert "Formell" not in sida          # only the contact is missing


def test_instanstexter_escapas(client, monkeypatch):
    monkeypatch.setattr(config, "ORGANISATION", "<b>x</b>")
    sida = client.get("/integritet").text
    assert "<b>x</b>" not in sida and "&lt;b&gt;x&lt;/b&gt;" in sida


def test_footer_lankar_till_integritet_forvaltare(client, app_db):
    seed_trad(app_db)
    logga_in(client, app_db)
    assert 'href="/integritet"' in client.get("/trad").text


def test_footer_lankar_till_integritet_medlem(client, app_db):
    seed_trad(app_db)
    medlem = skapa_medlem(app_db, "Uppsala universitet")
    ratoken = ge_token(app_db, medlem)
    client.get(f"/svara/{ratoken}")           # exchange link for a member session
    assert 'href="/integritet"' in client.get("/svara").text
