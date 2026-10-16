"""Interna kommentarer på noderna (migration 0006): skrivande under noden,
kommentarsvyn grupperad per nod, avbockning (behandlad/dold) och att
kommentarerna aldrig når extern roll eller bär något namn."""

import sqlite3

import pytest

from tests.conftest import csrf_fran, klient_fabrik  # noqa: F401  (fixture)
from tests.conftest import logga_in, seed_trad

HTMX = {"HX-Request": "true"}


def _token(client, adress="/kommentarer"):
    return csrf_fran(client.get(adress).text)


def _skriv(client, nod_id, text, token, htmx=True):
    huvuden = HTMX | {"X-CSRF-Token": token} if htmx else {}
    return client.post(f"/kommentarer/nod/{nod_id}",
                       data={"text": text, "csrf_token": token},
                       headers=huvuden, follow_redirects=False)


def _status(client, kommentar_id, status, token, fran="vy"):
    return client.post(f"/kommentarer/{kommentar_id}/status",
                       data={"status": status, "fran": fran, "csrf_token": token},
                       headers=HTMX | {"X-CSRF-Token": token})


def test_tabellen_saknar_forfattare_och_foljer_noden(conn, trad):
    kolumner = {r["name"] for r in conn.execute("PRAGMA table_info(kommentar)")}
    assert kolumner == {"id", "funktion_id", "text", "status", "skapad", "hanterad"}

    conn.execute("INSERT INTO kommentar (funktion_id, text) VALUES (?, 'x')", (trad["wos"],))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO kommentar (funktion_id, text) VALUES (?, '  ')", (trad["wos"],))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO kommentar (funktion_id, text, status) VALUES (?, 'x', 'klar')",
                     (trad["wos"],))

    from app.services import trad as tjanst
    tjanst.ta_bort_nod(conn, trad["import"])
    assert conn.execute("SELECT COUNT(*) FROM kommentar").fetchone()[0] == 0


def test_skriva_under_noden_och_se_i_listan(client, app_db):
    ids = seed_trad(app_db)
    logga_in(client, app_db)
    token = _token(client)

    svar = _skriv(client, ids["wos"], "Kolla mot\nnya API:t", token)
    assert svar.status_code == 200
    # Blocket kommer tillbaka utfällt med kommentaren; toggeln och det gula
    # antalspillret följer med OOB.
    assert 'id="kommentarer-' + str(ids["wos"]) + '"' in svar.text
    assert "Kolla mot\nnya API:t" in svar.text
    assert 'id="kommentarantal-' + str(ids["wos"]) + '" hx-swap-oob="true"' in svar.text
    assert 'id="kommentarpill-' + str(ids["wos"]) + '" hx-swap-oob="true"' in svar.text
    assert 'aria-label="1 intern kommentar, 1 öppen"' in svar.text

    lista = client.get("/lista").text
    assert 'aria-label="1 intern kommentar, 1 öppen"' in lista
    trad = client.get("/trad").text
    assert 'aria-label="1 intern kommentar, 1 öppen"' in trad
    # Hopfällt syns inte texten i vyerna — bara pillret.
    assert "nya API:t" not in lista and "nya API:t" not in trad


def test_tom_kommentar_avvisas(client, app_db):
    ids = seed_trad(app_db)
    logga_in(client, app_db)
    svar = _skriv(client, ids["wos"], "   ", _token(client))
    assert "Kommentaren är tom." in svar.text
    assert app_db.execute("SELECT COUNT(*) FROM kommentar").fetchone()[0] == 0


def test_kommentarsvyn_grupperar_och_bockar_av(client, app_db):
    ids = seed_trad(app_db)
    logga_in(client, app_db)
    token = _token(client)
    _skriv(client, ids["dubblett"], "Första på dubbletter", token)
    _skriv(client, ids["registrera"], "Om avhandlingar", token)
    _skriv(client, ids["dubblett"], "Andra på dubbletter", token)

    vy = client.get("/kommentarer").text
    # Grupper i trädordning: Registrera avhandling kommer före Dubblettdetektering.
    assert vy.index(f'id="grupp-{ids["registrera"]}"') < vy.index(f'id="grupp-{ids["dubblett"]}"')
    # Inom gruppen äldst först.
    assert vy.index("Första på dubbletter") < vy.index("Andra på dubbletter")
    assert vy.count('<section id="grupp-') == 2

    forsta = app_db.execute("SELECT id FROM kommentar WHERE text = 'Första på dubbletter'").fetchone()[0]
    svar = _status(client, forsta, "behandlad", token).text
    # Svaret är vyn med samma flik (öppna): den behandlade är borta därifrån.
    assert "Första på dubbletter" not in svar and "Andra på dubbletter" in svar
    rad = app_db.execute("SELECT status, hanterad FROM kommentar WHERE id = ?", (forsta,)).fetchone()
    assert rad["status"] == "behandlad" and rad["hanterad"] is not None

    behandlade = client.get("/kommentarer?visa=behandlade").text
    assert "Första på dubbletter" in behandlade and "Andra på dubbletter" not in behandlade

    # Öppna igen nollar hanterad.
    _status(client, forsta, "öppen", token)
    assert app_db.execute("SELECT hanterad FROM kommentar WHERE id = ?", (forsta,)).fetchone()[0] is None


def test_behandlad_syns_under_noden_dold_gor_det_inte(client, app_db):
    ids = seed_trad(app_db)
    logga_in(client, app_db)
    token = _token(client)
    _skriv(client, ids["wos"], "Behandlas", token)
    _skriv(client, ids["wos"], "Döljs", token)
    behandlas, doljs = (r[0] for r in app_db.execute(
        "SELECT id FROM kommentar ORDER BY id").fetchall())
    _status(client, behandlas, "behandlad", token, fran="nod")
    svar = _status(client, doljs, "dold", token, fran="nod").text
    # fran=nod: svaret är nodblocket, inte vyn.
    assert f'id="kommentarer-{ids["wos"]}"' in svar and 'id="kommentarer-rot"' not in svar

    block = client.get(f"/kommentarer/nod/{ids['wos']}?oppen=1", headers=HTMX).text
    assert "Behandlas" in block and "Döljs" not in block
    # Pillret räknar bara det som syns under noden: den behandlade, inte den dolda.
    assert 'aria-label="1 intern kommentar, 0 öppna"' in client.get("/lista").text

    dolda = client.get("/kommentarer?visa=dolda").text
    assert "Döljs" in dolda and "Behandlas" not in dolda

    # Hopfällning ger ett tomt block.
    hopfallt = client.get(f"/kommentarer/nod/{ids['wos']}?oppen=0", headers=HTMX).text
    assert "Behandlas" not in hopfallt


def test_utan_js_egen_sida_och_redirect(client, app_db):
    ids = seed_trad(app_db)
    logga_in(client, app_db)
    sida = client.get(f"/kommentarer/nod/{ids['wos']}")
    assert sida.status_code == 200 and "Ny intern kommentar" in sida.text
    svar = _skriv(client, ids["wos"], "Utan htmx", csrf_fran(sida.text), htmx=False)
    assert svar.status_code == 303
    assert svar.headers["location"] == f"/kommentarer/nod/{ids['wos']}"


def test_intern_skriver_men_hanterar_inte(client, app_db):
    ids = seed_trad(app_db)
    app_db.execute("INSERT INTO kommentar (funktion_id, text) VALUES (?, 'Intern läser')", (ids["wos"],))
    app_db.commit()
    logga_in(client, app_db, namn="ingrid", roll="intern")
    vy = client.get("/kommentarer")
    assert vy.status_code == 200 and "Intern läser" in vy.text
    assert "✓&nbsp;Behandlad" not in vy.text
    assert 'href="/kommentarer"' in vy.text  # fliken

    # Brickan och skrivfältet finns för intern, statusknapparna inte.
    assert f'hx-get="/kommentarer/nod/{ids["registrera"]}?oppen=1"' in client.get("/lista").text
    block = client.get(f"/kommentarer/nod/{ids['wos']}?oppen=1", headers=HTMX).text
    assert 'name="text"' in block and "✓&nbsp;Behandlad" not in block

    token = csrf_fran(vy.text)
    svar = _skriv(client, ids["wos"], "Intern skriver", token)
    assert svar.status_code == 200 and "Intern skriver" in svar.text
    kid = app_db.execute("SELECT id FROM kommentar WHERE text = 'Intern läser'").fetchone()[0]
    assert _status(client, kid, "behandlad", token).status_code == 403
    assert _status(client, kid, "dold", token, fran="nod").status_code == 403


def test_extern_ser_aldrig_kommentarer(client, app_db):
    ids = seed_trad(app_db)
    app_db.execute("INSERT INTO kommentar (funktion_id, text) VALUES (?, 'Hemlig')", (ids["wos"],))
    app_db.commit()
    logga_in(client, app_db, namn="erik", roll="extern")
    assert client.get("/kommentarer").status_code == 403
    assert client.get(f"/kommentarer/nod/{ids['wos']}?oppen=1", headers=HTMX).status_code == 403
    trad = client.get("/trad").text
    assert "kommentarantal-" not in trad and "kommentarer-" not in trad
    assert "kommentarpill-" not in trad
    assert 'href="/kommentarer"' not in trad
    # Extern har ingen knapprad alls (inga ändringar, inga kommentarer).
    assert "knapprad" not in trad


def test_statusbyte_okand_status_och_saknad_kommentar(client, app_db):
    ids = seed_trad(app_db)
    logga_in(client, app_db)
    token = _token(client)
    _skriv(client, ids["wos"], "x", token)
    kid = app_db.execute("SELECT id FROM kommentar").fetchone()[0]
    assert _status(client, kid, "klar", token).status_code == 400
    assert _status(client, kid + 99, "dold", token).status_code == 404
    assert _skriv(client, 9999, "x", token).status_code == 404


def test_toggeln_i_knappraden_och_gult_pill_pa_raden(client, app_db):
    ids = seed_trad(app_db)
    app_db.execute("INSERT INTO kommentar (funktion_id, text) VALUES (?, 'a')", (ids["wos"],))
    app_db.execute("INSERT INTO kommentar (funktion_id, text, status)"
                   " VALUES (?, 'b', 'behandlad')", (ids["wos"],))
    app_db.commit()

    for roll, namn in (("admin", "anna"), ("intern", "ingrid")):
        logga_in(client, app_db, namn=namn, roll=roll)
        for adress in ("/trad", "/lista"):
            sida = client.get(adress).text
            rad = sida.split(f'id="rad-{ids["wos"]}"', 1)[1]
            # Knappraden kommer före pillret i båda vyerna.
            knapprad = rad.split('class="knapprad', 1)[1].split('id="kommentarpill-', 1)[0]
            # Toggeln sitter i knappraden — även för intern, som inte får ändra noden.
            assert f'id="kommentarantal-{ids["wos"]}"' in knapprad
            assert "kommentarer&nbsp;" in knapprad
            assert ("redigera" in knapprad) == (roll == "admin")
            # Det gula pillret med antalet (öppna + behandlade) syns på raden.
            assert 'aria-label="2 interna kommentarer, 1 öppen"' in rad
            assert "bg-amber-100" in rad
        client.post("/logout", data={"csrf_token": csrf_fran(sida)})


def test_brickan_vaxlar_mellan_utfallt_och_hopfallt(client, app_db):
    ids = seed_trad(app_db)
    logga_in(client, app_db)
    nod = ids["wos"]
    # Hopfällt i vyerna: brickan fäller ut.
    assert f'hx-get="/kommentarer/nod/{nod}?oppen=1"' in client.get("/trad").text
    assert f'hx-get="/kommentarer/nod/{nod}?oppen=1"' in client.get("/lista").text

    # Utfällt: den OOB-swappade toggeln fäller ihop vid nästa klick.
    utfallt = client.get(f"/kommentarer/nod/{nod}?oppen=1", headers=HTMX).text
    bricka = utfallt.split(f'id="kommentarantal-{nod}"', 1)[1]
    assert '?oppen=0"' in bricka and 'aria-expanded="true"' in bricka
    # Utan kommentarer är pillret en tom platshållare (OOB-mål för första).
    pill = utfallt.split(f'id="kommentarpill-{nod}"', 1)[1].split("</span>", 1)[0]
    assert "<a " not in pill

    # Hopfällt igen: tillbaka till att fälla ut.
    hopfallt = client.get(f"/kommentarer/nod/{nod}?oppen=0", headers=HTMX).text
    bricka = hopfallt.split(f'id="kommentarantal-{nod}"', 1)[1]
    assert '?oppen=1"' in bricka and 'aria-expanded="false"' in bricka


def test_redigera_noden_inline_i_kommentarsvyn(client, app_db):
    ids = seed_trad(app_db)
    logga_in(client, app_db)
    token = _token(client)
    _skriv(client, ids["wos"], "Byt namn på den här", token)
    nod = ids["wos"]

    vy = client.get("/kommentarer").text
    assert f'hx-get="/kommentarer/nod/{nod}/redigera"' in vy
    assert f'<header id="rad-{nod}"' in vy

    form = client.get(f"/kommentarer/nod/{nod}/redigera", headers=HTMX).text
    assert f'hx-post="/kommentarer/nod/{nod}/redigera"' in form
    assert 'hx-target="#kommentarer-rot"' in form
    assert f'hx-get="/kommentarer/nod/{nod}/rubrik"' in form
    assert f'<header id="rad-{nod}"' in form

    # Avbryt: bara rubriken tillbaka.
    rubrik = client.get(f"/kommentarer/nod/{nod}/rubrik", headers=HTMX).text
    assert f'<header id="rad-{nod}"' in rubrik and "<section" not in rubrik

    svar = client.post(f"/kommentarer/nod/{nod}/redigera",
                       data={"namn": "WoS-import", "foralder_id": str(ids["import"]),
                             "typ": "funktion", "status": "utreds", "csrf_token": token},
                       headers=HTMX | {"X-CSRF-Token": token}).text
    assert 'id="kommentarer-rot"' in svar and "WoS-import" in svar
    assert "Byt namn på den här" in svar
    rad = app_db.execute("SELECT namn, status FROM funktion WHERE id = ?", (nod,)).fetchone()
    assert rad["namn"] == "WoS-import" and rad["status"] == "utreds"

    # Regelbrott (planerad utan avgång) ger felbannern i vyn, inget sparas.
    fel = client.post(f"/kommentarer/nod/{nod}/redigera",
                      data={"namn": "X", "foralder_id": str(ids["import"]),
                            "typ": "funktion", "status": "planerad", "fas": "",
                            "csrf_token": token},
                      headers=HTMX | {"X-CSRF-Token": token}).text
    assert 'id="kommentarer-fel"' in fel
    assert app_db.execute("SELECT namn FROM funktion WHERE id = ?", (nod,)).fetchone()[0] == "WoS-import"

    # Utan htmx: tillbaka till vyn med ankare på noden.
    svar = client.post(f"/kommentarer/nod/{nod}/redigera",
                       data={"namn": "WoS", "foralder_id": str(ids["import"]),
                             "typ": "funktion", "status": "utreds", "csrf_token": token},
                       follow_redirects=False)
    assert svar.status_code == 303 and svar.headers["location"] == f"/kommentarer#rad-{nod}"


def test_intern_far_inte_redigera_noden_i_kommentarsvyn(client, app_db):
    ids = seed_trad(app_db)
    app_db.execute("INSERT INTO kommentar (funktion_id, text) VALUES (?, 'x')", (ids["wos"],))
    app_db.commit()
    logga_in(client, app_db, namn="ingrid", roll="intern")
    vy = client.get("/kommentarer").text
    assert "/redigera" not in vy
    assert client.get(f"/kommentarer/nod/{ids['wos']}/redigera", headers=HTMX).status_code == 403
