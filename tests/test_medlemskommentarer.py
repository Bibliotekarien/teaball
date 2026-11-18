"""Medlemmarnas kommentarer sedda från förvaltningen (migration 0013):
pillret och blocket i behovsträdet, kommentarsvyn med läskvittens och
radering, och att extern roll aldrig ser dem."""

from app.services import bedomning
from app.services import medlemskommentarer as tjanst
from tests.conftest import (
    csrf_fran, huvuddel, logga_in, satt_svar, seed_trad, skapa_medlem,
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


def _post(client, adress, data, token):
    return client.post(adress, data=data | {"csrf_token": token},
                       headers=HTMX | {"X-CSRF-Token": token})


def test_vyn_listar_alla_kommentarer_per_nod(conn):
    ids = _seed(conn)
    assert tjanst.antal_per_visning(conn) == {"olästa": 3, "lästa": 0, "alla": 3}
    assert tjanst.antal_per_nod(conn) == {ids["wos"]: {"totalt": 3, "olasta": 3}}
    grupper = tjanst.grupperat(conn, "olästa")
    assert [g["nod"]["id"] for g in grupper] == [ids["wos"]]
    assert [(c["medlem_namn"], c["falt"]) for c in grupper[0]["kommentarer"]] == [
        ("Lunds universitet", "intern"),
        ("Uppsala universitet", "oppen"),
        ("Uppsala universitet", "intern"),
    ]


def test_kvittens_nollas_nar_medlemmen_andrar_texten(conn):
    ids = _seed(conn)
    tjanst.kvittera(conn, ids["uu"], ids["wos"], "oppen", True)
    tjanst.kvittera(conn, ids["uu"], ids["wos"], "intern", True)
    assert tjanst.antal_per_visning(conn)["lästa"] == 2

    # Samma text (som vid ett byte av delning) behåller kvittensen ...
    bedomning.satt_oppen_kommentar(conn, ids["uu"], ids["wos"],
                                   "Formuleringen är otydlig", "namn")
    assert tjanst.hamta(conn, ids["uu"], ids["wos"], "oppen")["kvitterad"]
    # ... en ändrad text blir oläst igen, men bara den kommentaren.
    bedomning.satt_oppen_kommentar(conn, ids["uu"], ids["wos"], "Ny text", "namn")
    assert tjanst.hamta(conn, ids["uu"], ids["wos"], "oppen")["kvitterad"] is None
    assert tjanst.hamta(conn, ids["uu"], ids["wos"], "intern")["kvitterad"]
    # Ett byte av svar (UPDATE av svar) rör inte kvittensen.
    bedomning.satt_svar(conn, ids["uu"], ids["wos"], "kan_vanta", "x")
    assert tjanst.hamta(conn, ids["uu"], ids["wos"], "intern")["kvitterad"]
    # Tar medlemmen bort svaret följer kvittenserna med (kaskad).
    bedomning.satt_svar(conn, ids["uu"], ids["wos"], "kan_vanta", "x")
    assert conn.execute("SELECT COUNT(*) FROM medlemskommentar_kvittens").fetchone()[0] == 0


def test_radera_tommer_bara_kommentaren(conn):
    ids = _seed(conn)
    tjanst.kvittera(conn, ids["uu"], ids["wos"], "oppen", True)
    tjanst.radera(conn, ids["uu"], ids["wos"], "oppen")
    rad = conn.execute("SELECT * FROM bedomning WHERE medlem_id = ? AND funktion_id = ?",
                       (ids["uu"], ids["wos"])).fetchone()
    assert rad["svar"] == "golive_krav"
    assert rad["oppen_kommentar"] is None
    assert rad["intern_kommentar"] == "Vi använder WoS dagligen"
    assert conn.execute("SELECT COUNT(*) FROM medlemskommentar_kvittens").fetchone()[0] == 0
    # Den gamla texten finns kvar i historiken.
    assert conn.execute(
        "SELECT COUNT(*) FROM bedomning_historik WHERE oppen_kommentar = ?",
        ("Formuleringen är otydlig",),
    ).fetchone()[0] == 1


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
    assert "/kvittera" not in svar.text and "/radera" not in svar.text


def test_admin_kvitterar_och_raderar_i_vyn(client, app_db):
    ids = _seed(app_db)
    logga_in(client, app_db)
    sida = client.get("/kommentarer/medlemmar")
    assert "Vi använder WoS dagligen" in huvuddel(sida.text)
    token = csrf_fran(sida.text)
    bas = f"/kommentarer/medlemmar/{ids['uu']}/{ids['wos']}"

    svar = _post(client, f"{bas}/intern/kvittera", {"last": "1"}, token)
    assert svar.status_code == 200
    # Olästa-fliken (standard) visar inte längre den kvitterade.
    assert "Vi använder WoS dagligen" not in svar.text
    assert tjanst.antal_per_visning(app_db) == {"olästa": 2, "lästa": 1, "alla": 3}

    svar = _post(client, f"{bas}/intern/kvittera", {"last": "0"}, token)
    assert tjanst.antal_per_visning(app_db)["lästa"] == 0

    svar = _post(client, f"{bas}/oppen/radera", {"fran": "nod"}, token)
    assert svar.status_code == 200
    assert 'id="medlemskommentarer-' + str(ids["wos"]) + '"' in svar.text
    assert "Formuleringen är otydlig" not in svar.text
    assert tjanst.antal_per_visning(app_db)["alla"] == 2


def test_utan_js_redirectar_formularen(client, app_db):
    ids = _seed(app_db)
    logga_in(client, app_db)
    token = csrf_fran(client.get("/kommentarer/medlemmar").text)
    svar = client.post(f"/kommentarer/medlemmar/{ids['lu']}/{ids['wos']}/intern/kvittera",
                       data={"last": "1", "fran": "nod", "csrf_token": token},
                       follow_redirects=False)
    assert svar.status_code == 303
    assert svar.headers["location"] == f"/kommentarer/medlemmar/nod/{ids['wos']}"
    sida = client.get(svar.headers["location"]).text
    assert "Oklart för oss" in sida and "Markera&nbsp;oläst" in sida


def test_okand_kommentar_ger_404(client, app_db):
    ids = _seed(app_db)
    logga_in(client, app_db)
    token = csrf_fran(client.get("/kommentarer/medlemmar").text)
    # Lund har ingen öppen kommentar; ett påhittat fält finns inte alls.
    for falt in ("oppen", "workaround"):
        svar = _post(client, f"/kommentarer/medlemmar/{ids['lu']}/{ids['wos']}/{falt}/radera",
                     {}, token)
        assert svar.status_code == 404


def test_intern_far_inte_kvittera_eller_radera(client, app_db):
    ids = _seed(app_db)
    logga_in(client, app_db, "ivar", roll="intern")
    token = csrf_fran(client.get("/kommentarer/medlemmar").text)
    bas = f"/kommentarer/medlemmar/{ids['uu']}/{ids['wos']}/oppen"
    assert _post(client, f"{bas}/kvittera", {"last": "1"}, token).status_code == 403
    assert _post(client, f"{bas}/radera", {}, token).status_code == 403
    assert tjanst.hamta(app_db, ids["uu"], ids["wos"], "oppen")["kvitterad"] is None


def test_extern_ser_inga_medlemskommentarer(client, app_db):
    ids = _seed(app_db)
    logga_in(client, app_db, "erik", roll="extern")
    trad = client.get("/trad").text
    assert "från medlemmar" not in trad
    assert "medlemskommentarer-" not in trad
    for adress in ("/kommentarer/medlemmar", f"/kommentarer/medlemmar/nod/{ids['wos']}"):
        assert client.get(adress, follow_redirects=False).status_code in (303, 403)
