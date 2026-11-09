"""Radbrytningar i beskrivningarna visas som radbrytningar (white-space:
pre-line) i trädet, listan, bedömningen och den fristående HTML-exporten —
i stället för att flyta ihop till ett stycke."""

from tests.conftest import ge_token, klient_fabrik  # noqa: F401  (fixture)
from tests.conftest import logga_in, seed_trad, skapa_funktion, skapa_medlem

BESKRIVNING = "Första stycket.\r\n\r\nAndra stycket:\r\n- en punkt"


def _med_beskrivning(app_db):
    ids = seed_trad(app_db)
    skapa_funktion(app_db, "Med stycken", ids["publicering"], typ="funktion",
                   beskrivning=BESKRIVNING, sortering=30)
    app_db.commit()


def _stycke(sida: str) -> str:
    """Elementet som bär beskrivningen, från klassattributet till texten."""
    fore = sida.split(">Första stycket.", 1)[0]
    return fore.rsplit("<", 1)[1]


def test_tradet_och_listan_visar_radbrytningar(client, app_db):
    _med_beskrivning(app_db)
    logga_in(client, app_db)
    for adress in ("/trad?vy=detaljerad", "/lista?vy=detaljerad"):
        sida = client.get(adress).text
        assert "whitespace-pre-line" in _stycke(sida), adress
        # Texten skickas oförändrad; det är CSS:en som bryter raderna.
        assert "Första stycket.\r\n\r\nAndra stycket:" in sida, adress


def test_bedomningen_visar_radbrytningar(app_db, klient_fabrik):
    _med_beskrivning(app_db)
    medlem = skapa_medlem(app_db, "Uppsala universitet")
    token = ge_token(app_db, medlem)
    klient = klient_fabrik()
    klient.get(f"/svara/{token}", follow_redirects=False)
    assert "whitespace-pre-line" in _stycke(klient.get("/svara").text)


def test_html_exporten_visar_radbrytningar(client, app_db):
    _med_beskrivning(app_db)
    logga_in(client, app_db)
    sida = client.get("/export/kravtrad.html").text
    assert 'class="beskrivning">Första stycket.' in sida
    assert "white-space: pre-line" in sida
