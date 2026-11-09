"""Den utfällbara ordlistan: finns i båda ramarna för inloggade, och begrepp
medlemmar aldrig möter visas bara för förvaltare."""

from tests.conftest import (
    ge_token,
    klient_fabrik,  # noqa: F401  (fixture)
    logga_in,
    seed_trad,
    skapa_medlem,
)


def test_ordlista_for_medlem(app_db, klient_fabrik):
    seed_trad(app_db)
    medlem = skapa_medlem(app_db, "Uppsala universitet")
    token = ge_token(app_db, medlem)
    klient = klient_fabrik()
    klient.get(f"/svara/{token}", follow_redirects=False)

    for sida in (klient.get("/svara").text, klient.get("/svara/roadmap").text):
        assert "data-ordlista" in sida
        # Typer, statusar och svar ur de delade tabellerna, plus egna begrepp.
        assert "Ett behov som ska vara uppfyllt" in sida
        assert "Beslutad att byggas" in sida
        assert "Ja, kan vänta 6–12 mån" in sida
        assert ">Ärvt svar</dt>" in sida
        # Förvaltarbegrepp visas inte för medlemmar.
        assert ">Proxy</dt>" not in sida
        assert ">Dold för medlemmar</dt>" not in sida


def test_ordlista_for_forvaltare(client, app_db):
    seed_trad(app_db)
    logga_in(client, app_db)
    sida = client.get("/trad").text
    assert "data-ordlista" in sida
    assert ">Proxy</dt>" in sida
    assert ">Dold för medlemmar</dt>" in sida


def test_ingen_ordlista_utan_inloggning(client):
    assert "data-ordlista" not in client.get("/login").text
