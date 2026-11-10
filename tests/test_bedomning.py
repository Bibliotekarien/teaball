"""Tests for the assessment view in admin proxy mode (B1, B3–B6) and the
UI half of acceptance test §9.3."""

from tests.conftest import (
    csrf_fran,
    ge_token,
    huvuddel,
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
    client.post(f"{bas}/oppen-kommentar",
                data={"oppen_kommentar": "Cron-skript som diffar mot gårdagens skörd.",
                      "oppen_delning": "anonym", "csrf_token": token})
    client.post(f"{bas}/intern-kommentar",
                data={"intern_kommentar": "Väntar på styrgruppen.", "csrf_token": token})

    # B4: the open comment is tinted by the answer (kan vänta: amber) ...
    sida = client.get(f"/bedomning?medlem_id={medlem}").text
    assert "Öppen kommentar ✓ (alla medlemmar, anonymt)" in sida
    assert "focus:ring-blue-700 border-amber-200 bg-amber-50" in sida

    # ... then change the answer to golive_krav (§9.3).
    client.post(f"{bas}/svar", data={"svar": "golive_krav", "csrf_token": token})

    hist = app_db.execute(
        "SELECT * FROM bedomning_historik WHERE funktion_id = ? ORDER BY id DESC LIMIT 1",
        (ids["wos"],),
    ).fetchone()
    assert hist["svar"] == "kan_vanta"
    assert hist["oppen_kommentar"] == "Cron-skript som diffar mot gårdagens skörd."
    assert hist["oppen_delning"] == "anonym"
    assert hist["intern_kommentar"] == "Väntar på styrgruppen."

    # Both comments stay with the new answer, and the colour follows it.
    sida = client.get(f"/bedomning?medlem_id={medlem}").text
    assert "focus:ring-blue-700 border-rose-200 bg-rose-50" in sida
    rad = app_db.execute("SELECT * FROM bedomning WHERE funktion_id = ?", (ids["wos"],)).fetchone()
    assert rad["svar"] == "golive_krav"
    assert rad["oppen_kommentar"] == "Cron-skript som diffar mot gårdagens skörd."
    assert rad["intern_kommentar"] == "Väntar på styrgruppen."


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
    # "Behovsträdet är tomt".
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

    # När allt är driftsatt: eget tomt-läge i stället för "Behovsträdet är tomt".
    app_db.execute("UPDATE funktion SET status = 'driftsatt'")
    app_db.commit()
    sida = client.get(f"/bedomning?medlem_id={medlem}&dolj_driftsatta=1").text
    assert "Allt i behovsträdet är driftsatt" in sida


def test_formagor_ar_hierarki_utan_piller(client, app_db):
    ids, medlem, token = _förbered(client, app_db)

    # Förmågor är bara hierarki i bedömningen: den driftsatta förmågan
    # Publicering får ingen statusbricka. Seedens enda driftsatta noder är
    # förmågor, så sidan ska sakna brickan helt ...
    sida = client.get(f"/bedomning?medlem_id={medlem}").text
    assert ">Publicering</span>" in sida
    assert ">Driftsatt</span>" not in huvuddel(sida)

    # ... men en driftsatt FUNKTION behåller sin bricka.
    app_db.execute("UPDATE funktion SET status = 'driftsatt' WHERE id = ?",
                   (ids["import"],))
    app_db.commit()
    assert ">Driftsatt</span>" in huvuddel(client.get(f"/bedomning?medlem_id={medlem}").text)


def test_dolj_formagor(client, app_db):
    ids, medlem, token = _förbered(client, app_db)

    # Dölj förmågor lyfter upp barnen i förmågans ställe — inget under
    # Publicering försvinner, bara rubriknivån.
    sida = client.get(f"/bedomning?medlem_id={medlem}&dolj_formagor=1").text
    assert ">Publicering</span>" not in sida
    assert "Export &amp; spridning" not in sida
    assert ">Registrera avhandling</span>" in sida
    assert "Import från Web of Science" in sida
    # Räknaren mäter hela trädet och påverkas inte av filtret.
    assert "<strong>4</strong> kvar" in sida


def test_dolj_formagor_i_medlemsvyn(app_db, klient_fabrik):
    seed_trad(app_db)
    medlem = skapa_medlem(app_db, "Uppsala universitet")
    token = ge_token(app_db, medlem)
    klient = klient_fabrik()
    klient.get(f"/svara/{token}", follow_redirects=False)

    sida = klient.get("/svara?dolj_formagor=1").text
    assert ">Publicering</span>" not in sida
    assert ">Registrera avhandling</span>" in sida
    assert 'name="dolj_formagor" value="1" data-autosubmit checked' in sida


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


def test_dolj_lasta_i_medlemsvyn(app_db, klient_fabrik):
    ids = seed_trad(app_db)
    app_db.execute("UPDATE funktion SET rankning_last = 1 WHERE id IN (?, ?)",
                   (ids["import"], ids["registrera"]))
    app_db.commit()
    medlem = skapa_medlem(app_db, "Uppsala universitet")
    token = ge_token(app_db, medlem)
    klient = klient_fabrik()
    klient.get(f"/svara/{token}", follow_redirects=False)

    sida = klient.get("/svara").text
    assert ">Registrera avhandling</span>" in sida
    sida = klient.get("/svara?dolj_lasta=1").text
    assert ">Registrera avhandling</span>" not in sida
    # Låset ärvs inte: låsta Import står kvar som sammanhang för WoS.
    assert f'id="gren-{ids["import"]}"' in sida
    assert ">Import från Web of Science</span>" in sida
    assert 'name="dolj_lasta" value="1" data-autosubmit checked' in sida


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


def test_vyvaxling_i_medlemsvyn(app_db, klient_fabrik):
    ids = seed_trad(app_db)
    detaljer = skapa_funktion(app_db, "Med detaljer", ids["publicering"], typ="funktion",
                              beskrivning="En längre förklaring.", sortering=30)
    medlem = skapa_medlem(app_db, "Uppsala universitet")
    token = ge_token(app_db, medlem)
    klient = klient_fabrik()
    klient.get(f"/svara/{token}", follow_redirects=False)

    # Detaljerad är standard i bedömningen: beskrivningen är det medlemmen
    # bedömer utifrån. Panelen erbjuder kompakt och alla-knapparna.
    sida = klient.get("/svara").text
    assert ">En längre förklaring.</p>" in sida
    assert ">Kompakt vy</a>" in sida
    assert 'data-trad-alla="kompaktera"' in sida

    # Vylänken behåller sidans filter.
    sida = klient.get("/svara?dolj_driftsatta=1").text
    assert 'href="/svara?dolj_driftsatta=1&amp;vy=kompakt"' in sida

    # Kompakt: beskrivningen bara som tooltip, och valet är klibbigt — även
    # för grenen som kommer tillbaka efter ett svar.
    sida = klient.get("/svara?vy=kompakt").text
    assert ">En längre förklaring.</p>" not in sida
    assert 'title="En längre förklaring.">Med detaljer</span>' in sida
    assert ">Detaljerad vy</a>" in sida
    assert ">En längre förklaring.</p>" not in klient.get("/svara").text
    csrf = csrf_fran(klient.get("/svara").text)
    gren = klient.post(f"/svara/{detaljer}/svar", data={"svar": "golive_krav"},
                       headers={"HX-Request": "true", "X-CSRF-Token": csrf})
    assert f'id="gren-{detaljer}"' in gren.text
    assert ">En längre förklaring.</p>" not in gren.text


def test_delade_oppna_kommentarer_visas_anonymt(client, app_db):
    ids, medlem, token = _förbered(client, app_db)
    annan = skapa_medlem(app_db, "Kungliga Tekniska högskolan")
    app_db.execute(
        "INSERT INTO bedomning (medlem_id, funktion_id, svar, oppen_kommentar, oppen_delning)"
        " VALUES (?, ?, 'kan_vanta', 'Egen XSLT-transform i pipeline.', 'anonym')",
        (annan, ids["wos"]),
    )
    app_db.commit()

    sida = client.get(f"/bedomning?medlem_id={medlem}").text
    assert "Öppna kommentarer från andra medlemmar (1)" in sida
    assert "Egen XSLT-transform i pipeline." in sida

    # Anonymity (B8): the subtree partial (which has no member <select>) must
    # not attribute the comment to its author.
    partial = client.post(f"/bedomning/{medlem}/{ids['wos']}/svar",
                          data={"svar": "behovs_ej"},
                          headers={"HX-Request": "true", "X-CSRF-Token": token}).text
    assert "Egen XSLT-transform i pipeline." in partial
    assert "Kungliga Tekniska högskolan" not in partial
