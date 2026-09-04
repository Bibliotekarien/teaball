"""Role boundaries for staff accounts (admin/intern/extern): intern reads
everything but every mutation is refused server-side; extern only ever
receives externally visible content and cannot reach the internal views.
Complements test_isolering.py, which guards the member-session boundaries."""

from tests.conftest import (
    csrf_fran,
    logga_in,
    satt_svar,
    seed_trad,
    skapa_medlem,
)


def _csrf(client) -> str:
    # The login page always carries the session's CSRF token in a hidden
    # field, independent of which edit controls a role gets to see.
    return csrf_fran(client.get("/login").text)


def _förbered(client, app_db, roll, namn):
    ids = seed_trad(app_db)
    medlem_id = skapa_medlem(app_db, "KTH")
    satt_svar(app_db, medlem_id, ids["dubblett"], "golive_krav",
              kommentar="Privat anteckning om spikblad")
    app_db.commit()
    logga_in(client, app_db, namn=namn, roll=roll)
    return ids, medlem_id


ALLA_SKRIVNINGAR = [
    ("/trad/nod", {"namn": "Ny", "typ": "krav", "status": "planerad"}),
    ("/trad/nod/{nod}", {"namn": "Bytt", "typ": "krav", "status": "planerad"}),
    ("/trad/nod/{nod}/flytta", {"foralder_id": ""}),
    ("/trad/nod/{nod}/ordna", {"riktning": "upp"}),
    ("/trad/sortera", {"foralder_id": "", "nod_id": "{nod}"}),
    ("/trad/nod/{nod}/synlighet", {}),
    ("/trad/nod/{nod}/ta-bort", {}),
    ("/bedomning/{medlem}/{nod}/svar", {"svar": "kan_vanta"}),
    ("/bedomning/{medlem}/{nod}/workaround", {"workaround": "x"}),
    ("/bedomning/{medlem}/{nod}/kommentar", {"kommentar": "x"}),
    ("/roadmap/flytta", {"nod_id": "{nod}", "fas": "senare"}),
    ("/medlemmar", {"namn": "Ny medlem"}),
    ("/medlemmar/{medlem}", {"namn": "Bytt namn"}),
    ("/medlemmar/{medlem}/ta-bort", {}),
    ("/medlemmar/{medlem}/token", {}),
    ("/medlemmar/{medlem}/token/ta-bort", {}),
]


def _fyll_i(mall: str, nod_id: int, medlem_id: int) -> str:
    return mall.replace("{nod}", str(nod_id)).replace("{medlem}", str(medlem_id))


def test_intern_ser_allt_men_bara_lasning(client, app_db):
    ids, medlem_id = _förbered(client, app_db, "intern", "ines")

    app_db.execute("UPDATE funktion SET synlig_externt = 0 WHERE id = ?", (ids["import"],))
    app_db.commit()

    svar = client.get("/trad")
    assert svar.status_code == 200
    assert "Import från Web of Science" in svar.text  # dolda noder syns

    svar = client.get(f"/bedomning?medlem_id={medlem_id}")
    assert svar.status_code == 200
    assert "Privat anteckning om spikblad" in svar.text

    for adress in ("/analys", "/analys/medlemmar", "/analys/gemensamt",
                   "/medlemmar", "/export", "/roadmap"):
        assert client.get(adress).status_code == 200, adress


def test_intern_ser_inga_redigeringskontroller(client, app_db):
    ids, medlem_id = _förbered(client, app_db, "intern", "ines")

    trad = client.get("/trad").text
    for kontroll in ("greppyta", "+ Ny nod", ">redigera<", "ta&nbsp;bort", "data-skrivbar"):
        assert kontroll not in trad, kontroll
    assert "Confluence" in trad  # intern får hämta Confluence-markup

    bedomning = client.get(f"/bedomning?medlem_id={medlem_id}").text
    assert 'name="svar"' not in bedomning
    assert 'action="/bedomning/' not in bedomning
    assert "Visar svar för:" in bedomning

    medlemmar = client.get("/medlemmar").text
    # Utloggningsformuläret i sidhuvudet finns kvar — det är medlemsformulären
    # (skapa/redigera/token/ta bort) som ska vara borta.
    assert 'action="/medlemmar' not in medlemmar
    assert "skapa länk" not in medlemmar
    assert "KTH" in medlemmar

    assert "Redigera roadmap" not in client.get("/roadmap").text


def test_extern_nav_visar_bara_kravtrad_och_roadmap(client, app_db):
    _förbered(client, app_db, "extern", "elis")
    sida = client.get("/trad").text
    assert 'href="/roadmap"' in sida
    for adress in ("/bedomning", "/analys", "/medlemmar", "/export"):
        assert f'href="{adress}"' not in sida, adress
    assert "Confluence" not in sida


def test_admin_ser_redigeringskontroller(client, app_db):
    _förbered(client, app_db, "admin", "anna")
    trad = client.get("/trad").text
    for kontroll in ("greppyta", "+ Ny nod", "data-skrivbar"):
        assert kontroll in trad, kontroll


def test_intern_far_403_pa_alla_skrivningar(client, app_db):
    ids, medlem_id = _förbered(client, app_db, "intern", "ines")
    token = _csrf(client)
    fore = {
        tabell: app_db.execute(f"SELECT COUNT(*) FROM {tabell}").fetchone()[0]
        for tabell in ("funktion", "medlem", "bedomning")
    }

    for mall, data in ALLA_SKRIVNINGAR:
        adress = _fyll_i(mall, ids["dubblett"], medlem_id)
        fylld = {k: _fyll_i(v, ids["dubblett"], medlem_id) for k, v in data.items()}
        svar = client.post(adress, data=fylld | {"csrf_token": token},
                           follow_redirects=False)
        assert svar.status_code == 403, f"{adress}: {svar.status_code}"

    for tabell, antal in fore.items():
        assert app_db.execute(f"SELECT COUNT(*) FROM {tabell}").fetchone()[0] == antal
    kommentar = app_db.execute(
        "SELECT kommentar FROM bedomning WHERE medlem_id = ?", (medlem_id,)
    ).fetchone()["kommentar"]
    assert kommentar == "Privat anteckning om spikblad"


def test_intern_far_403_pa_redigeringsformular(client, app_db):
    ids, medlem_id = _förbered(client, app_db, "intern", "ines")
    for adress in ("/trad/nod/ny", "/trad/nod/namnkoll?namn=Import",
                   f"/trad/nod/{ids['dubblett']}/redigera",
                   f"/trad/nod/{ids['dubblett']}/ta-bort",
                   f"/medlemmar/{medlem_id}/ta-bort"):
        assert client.get(adress, follow_redirects=False).status_code == 403, adress


def test_extern_ser_bara_synligt_trad(client, app_db):
    ids, _ = _förbered(client, app_db, "extern", "elis")
    app_db.execute("UPDATE funktion SET synlig_externt = 0 WHERE id = ?", (ids["import"],))
    app_db.commit()

    svar = client.get("/trad")
    assert svar.status_code == 200
    assert "Publicering" in svar.text
    # Hela undergrenen under den dolda noden är borta (T5-transitivitet).
    assert "Import" not in svar.text
    assert "Dubblettdetektering" not in svar.text


def test_extern_far_403_pa_interna_vyer(client, app_db):
    _förbered(client, app_db, "extern", "elis")
    for adress in ("/bedomning", "/analys", "/analys/medlemmar", "/analys/gemensamt",
                   "/medlemmar", "/export", "/export/teaball.xlsx", "/export/json",
                   "/export/trad.csv", "/export/bedomningar.csv",
                   "/export/kravtrad.html", "/export/kravtrad.html?endast_synliga=1",
                   "/export/rapport.pdf?endast_synliga=1", "/export/confluence/kravtrad"):
        assert client.get(adress, follow_redirects=False).status_code == 403, adress


def test_extern_roadmap_ignorerar_redigeringslage(client, app_db):
    ids, _ = _förbered(client, app_db, "extern", "elis")
    app_db.execute("UPDATE funktion SET synlig_externt = 0 WHERE id = ?", (ids["import"],))
    app_db.commit()

    svar = client.get("/roadmap?redigera=1&visa_krav=1")
    assert svar.status_code == 200
    assert "data-redigera" not in svar.text
    assert "Import från Web of Science" not in svar.text


def test_extern_kan_ladda_ner_roadmap_export(client, app_db):
    ids, _ = _förbered(client, app_db, "extern", "elis")
    app_db.execute("UPDATE funktion SET synlig_externt = 0 WHERE id = ?", (ids["import"],))
    app_db.commit()

    svar = client.get("/roadmap/export?visa_krav=1")
    assert svar.status_code == 200
    assert "attachment" in svar.headers["content-disposition"]
    assert "Import från Web of Science" not in svar.text


def test_htmx_skrivforsok_ger_403_med_hx_refresh(client, app_db):
    ids, _ = _förbered(client, app_db, "intern", "ines")
    svar = client.post(
        f"/trad/nod/{ids['dubblett']}/synlighet",
        headers={"HX-Request": "true", "X-CSRF-Token": _csrf(client)},
        follow_redirects=False,
    )
    assert svar.status_code == 403
    assert svar.headers.get("hx-refresh") == "true"


def test_admin_paverkas_inte(client, app_db):
    ids, medlem_id = _förbered(client, app_db, "admin", "anna")
    svar = client.post(
        "/trad/nod",
        data={"namn": "Ny nod", "typ": "krav", "status": "planerad",
              "csrf_token": _csrf(client)},
        follow_redirects=False,
    )
    assert svar.status_code == 303
    assert app_db.execute(
        "SELECT 1 FROM funktion WHERE namn = 'Ny nod'"
    ).fetchone() is not None
