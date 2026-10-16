"""Ankarlänkar till noderna (#rad-<id>) i alla vyer som visar noder: varje
rad bär id:t och en #-länk dit, och id:t förekommer bara en gång per sida
även när roadmapen visar samma förmåga i flera avgångar."""

from tests.conftest import (
    ge_token,
    klient_fabrik,  # noqa: F401  (fixture)
    logga_in,
    seed_trad,
    skapa_medlem,
)


def _har_ankare(sida, nod_id):
    assert sida.count(f'id="rad-{nod_id}"') == 1, nod_id
    assert f'href="#rad-{nod_id}"' in sida, nod_id


def test_forvaltarvyerna_har_ankare(client, app_db):
    ids = seed_trad(app_db)
    medlem = skapa_medlem(app_db, "Uppsala universitet")
    app_db.commit()
    logga_in(client, app_db)

    for url in ("/trad", "/lista", f"/bedomning?medlem_id={medlem}"):
        sida = client.get(url).text
        for nod_id in ids.values():
            _har_ankare(sida, nod_id)

    # Roadmapen: Publicering står som kontext i både Avgång 1 och senare —
    # länken finns på båda raderna, id:t bara på den första.
    sida = client.get("/roadmap").text
    assert sida.count(f'href="#rad-{ids["publicering"]}"') == 2
    for nyckel in ("publicering", "registrera", "import", "wos"):
        _har_ankare(sida, ids[nyckel])


def test_medlemsvyerna_har_ankare(app_db, klient_fabrik):
    ids = seed_trad(app_db)
    medlem = skapa_medlem(app_db, "Uppsala universitet")
    token = ge_token(app_db, medlem)
    klient = klient_fabrik()
    klient.get(f"/svara/{token}", follow_redirects=False)

    sida = klient.get("/svara").text
    for nod_id in ids.values():
        _har_ankare(sida, nod_id)

    sida = klient.get("/svara/roadmap").text
    for nyckel in ("publicering", "registrera", "import", "wos"):
        _har_ankare(sida, ids[nyckel])
