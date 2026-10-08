"""Medlemmens roadmap (/svara/roadmap): samma urval som styrgruppens export,
medlemmens egna effektiva svar per rad, och ingenting av det förvaltarnas
roadmap bär på — redigering, dolda noder, exportlänkar, andras svar."""

from app import matomo
from tests.conftest import (
    ge_token,
    klient_fabrik,  # noqa: F401  (fixture)
    logga_in,
    satt_svar,
    seed_trad,
    skapa_medlem,
)


def _medlemsklient(fabrik, token):
    klient = fabrik()
    svar = klient.get(f"/svara/{token}", follow_redirects=False)
    assert svar.status_code == 303
    return klient


def test_roadmap_visar_avgangar_och_egna_svar(app_db, klient_fabrik):
    ids = seed_trad(app_db)
    a = skapa_medlem(app_db, "Uppsala universitet")
    b = skapa_medlem(app_db, "Umeå universitet")
    # A svarar go-live på Import (ärvs av WoS-importen); B svarar annat på WoS.
    satt_svar(app_db, a, ids["import"], "golive_krav")
    satt_svar(app_db, b, ids["wos"], "behovs_ej")
    app_db.commit()

    klient = _medlemsklient(klient_fabrik, ge_token(app_db, a))
    svar = klient.get("/svara/roadmap")
    assert svar.status_code == 200
    sida = svar.text
    # Avgångarna och raderna, med namn, typ och status.
    assert ">Medlem 1</h2>" in sida and ">senare</h2>" in sida
    assert "Registrera avhandling" in sida and "Import från Web of Science" in sida
    assert ">Planerad<" in sida
    # A:s eget direkta svar och det ärvda, märkt som ärvt.
    assert "Go-live" in sida
    assert "(ärvt)" in sida and "ärvt från Import" in sida
    # B:s svar syns inte — varken etikett, antal eller namn.
    assert "Behövs ej" not in sida
    assert "Umeå" not in sida
    # Obedömda bedömbara noder markeras; raderna länkar till bedömningen.
    assert "ej bedömd" in sida
    assert f'href="/svara#gren-{ids["registrera"]}"' in sida


def test_roadmap_doljer_dolda_grenar_och_forvaltarkontroller(app_db, klient_fabrik):
    ids = seed_trad(app_db)
    a = skapa_medlem(app_db, "Uppsala universitet")
    app_db.execute("UPDATE funktion SET synlig_externt = 0 WHERE id = ?", (ids["import"],))
    app_db.commit()

    klient = _medlemsklient(klient_fabrik, ge_token(app_db, a))
    sida = klient.get("/svara/roadmap?visa_krav=1").text
    # Hela den dolda grenen är borta, syskonen kvar.
    assert "Import från Web of Science" not in sida
    assert "Dubblettdetektering" not in sida
    assert "Registrera avhandling" in sida
    # Inget av förvaltarnas roadmap läcker in i medlemsvyn.
    for kontroll in ("Redigera roadmap", "greppyta", ">dold<", "Confluence",
                     "Markdown", "Ladda ner", "/roadmap/flytta", "/export/"):
        assert kontroll not in sida, kontroll
    # Flikraden finns och markerar roadmapen som aktiv.
    assert 'href="/svara"' in sida and 'href="/svara/roadmap"' in sida
    assert 'aria-current="page"' in sida


def test_roadmap_filter(app_db, klient_fabrik):
    ids = seed_trad(app_db)
    a = skapa_medlem(app_db, "Uppsala universitet")
    satt_svar(app_db, a, ids["wos"], "kan_vanta")
    app_db.commit()
    klient = _medlemsklient(klient_fabrik, ge_token(app_db, a))

    utan_krav = klient.get("/svara/roadmap").text
    assert "Dubblettdetektering" not in utan_krav          # krav döljs som standard
    med_krav = klient.get("/svara/roadmap?visa_krav=1").text
    assert "Dubblettdetektering" in med_krav
    utan_formagor = klient.get("/svara/roadmap?dolj_formagor=1").text
    assert "Publicering" not in utan_formagor and "Import från Web of Science" in utan_formagor
    utan_svar = klient.get("/svara/roadmap?dolj_svar=1").text
    assert "Kan vänta" not in utan_svar and "ej bedömd" not in utan_svar
    assert "Kan vänta" in med_krav


def test_roadmap_kraver_medlemssession(client, app_db, klient_fabrik):
    seed_trad(app_db)
    # Anonym: 403 med hänvisning till svarslänken, inte en inloggningsredirect.
    assert client.get("/svara/roadmap", follow_redirects=False).status_code == 403
    # Förvaltarsession (även admin) är inte en medlemssession.
    logga_in(client, app_db)
    assert client.get("/svara/roadmap", follow_redirects=False).status_code == 403
    # Och ordet "roadmap" tolkas aldrig som en ogiltig svarslänk (404).
    anonym = klient_fabrik()
    assert anonym.get("/svara/roadmap", follow_redirects=False).status_code == 403
    assert anonym.get("/svara/roadmapp", follow_redirects=False).status_code == 404


def test_arvt_fran_dold_nod_lacker_inte_namnet(app_db, klient_fabrik):
    """Medlemmen svarar på Import; Import döljs sedan av förvaltaren. Svaret
    ärvs fortfarande ned i grenen (bedomning_effektiv), men ingen rad eller
    tooltip får nämna den dolda noden. Invarianten bygger på att synlig_stig
    är transitiv — därav låsningen här, mot framtida ändringar i roadmap_data
    eller svarskarta."""
    ids = seed_trad(app_db)
    a = skapa_medlem(app_db, "Uppsala universitet")
    satt_svar(app_db, a, ids["import"], "golive_krav")
    # Dölj Import men inte dess barn — barnens synlig_stig blir ändå 0.
    app_db.execute("UPDATE funktion SET synlig_externt = 0 WHERE id = ?", (ids["import"],))
    app_db.commit()

    klient = _medlemsklient(klient_fabrik, ge_token(app_db, a))
    for qs in ("", "?visa_krav=1", "?dolj_formagor=1", "?visa_krav=1&dolj_formagor=1"):
        sida = klient.get(f"/svara/roadmap{qs}").text
        assert "Import" not in sida.replace("Import från", ""), qs   # inte ens i tooltip
        assert "Import från Web of Science" not in sida, qs           # hela grenen dold
        assert "Registrera avhandling" in sida, qs                    # syskonet kvar


def test_matomo_maskar_token_men_inte_roadmap():
    assert matomo.sanitize_path("/svara/abc123XYZ") == "/svara/_token_"
    assert matomo.sanitize_path("/svara/roadmap") == "/svara/roadmap"
    assert matomo.sanitize_path("/svara") == "/svara"
