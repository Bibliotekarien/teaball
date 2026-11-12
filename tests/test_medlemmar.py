"""Editing and deleting members through the HTTP routes. Deleting is the
sensitive one: the member's answers must reach the history (D2 trigger)
before the member row and its FK cascade go away — the privacy page
promises exactly that."""

from tests.conftest import csrf_fran, ge_token, logga_in, satt_svar, seed_trad, skapa_medlem


def _csrf(client):
    return csrf_fran(client.get("/medlemmar").text)


def test_uppdatera_byter_namn_och_kategori(client, app_db):
    medlem = skapa_medlem(app_db, "Gamla namnet", "högskola")
    app_db.commit()
    logga_in(client, app_db)

    svar = client.post(
        f"/medlemmar/{medlem}",
        data={"namn": "  Nya namnet  ", "kategori": "", "csrf_token": _csrf(client)},
        follow_redirects=False,
    )

    assert svar.status_code == 303
    rad = app_db.execute("SELECT namn, kategori FROM medlem WHERE id = ?", (medlem,)).fetchone()
    assert rad["namn"] == "Nya namnet"
    assert rad["kategori"] is None  # tom kategori sparas som NULL, inte ""
    assert "Nya namnet" in client.get("/medlemmar").text


def test_uppdatera_kapar_overlanga_varden(client, app_db):
    medlem = skapa_medlem(app_db, "Kort")
    app_db.commit()
    logga_in(client, app_db)

    client.post(
        f"/medlemmar/{medlem}",
        data={"namn": "n" * 500, "kategori": "k" * 500, "csrf_token": _csrf(client)},
    )

    rad = app_db.execute("SELECT namn, kategori FROM medlem WHERE id = ?", (medlem,)).fetchone()
    assert len(rad["namn"]) == 200
    assert len(rad["kategori"]) == 100


def test_bekraftelsesidan_visar_namn_och_antal_svar(client, app_db):
    ids = seed_trad(app_db)
    medlem = skapa_medlem(app_db, "Lärosätet")
    satt_svar(app_db, medlem, ids["dubblett"], "golive_krav")
    satt_svar(app_db, medlem, ids["registrera"], "kan_vanta")
    app_db.commit()
    logga_in(client, app_db)

    sida = client.get(f"/medlemmar/{medlem}/ta-bort").text

    assert "Ta bort ”Lärosätet”?" in sida
    assert "2 svar" in sida
    assert "bevaras i historiken" in sida
    assert f'action="/medlemmar/{medlem}/ta-bort"' in sida


def test_bekraftelsesidan_utan_svar_namner_ingen_historik(client, app_db):
    medlem = skapa_medlem(app_db, "Ny medlem")
    app_db.commit()
    logga_in(client, app_db)

    sida = client.get(f"/medlemmar/{medlem}/ta-bort").text

    assert "Ta bort ”Ny medlem”?" in sida
    assert "historiken" not in sida


def test_bekraftelsesidan_for_okand_medlem_leder_tillbaka(client, app_db):
    logga_in(client, app_db)

    svar = client.get("/medlemmar/9999/ta-bort", follow_redirects=False)

    assert svar.status_code == 303
    assert svar.headers["location"] == "/medlemmar"


def test_ta_bort_bevarar_svaren_i_historiken(client, app_db):
    ids = seed_trad(app_db)
    medlem = skapa_medlem(app_db, "Lärosätet")
    kvar = skapa_medlem(app_db, "Kvarvarande")
    satt_svar(app_db, medlem, ids["dubblett"], "golive_krav", oppen_kommentar="viktigt")
    satt_svar(app_db, kvar, ids["dubblett"], "golive_krav")
    app_db.commit()
    logga_in(client, app_db)

    svar = client.post(
        f"/medlemmar/{medlem}/ta-bort", data={"csrf_token": _csrf(client)},
        follow_redirects=False,
    )

    assert svar.status_code == 303
    assert app_db.execute("SELECT 1 FROM medlem WHERE id = ?", (medlem,)).fetchone() is None
    assert app_db.execute(
        "SELECT COUNT(*) FROM bedomning WHERE medlem_id = ?", (medlem,)
    ).fetchone()[0] == 0
    historik = app_db.execute(
        "SELECT funktion_id, svar, oppen_kommentar FROM bedomning_historik WHERE medlem_id = ?",
        (medlem,),
    ).fetchall()
    assert [tuple(r) for r in historik] == [(ids["dubblett"], "golive_krav", "viktigt")]
    # Andra medlemmars svar rörs inte.
    assert app_db.execute(
        "SELECT COUNT(*) FROM bedomning WHERE medlem_id = ?", (kvar,)
    ).fetchone()[0] == 1


def test_borttagen_medlems_lank_slutar_fungera(client, app_db, klient_fabrik):
    medlem = skapa_medlem(app_db, "Lärosätet")
    app_db.commit()
    token = ge_token(app_db, medlem)
    assert klient_fabrik().get(f"/svara/{token}", follow_redirects=False).status_code != 404
    logga_in(client, app_db)

    client.post(f"/medlemmar/{medlem}/ta-bort", data={"csrf_token": _csrf(client)})

    assert klient_fabrik().get(f"/svara/{token}", follow_redirects=False).status_code == 404
