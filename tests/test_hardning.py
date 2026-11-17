"""Regression tests for the hardening added after the security review:
login throttling, session invalidation on password change, the token-link
session-switch confirmation, robust 404s instead of 500s, and /health."""

from tests.conftest import (
    csrf_fran,
    ge_token,
    huvuddel,
    logga_in,
    seed_trad,
    skapa_forvaltare,
    skapa_medlem,
)


def test_health(client):
    svar = client.get("/health")
    assert svar.status_code == 200
    assert svar.json() == {"status": "ok"}


def test_login_sparras_efter_upprepade_misslyckanden(client, app_db):
    from app.routers import inloggning

    inloggning._misslyckanden.clear()
    skapa_forvaltare(app_db, "anna", "hemligt-losen")
    token = csrf_fran(client.get("/login").text)
    for _ in range(5):
        svar = client.post("/login", data={"anvandarnamn": "anna", "losenord": "fel",
                                           "csrf_token": token})
        assert svar.status_code == 401
    svar = client.post("/login", data={"anvandarnamn": "anna", "losenord": "hemligt-losen",
                                       "csrf_token": token})
    assert svar.status_code == 429
    assert "För många misslyckade försök" in svar.text
    inloggning._misslyckanden.clear()  # don't leak state into other tests


def test_sparren_kortar_langa_anvandarnamn(client, app_db):
    """A megabyte username must not become a megabyte key — and cutting it
    must not let the attempts escape the lockout."""
    from app.routers import inloggning

    inloggning._misslyckanden.clear()
    token = csrf_fran(client.get("/login").text)
    langt = "a" * 100_000
    for _ in range(inloggning.MAX_FORSOK):
        client.post("/login", data={"anvandarnamn": langt, "losenord": "fel",
                                    "csrf_token": token})
    ((_, namn),) = inloggning._misslyckanden
    assert len(namn) == inloggning.MAX_NAMNLANGD
    svar = client.post("/login", data={"anvandarnamn": langt + "b", "losenord": "fel",
                                       "csrf_token": token})
    assert svar.status_code == 429
    inloggning._misslyckanden.clear()


def test_sparren_vaxer_inte_utan_grans(monkeypatch):
    """Unique usernames one after another: the dict stays under MAX_POSTER,
    expired entries go first, and a fresh lockout survives the pruning."""
    from app.routers import inloggning

    inloggning._misslyckanden.clear()
    monkeypatch.setattr(inloggning, "MAX_POSTER", 50)
    nu = [1000.0]
    monkeypatch.setattr(inloggning.time, "monotonic", lambda: nu[0])

    for i in range(30):
        inloggning._registrera_misslyckande(("1.2.3.4", f"gammal{i}"))
    nu[0] += inloggning.SPARR_SEKUNDER  # the old ones have expired
    for _ in range(inloggning.MAX_FORSOK):
        inloggning._registrera_misslyckande(("1.2.3.4", "anna"))
    for i in range(40):
        inloggning._registrera_misslyckande(("5.6.7.8", f"ny{i}"))

    assert len(inloggning._misslyckanden) <= 50
    assert not any(n.startswith("gammal") for _, n in inloggning._misslyckanden)
    assert inloggning._sparrad(("1.2.3.4", "anna"))

    for i in range(200):  # sustained flood: the oldest go, the size holds
        inloggning._registrera_misslyckande(("5.6.7.8", f"flod{i}"))
    assert len(inloggning._misslyckanden) <= 50
    inloggning._misslyckanden.clear()


def test_okant_anvandarnamn_hashar_anda(client, app_db, monkeypatch):
    """An unknown username must cost an argon2 hash like a wrong password
    does, or the response time reveals which accounts exist. Same 401 and
    same message as a wrong password, too."""
    from app.auth import password
    from app.routers import inloggning

    inloggning._misslyckanden.clear()
    skapa_forvaltare(app_db, "anna", "hemligt-losen")
    hashade = []
    riktig = password._hasher

    class RaknandeHasher:  # PasswordHasher has __slots__, so wrap it instead
        def hash(self, losen):
            hashade.append(losen)
            return riktig.hash(losen)

        def verify(self, *args):
            return riktig.verify(*args)

    monkeypatch.setattr(password, "_hasher", RaknandeHasher())
    token = csrf_fran(client.get("/login").text)

    okand = client.post("/login", data={"anvandarnamn": "finns-inte", "losenord": "x",
                                        "csrf_token": token})
    fel_losen = client.post("/login", data={"anvandarnamn": "anna", "losenord": "x",
                                            "csrf_token": token})

    assert hashade == ["x"]
    assert okand.status_code == fel_losen.status_code == 401
    assert huvuddel(okand.text) == huvuddel(fel_losen.text)
    inloggning._misslyckanden.clear()


def test_losenordsbyte_dodar_sessionen(client, app_db):
    from app.auth.password import hash_losen

    logga_in(client, app_db)
    assert client.get("/trad").status_code == 200
    app_db.execute("UPDATE forvaltare SET losen_hash = ? WHERE anvandarnamn = 'anna'",
                   (hash_losen("nytt-losen-123"),))
    app_db.commit()
    svar = client.get("/trad", follow_redirects=False)
    assert svar.status_code == 303 and svar.headers["location"] == "/login"


def test_htmx_far_hx_redirect_vid_utloggad(client, app_db):
    seed_trad(app_db)
    svar = client.get("/trad", headers={"HX-Request": "true"}, follow_redirects=False)
    assert svar.status_code == 401
    assert svar.headers["hx-redirect"] == "/login"


def test_inloggningen_hanvisar_medlemmar_till_lanken(client, app_db):
    """A member whose session expired lands on /login without a password;
    the page must tell them to open their personal link instead (#95)."""
    sida = client.get("/login").text
    assert "personliga svarslänk" in sida
    assert "inget lösenord" in sida
    assert "Hittar du inte länken?" in sida


def test_tokenlank_med_aktiv_session_kraver_bekraftelse(client, app_db):
    """A GET with a valid token must not silently replace an existing session
    (login CSRF). The confirmation POST performs the switch."""
    medlem = skapa_medlem(app_db, "Uppsala universitet")
    ratoken = ge_token(app_db, medlem)
    logga_in(client, app_db)

    svar = client.get(f"/svara/{ratoken}", follow_redirects=False)
    assert svar.status_code == 200
    assert "Fortsätt som Uppsala universitet" in svar.text
    # The admin session is untouched until confirmed.
    assert client.get("/trad").status_code == 200

    svar = client.post("/svara/vaxla",
                       data={"token": ratoken, "csrf_token": csrf_fran(svar.text)},
                       follow_redirects=False)
    assert svar.status_code == 303 and svar.headers["location"] == "/svara"
    assert client.get("/svara").status_code == 200


def test_sanitize_referrer_maskar_token():
    from app.matomo import sanitize_referrer

    # The raw token in a same-origin referrer is masked, host/query kept.
    assert sanitize_referrer("https://teaball.bibliotekarien.se/svara/HEMLIG?x=1") == (
        "https://teaball.bibliotekarien.se/svara/_token_?x=1")
    # Other paths and empty referrers pass through untouched.
    assert sanitize_referrer("https://teaball.bibliotekarien.se/trad") == (
        "https://teaball.bibliotekarien.se/trad")
    assert sanitize_referrer("") == ""


def test_vaxla_sidan_laker_inte_token_i_referer(client, app_db):
    """The token URL's only 200-page must not let the raw token leave via the
    Referer header on a later click."""
    medlem = skapa_medlem(app_db, "Uppsala universitet")
    ratoken = ge_token(app_db, medlem)
    logga_in(client, app_db)

    svar = client.get(f"/svara/{ratoken}", follow_redirects=False)
    assert svar.status_code == 200
    assert svar.headers["referrer-policy"] == "no-referrer"


def test_404_i_stallet_for_500(client, app_db):
    seed_trad(app_db)
    logga_in(client, app_db)
    assert client.get("/trad/nod/999999/redigera").status_code == 404
    assert client.get("/trad/nod/999999/ta-bort").status_code == 404
    assert client.get("/bedomning", params={"medlem_id": "abc"}).status_code == 200
    assert client.get("/analys/medlemmar", params={"medlem_id": "abc"}).status_code == 200
    token = csrf_fran(client.get("/trad").text)
    svar = client.post("/bedomning/999999/1/svar",
                       data={"svar": "golive_krav", "csrf_token": token})
    assert svar.status_code == 404


def test_sakerhetsheaders(client, app_db):
    logga_in(client, app_db)
    huvuden = client.get("/trad").headers
    assert "'unsafe-inline'" not in huvuden["content-security-policy"].split("style-src")[0]
    assert huvuden["cache-control"] == "no-store"
    assert huvuden["x-frame-options"] == "DENY"
    statiska = client.get("/static/css/app.css").headers
    assert statiska.get("cache-control") != "no-store"


def test_statiska_lankar_bar_innehallshash(client, app_db):
    """Static assets may cache freely, so every link to them must change when
    the file does — otherwise a deploy renders new templates with a stale
    app.css from the browser cache (the oversized header logo, Oct 2026)."""
    import re

    from app.web import _statisk_version, static_url

    sida = client.get("/login").text
    lankar = re.findall(r'(?:href|src)="(/static/[^"]+)"', sida)
    assert lankar, "inga statiska länkar på inloggningssidan"
    for lank in lankar:
        assert re.search(r"\?v=[0-9a-f]{10}$", lank), lank
        assert client.get(lank).status_code == 200
    assert static_url("css/app.css") in lankar
    assert _statisk_version("css/app.css") != _statisk_version("js/app.js")
    assert _statisk_version("finns-inte.css") == "0"
