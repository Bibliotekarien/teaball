"""Authorization-boundary tests (spec I5, S2, B5, B8) plus acceptance test §9.2
end-to-end and the member half of §9.4. Member A must never be able to read or
write member B's data, and admin routes must reject member sessions."""

import re

from tests.conftest import (
    ge_token,
    klient_fabrik,  # noqa: F401  (fixture)
    logga_in,
    seed_trad,
    skapa_medlem,
)


def _medlemsklient(fabrik, token):
    klient = fabrik()
    svar = klient.get(f"/svara/{token}", follow_redirects=False)
    assert svar.status_code == 303 and svar.headers["location"] == "/svara"
    return klient


def _csrf(klient) -> str:
    sida = klient.get("/svara").text
    return re.search(r'name="csrf_token" value="([^"]+)"', sida).group(1)


def test_acceptance_9_2_medlemsflode(app_db, klient_fabrik):
    ids = seed_trad(app_db)
    a = skapa_medlem(app_db, "Uppsala universitet")
    b = skapa_medlem(app_db, "Umeå universitet")
    app_db.commit()

    klient_a = _medlemsklient(klient_fabrik, ge_token(app_db, a))
    token_a = _csrf(klient_a)

    # A answers kan_vanta on a function node, writes a workaround, shares it,
    # and leaves a private comment.
    klient_a.post(f"/svara/{ids['wos']}/svar", data={"svar": "kan_vanta", "csrf_token": token_a})
    klient_a.post(f"/svara/{ids['wos']}/workaround",
                  data={"workaround": "Cron-skript som diffar mot gårdagens skörd.",
                        "workaround_delas": "1", "csrf_token": token_a})
    klient_a.post(f"/svara/{ids['wos']}/kommentar",
                  data={"kommentar": "Internt: rektorsbeslut väntas i höst.", "csrf_token": token_a})

    # A's children show the inherited label.
    sida_a = klient_a.get("/svara").text
    assert "ärvt: Kan vänta (från Import från Web of Science)" in sida_a

    # B sees the shared workaround anonymously — but never A's comment or name.
    klient_b = _medlemsklient(klient_fabrik, ge_token(app_db, b))
    sida_b = klient_b.get("/svara").text
    assert "Cron-skript som diffar mot gårdagens skörd." in sida_b
    assert "Workarounds från andra medlemmar (1)" in sida_b
    assert "Uppsala universitet" not in sida_b
    assert "rektorsbeslut" not in sida_b

    # And A's answer is A's alone: B's page has no selected pill for wos.
    assert app_db.execute(
        "SELECT COUNT(*) FROM bedomning WHERE medlem_id = ?", (b,)
    ).fetchone()[0] == 0


def test_acceptance_9_4_medlemsvy(app_db, klient_fabrik):
    ids = seed_trad(app_db)
    a = skapa_medlem(app_db, "Uppsala universitet")
    app_db.execute("UPDATE funktion SET synlig_externt = 0 WHERE id = ?", (ids["publicering"],))
    app_db.commit()

    klient = _medlemsklient(klient_fabrik, ge_token(app_db, a))
    sida = klient.get("/svara").text
    # The whole hidden subtree is gone from the member view ...
    assert "Publicering" not in sida
    assert "Import från Web of Science" not in sida
    assert "Export &amp; spridning" in sida
    # ... and hidden nodes cannot be answered either.
    svar = klient.post(f"/svara/{ids['wos']}/svar",
                       data={"svar": "golive_krav", "csrf_token": _csrf(klient)})
    assert svar.status_code == 404


def test_medlem_kan_inte_na_adminvyer(app_db, klient_fabrik):
    seed_trad(app_db)
    a = skapa_medlem(app_db, "Uppsala universitet")
    app_db.commit()
    klient = _medlemsklient(klient_fabrik, ge_token(app_db, a))
    for adress in ("/trad", "/bedomning", "/analys", "/roadmap", "/medlemmar", "/export"):
        svar = klient.get(adress, follow_redirects=False)
        assert svar.status_code == 303, adress
        assert svar.headers["location"] == "/login"


def test_medlem_kan_inte_skriva_via_proxyrutt(app_db, klient_fabrik):
    """Forged medlem_id in the proxy route must not work for members (I5)."""
    ids = seed_trad(app_db)
    a = skapa_medlem(app_db, "Uppsala universitet")
    b = skapa_medlem(app_db, "Umeå universitet")
    app_db.commit()
    klient = _medlemsklient(klient_fabrik, ge_token(app_db, a))
    svar = klient.post(f"/bedomning/{b}/{ids['wos']}/svar",
                       data={"svar": "golive_krav", "csrf_token": _csrf(klient)},
                       follow_redirects=False)
    assert svar.status_code == 303 and svar.headers["location"] == "/login"
    assert app_db.execute("SELECT COUNT(*) FROM bedomning").fetchone()[0] == 0


def test_ogiltig_revokerad_och_regenererad_token(app_db, klient_fabrik):
    seed_trad(app_db)
    a = skapa_medlem(app_db, "Uppsala universitet")
    app_db.commit()

    assert klient_fabrik().get("/svara/helt-fel-token").status_code == 404

    token = ge_token(app_db, a)
    klient = _medlemsklient(klient_fabrik, token)
    assert klient.get("/svara").status_code == 200

    # Revocation kills both the link and the live session (S2).
    app_db.execute("UPDATE medlem SET token = NULL WHERE id = ?", (a,))
    app_db.commit()
    assert klient.get("/svara").status_code == 403
    assert klient_fabrik().get(f"/svara/{token}").status_code == 404

    # Regeneration: the new link works, the old one stays dead.
    ny = ge_token(app_db, a)
    assert ny != token
    assert klient_fabrik().get(f"/svara/{token}").status_code == 404
    assert _medlemsklient(klient_fabrik, ny).get("/svara").status_code == 200


def test_medlem_post_utan_csrf(app_db, klient_fabrik):
    ids = seed_trad(app_db)
    a = skapa_medlem(app_db, "Uppsala universitet")
    app_db.commit()
    klient = _medlemsklient(klient_fabrik, ge_token(app_db, a))
    svar = klient.post(f"/svara/{ids['wos']}/svar", data={"svar": "golive_krav"})
    assert svar.status_code == 400


def test_medlemsadmin_tokenflode(client, app_db, klient_fabrik):
    logga_in(client, app_db)
    sida = client.get("/medlemmar").text
    token = re.search(r'name="csrf_token" value="([^"]+)"', sida).group(1)

    client.post("/medlemmar", data={"namn": "Testlärosätet", "kategori": "högskola",
                                    "csrf_token": token})
    medlem = app_db.execute("SELECT id FROM medlem WHERE namn = 'Testlärosätet'").fetchone()["id"]

    # Generating shows the link exactly once.
    svar = client.post(f"/medlemmar/{medlem}/token", data={"csrf_token": token})
    forsta = svar.text
    assert "Ny svarslänk för Testlärosätet" in forsta
    lank = re.search(r'value="(http[^"]+/svara/[^"]+)"', forsta).group(1)
    assert "Ny svarslänk" not in client.get("/medlemmar").text  # flash consumed

    # The link works (checked with a separate client — following it in the
    # admin's own browser would replace the admin session), and revocation
    # kills it.
    ratoken = lank.rsplit("/", 1)[1]
    assert klient_fabrik().get(f"/svara/{ratoken}", follow_redirects=False).status_code == 303
    client.post(f"/medlemmar/{medlem}/token/ta-bort", data={"csrf_token": token})
    assert klient_fabrik().get(f"/svara/{ratoken}", follow_redirects=False).status_code == 404
