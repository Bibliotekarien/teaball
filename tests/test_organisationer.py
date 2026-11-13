"""Flera organisationer på en installation (app/organisationer.py): en
databasfil per hostnamn, och inget — data, texter, sessioner, svarslänkar —
får läcka mellan dem."""

import pytest
from fastapi.testclient import TestClient

from app import config, db as appdb, instans, organisationer
from tests.conftest import csrf_fran, ge_token, logga_in, skapa_funktion, skapa_medlem

A = "a.example.org"
B = "b.example.org"


@pytest.fixture()
def tva(tmp_path, monkeypatch):
    """Två organisationer i ORGANISATIONER_DIR. DB_PATH pekar på en fil som
    inte får uppstå: ingenting ska falla tillbaka på den."""
    katalog = tmp_path / "organisationer"
    katalog.mkdir()
    monkeypatch.setattr(config, "ORGANISATIONER_DIR", katalog)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "far-inte-finnas.db")
    conns = {}
    for vard in (A, B):
        conn = appdb.connect(katalog / f"{vard}.db")
        appdb.init_db(conn)
        conns[vard] = conn
    yield conns
    for conn in conns.values():
        conn.close()
    assert not (tmp_path / "far-inte-finnas.db").exists()


@pytest.fixture()
def klient(tva):
    from app.main import create_app

    skapade = []

    def fabrik(vard):
        k = TestClient(create_app(), base_url=f"http://{vard}")
        k.__enter__()
        skapade.append(k)
        return k

    yield fabrik
    for k in skapade:
        k.__exit__(None, None, None)


def test_texterna_foljer_hostnamnet(tva, klient):
    instans.spara(tva[A], organisation="Organisation A")
    instans.spara(tva[B], organisation="Organisation B")
    sida_a = klient(A).get("/integritet").text
    sida_b = klient(B).get("/integritet").text
    assert "Organisation A" in sida_a and "Organisation B" not in sida_a
    assert "Organisation B" in sida_b and "Organisation A" not in sida_b


def test_data_foljer_hostnamnet(tva, klient):
    skapa_funktion(tva[A], "Bara hos A")
    tva[A].commit()
    a, b = klient(A), klient(B)
    logga_in(a, tva[A])
    logga_in(b, tva[B])
    assert "Bara hos A" in a.get("/trad").text
    assert "Bara hos A" not in b.get("/trad").text


@pytest.mark.parametrize("vard", [
    "okand.example.org",                  # ingen fil
    "a.example.org.fore-0010-20261112t000000z",  # kopia före migration
    "..",
    "a.example.org/../b",
    "",
])
def test_okant_hostnamn_ger_404(tva, klient, vard):
    from app.main import create_app

    with TestClient(create_app()) as k:
        svar = k.get("/integritet", headers={"host": vard})
    assert svar.status_code == 404


def test_port_och_versaler_ar_samma_organisation(tva, klient):
    instans.spara(tva[A], organisation="Organisation A")
    k = klient(A)
    assert "Organisation A" in k.get("/integritet", headers={"host": "A.Example.org:8443"}).text


def test_health_kraver_ingen_organisation(tva):
    from app.main import create_app

    with TestClient(create_app()) as k:
        assert k.get("/health", headers={"host": "vad-som-helst"}).status_code == 200


def test_session_galler_bara_i_sin_organisation(tva, klient):
    """Samma SECRET_KEY överallt: en kaka kopierad till en annan organisations
    hostnamn verifieras. Även med samma konto-id och samma lösenordshash i
    båda databaserna ska den inte logga in där."""
    a = klient(A)
    logga_in(a, tva[A])
    rad = tva[A].execute("SELECT anvandarnamn, losen_hash, roll FROM forvaltare").fetchone()
    tva[B].execute("INSERT INTO forvaltare (anvandarnamn, losen_hash, roll) VALUES (?, ?, ?)",
                   tuple(rad))
    tva[B].commit()
    kaka = a.cookies.get("teaball_session")

    b = klient(B)
    svar = b.get("/trad", headers={"cookie": f"teaball_session={kaka}"}, follow_redirects=False)
    assert svar.status_code == 303 and svar.headers["location"] == "/login"
    assert a.get("/trad", follow_redirects=False).status_code == 200


def test_medlemssession_galler_bara_i_sin_organisation(tva, klient):
    medlem = skapa_medlem(tva[A], "Uppsala universitet")
    token = ge_token(tva[A], medlem)
    a = klient(A)
    a.get(f"/svara/{token}")
    assert a.get("/svara").status_code == 200
    # Samma medlem och samma tokenhash hos B: kakan ska ändå inte räcka.
    hash_ = tva[A].execute("SELECT token FROM medlem").fetchone()[0]
    tva[B].execute("INSERT INTO medlem (namn, token) VALUES (?, ?)", ("Uppsala universitet", hash_))
    tva[B].commit()
    kaka = a.cookies.get("teaball_session")
    svar = klient(B).get("/svara", headers={"cookie": f"teaball_session={kaka}"})
    assert svar.status_code == 403


def test_svarslanken_anvander_organisationens_adress(tva, klient, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://fel.example.org")
    medlem = skapa_medlem(tva[B], "Lunds universitet")
    tva[B].commit()
    b = klient(B)
    logga_in(b, tva[B])
    token = csrf_fran(b.get("/medlemmar").text)
    sida = b.post(f"/medlemmar/{medlem}/token", data={"csrf_token": token}).text
    assert f"http://{B}/svara/" in sida
    assert "fel.example.org" not in sida


def test_inloggningsspärren_ar_per_organisation(tva, klient):
    from app.routers import inloggning

    inloggning._misslyckanden.clear()
    a, b = klient(A), klient(B)
    logga_in(b, tva[B])                   # skapar anna hos B
    for _ in range(inloggning.MAX_FORSOK):
        a.post("/login", data={"anvandarnamn": "anna", "losenord": "fel-losen",
                               "csrf_token": csrf_fran(a.get("/login").text)})
    b2 = klient(B)
    logga_in(b2, tva[B])                  # B:s anna är inte spärrad
    inloggning._misslyckanden.clear()


def test_alla_hoppar_over_kopior(tva):
    katalog = config.ORGANISATIONER_DIR
    (katalog / f"{A}.fore-0011-20261113T000000Z.db").write_bytes(b"")
    (katalog / "inte en organisation.db").write_bytes(b"")
    assert [o.nyckel for o in organisationer.alla()] == [A, B]


def test_utan_anrop_finns_ingen_organisation(tva):
    """Skript måste ange --db; de får aldrig en gissad organisation."""
    with pytest.raises(RuntimeError, match="--db"):
        appdb.connect()


def test_en_organisation_som_forut(app_db, client):
    """Utan ORGANISATIONER_DIR gäller DB_PATH för alla hostnamn, och sessioner
    från före organisationerna (utan nyckel) fortsätter gälla."""
    import base64
    import json

    from itsdangerous import TimestampSigner

    from app.auth.core import losen_digest
    from tests.conftest import skapa_forvaltare

    assert config.ORGANISATIONER_DIR is None
    instans.spara(app_db, organisation="Enda")
    assert "Enda" in client.get("/integritet", headers={"host": "vad-som-helst"}).text

    # En kaka som den förra versionen satte den: utan organisationsnyckel.
    skapa_forvaltare(app_db)
    rad = app_db.execute("SELECT id, losen_hash FROM forvaltare").fetchone()
    data = {"forvaltare_id": rad["id"], "forvaltare_losen_digest": losen_digest(rad["losen_hash"])}
    kaka = TimestampSigner(config.SECRET_KEY).sign(
        base64.b64encode(json.dumps(data).encode())).decode()
    svar = client.get("/trad", headers={"cookie": f"teaball_session={kaka}"},
                      follow_redirects=False)
    assert svar.status_code == 200
