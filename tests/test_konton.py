"""The admin accounts view (/konton) and the last-activity stamps: password
login stamps forvaltare.senast_inloggad, member link login stamps
medlem.senast_anvand — a single overwritten timestamp each (data minimization),
visible to the admin role only."""

from tests.conftest import (
    csrf_fran,
    ge_token,
    logga_in,
    skapa_forvaltare,
    skapa_medlem,
)


def _csrf(client) -> str:
    return csrf_fran(client.get("/login").text)


def test_login_stamplar_senast_inloggad(client, app_db):
    assert app_db.execute("SELECT COUNT(*) FROM forvaltare").fetchone()[0] == 0
    logga_in(client, app_db)
    stampel = app_db.execute(
        "SELECT senast_inloggad FROM forvaltare WHERE anvandarnamn = 'anna'"
    ).fetchone()["senast_inloggad"]
    assert stampel is not None and stampel[:2] == "20"


def test_svarslank_stamplar_senast_anvand(client, app_db):
    medlem_id = skapa_medlem(app_db, "KTH")
    token = ge_token(app_db, medlem_id)

    svar = client.get(f"/svara/{token}", follow_redirects=False)
    assert svar.status_code == 303

    stampel = app_db.execute(
        "SELECT senast_anvand FROM medlem WHERE id = ?", (medlem_id,)
    ).fetchone()["senast_anvand"]
    assert stampel is not None


def test_vaxlingssidan_stamplar_inte(client, app_db):
    medlem_a = skapa_medlem(app_db, "KTH")
    medlem_b = skapa_medlem(app_db, "Lunds universitet")
    token_a = ge_token(app_db, medlem_a)
    token_b = ge_token(app_db, medlem_b)

    client.get(f"/svara/{token_a}", follow_redirects=False)
    # An existing session means B's link only renders the switch confirmation —
    # the link was shown, not used, so B must remain unstamped.
    svar = client.get(f"/svara/{token_b}", follow_redirects=False)
    assert svar.status_code == 200
    assert app_db.execute(
        "SELECT senast_anvand FROM medlem WHERE id = ?", (medlem_b,)
    ).fetchone()["senast_anvand"] is None

    # A confirmed switch (POST /svara/vaxla) is a real login and stamps.
    svar = client.post(
        "/svara/vaxla",
        data={"token": token_b, "csrf_token": _csrf(client)},
        follow_redirects=False,
    )
    assert svar.status_code == 303
    assert app_db.execute(
        "SELECT senast_anvand FROM medlem WHERE id = ?", (medlem_b,)
    ).fetchone()["senast_anvand"] is not None


def test_konton_visar_konton_och_roller(client, app_db):
    skapa_forvaltare(app_db, "berit", roll="intern")  # aldrig inloggad
    logga_in(client, app_db)  # anna, admin

    svar = client.get("/konton")
    assert svar.status_code == 200
    assert "anna" in svar.text and "berit" in svar.text
    assert ">admin<" in svar.text and ">intern<" in svar.text
    assert "aldrig" in svar.text  # berit
    stampel = app_db.execute(
        "SELECT senast_inloggad FROM forvaltare WHERE anvandarnamn = 'anna'"
    ).fetchone()["senast_inloggad"]
    assert stampel[:16] in svar.text


def test_konton_kraver_admin(client, app_db):
    assert client.get("/konton", follow_redirects=False).status_code == 303

    logga_in(client, app_db, namn="ines", roll="intern")
    assert client.get("/konton", follow_redirects=False).status_code == 403

    logga_in(client, app_db, namn="elis", roll="extern")
    assert client.get("/konton", follow_redirects=False).status_code == 403


def test_konton_i_nav_bara_for_admin(client, app_db):
    logga_in(client, app_db)
    assert 'href="/konton"' in client.get("/trad").text

    logga_in(client, app_db, namn="ines", roll="intern")
    assert 'href="/konton"' not in client.get("/trad").text

    logga_in(client, app_db, namn="elis", roll="extern")
    assert 'href="/konton"' not in client.get("/trad").text


def test_medlemssidan_visar_senast_anvand(client, klient_fabrik, app_db):
    medlem_id = skapa_medlem(app_db, "KTH")
    oanvand_id = skapa_medlem(app_db, "Lunds universitet")
    token = ge_token(app_db, medlem_id)
    ge_token(app_db, oanvand_id)

    medlemsklient = klient_fabrik()
    medlemsklient.get(f"/svara/{token}", follow_redirects=False)

    logga_in(client, app_db)
    svar = client.get("/medlemmar")
    assert "inne 20" in svar.text  # datumchip (YYYY-…) för KTH
    assert "aldrig använd" in svar.text  # Lund har länk men har inte varit inne