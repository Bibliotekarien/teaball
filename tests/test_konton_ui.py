"""Kontohantering i gränssnittet: skapa med slumpat namn och lösenord, byta
roll, nytt lösenord, ta bort, spärrarna mot att låsa ute sig själv, samt byte
av eget lösenord på /losenord."""

import re

import pytest

from app.services import konton
from tests.conftest import csrf_fran, logga_in, sessionsinnehall, skapa_forvaltare

LOSENORD_I_RUTAN = re.compile(r'value="([^"]+)" data-markera aria-label="Lösenord"')


def _csrf_konton(client) -> str:
    return csrf_fran(client.get("/konton").text)


def _konto(app_db, namn):
    return app_db.execute(
        "SELECT id, roll FROM forvaltare WHERE anvandarnamn = ?", (namn,)
    ).fetchone()


def _logga_in_med(client, namn, losenord) -> int:
    token = csrf_fran(client.get("/login").text)
    return client.post("/login", data={"anvandarnamn": namn, "losenord": losenord,
                                       "csrf_token": token},
                       follow_redirects=False).status_code


def test_skapa_konto_med_slumpat_namn_och_losenord(client, klient_fabrik, app_db):
    logga_in(client, app_db)
    sida = client.get("/konton").text
    # Förslaget är två ord med bindestreck, redan ifyllt i formuläret.
    assert re.search(r'name="anvandarnamn" value="[a-z]+-[a-z]+"', sida)

    # The password is in the POST response itself — no redirect, no flash.
    svar = client.post("/konton", data={"anvandarnamn": "", "roll": "intern",
                                        "csrf_token": csrf_fran(sida)},
                       follow_redirects=False)
    assert svar.status_code == 200
    assert "Nytt konto" in svar.text
    losenord = LOSENORD_I_RUTAN.search(svar.text).group(1)
    assert len(losenord) >= 16
    # Never in the (signed but unencrypted) session cookie. The first check
    # proves the decoding works, so the second cannot pass vacuously.
    assert "forvaltare_id" in sessionsinnehall(client)
    assert losenord not in sessionsinnehall(client)
    skapat = app_db.execute(
        "SELECT anvandarnamn, roll FROM forvaltare WHERE anvandarnamn != 'anna'"
    ).fetchone()
    assert re.fullmatch(r"[a-z]+-[a-z]+", skapat["anvandarnamn"])
    assert skapat["roll"] == "intern"

    # Lösenordet visas bara en gång …
    assert "Nytt konto" not in client.get("/konton").text
    # … och fungerar för inloggning.
    assert _logga_in_med(klient_fabrik(), skapat["anvandarnamn"], losenord) == 303


def test_skapa_konto_med_eget_namn_och_fel(client, app_db):
    logga_in(client, app_db)
    token = _csrf_konton(client)
    svar = client.post("/konton", data={"anvandarnamn": "styrgrupp-sö", "roll": "extern",
                                        "csrf_token": token}, follow_redirects=False)
    assert svar.status_code == 200
    assert _konto(app_db, "styrgrupp-sö")["roll"] == "extern"

    # Dubblett → 400 med feltext, inget nytt konto.
    svar = client.post("/konton", data={"anvandarnamn": "styrgrupp-sö", "roll": "extern",
                                        "csrf_token": token})
    assert svar.status_code == 400 and "finns redan" in svar.text
    # Otillåtna tecken → 400, och det inskrivna står kvar i fältet.
    svar = client.post("/konton", data={"anvandarnamn": "a b/c", "roll": "intern",
                                        "csrf_token": token})
    assert svar.status_code == 400 and 'value="a b/c"' in svar.text
    assert app_db.execute("SELECT COUNT(*) FROM forvaltare").fetchone()[0] == 2


def test_byt_roll_slar_igenom_direkt(client, klient_fabrik, app_db):
    logga_in(client, app_db)
    berit = klient_fabrik()
    logga_in(berit, app_db, namn="berit", roll="intern")
    assert berit.get("/analys").status_code == 200

    svar = client.post(f"/konton/{_konto(app_db, 'berit')['id']}/roll",
                       data={"roll": "extern", "csrf_token": _csrf_konton(client)},
                       follow_redirects=False)
    assert svar.status_code == 303
    # Ingen omloggning: rollen läses per request.
    assert berit.get("/analys", follow_redirects=False).status_code == 403


def test_kan_inte_andra_sitt_eget_konto(client, app_db):
    logga_in(client, app_db)
    skapa_forvaltare(app_db, "ines", roll="admin")   # så att "sista admin" inte stör
    anna = _konto(app_db, "anna")["id"]
    token = _csrf_konton(client)
    for adress, data in ((f"/konton/{anna}/roll", {"roll": "intern"}),
                         (f"/konton/{anna}/losenord", {}),
                         (f"/konton/{anna}/ta-bort", {})):
        svar = client.post(adress, data={**data, "csrf_token": token}, follow_redirects=False)
        assert svar.status_code == 303, adress
        assert "eget konto" in client.get("/konton").text, adress
    assert _konto(app_db, "anna")["roll"] == "admin"
    # Den egna raden har ingen rollväljare och inga farliga knappar, bara länken
    # till /losenord.
    sida = client.get("/konton").text
    assert f'action="/konton/{anna}/roll"' not in sida
    assert f'href="/konton/{anna}/ta-bort"' not in sida
    assert 'href="/losenord"' in sida


def test_sista_admin_skyddas(client, app_db):
    logga_in(client, app_db)                         # anna, admin
    skapa_forvaltare(app_db, "ines", roll="admin")
    anna = _konto(app_db, "anna")["id"]
    ines = _konto(app_db, "ines")["id"]

    # Två admin: anna får nedgradera ines via gränssnittet.
    client.post(f"/konton/{ines}/roll", data={"roll": "intern",
                                              "csrf_token": _csrf_konton(client)})
    assert _konto(app_db, "ines")["roll"] == "intern"

    # Nu är anna ensam admin. Spärren ligger i tjänsten (routern når den aldrig
    # för det egna kontot, eftersom sig-själv-spärren slår först).
    with pytest.raises(konton.Kontofel, match="sista administratören"):
        konton.byt_roll(app_db, anna, "intern", aktor_id=ines)
    with pytest.raises(konton.Kontofel, match="sista administratören"):
        konton.ta_bort(app_db, anna, aktor_id=ines)
    assert _konto(app_db, "anna")["roll"] == "admin"
    # Att göra någon annan till admin går alltid.
    konton.byt_roll(app_db, ines, "admin", aktor_id=anna)
    assert _konto(app_db, "ines")["roll"] == "admin"


def test_nytt_losenord_loggar_ut_kontot(client, klient_fabrik, app_db):
    logga_in(client, app_db)
    berit = klient_fabrik()
    logga_in(berit, app_db, namn="berit", roll="intern")
    assert berit.get("/trad").status_code == 200

    svar = client.post(f"/konton/{_konto(app_db, 'berit')['id']}/losenord",
                       data={"csrf_token": _csrf_konton(client)}, follow_redirects=False)
    assert svar.status_code == 200
    assert "Nytt lösenord för" in svar.text and "berit" in svar.text
    losenord = LOSENORD_I_RUTAN.search(svar.text).group(1)
    assert losenord not in sessionsinnehall(client)
    assert "Nytt lösenord för" not in client.get("/konton").text   # shown once
    # Berits gamla session är död …
    assert berit.get("/trad", follow_redirects=False).status_code == 303
    # … det gamla lösenordet nekas och det nya fungerar.
    assert _logga_in_med(berit, "berit", "hemligt-losen") == 401
    assert _logga_in_med(berit, "berit", losenord) == 303


def test_ta_bort_konto(client, klient_fabrik, app_db):
    logga_in(client, app_db)
    berit = klient_fabrik()
    logga_in(berit, app_db, namn="berit", roll="extern")
    berit_id = _konto(app_db, "berit")["id"]

    bekrafta = client.get(f"/konton/{berit_id}/ta-bort")
    assert bekrafta.status_code == 200 and "berit" in bekrafta.text
    svar = client.post(f"/konton/{berit_id}/ta-bort",
                       data={"csrf_token": _csrf_konton(client)}, follow_redirects=False)
    assert svar.status_code == 303
    assert _konto(app_db, "berit") is None
    assert berit.get("/trad", follow_redirects=False).status_code == 303
    # Bekräftelsesidan för ett borttaget konto skickar bara tillbaka.
    assert client.get(f"/konton/{berit_id}/ta-bort", follow_redirects=False).status_code == 303


def test_kontohantering_kraver_admin(client, app_db):
    skapa_forvaltare(app_db, "mål", roll="extern")
    mal = _konto(app_db, "mål")["id"]
    logga_in(client, app_db, namn="ines", roll="intern")
    token = csrf_fran(client.get("/trad").text)
    for adress, data in (("/konton", {"anvandarnamn": "", "roll": "intern"}),
                         (f"/konton/{mal}/roll", {"roll": "admin"}),
                         (f"/konton/{mal}/losenord", {}),
                         (f"/konton/{mal}/ta-bort", {})):
        svar = client.post(adress, data={**data, "csrf_token": token}, follow_redirects=False)
        assert svar.status_code == 403, adress
    assert client.get(f"/konton/{mal}/ta-bort", follow_redirects=False).status_code == 403
    assert _konto(app_db, "mål")["roll"] == "extern"
    assert app_db.execute("SELECT COUNT(*) FROM forvaltare").fetchone()[0] == 2


def test_byt_eget_losenord(client, klient_fabrik, app_db):
    logga_in(client, app_db, namn="elis", roll="extern")   # alla roller får byta
    annan_flik = klient_fabrik()
    logga_in(annan_flik, app_db, namn="elis", roll="extern")
    assert 'href="/losenord"' in client.get("/trad").text

    sida = client.get("/losenord")
    assert sida.status_code == 200
    token = csrf_fran(sida.text)

    # Fel nuvarande, för kort nytt, olika upprepning → 400 och oförändrat.
    for data in ({"nuvarande": "fel", "nytt": "nytt-losen-1", "upprepat": "nytt-losen-1"},
                 {"nuvarande": "hemligt-losen", "nytt": "kort", "upprepat": "kort"},
                 {"nuvarande": "hemligt-losen", "nytt": "nytt-losen-1", "upprepat": "annat-1"}):
        assert client.post("/losenord", data={**data, "csrf_token": token}).status_code == 400
    assert annan_flik.get("/trad").status_code == 200

    svar = client.post("/losenord", data={"nuvarande": "hemligt-losen", "nytt": "nytt-losen-1",
                                          "upprepat": "nytt-losen-1", "csrf_token": token})
    assert svar.status_code == 200 and "Lösenordet är bytt" in svar.text
    # Den egna sessionen överlever; den andra fliken loggas ut.
    assert client.get("/trad").status_code == 200
    assert annan_flik.get("/trad", follow_redirects=False).status_code == 303
    assert _logga_in_med(annan_flik, "elis", "hemligt-losen") == 401
    assert _logga_in_med(annan_flik, "elis", "nytt-losen-1") == 303


def test_losenord_kraver_inloggning(client, app_db):
    assert client.get("/losenord", follow_redirects=False).status_code == 303


def test_slumpat_anvandarnamn_undviker_kollision(app_db, monkeypatch):
    monkeypatch.setattr(konton, "ADJEKTIV", ("stilla",))
    monkeypatch.setattr(konton, "SUBSTANTIV", ("lax", "ek"))
    skapa_forvaltare(app_db, "stilla-lax", roll="intern")
    assert konton.slumpa_anvandarnamn(app_db) == "stilla-ek"
    skapa_forvaltare(app_db, "stilla-ek", roll="intern")
    # Båda upptagna → suffix i stället för evig loop.
    assert re.fullmatch(r"stilla-(lax|ek)-\d{3}", konton.slumpa_anvandarnamn(app_db))


# --- Rättningar efter säkerhetsgranskningen av PR #38 -------------------------

def test_sista_admin_skyddas_atomiskt_i_skrivsatsen(app_db, monkeypatch):
    """Räkningen före skrivsatsen ligger utanför transaktionen; villkoret i
    själva DELETE/UPDATE är det som gäller. Stäng av förkontrollen och visa
    att skrivsatsen ändå vägrar."""
    skapa_forvaltare(app_db, "anna", roll="admin")
    skapa_forvaltare(app_db, "ines", roll="intern")
    anna = _konto(app_db, "anna")["id"]
    ines = _konto(app_db, "ines")["id"]
    monkeypatch.setattr(konton, "_inte_sista_admin", lambda *a, **k: None)

    with pytest.raises(konton.Kontofel, match="sista administratören"):
        konton.ta_bort(app_db, anna, aktor_id=ines)
    with pytest.raises(konton.Kontofel, match="sista administratören"):
        konton.byt_roll(app_db, anna, "intern", aktor_id=ines)
    assert _konto(app_db, "anna")["roll"] == "admin"
    # Med två admin går det igenom.
    skapa_forvaltare(app_db, "bo", roll="admin")
    konton.ta_bort(app_db, anna, aktor_id=ines)
    assert _konto(app_db, "anna") is None


def test_dubblett_i_racet_blir_kontofel_inte_500(app_db, monkeypatch):
    skapa_forvaltare(app_db, "anna", roll="admin")
    monkeypatch.setattr(konton, "_finns_namn", lambda conn, namn: False)
    with pytest.raises(konton.Kontofel, match="finns redan"):
        konton.skapa(app_db, "anna", "intern")


def test_anvandarnamn_tillater_svenska_men_inte_homoglyfer():
    assert konton.giltigt_anvandarnamn("styrgrupp-sö")
    assert konton.giltigt_anvandarnamn("kb_titt.2")
    assert not konton.giltigt_anvandarnamn("аnna")      # kyrilliskt а
    assert not konton.giltigt_anvandarnamn("a")
    assert not konton.giltigt_anvandarnamn("anna\n")


def test_losenord_throttlas_efter_upprepade_fel(client, app_db):
    from app.routers import inloggning
    inloggning._misslyckanden.clear()
    logga_in(client, app_db)
    token = csrf_fran(client.get("/losenord").text)
    fel = {"nuvarande": "fel", "nytt": "nytt-losen-1", "upprepat": "nytt-losen-1",
           "csrf_token": token}
    for _ in range(inloggning.MAX_FORSOK):
        assert client.post("/losenord", data=fel).status_code == 400
    # Spärrad — även rätt lösenord nekas nu, och inget byts.
    ratt = {**fel, "nuvarande": "hemligt-losen"}
    assert client.post("/losenord", data=ratt).status_code == 429
    # Nyckeln delas med /login, så även inloggning är spärrad under tiden.
    assert _logga_in_med(client, "anna", "hemligt-losen") == 429
    inloggning._misslyckanden.clear()
    assert _logga_in_med(client, "anna", "hemligt-losen") == 303   # gamla gäller
    token = csrf_fran(client.get("/losenord").text)
    ratt["csrf_token"] = token
    # Formfel (olika upprepning) räknas inte som gissning.
    for _ in range(inloggning.MAX_FORSOK + 1):
        svar = client.post("/losenord", data={**ratt, "upprepat": "annat-1"})
        assert svar.status_code == 400
    assert client.post("/losenord", data=ratt).status_code == 200
    inloggning._misslyckanden.clear()
