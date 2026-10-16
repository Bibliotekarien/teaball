"""Tests for the flat list view (/lista): the timestamp stamps (migration
0005 + funktion_stampel triggers), sorting on skapad/uppdaterad, the T4
filters shared with the tree, the view toggle and the quick-create form."""

from tests.conftest import csrf_fran, klient_fabrik  # noqa: F401  (fixture)
from tests.conftest import logga_in, seed_trad, skapa_funktion


def lista_delen(sida: str) -> str:
    """The markup from #lista-rot on: row-order assertions must not trip on
    node names that also appear in the quick form's parent <select>."""
    return sida.split('id="lista-rot"', 1)[1]


def test_stamplar_satts_och_uppdateras(conn):
    nod = skapa_funktion(conn, "Ny nod", typ="funktion")
    rad = conn.execute(
        "SELECT skapad, uppdaterad FROM funktion WHERE id = ?", (nod,)
    ).fetchone()
    assert rad["skapad"] is not None
    assert rad["uppdaterad"] == rad["skapad"]

    # En innehållsändring flyttar uppdaterad (skapad står stilla) ...
    conn.execute("UPDATE funktion SET uppdaterad = '2020-01-01 00:00:00' WHERE id = ?", (nod,))
    conn.execute("UPDATE funktion SET beskrivning = 'ny text' WHERE id = ?", (nod,))
    efter = conn.execute(
        "SELECT skapad, uppdaterad FROM funktion WHERE id = ?", (nod,)
    ).fetchone()
    assert efter["uppdaterad"] != "2020-01-01 00:00:00"
    assert efter["skapad"] == rad["skapad"]

    # ... men en skrivning med oförändrat värde stämplar inte om (redigerings-
    # formuläret skriver alla kolumner varje spar) ...
    conn.execute("UPDATE funktion SET uppdaterad = '2020-01-01 00:00:00' WHERE id = ?", (nod,))
    conn.execute("UPDATE funktion SET beskrivning = 'ny text' WHERE id = ?", (nod,))
    assert conn.execute(
        "SELECT uppdaterad FROM funktion WHERE id = ?", (nod,)
    ).fetchone()["uppdaterad"] == "2020-01-01 00:00:00"

    # ... och omsortering är ingen innehållsändring.
    conn.execute("UPDATE funktion SET sortering = 999 WHERE id = ?", (nod,))
    assert conn.execute(
        "SELECT uppdaterad FROM funktion WHERE id = ?", (nod,)
    ).fetchone()["uppdaterad"] == "2020-01-01 00:00:00"


def test_lista_sortering(client, app_db):
    seed_trad(app_db)
    logga_in(client, app_db)
    app_db.execute("UPDATE funktion SET skapad = '2026-02-01 10:00:00',"
                   " uppdaterad = '2026-05-01 10:00:00'"
                   " WHERE namn = 'Registrera avhandling'")
    app_db.execute("UPDATE funktion SET skapad = '2026-03-01 10:00:00',"
                   " uppdaterad = '2026-04-01 10:00:00'"
                   " WHERE namn = 'Import från Web of Science'")
    app_db.execute("UPDATE funktion SET skapad = NULL, uppdaterad = NULL"
                   " WHERE namn = 'Dubblettdetektering'")
    app_db.commit()

    # Standard: skapad fallande — nyast först, ostämplade (NULL) alltid sist.
    rader = lista_delen(client.get("/lista").text)
    assert rader.index("Import från Web of Science") < rader.index("Registrera avhandling")
    assert rader.index("Registrera avhandling") < rader.index("Dubblettdetektering")

    rader = lista_delen(client.get("/lista?sortera=skapad&riktning=stigande").text)
    assert rader.index("Registrera avhandling") < rader.index("Import från Web of Science")
    assert rader.index("Import från Web of Science") < rader.index("Dubblettdetektering")

    # Uppdaterad har omvänd ordning mellan de två i testdatat.
    rader = lista_delen(client.get("/lista?sortera=uppdaterad").text)
    assert rader.index("Registrera avhandling") < rader.index("Import från Web of Science")


def test_lista_filter_som_kravtradet(client, app_db):
    ids = seed_trad(app_db)
    logga_in(client, app_db)

    def rad(nod):
        return f'id="rad-{ids[nod]}"'

    # Fritext — men utan trädets förfäderskontext: bara träffarna får rader
    # (förfäderna syns ändå, som breadcrumb på träffens rad).
    rader = lista_delen(client.get("/lista?q=web").text)
    assert rad("wos") in rader
    assert rad("registrera") not in rader and rad("publicering") not in rader
    assert "Publicering" in rader  # i breadcrumben
    # Typfilter.
    rader = lista_delen(client.get("/lista?typ=krav").text)
    assert rad("dubblett") in rader and rad("publicering") not in rader
    # Statusfilter + avgång.
    rader = lista_delen(client.get("/lista?status=driftsatt&fas=Avg%C3%A5ng+1").text)
    assert rad("publicering") in rader and rad("registrera") not in rader


def test_lista_dolj_dolda(client, app_db):
    ids = seed_trad(app_db)
    # Synligheten ärvs: en dold Import döljer hela grenen under den.
    app_db.execute("UPDATE funktion SET synlig_externt = 0 WHERE id = ?", (ids["import"],))
    app_db.commit()
    logga_in(client, app_db)

    rader = lista_delen(client.get("/lista").text)
    assert f'id="rad-{ids["wos"]}"' in rader  # standard: dolda syns, med etikett
    rader = lista_delen(client.get("/lista?dolj_dolda=1").text)
    for nod in ("import", "wos", "dubblett"):
        assert f'id="rad-{ids[nod]}"' not in rader
    assert f'id="rad-{ids["registrera"]}"' in rader
    # Rutan speglar filtret, och det kombineras med de andra.
    assert 'name="dolj_dolda" value="1" checked' in client.get("/lista?dolj_dolda=1").text
    rader = lista_delen(client.get("/lista?dolj_dolda=1&typ=krav").text)
    assert f'id="rad-{ids["dubblett"]}"' not in rader


def test_lista_vyvaxling(client, app_db):
    seed_trad(app_db)
    skapa_funktion(app_db, "Med detaljer", typ="funktion",
                   beskrivning="En längre förklaring.")
    app_db.commit()
    logga_in(client, app_db)
    # Kompakt är standard: inget detaljblock i raden (beskrivningen finns
    # bara som title-attribut, precis som i trädet) ...
    assert ">En längre förklaring.</p>" not in lista_delen(client.get("/lista").text)
    # ... detaljerad renderar blocket, och valet är klibbigt i sessionen.
    assert ">En längre förklaring.</p>" in lista_delen(client.get("/lista?vy=detaljerad").text)
    assert ">En längre förklaring.</p>" in lista_delen(client.get("/lista").text)


def test_lista_snabbformular(client, app_db):
    seed_trad(app_db)
    logga_in(client, app_db)
    sida = client.get("/lista").text
    assert 'action="/lista/nod"' in sida
    token = csrf_fran(sida)

    svar = client.post("/lista/nod",
                       data={"namn": "Inkorgsgrej", "typ": "funktion",
                             "status": "utreds", "csrf_token": token},
                       follow_redirects=False)
    assert svar.status_code == 303 and svar.headers["location"] == "/lista"
    # Nyast skapad ⇒ överst i standardsorteringen, direkt under formuläret.
    rader = lista_delen(client.get("/lista").text)
    assert rader.index("Inkorgsgrej") < rader.index("Publicering")

    # Över htmx: omrenderad lista + färskt formulär OOB-swappat på plats.
    partial = client.post("/lista/nod",
                          data={"namn": "Htmx-grej", "typ": "funktion",
                                "status": "utreds"},
                          headers={"HX-Request": "true", "X-CSRF-Token": token}).text
    assert 'id="lista-rot"' in partial
    assert 'id="lista-nyform" hx-swap-oob="innerHTML"' in partial

    # Avgångskravet gäller även här: planerad utan avgång stoppas med
    # regeltexten inline (helsida = 400, som i trädet).
    svar = client.post("/lista/nod",
                       data={"namn": "Utan avgång", "typ": "funktion",
                             "status": "planerad", "csrf_token": token})
    assert svar.status_code == 400
    assert "avgång" in svar.text


def test_lista_behorigheter(app_db, klient_fabrik):
    seed_trad(app_db)
    # Intern läser men får inget formulär och kan inte skapa.
    intern = klient_fabrik()
    logga_in(intern, app_db, namn="ivan", roll="intern")
    sida = intern.get("/lista")
    assert sida.status_code == 200
    assert 'action="/lista/nod"' not in sida.text
    # Giltig CSRF (utloggningsformuläret bär token) så det är ROLLEN som stoppar.
    assert intern.post("/lista/nod",
                       data={"namn": "X", "typ": "krav", "status": "utreds",
                             "csrf_token": csrf_fran(sida.text)}
                       ).status_code == 403
    # Extern har kravträdet — listvyn är ett internt arbetsverktyg.
    extern = klient_fabrik()
    logga_in(extern, app_db, namn="eva", roll="extern")
    assert extern.get("/lista").status_code == 403


def test_lista_breadcrumb(client, app_db):
    """Varje rad bär sin plats i trädet: förfäderna från roten som länkar in i
    kravträdet, rotnoder som (rotnivå). Även den fristående raden (avbryt i
    inline-redigeringen) har den, så raden inte byter form efter avbryt."""
    ids = seed_trad(app_db)
    logga_in(client, app_db)
    rader = lista_delen(client.get("/lista").text)

    dubblett = rader.split(f'id="rad-{ids["dubblett"]}"', 1)[1].split("</li>", 1)[0]
    lankar = [f'<a href="/trad#rad-{ids[n]}"' for n in ("publicering", "import", "wos")]
    for lank in lankar:
        assert lank in dubblett
    assert dubblett.index(lankar[0]) < dubblett.index(lankar[1]) < dubblett.index(lankar[2])
    assert dubblett.count('<span aria-hidden="true">/</span>') == 2  # mellan länkarna, inte efter sista
    assert f'/trad#rad-{ids["dubblett"]}' not in dubblett  # noden själv ingår inte
    assert "(rotnivå)" not in dubblett

    rot = rader.split(f'id="rad-{ids["export"]}"', 1)[1].split("</li>", 1)[0]
    assert "(rotnivå)" in rot
    assert "/trad#rad-" not in rot

    rad = client.get(f"/lista/nod/{ids['wos']}/rad", headers={"HX-Request": "true"}).text
    assert f'<a href="/trad#rad-{ids["import"]}"' in rad
    assert ">Import</a>" in rad


def test_lista_redigera_inline(client, app_db):
    """Redigera på raden: kravträdets formulär riktat mot listan, sparande
    som byter ut listan (sessionens sortering/filter består) och avbryt som
    bara hämtar raden igen."""
    ids = seed_trad(app_db)
    logga_in(client, app_db)
    sida = client.get("/lista?sortera=uppdaterad").text
    token = csrf_fran(sida)
    assert f'hx-get="/lista/nod/{ids["wos"]}/redigera"' in sida
    assert f'id="rad-{ids["wos"]}"' in sida

    # Över htmx: formuläret som ett <li> på radens plats, postar till listan,
    # swappar #lista-rot, och avbryt hämtar bara raden.
    form = client.get(f"/lista/nod/{ids['wos']}/redigera",
                      headers={"HX-Request": "true"}).text
    assert form.lstrip().startswith(f'<li id="rad-{ids["wos"]}"')
    assert form.rstrip().endswith("</li>")
    assert f'action="/lista/nod/{ids["wos"]}"' in form
    assert 'hx-target="#lista-rot"' in form
    assert f'hx-get="/lista/nod/{ids["wos"]}/rad" hx-target="#rad-{ids["wos"]}"' in form
    assert 'value="Import från Web of Science"' in form
    assert '<option value="funktion" selected>funktion</option>' in form
    # Egen undergren är utesluten ur förälderväljaren (skulle bli en cykel).
    assert f'<option value="{ids["dubblett"]}"' not in form
    # Helsida utan htmx, som i trädet.
    helsida = client.get(f"/lista/nod/{ids['wos']}/redigera").text
    assert "Redigera ”Import från Web of Science”" in helsida
    assert f'action="/lista/nod/{ids["wos"]}"' in helsida

    # Avbryt: bara raden, inte hela listan.
    rad = client.get(f"/lista/nod/{ids['wos']}/rad", headers={"HX-Request": "true"}).text
    assert rad.lstrip().startswith(f'<li id="rad-{ids["wos"]}"')
    assert 'id="lista-rot"' not in rad
    assert client.get(f"/lista/nod/{ids['wos']}/rad",
                      follow_redirects=False).status_code == 303

    # Spara över htmx: hela listan tillbaka med sessionens sortering, noden
    # omdöpt, länk sparad och flyttad till ny förälder.
    partial = client.post(
        f"/lista/nod/{ids['wos']}",
        data={"namn": "Import från WoS", "foralder_id": str(ids["export"]),
              "typ": "funktion", "status": "planerad", "fas": "Avgång 1",
              "lank_jira": "https://jira.example/WOS-1", "synlig_externt": "1"},
        headers={"HX-Request": "true", "X-CSRF-Token": token}).text
    assert 'id="lista-rot"' in partial and 'id="lista-fel"' not in partial
    assert "Import från WoS" in partial
    assert 'title="Sortera på uppdaterad, stigande"' in partial  # sorteringen kvar
    rad = app_db.execute("SELECT * FROM funktion WHERE id = ?", (ids["wos"],)).fetchone()
    assert rad["foralder_id"] == ids["export"]
    assert rad["lank_jira"] == "https://jira.example/WOS-1"
    assert rad["status"] == "planerad" and rad["fas"] == "Avgång 1"

    # Utan htmx: 303 tillbaka till listan.
    svar = client.post(f"/lista/nod/{ids['wos']}",
                       data={"namn": "Import från WoS", "foralder_id": str(ids["export"]),
                             "typ": "funktion", "status": "utreds", "csrf_token": token},
                       follow_redirects=False)
    assert svar.status_code == 303 and svar.headers["location"] == "/lista"

    # Regelbrott inline: ogiltig länk och avgångskravet ger listan med banner.
    svar = client.post(f"/lista/nod/{ids['wos']}",
                       data={"namn": "X", "typ": "funktion", "status": "utreds",
                             "lank_jira": "javascript:alert(1)"},
                       headers={"HX-Request": "true", "X-CSRF-Token": token})
    assert svar.status_code == 200
    assert 'id="lista-fel"' in svar.text and "http://" in svar.text
    svar = client.post(f"/lista/nod/{ids['wos']}",
                       data={"namn": "X", "typ": "funktion", "status": "planerad",
                             "csrf_token": token})
    assert svar.status_code == 400 and "avgång" in svar.text
    assert app_db.execute("SELECT namn FROM funktion WHERE id = ?",
                          (ids["wos"],)).fetchone()["namn"] == "Import från WoS"

    assert client.get("/lista/nod/999999/redigera").status_code == 404


def test_lista_ta_bort_inline(client, app_db):
    """Ta bort på raden: kravträdets bekräftelse riktad mot listan, med
    konsekvensen angiven, och listan tillbaka efter borttagning."""
    ids = seed_trad(app_db)
    logga_in(client, app_db)
    sida = client.get("/lista").text
    token = csrf_fran(sida)
    assert f'hx-get="/lista/nod/{ids["import"]}/ta-bort"' in sida

    bekraftelse = client.get(f"/lista/nod/{ids['import']}/ta-bort",
                             headers={"HX-Request": "true"}).text
    assert bekraftelse.lstrip().startswith(f'<li id="rad-{ids["import"]}"')
    assert "Ta bort ”Import”?" in bekraftelse
    assert "2 underliggande noder" in bekraftelse
    assert f'action="/lista/nod/{ids["import"]}/ta-bort"' in bekraftelse
    assert 'hx-target="#lista-rot"' in bekraftelse
    assert f'hx-get="/lista/nod/{ids["import"]}/rad" hx-target="#rad-{ids["import"]}"' in bekraftelse
    # Helsida utan htmx.
    assert "Ta bort ”Import”?" in client.get(f"/lista/nod/{ids['import']}/ta-bort").text

    partial = client.post(f"/lista/nod/{ids['import']}/ta-bort",
                          headers={"HX-Request": "true", "X-CSRF-Token": token}).text
    assert 'id="lista-rot"' in partial
    assert "Import" not in lista_delen(client.get("/lista").text)
    assert app_db.execute("SELECT COUNT(*) FROM funktion WHERE id IN (?, ?, ?)",
                          (ids["import"], ids["wos"], ids["dubblett"])).fetchone()[0] == 0

    svar = client.post(f"/lista/nod/{ids['registrera']}/ta-bort",
                       data={"csrf_token": token}, follow_redirects=False)
    assert svar.status_code == 303 and svar.headers["location"] == "/lista"
    assert client.get("/lista/nod/999999/ta-bort").status_code == 404


def test_lista_redigering_kraver_admin(app_db, klient_fabrik):
    ids = seed_trad(app_db)
    intern = klient_fabrik()
    logga_in(intern, app_db, namn="ivan", roll="intern")
    sida = intern.get("/lista")
    assert "/redigera" not in lista_delen(sida.text)
    assert "/ta-bort" not in lista_delen(sida.text)
    token = csrf_fran(sida.text)
    assert intern.get(f"/lista/nod/{ids['wos']}/redigera").status_code == 403
    assert intern.get(f"/lista/nod/{ids['wos']}/ta-bort").status_code == 403
    assert intern.post(f"/lista/nod/{ids['wos']}",
                       data={"namn": "X", "typ": "funktion", "status": "utreds",
                             "csrf_token": token}).status_code == 403
    assert intern.post(f"/lista/nod/{ids['wos']}/ta-bort",
                       data={"csrf_token": token}).status_code == 403
    assert app_db.execute("SELECT COUNT(*) FROM funktion WHERE id = ?",
                          (ids["wos"],)).fetchone()[0] == 1
