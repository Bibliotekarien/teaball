"""The public privacy notice and its footer link."""

import pytest
from fastapi.testclient import TestClient

from app import config, db as appdb, instans
from tests.conftest import ge_token, logga_in, seed_trad, skapa_medlem

VARD = "teaball.exempel.se"


def _platt(svar) -> str:
    """Sidans text med radbrytningar och indrag hopslagna till ett mellanslag."""
    return " ".join(svar.text.split())


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
    monkeypatch.setattr(config, "MATOMO_URL", "")
    monkeypatch.setattr(config, "ROBOTSKYDD", False)
    sida = client.get("/integritet").text
    assert "DiVA" not in sida and "konsorti" not in sida
    assert "den organisation som driver" in sida
    assert "fastställs och fylls i här" in sida
    assert "Ingen besöksstatistik samlas in" in sida
    assert "Matomo" not in sida and "Teknisk statistik" not in sida
    assert "robotskyddet" not in sida


def test_integritetssidan_med_instanstexter(client, app_db, monkeypatch):
    instans.spara(app_db, organisation="Exempelkonsortiet",
                  personuppgiftsansvarig="Exempeluniversitetet",
                  dataskydd_kontakt="dataskydd@example.org",
                  rattslig_grund="Grunden är allmänt intresse (6.1 e).",
                  lagringsplats="Uppgifterna lagras i Sverige.",
                  gallring="Historiken gallras efter två år.")
    monkeypatch.setattr(config, "MATOMO_URL", "https://matomo.example.org")
    monkeypatch.setattr(config, "MATOMO_SITE_ID", "7")
    monkeypatch.setattr(config, "ROBOTSKYDD", True)
    sida = client.get("/integritet").text
    assert "behovsarbetet inom Exempelkonsortiet inför" in sida
    assert "Personuppgiftsansvarig är Exempeluniversitetet." in sida
    assert "Frågor om dataskydd: dataskydd@example.org." in sida
    assert "Grunden är allmänt intresse (6.1 e)." in sida
    assert "Uppgifterna lagras i Sverige." in sida
    assert "Historiken gallras efter två år." in sida
    assert "fylls i här" not in sida
    assert "personuppgiftsbiträde" not in sida    # en organisation, ingen DRIFTARE
    assert "Matomo" in sida and "Teknisk statistik" in sida
    assert "robotskyddet" in sida


def test_integritetssidan_saknad_kontaktvag_markeras(client, app_db):
    instans.spara(app_db, personuppgiftsansvarig="Exempeluniversitetet")
    sida = client.get("/integritet").text
    assert "Personuppgiftsansvarig är Exempeluniversitetet." in sida
    assert "dataskyddsfrågor fylls i här innan" in sida
    assert "Formell" not in sida          # only the contact is missing


def test_instanstexter_escapas(client, app_db):
    instans.spara(app_db, organisation="<b>x</b>")
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


def test_tomma_integritetstexter_markeras(client):
    """#105: en ny organisation får ingen lånad rättslig grund, lagringsplats
    eller gallring, utan den gula markeringen."""
    sida = _platt(client.get("/integritet"))
    assert "Den rättsliga grunden fylls i här" in sida
    assert "Hur länge historiken sparas fylls i här" in sida
    assert "Var tjänsten och dess säkerhetskopior driftas" in sida
    assert "6.1 e" not in sida and "servrar inom EU" not in sida


def test_driftaren_namns_med_en_organisation_om_satt(client, monkeypatch):
    monkeypatch.setattr(config, "DRIFTARE", "Exempeldrift AB")
    monkeypatch.setattr(config, "DRIFTARE_KONTAKT", "drift@example.org")
    sida = _platt(client.get("/integritet"))
    assert "Tjänsten driftas av Exempeldrift AB, som är personuppgiftsbiträde" in sida
    assert "Kontakt: drift@example.org." in sida


@pytest.fixture()
def katalog(tmp_path, monkeypatch):
    """Katalogläge med en organisation, som teaball.bibliotekarien.se."""
    katalog = tmp_path / "organisationer"
    katalog.mkdir()
    monkeypatch.setattr(config, "ORGANISATIONER_DIR", katalog)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "far-inte-finnas.db")
    conn = appdb.connect(katalog / f"{VARD}.db")
    appdb.init_db(conn)
    yield conn
    conn.close()


@pytest.fixture()
def flera(katalog):
    """Två organisationer i katalogen: driftaren behandlar data åt andra."""
    annan = appdb.connect(config.ORGANISATIONER_DIR / "annan.exempel.se.db")
    appdb.init_db(annan)
    annan.close()
    return katalog


def _klient():
    from app.main import create_app
    return TestClient(create_app(), base_url=f"http://{VARD}")


def test_kataloglage_med_en_organisation_utan_markering(katalog):
    """Katalogläget ensamt betyder inte att någon annans data behandlas:
    teaball.bibliotekarien.se ska inte få en gul markering för driftaren."""
    with _klient() as k:
        sida = _platt(k.get("/integritet"))
    assert "personuppgiftsbiträde" not in sida
    assert "Driftaren och dess" not in sida


def test_flera_organisationer_utan_driftare_markeras(flera):
    with _klient() as k:
        sida = _platt(k.get("/integritet"))
    assert "driftas av en annan organisation, som är personuppgiftsbiträde" in sida
    assert "Driftaren och dess kontaktväg fylls i här" in sida


def test_flera_organisationer_med_driftare(flera, monkeypatch):
    monkeypatch.setattr(config, "DRIFTARE", "Exempeldrift AB")
    monkeypatch.setattr(config, "MATOMO_URL", "https://matomo.example.org")
    instans.spara_matomo(flera, "11")
    with _klient() as k:
        sida = _platt(k.get("/integritet"))
    assert "Tjänsten driftas av Exempeldrift AB, som är personuppgiftsbiträde" in sida
    assert "Kontakt:" not in sida
    assert "Driftaren och dess" not in sida
    assert "Matomo-installation hos Exempeldrift AB, i en egen sajt" in sida


def test_driftaren_escapas(client, monkeypatch):
    monkeypatch.setattr(config, "DRIFTARE", "<b>x</b>")
    sida = client.get("/integritet").text
    assert "<b>x</b>" not in sida and "&lt;b&gt;x&lt;/b&gt;" in sida
