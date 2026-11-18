"""Medlemmarnas kommentarer sedda från förvaltningen (migration 0013):
pillret och blocket i behovsträdet, kommentarsvyn med hantering (läst,
arkiverad) som aldrig rör medlemmens kommentar, och att extern roll aldrig
ser dem."""

from app.services import bedomning
from app.services import medlemskommentarer as tjanst
from tests.conftest import (
    csrf_fran, ge_token, huvuddel, logga_in, satt_svar, seed_trad, skapa_medlem,
)

HTMX = {"HX-Request": "true"}


def _seed(conn):
    ids = seed_trad(conn)
    ids["uu"] = skapa_medlem(conn, "Uppsala universitet")
    ids["lu"] = skapa_medlem(conn, "Lunds universitet")
    satt_svar(conn, ids["uu"], ids["wos"], "golive_krav",
              oppen_kommentar="Formuleringen är otydlig", oppen_delning="anonym",
              intern_kommentar="Vi använder WoS dagligen")
    satt_svar(conn, ids["lu"], ids["wos"], "kan_vanta", intern_kommentar="Oklart för oss")
    satt_svar(conn, ids["lu"], ids["registrera"], "behovs_ej")  # utan kommentar
    conn.commit()
    return ids


def _status(client, ids, medlem, falt, status, token, fran="vy"):
    return client.post(
        f"/kommentarer/medlemmar/{ids[medlem]}/{ids['wos']}/{falt}/status",
        data={"status": status, "fran": fran, "csrf_token": token},
        headers=HTMX | {"X-CSRF-Token": token})


def test_vyn_listar_alla_kommentarer_per_nod(conn):
    ids = _seed(conn)
    assert tjanst.antal_per_visning(conn) == {
        "olästa": 3, "lästa": 0, "arkiverade": 0, "alla": 3}
    assert tjanst.antal_per_nod(conn) == {ids["wos"]: {"totalt": 3, "olasta": 3}}
    grupper = tjanst.grupperat(conn, "olästa")
    assert [g["nod"]["id"] for g in grupper] == [ids["wos"]]
    assert [(c["medlem_namn"], c["falt"]) for c in grupper[0]["kommentarer"]] == [
        ("Lunds universitet", "intern"),
        ("Uppsala universitet", "oppen"),
        ("Uppsala universitet", "intern"),
    ]


def test_arkiverad_lamnar_noden_men_inte_medlemmen(conn):
    ids = _seed(conn)
    tjanst.satt_status(conn, ids["uu"], ids["wos"], "oppen", "läst")
    tjanst.satt_status(conn, ids["uu"], ids["wos"], "intern", "arkiverad")
    assert tjanst.antal_per_visning(conn) == {
        "olästa": 1, "lästa": 1, "arkiverade": 1, "alla": 3}
    # Under noden: olästa och lästa, inte arkiverade.
    assert tjanst.antal_per_nod(conn) == {ids["wos"]: {"totalt": 2, "olasta": 1}}
    assert [c["falt"] for c in tjanst.for_nod(conn, ids["wos"])
            if c["medlem_id"] == ids["uu"]] == ["oppen"]
    # Medlemmens kommentarer står orörda.
    rad = conn.execute("SELECT * FROM bedomning WHERE medlem_id = ? AND funktion_id = ?",
                       (ids["uu"], ids["wos"])).fetchone()
    assert rad["oppen_kommentar"] == "Formuleringen är otydlig"
    assert rad["intern_kommentar"] == "Vi använder WoS dagligen"
    # Hanteringen skriver ingen svarshistorik.
    assert conn.execute("SELECT COUNT(*) FROM bedomning_historik").fetchone()[0] == 0

    tjanst.satt_status(conn, ids["uu"], ids["wos"], "intern", "oläst")
    assert tjanst.hamta(conn, ids["uu"], ids["wos"], "intern")["hantering"] is None


def test_hanteringen_nollas_nar_medlemmen_andrar_texten(conn):
    ids = _seed(conn)
    tjanst.satt_status(conn, ids["uu"], ids["wos"], "oppen", "arkiverad")
    tjanst.satt_status(conn, ids["uu"], ids["wos"], "intern", "läst")

    # Samma text (som vid ett byte av delning) behåller hanteringen ...
    bedomning.satt_oppen_kommentar(conn, ids["uu"], ids["wos"],
                                   "Formuleringen är otydlig", "namn")
    assert tjanst.hamta(conn, ids["uu"], ids["wos"], "oppen")["hantering"] == "arkiverad"
    # ... en ändrad text blir oläst igen, även en arkiverad, men bara den.
    bedomning.satt_oppen_kommentar(conn, ids["uu"], ids["wos"], "Ny text", "namn")
    assert tjanst.hamta(conn, ids["uu"], ids["wos"], "oppen")["hantering"] is None
    assert tjanst.hamta(conn, ids["uu"], ids["wos"], "intern")["hantering"] == "läst"
    # Ett byte av svar rör inte hanteringen.
    bedomning.satt_svar(conn, ids["uu"], ids["wos"], "kan_vanta", "x")
    assert tjanst.hamta(conn, ids["uu"], ids["wos"], "intern")["hantering"] == "läst"
    # Tar medlemmen bort svaret följer hanteringen med (kaskad).
    bedomning.satt_svar(conn, ids["uu"], ids["wos"], "kan_vanta", "x")
    assert conn.execute(
        "SELECT COUNT(*) FROM medlemskommentar_hantering").fetchone()[0] == 0


def test_tradet_visar_pill_och_block(client, app_db):
    ids = _seed(app_db)
    logga_in(client, app_db, "ivar", roll="intern")
    trad = client.get("/trad").text
    assert 'aria-label="3 kommentarer från medlemmar, 3 olästa"' in trad
    assert 'id="medlemskommentarer-' + str(ids["wos"]) + '"' in trad
    # Hopfällt: bara pillret, ingen text.
    assert "Formuleringen är otydlig" not in trad

    svar = client.get(f"/kommentarer/medlemmar/nod/{ids['wos']}?oppen=1", headers=HTMX)
    assert "Formuleringen är otydlig" in svar.text
    assert "Uppsala universitet" in svar.text
    assert "alla medlemmar, anonymt" in svar.text
    assert 'id="medlemskommentarpill-' + str(ids["wos"]) + '" hx-swap-oob="true"' in svar.text
    # Intern läser men hanterar inte.
    assert "/status" not in svar.text


def test_admin_hanterar_i_vyn_och_i_tradet(client, app_db):
    ids = _seed(app_db)
    logga_in(client, app_db)
    sida = client.get("/kommentarer/medlemmar")
    assert "Vi använder WoS dagligen" in huvuddel(sida.text)
    token = csrf_fran(sida.text)

    svar = _status(client, ids, "uu", "intern", "läst", token)
    assert svar.status_code == 200
    # Olästa-fliken (standard) visar inte längre den avbockade.
    assert "Vi använder WoS dagligen" not in svar.text
    assert tjanst.antal_per_visning(app_db)["lästa"] == 1

    svar = _status(client, ids, "uu", "oppen", "arkiverad", token, fran="nod")
    assert svar.status_code == 200
    assert 'id="medlemskommentarer-' + str(ids["wos"]) + '"' in svar.text
    assert "Formuleringen är otydlig" not in svar.text
    assert 'aria-label="2 kommentarer från medlemmar, 1 oläst"' in svar.text

    arkiv = client.get("/kommentarer/medlemmar?visa=arkiverade").text
    assert "Formuleringen är otydlig" in arkiv and "Visa som läst" in arkiv


def test_medlemmen_ser_arkiverad_kommentar_som_forut(client, app_db, klient_fabrik):
    ids = _seed(app_db)
    tjanst.satt_status(app_db, ids["uu"], ids["wos"], "oppen", "arkiverad")
    tjanst.satt_status(app_db, ids["uu"], ids["wos"], "intern", "arkiverad")
    app_db.commit()
    medlem = klient_fabrik()
    medlem.get(f"/svara/{ge_token(app_db, ids['uu'])}")
    sida = medlem.get("/svara").text
    assert "Formuleringen är otydlig" in sida and "Vi använder WoS dagligen" in sida
    # Den delade öppna syns fortfarande för andra medlemmar.
    annan = klient_fabrik()
    annan.get(f"/svara/{ge_token(app_db, ids['lu'])}")
    assert "Formuleringen är otydlig" in annan.get("/svara").text


def test_utan_js_redirectar_formularen(client, app_db):
    ids = _seed(app_db)
    logga_in(client, app_db)
    token = csrf_fran(client.get("/kommentarer/medlemmar").text)
    svar = client.post(f"/kommentarer/medlemmar/{ids['lu']}/{ids['wos']}/intern/status",
                       data={"status": "läst", "fran": "nod", "csrf_token": token},
                       follow_redirects=False)
    assert svar.status_code == 303
    assert svar.headers["location"] == f"/kommentarer/medlemmar/nod/{ids['wos']}"
    sida = client.get(svar.headers["location"]).text
    assert "Oklart för oss" in sida and "Markera&nbsp;oläst" in sida
    # Dölj-länken leder utan JS tillbaka till noden i trädet.
    assert f'href="/trad#rad-{ids["wos"]}" hx-get=' in sida


def test_okand_kommentar_eller_status_avvisas(client, app_db):
    ids = _seed(app_db)
    logga_in(client, app_db)
    token = csrf_fran(client.get("/kommentarer/medlemmar").text)
    # Lund har ingen öppen kommentar; ett påhittat fält finns inte alls.
    assert _status(client, ids, "lu", "oppen", "läst", token).status_code == 404
    svar = client.post(f"/kommentarer/medlemmar/{ids['lu']}/{ids['wos']}/workaround/status",
                       data={"status": "läst", "csrf_token": token},
                       headers=HTMX | {"X-CSRF-Token": token})
    assert svar.status_code == 404
    assert _status(client, ids, "lu", "intern", "raderad", token).status_code == 400


def test_intern_far_inte_hantera(client, app_db):
    ids = _seed(app_db)
    logga_in(client, app_db, "ivar", roll="intern")
    token = csrf_fran(client.get("/kommentarer/medlemmar").text)
    assert _status(client, ids, "uu", "oppen", "läst", token).status_code == 403
    assert tjanst.hamta(app_db, ids["uu"], ids["wos"], "oppen")["hantering"] is None


def test_extern_ser_inga_medlemskommentarer(client, app_db):
    ids = _seed(app_db)
    logga_in(client, app_db, "erik", roll="extern")
    trad = client.get("/trad").text
    assert "från medlemmar" not in trad
    assert "medlemskommentarer-" not in trad
    for adress in ("/kommentarer/medlemmar", f"/kommentarer/medlemmar/nod/{ids['wos']}"):
        assert client.get(adress, follow_redirects=False).status_code in (303, 403)
