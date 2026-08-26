"""End-to-end tests for the requirements tree (spec 5.1): CRUD, the three
move/reorder endpoints (shared by no-JS forms and SortableJS), the Swedish
cycle error in HTML (§9.1), delete confirmation impact (T2), filters (T4),
transitive visibility (T5/D4) and CSRF enforcement."""

from tests.conftest import (
    csrf_fran,
    logga_in,
    satt_svar,
    seed_trad,
    skapa_medlem,
)


def _token(client) -> str:
    return csrf_fran(client.get("/trad").text)


def test_kraver_inloggning(client):
    svar = client.get("/trad", follow_redirects=False)
    assert svar.status_code == 303
    assert svar.headers["location"] == "/login"


def test_post_utan_csrf_avvisas(client, app_db):
    logga_in(client, app_db)
    svar = client.post("/trad/nod", data={"namn": "X", "typ": "krav", "status": "planerad"})
    assert svar.status_code == 400


def test_skapa_och_redigera_nod(client, app_db):
    logga_in(client, app_db)
    token = _token(client)
    svar = client.post(
        "/trad/nod",
        data={"namn": "Publicering", "typ": "förmåga", "status": "befintlig",
              "synlig_externt": "1", "csrf_token": token},
        follow_redirects=False,
    )
    assert svar.status_code == 303
    assert "Publicering" in client.get("/trad").text

    nod_id = app_db.execute("SELECT id FROM funktion WHERE namn = 'Publicering'").fetchone()["id"]
    svar = client.post(
        f"/trad/nod/{nod_id}",
        data={"namn": "Publicering & spikblad", "typ": "förmåga", "status": "planerad",
              "fas": "nästa", "csrf_token": token},
        follow_redirects=False,
    )
    assert svar.status_code == 303
    rad = app_db.execute("SELECT * FROM funktion WHERE id = ?", (nod_id,)).fetchone()
    assert rad["namn"] == "Publicering & spikblad"
    assert rad["status"] == "planerad" and rad["fas"] == "nästa"
    assert rad["synlig_externt"] == 0  # unchecked checkbox


def test_acceptance_9_1_via_ui(client, app_db):
    ids = seed_trad(app_db)
    logga_in(client, app_db)
    token = _token(client)

    # Move Dubblettdetektering to root level ...
    svar = client.post(f"/trad/nod/{ids['dubblett']}/flytta",
                       data={"foralder_id": "", "csrf_token": token}, follow_redirects=False)
    assert svar.status_code == 303
    assert app_db.execute("SELECT foralder_id FROM funktion WHERE id = ?",
                          (ids["dubblett"],)).fetchone()[0] is None

    # ... move it back under Import från Web of Science ...
    client.post(f"/trad/nod/{ids['dubblett']}/flytta",
                data={"foralder_id": str(ids["wos"]), "csrf_token": token})

    # ... then try to make its ancestor its child: rejected with a Swedish error.
    svar = client.post(f"/trad/nod/{ids['wos']}/flytta",
                       data={"foralder_id": str(ids["dubblett"]), "csrf_token": token})
    assert svar.status_code == 400
    assert "kan inte flyttas" in svar.text
    # htmx variant: 200 with the error banner in the tree partial.
    svar = client.post(f"/trad/nod/{ids['wos']}/flytta",
                       data={"foralder_id": str(ids["dubblett"])},
                       headers={"HX-Request": "true", "X-CSRF-Token": token})
    assert svar.status_code == 200
    assert "kan inte flyttas" in svar.text


def test_ta_bort_med_bekraftelse(client, app_db):
    ids = seed_trad(app_db)
    medlem = skapa_medlem(app_db, "Uppsala universitet")
    satt_svar(app_db, medlem, ids["dubblett"], "golive_krav")
    app_db.commit()
    logga_in(client, app_db)

    sida = client.get(f"/trad/nod/{ids['wos']}/ta-bort").text
    assert "1 underliggande nod" in sida
    assert "1 bedömning" in sida

    svar = client.post(f"/trad/nod/{ids['wos']}/ta-bort",
                       data={"csrf_token": csrf_fran(sida)}, follow_redirects=False)
    assert svar.status_code == 303
    kvar = app_db.execute("SELECT COUNT(*) FROM funktion WHERE id IN (?, ?)",
                          (ids["wos"], ids["dubblett"])).fetchone()[0]
    assert kvar == 0
    # The deleted assessment is preserved in the history (D2 via explicit delete).
    hist = app_db.execute("SELECT COUNT(*) FROM bedomning_historik WHERE funktion_id = ?",
                          (ids["dubblett"],)).fetchone()[0]
    assert hist == 1


def test_ordna_och_sortera(client, app_db):
    ids = seed_trad(app_db)
    logga_in(client, app_db)
    token = _token(client)

    # Up/down buttons: move Import above Registrera avhandling.
    client.post(f"/trad/nod/{ids['import']}/ordna",
                data={"riktning": "upp", "csrf_token": token})
    ordning = [r["id"] for r in app_db.execute(
        "SELECT id FROM funktion WHERE foralder_id = ? ORDER BY sortering, id",
        (ids["publicering"],))]
    assert ordning == [ids["import"], ids["registrera"]]

    # SortableJS endpoint: new root order, with Registrera dragged out to root level.
    svar = client.post("/trad/sortera",
                       data={"foralder_id": "",
                             "nod_id": [str(ids["export"]), str(ids["publicering"]),
                                        str(ids["registrera"])],
                             "csrf_token": token},
                       follow_redirects=False)
    assert svar.status_code == 303
    rotter = [r["id"] for r in app_db.execute(
        "SELECT id FROM funktion WHERE foralder_id IS NULL ORDER BY sortering, id")]
    assert rotter == [ids["export"], ids["publicering"], ids["registrera"]]


def test_filter_visar_traffar_med_forfader(client, app_db):
    seed_trad(app_db)
    logga_in(client, app_db)
    sida = client.get("/trad", params={"q": "dubblett"}).text
    assert "Dubblettdetektering" in sida
    assert "Import från Web of Science" in sida  # ancestor kept for context
    assert "Registrera avhandling" not in sida
    assert "Export &amp; spridning" not in sida


def test_synlighet_ar_transitiv(client, app_db):
    ids = seed_trad(app_db)
    logga_in(client, app_db)
    client.post(f"/trad/nod/{ids['import']}/synlighet",
                data={"csrf_token": _token(client)})
    stig = {r["id"]: r["synlig_stig"]
            for r in app_db.execute("SELECT id, synlig_stig FROM funktion_trad")}
    assert stig[ids["import"]] == 0
    assert stig[ids["wos"]] == 0 and stig[ids["dubblett"]] == 0  # whole subtree hidden
    assert stig[ids["publicering"]] == 1 and stig[ids["registrera"]] == 1


def test_funktion_trad_visningsordning(app_db):
    seed_trad(app_db)
    namn = [r["namn"] for r in app_db.execute("SELECT namn FROM funktion_trad ORDER BY vag")]
    assert namn == [
        "Publicering", "Registrera avhandling", "Import",
        "Import från Web of Science", "Dubblettdetektering",
        "Export & spridning",
    ]
