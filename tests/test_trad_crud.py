"""End-to-end tests for the requirements tree (spec 5.1): CRUD, the three
move/reorder endpoints (shared by no-JS forms and SortableJS), the Swedish
cycle error in HTML (§9.1), delete confirmation impact (T2), filters (T4),
transitive visibility (T5/D4) and CSRF enforcement."""

from app.web import STATUS
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
    svar = client.post("/trad/nod",
                       data={"namn": "X", "typ": "krav", "status": "planerad", "fas": "nu"})
    assert svar.status_code == 400


def test_skapa_och_redigera_nod(client, app_db):
    logga_in(client, app_db)
    token = _token(client)
    svar = client.post(
        "/trad/nod",
        data={"namn": "Publicering", "typ": "förmåga", "status": "driftsatt",
              "fas": "Medlem 1", "synlig_externt": "1", "csrf_token": token},
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


def test_namnkoll_varnar_for_dubblett(client, app_db):
    logga_in(client, app_db)
    token = _token(client)
    client.post("/trad/nod", data={"namn": "Återläsning", "typ": "funktion",
                                   "status": "utreds", "csrf_token": token})

    # Träff oavsett skiftläge och kringliggande blanksteg — även Å/Ä/Ö, som
    # SQLite:s NOCASE inte viker (därför casefold i Python).
    svar = client.get("/trad/nod/namnkoll", params={"namn": "  återläsning "})
    assert "finns redan" in svar.text

    svar = client.get("/trad/nod/namnkoll", params={"namn": "Öppen data"})
    assert "finns redan" not in svar.text

    # Tomt namn ska inte larma.
    svar = client.get("/trad/nod/namnkoll", params={"namn": "   "})
    assert "finns redan" not in svar.text


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


def test_ny_nod_hamnar_forst_och_formularet_aterstalls(client, app_db):
    ids = seed_trad(app_db)
    logga_in(client, app_db)
    token = _token(client)

    # htmx create under Import: lands FIRST among the siblings ...
    svar = client.post(
        "/trad/nod",
        data={"namn": "Ny under Import", "foralder_id": str(ids["import"]),
              "typ": "funktion", "status": "utreds"},
        headers={"HX-Request": "true", "X-CSRF-Token": token},
    )
    assert svar.status_code == 200
    ordning = [r["namn"] for r in app_db.execute(
        "SELECT namn FROM funktion WHERE foralder_id = ? ORDER BY sortering, id",
        (ids["import"],))]
    assert ordning[0] == "Ny under Import"
    # ... and the response swaps in a fresh form out-of-band: same parent
    # preselected, name field empty.
    assert 'id="ny-nod-plats" hx-swap-oob="innerHTML"' in svar.text
    assert f'<option value="{ids["import"]}" selected>' in svar.text
    assert 'value="Ny under Import"' not in svar.text

    # Parentless create lands at the top of the root level.
    svar = client.post(
        "/trad/nod",
        data={"namn": "Ny rot", "typ": "förmåga", "status": "planerad",
              "fas": "Medlem 1", "csrf_token": token},
        follow_redirects=False,
    )
    assert svar.status_code == 303
    rotter = [r["namn"] for r in app_db.execute(
        "SELECT namn FROM funktion WHERE foralder_id IS NULL ORDER BY sortering, id")]
    assert rotter[0] == "Ny rot"


def test_filter_overlever_htmx_uppdatering(client, app_db):
    ids = seed_trad(app_db)
    logga_in(client, app_db)
    token = _token(client)

    # Aktivera ett filter (samma htmx-GET som filterformuläret gör) ...
    client.get("/trad", params={"q": "dubblett"}, headers={"HX-Request": "true"})

    # ... och redigera en nod. Swappen ska fortfarande vara filtrerad —
    # filterformuläret står kvar utanför #trad-rot och måste matcha trädet.
    svar = client.post(
        f"/trad/nod/{ids['dubblett']}",
        data={"namn": "Dubblettdetektering", "typ": "krav", "status": "utreds",
              "synlig_externt": "1"},
        headers={"HX-Request": "true", "X-CSRF-Token": token},
    )
    assert svar.status_code == 200
    assert "Dubblettdetektering" in svar.text
    assert "Registrera avhandling" not in svar.text

    # En ren sidladdning utan query nollställer det sparade filtret.
    client.get("/trad")
    svar = client.post(
        f"/trad/nod/{ids['dubblett']}/ordna",
        data={"riktning": "upp", "csrf_token": token},
        headers={"HX-Request": "true", "X-CSRF-Token": token},
    )
    assert "Registrera avhandling" in svar.text


def test_utgar_stryks_over_i_tradet(client, app_db):
    ids = seed_trad(app_db)
    app_db.execute("UPDATE funktion SET status = 'utgår' WHERE id = ?", (ids["registrera"],))
    app_db.commit()
    logga_in(client, app_db)
    sida = client.get("/trad").text
    assert 'line-through text-stone-400" title="Registrera avhandling"' in sida
    assert 'line-through text-stone-400" title="Publicering"' not in sida


def test_filter_med_flera_val(client, app_db):
    seed_trad(app_db)
    logga_in(client, app_db)

    # OR within a filter: driftsatt + idé at once.
    sida = client.get("/trad", params={"status": ["driftsatt", "idé"]}).text
    assert "Dubblettdetektering" in sida                 # idé
    assert "Export &amp; spridning" in sida              # driftsatt
    # Registrera avhandling is planerad and not an ancestor of any match.
    assert "Registrera avhandling" not in sida
    # Its checkboxes come back checked.
    assert sida.count('name="status"') == 5
    assert 'value="driftsatt" checked' in sida and 'value="idé" checked' in sida

    # AND between filters: typ förmåga+krav, status idé → only Dubblett's chain.
    sida = client.get("/trad", params={"typ": ["förmåga", "krav"], "status": ["idé"]}).text
    assert "Dubblettdetektering" in sida
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


def test_lankar_och_detaljerad_vy(client, app_db):
    logga_in(client, app_db)
    token = _token(client)
    svar = client.post(
        "/trad/nod",
        data={"namn": "ORCID-validering", "typ": "krav", "status": "utreds",
              "beskrivning": "Validering vid inmatning.",
              "lank_dokumentation": "https://wiki.example/orcid",
              "lank_jira": "https://jira.example/DIVA-123",
              "csrf_token": token},
        follow_redirects=False,
    )
    assert svar.status_code == 303

    # Compact view (the default) hides links and description in the tree.
    sida = client.get("/trad").text
    assert "https://jira.example/DIVA-123" not in sida
    assert "Detaljerad vy" in sida
    assert "Vad betyder typerna och statusarna?" in sida     # legend
    assert "Finns i DiVA Classic" in sida                    # utreds explained

    # The detailed view shows both, and sticks in the session.
    sida = client.get("/trad", params={"vy": "detaljerad"}).text
    assert 'href="https://jira.example/DIVA-123"' in sida
    assert "Jira&nbsp;↗" in sida and "Dokumentation&nbsp;↗" in sida
    assert "Validering vid inmatning." in sida
    assert "Kompakt vy" in sida
    assert 'href="https://wiki.example/orcid"' in client.get("/trad").text


def test_ny_nod_har_forval_funktion_utreds(client, app_db):
    ids = seed_trad(app_db)
    logga_in(client, app_db)
    form = client.get("/trad/nod/ny").text
    assert '<option value="funktion" selected>funktion</option>' in form
    assert '<option value="utreds" selected>utreds</option>' in form
    # Editing keeps the node's own values.
    form = client.get(f"/trad/nod/{ids['publicering']}/redigera").text
    assert '<option value="förmåga" selected>förmåga</option>' in form
    assert '<option value="driftsatt" selected>driftsatt</option>' in form


def test_typen_krav_visas_som_behov(client, app_db):
    # UI-termen är "behov"; värdet i formulär, filter och databas är kvar krav.
    seed_trad(app_db)
    logga_in(client, app_db)
    form = client.get("/trad/nod/ny").text
    assert '<option value="krav" >behov</option>' in form
    sida = client.get("/trad").text
    assert 'name="typ" value="krav" >behov</label>' in sida
    assert ">behov</span>" in sida
    assert ">krav<" not in sida


def test_ogiltig_lank_avvisas(client, app_db):
    logga_in(client, app_db)
    token = _token(client)
    svar = client.post(
        "/trad/nod",
        data={"namn": "X", "typ": "krav", "status": "planerad",
              "lank_jira": "javascript:alert(1)", "csrf_token": token},
    )
    assert svar.status_code == 400
    assert "http://" in svar.text
    assert app_db.execute("SELECT COUNT(*) FROM funktion").fetchone()[0] == 0


def test_planerad_utan_avgang_avvisas_i_ui(client, app_db):
    """Avgångstriggern via routrarna: svenskt inline-fel, aldrig 500."""
    ids = seed_trad(app_db)
    logga_in(client, app_db)
    token = _token(client)

    # Skapa utan avgång: helsida ⇒ 400 + feltext, inget skrivs.
    svar = client.post(
        "/trad/nod",
        data={"namn": "Ny planerad", "typ": "funktion", "status": "planerad",
              "csrf_token": token},
    )
    assert svar.status_code == 400
    assert "måste ha en avgång" in svar.text
    assert app_db.execute(
        "SELECT COUNT(*) FROM funktion WHERE namn = 'Ny planerad'"
    ).fetchone()[0] == 0

    # htmx ⇒ 200 (htmx swappar inte icke-2xx) med felbanner i trädswappen.
    svar = client.post(
        "/trad/nod",
        data={"namn": "Ny planerad", "typ": "funktion", "status": "planerad"},
        headers={"HX-Request": "true", "X-CSRF-Token": token},
    )
    assert svar.status_code == 200
    assert 'id="trad-fel"' in svar.text and "måste ha en avgång" in svar.text

    # Redigering som byter status till planerad utan avgång avvisas orört.
    svar = client.post(
        f"/trad/nod/{ids['dubblett']}",
        data={"namn": "Dubblettdetektering", "typ": "krav", "status": "planerad",
              "fas": "", "csrf_token": token},
    )
    assert svar.status_code == 400 and "måste ha en avgång" in svar.text
    rad = app_db.execute("SELECT status, fas FROM funktion WHERE id = ?",
                         (ids["dubblett"],)).fetchone()
    assert rad["status"] == "idé" and rad["fas"] == "senare"


def test_funktion_trad_visningsordning(app_db):
    seed_trad(app_db)
    namn = [r["namn"] for r in app_db.execute("SELECT namn FROM funktion_trad ORDER BY vag")]
    assert namn == [
        "Publicering", "Registrera avhandling", "Import",
        "Import från Web of Science", "Dubblettdetektering",
        "Export & spridning",
    ]


def test_statusfordelning_raknar_grenens_lov(trad, conn):
    from app.services.trad import hamta_trad, hitta_nod

    rotter = hamta_trad(conn)
    publicering = hitta_nod(rotter, trad["publicering"])
    # Bara löven räknas (Registrera avhandling + Dubblettdetektering): noder
    # med undernoder är struktur, och nodens egen status ingår aldrig.
    assert publicering["status_under"] == {"planerad": 1, "idé": 1}
    assert publicering["antal_under"] == 2
    assert hitta_nod(rotter, trad["import"])["status_under"] == {"idé": 1}
    assert hitta_nod(rotter, trad["export"])["antal_under"] == 0

    # Ett statusfilter beskär trädet men inte fördelningen: stapeln ska visa
    # grenens verkliga läge, inte det filtrerade urvalet.
    rotter = hamta_trad(conn, status=["idé"])
    assert hitta_nod(rotter, trad["publicering"])["antal_under"] == 2

    # Medlemsvyn räknar däremot bara synliga noder (dold gren = dold undergren).
    conn.execute("UPDATE funktion SET synlig_externt = 0 WHERE id = ?", (trad["import"],))
    rotter = hamta_trad(conn, endast_synliga=True)
    assert hitta_nod(rotter, trad["publicering"])["status_under"] == {"planerad": 1}


def test_grenniva_visar_fordelning_i_stallet_for_status(client, app_db):
    seed_trad(app_db)
    logga_in(client, app_db)
    sida = client.get("/trad").text

    # Nivå 0–1 med undergren: driftsatta/grenens löv plus fördelningsstapeln.
    assert "0/2" in sida and "0/1" in sida
    assert sida.count('role="img"') == 2  # Publicering + Import; lövnoder får ingen
    assert 'title="Planerad: 1"' in sida and 'style="flex-grow: 1"' in sida

    # Inget status-piller på nivå 0–1 (statusvärdet finns kvar i datat):
    # driftsatt bärs bara av rotnoderna, så pillrets tooltip ska inte finnas.
    # (Beskrivningen som löptext i legenden räknas inte — bara title-attributet.)
    assert f'title="{STATUS["driftsatt"]["beskrivning"]}"' not in sida
    # På djup 2+ visas pillret som förut (wos planerad, dubblett idé).
    assert sida.count(f'title="{STATUS["planerad"]["beskrivning"]}"') == 1
    assert sida.count(f'title="{STATUS["idé"]["beskrivning"]}"') == 1


def test_sidomeny_lankar_till_de_tva_oversta_nivaerna(client, app_db):
    """Sidomenyn bredvid trädet: rötter + deras barn som ankarlänkar till
    raderna, inget djupare. Den ligger i #trad-rot så filtrering och
    htmx-swappar bygger om den — en bortfiltrerad gren har ingen länk."""
    ids = seed_trad(app_db)
    logga_in(client, app_db)
    sida = client.get("/trad").text
    start = sida.index("data-tradmeny")
    meny = sida[start:sida.index("</nav>", start)]

    for nyckel in ("publicering", "registrera", "import", "export"):
        assert f'href="#rad-{ids[nyckel]}"' in meny
    for nyckel in ("wos", "dubblett"):  # djup 2+ hör inte hemma i menyn
        assert f'href="#rad-{ids[nyckel]}"' not in meny
    # Alla länkmål finns som rader i trädet.
    for nyckel in ("publicering", "registrera", "import", "export"):
        assert f'id="rad-{ids[nyckel]}"' in sida

    # htmx-partialen (filtrering) bär samma meny, byggd från det filtrerade trädet.
    partial = client.get("/trad?q=Export", headers={"HX-Request": "true"}).text
    assert "data-tradmeny" in partial
    assert f'href="#rad-{ids["export"]}"' in partial
    assert f'href="#rad-{ids["publicering"]}"' not in partial

    # Inga noder att visa ⇒ ingen meny alls.
    assert "data-tradmeny" not in client.get("/trad?q=finnsinte").text
