"""Tests for the assessment view in admin proxy mode (B1, B3–B6) and the
UI half of acceptance test §9.3."""

from tests.conftest import (
    csrf_fran,
    ge_token,
    klient_fabrik,  # noqa: F401  (fixture)
    logga_in,
    seed_trad,
    skapa_funktion,
    skapa_medlem,
)


def _förbered(client, app_db):
    ids = seed_trad(app_db)
    medlem = skapa_medlem(app_db, "Uppsala universitet")
    app_db.commit()
    logga_in(client, app_db)
    token = csrf_fran(client.get("/bedomning").text)
    return ids, medlem, token


def test_b3_toggle_och_arvsvisning(client, app_db):
    ids, medlem, token = _förbered(client, app_db)

    # Answer on Import — descendants show the inherited label (A2/B6).
    svar = client.post(f"/bedomning/{medlem}/{ids['import']}/svar",
                       data={"svar": "kan_vanta", "csrf_token": token},
                       follow_redirects=False)
    assert svar.status_code == 303
    rad = app_db.execute("SELECT * FROM bedomning WHERE medlem_id = ?", (medlem,)).fetchone()
    assert rad["svar"] == "kan_vanta"
    assert rad["besvarat_av"] == "proxy: anna"

    sida = client.get(f"/bedomning?medlem_id={medlem}").text
    assert "ärvt: Kan vänta (från Import)" in sida

    # Clicking the same button again removes the answer (B3).
    client.post(f"/bedomning/{medlem}/{ids['import']}/svar",
                data={"svar": "kan_vanta", "csrf_token": token})
    assert app_db.execute("SELECT COUNT(*) FROM bedomning WHERE medlem_id = ?",
                          (medlem,)).fetchone()[0] == 0
    assert "ärvt:" not in client.get(f"/bedomning?medlem_id={medlem}").text


def test_htmx_svar_ger_undergren_partial(client, app_db):
    ids, medlem, token = _förbered(client, app_db)
    svar = client.post(f"/bedomning/{medlem}/{ids['import']}/svar",
                       data={"svar": "golive_krav"},
                       headers={"HX-Request": "true", "X-CSRF-Token": token})
    assert svar.status_code == 200
    # The whole subtree comes back so descendants' inherited labels update.
    assert f'id="gren-{ids["import"]}"' in svar.text
    assert f'id="gren-{ids["wos"]}"' in svar.text
    assert "ärvt: Go-live (från Import)" in svar.text


def test_acceptance_9_3_historik_intakt(client, app_db):
    ids, medlem, token = _förbered(client, app_db)
    bas = f"/bedomning/{medlem}/{ids['wos']}"

    client.post(f"{bas}/svar", data={"svar": "kan_vanta", "csrf_token": token})
    client.post(f"{bas}/workaround",
                data={"workaround": "Cron-skript som diffar mot gårdagens skörd.",
                      "workaround_delas": "1", "csrf_token": token})
    client.post(f"{bas}/kommentar",
                data={"kommentar": "Väntar på styrgruppen.", "csrf_token": token})

    # B4: the workaround field is visible while the answer is kan_vanta ...
    sida = client.get(f"/bedomning?medlem_id={medlem}").text
    assert "Workaround: hur klarar ni er under tiden?" in sida

    # ... then change the answer to golive_krav (§9.3).
    client.post(f"{bas}/svar", data={"svar": "golive_krav", "csrf_token": token})

    hist = app_db.execute(
        "SELECT * FROM bedomning_historik WHERE funktion_id = ? ORDER BY id DESC LIMIT 1",
        (ids["wos"],),
    ).fetchone()
    assert hist["svar"] == "kan_vanta"
    assert hist["workaround"] == "Cron-skript som diffar mot gårdagens skörd."
    assert hist["kommentar"] == "Väntar på styrgruppen."

    # The field disappears with the new answer (B4) but the row keeps its data.
    sida = client.get(f"/bedomning?medlem_id={medlem}").text
    assert "Workaround: hur klarar ni er under tiden?" not in sida
    rad = app_db.execute("SELECT * FROM bedomning WHERE funktion_id = ?", (ids["wos"],)).fetchone()
    assert rad["svar"] == "golive_krav"
    assert rad["workaround"] == "Cron-skript som diffar mot gårdagens skörd."


def test_driftsatt_och_utgar_kan_inte_rankas(client, app_db):
    ids, medlem, token = _förbered(client, app_db)
    utgatt = skapa_funktion(app_db, "Gammal exportmodul", ids["export"],
                            typ="funktion", status="utgår")
    app_db.commit()

    # UI: svarsknapparna ersätts av statusbrickan; utgår-namnet stryks dessutom.
    sida = client.get(f"/bedomning?medlem_id={medlem}").text
    assert f'action="/bedomning/{medlem}/{ids["import"]}/svar"' in sida
    assert f'action="/bedomning/{medlem}/{ids["publicering"]}/svar"' not in sida
    assert f'action="/bedomning/{medlem}/{utgatt}/svar"' not in sida
    assert 'line-through text-stone-400">Gammal exportmodul' in sida
    assert 'line-through text-stone-400">Publicering' not in sida

    # Servern är sista spärren: en direkt POST (t.ex. från ett formulär som
    # renderades före ett statusbyte) avvisas.
    for nod in (ids["publicering"], utgatt):
        svar = client.post(f"/bedomning/{medlem}/{nod}/svar",
                           data={"svar": "golive_krav", "csrf_token": token},
                           follow_redirects=False)
        assert svar.status_code == 400
    assert app_db.execute("SELECT COUNT(*) FROM bedomning").fetchone()[0] == 0


def test_raknare_och_dolj_bedomda(client, app_db):
    ids, medlem, token = _förbered(client, app_db)

    # Rankbara i seedträdet: registrera, import, wos, dubblett — de driftsatta
    # förmågorna hör inte hemma i någon av kolumnerna.
    sida = client.get(f"/bedomning?medlem_id={medlem}").text
    assert "<strong>0</strong> av 4 bedömda" in sida
    assert "<strong>4</strong> kvar" in sida

    # Ett svar på Import täcker via arvet även wos och dubblett; räknaren
    # följer med out-of-band i htmx-svaret.
    partial = client.post(f"/bedomning/{medlem}/{ids['import']}/svar",
                          data={"svar": "kan_vanta"},
                          headers={"HX-Request": "true", "X-CSRF-Token": token}).text
    assert 'id="bedomning-raknare" hx-swap-oob="outerHTML"' in partial
    assert "<strong>3</strong> av 4 bedömda" in partial

    # Filtret döljer den bedömda grenen (även det ärvda) men behåller det
    # obedömda — och driftsatta förfäder som kontext.
    sida = client.get(f"/bedomning?medlem_id={medlem}&dolj_bedomda=1").text
    assert ">Registrera avhandling</span>" in sida
    assert ">Publicering</span>" in sida             # driftsatt förfader, kontext
    assert ">Import</span>" not in sida
    assert "Import från Web of Science" not in sida  # ärvt bedömd
    assert "Export &amp; spridning" not in sida      # driftsatt utan något kvar

    # När allt är bedömt: grön räknare och ett eget tomt-läge i stället för
    # "Kravträdet är tomt".
    client.post(f"/bedomning/{medlem}/{ids['registrera']}/svar",
                data={"svar": "behovs_ej", "csrf_token": token})
    sida = client.get(f"/bedomning?medlem_id={medlem}&dolj_bedomda=1").text
    assert "Allt bedömt" in sida
    assert "Allt som går att bedöma är bedömt" in sida


def test_dolj_driftsatta(client, app_db):
    ids, medlem, token = _förbered(client, app_db)

    # Driftsatta noder döljs; en driftsatt förfader med bedömbara barn kvar
    # behålls som kontext (samma princip som dölj bedömda).
    sida = client.get(f"/bedomning?medlem_id={medlem}&dolj_driftsatta=1").text
    assert ">Publicering</span>" in sida             # driftsatt, men barnen är kvar
    assert ">Registrera avhandling</span>" in sida
    assert "Export &amp; spridning" not in sida      # driftsatt utan något under
    # Räknaren mäter hela trädet och påverkas inte av filtret.
    assert "<strong>4</strong> kvar" in sida

    # Kombinerat med dölj bedömda: svaret på Import döljer den grenen också.
    client.post(f"/bedomning/{medlem}/{ids['import']}/svar",
                data={"svar": "kan_vanta", "csrf_token": token})
    sida = client.get(
        f"/bedomning?medlem_id={medlem}&dolj_driftsatta=1&dolj_bedomda=1"
    ).text
    assert ">Registrera avhandling</span>" in sida
    assert ">Import</span>" not in sida
    assert "Export &amp; spridning" not in sida

    # När allt är driftsatt: eget tomt-läge i stället för "Kravträdet är tomt".
    app_db.execute("UPDATE funktion SET status = 'driftsatt'")
    app_db.commit()
    sida = client.get(f"/bedomning?medlem_id={medlem}&dolj_driftsatta=1").text
    assert "Allt i kravträdet är driftsatt" in sida


def test_dolj_driftsatta_i_medlemsvyn(app_db, klient_fabrik):
    seed_trad(app_db)
    medlem = skapa_medlem(app_db, "Uppsala universitet")
    token = ge_token(app_db, medlem)
    klient = klient_fabrik()
    klient.get(f"/svara/{token}", follow_redirects=False)

    sida = klient.get("/svara?dolj_driftsatta=1").text
    assert ">Registrera avhandling</span>" in sida
    assert "Export &amp; spridning" not in sida
    assert 'name="dolj_driftsatta" value="1" data-autosubmit checked' in sida


def test_raknare_och_filter_i_medlemsvyn(app_db, klient_fabrik):
    seed_trad(app_db)
    medlem = skapa_medlem(app_db, "Uppsala universitet")
    token = ge_token(app_db, medlem)
    klient = klient_fabrik()
    klient.get(f"/svara/{token}", follow_redirects=False)

    assert "<strong>0</strong> av 4 bedömda" in klient.get("/svara").text
    sida = klient.get("/svara?dolj_bedomda=1").text
    assert ">Registrera avhandling</span>" in sida
    assert 'name="dolj_bedomda" value="1" data-autosubmit checked' in sida


def test_delade_workarounds_visas_anonymt(client, app_db):
    ids, medlem, token = _förbered(client, app_db)
    annan = skapa_medlem(app_db, "Kungliga Tekniska högskolan")
    app_db.execute(
        "INSERT INTO bedomning (medlem_id, funktion_id, svar, workaround, workaround_delas)"
        " VALUES (?, ?, 'kan_vanta', 'Egen XSLT-transform i pipeline.', 1)",
        (annan, ids["wos"]),
    )
    app_db.commit()

    sida = client.get(f"/bedomning?medlem_id={medlem}").text
    assert "Workarounds från andra medlemmar (1)" in sida
    assert "Egen XSLT-transform i pipeline." in sida

    # Anonymity (B8): the subtree partial (which has no member <select>) must
    # not attribute the workaround to its author.
    partial = client.post(f"/bedomning/{medlem}/{ids['wos']}/svar",
                          data={"svar": "behovs_ej"},
                          headers={"HX-Request": "true", "X-CSRF-Token": token}).text
    assert "Egen XSLT-transform i pipeline." in partial
    assert "Kungliga Tekniska högskolan" not in partial
