"""The public privacy notice and its footer link."""

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
