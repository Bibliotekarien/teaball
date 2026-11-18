"""Matomo per organisation: med flera organisationer har var och en sin sajt i
operatörens Matomo (migration 0011), och träffarna får aldrig hamna i en annan
organisations statistik."""

import pytest
from fastapi.testclient import TestClient

from app import config, db as appdb, instans, matomo
from scripts import organisationer as skript
from tests.conftest import csrf_fran, logga_in

A = "a.example.org"
B = "b.example.org"


@pytest.fixture()
def traffar(monkeypatch):
    """Fångar idsite och url för varje träff i stället för att skicka den."""
    skickade = []

    def fanga(params):
        skickade.append((params["idsite"], params["url"]))

        async def klar():
            return None
        return klar()

    monkeypatch.setattr(matomo, "_send", fanga)
    monkeypatch.setattr(config, "MATOMO_URL", "https://matomo.example.org")
    monkeypatch.setattr(config, "MATOMO_SITE_ID", "99")   # ska inte användas
    return skickade


@pytest.fixture()
def tva(tmp_path, monkeypatch):
    katalog = tmp_path / "organisationer"
    katalog.mkdir()
    monkeypatch.setattr(config, "ORGANISATIONER_DIR", katalog)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "far-inte-finnas.db")
    conns = {}
    for vard in (A, B):
        conns[vard] = appdb.connect(katalog / f"{vard}.db")
        appdb.init_db(conns[vard])
    yield conns
    for conn in conns.values():
        conn.close()


def _klient(vard):
    from app.main import create_app
    return TestClient(create_app(), base_url=f"http://{vard}")


def test_varje_organisation_far_sin_sajt(tva, traffar):
    instans.spara_matomo(tva[A], "11")
    instans.spara_matomo(tva[B], "12")
    with _klient(A) as a, _klient(B) as b:
        a.get("/login")
        b.get("/login")
    assert ("11", f"http://{A}/login") in traffar
    assert ("12", f"http://{B}/login") in traffar
    assert all(idsite != "99" for idsite, _ in traffar)


def test_utan_sajt_ingen_statistik(tva, traffar):
    """MATOMO_SITE_ID i miljön gäller inte med flera organisationer: den
    skulle blanda allas statistik i en sajt."""
    instans.spara_matomo(tva[A], "11")
    with _klient(B) as b:
        sida = b.get("/integritet").text
    assert traffar == []
    assert "Ingen besöksstatistik samlas in" in sida


def test_integritetssidan_namner_operatorens_matomo(tva, traffar):
    instans.spara_matomo(tva[A], "11")
    with _klient(A) as a:
        sida = a.get("/integritet").text
    assert "hos den som driftar tjänsten" in sida
    assert "egen, självhostad" not in sida


def test_en_organisation_som_forut(app_db, client, traffar):
    client.get("/login")
    assert traffar and traffar[0][0] == "99"
    sida = client.get("/integritet").text
    assert "egen, självhostad" in sida


def test_admin_kan_inte_andra_sajten(tva, traffar):
    """Att spara Inställningar lämnar operatörens Matomo-sajt orörd. Det som
    vaktas är att spara inte nollar fält utanför formuläret (den första
    versionen skrev alla fält i Instans); det extra postade fältet ignoreras
    redan av routern."""
    instans.spara_matomo(tva[A], "11")
    with _klient(A) as a:
        logga_in(a, tva[A])
        token = csrf_fran(a.get("/installningar").text)
        a.post("/installningar", data={"organisation": "A", "matomo_site_id": "12",
                                       "csrf_token": token})
    assert instans.las(tva[A]).matomo_site_id == "11"
    assert instans.las(tva[A]).organisation == "A"


@pytest.mark.parametrize("site_id", ["abc", "1.5", "²", "-1", "0", "1" * 11])
def test_site_id_maste_vara_ett_heltal(tva, site_id):
    with pytest.raises(ValueError):
        instans.spara_matomo(tva[A], site_id)


def test_skriptet_satter_och_tar_bort_sajten(tva, traffar, capsys):
    assert skript.main(["matomo", A, "11"]) == 0
    assert "site-id 11" in capsys.readouterr().out
    assert instans.las(tva[A]).matomo_site_id == "11"
    assert skript.main(["lista"]) == 0
    rad = next(r for r in capsys.readouterr().out.splitlines() if r.startswith(A))
    assert rad.rstrip().endswith("11")
    assert skript.main(["matomo", A]) == 0
    assert instans.las(tva[A]).matomo_site_id == ""
    assert skript.main(["matomo", A, "abc"]) == 1
    assert skript.main(["matomo", "okand.example.org", "1"]) == 1


def test_installningar_visar_statistiklaget(tva, traffar):
    """Organisationen är personuppgiftsansvarig och ska se om statistik samlas
    in om dess besökare, men inte kunna ändra det."""
    with _klient(A) as a:
        logga_in(a, tva[A])
        assert "av. Ingen statistik samlas in om besökarna." in a.get("/installningar").text
        instans.spara_matomo(tva[A], "11")
        sida = a.get("/installningar").text
    assert "sajt 11 i driftarens" in sida
    assert "Ändras av den som driftar tjänsten." in sida
    assert 'name="matomo_site_id"' not in sida


def test_varnar_for_matomo_site_id_med_flera(tva, traffar, caplog):
    """En instans som flyttats in tappar annars statistiken utan att märka det."""
    with _klient(A):
        pass
    assert "MATOMO_SITE_ID=99 används inte med flera organisationer" in caplog.text


def test_skriptet_pa_omigrerad_databas(tva, capsys):
    tva[A].execute("ALTER TABLE instans DROP COLUMN matomo_site_id")
    tva[A].commit()
    assert skript.main(["matomo", A, "11"]) == 1
    assert "Starta om appen" in capsys.readouterr().err
