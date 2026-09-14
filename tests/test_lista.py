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
    seed_trad(app_db)
    logga_in(client, app_db)
    # Fritext — men utan trädets förfäderskontext: bara träffarna listas.
    rader = lista_delen(client.get("/lista?q=web").text)
    assert "Import från Web of Science" in rader
    assert "Registrera avhandling" not in rader and "Publicering" not in rader
    # Typfilter.
    rader = lista_delen(client.get("/lista?typ=krav").text)
    assert "Dubblettdetektering" in rader and "Publicering" not in rader
    # Statusfilter + avgång.
    rader = lista_delen(client.get("/lista?status=driftsatt&fas=Medlem+1").text)
    assert "Publicering" in rader and "Registrera avhandling" not in rader


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
