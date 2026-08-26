"""Tests for the assessment view in admin proxy mode (B1, B3–B6) and the
UI half of acceptance test §9.3."""

from tests.conftest import csrf_fran, logga_in, seed_trad, skapa_medlem


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
