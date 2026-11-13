"""scripts/organisationer.py (skapa, lista, ta bort) och scripts/backup_alla.sh."""

import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from app import config, db as appdb, organisationer
from scripts import organisationer as skript

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture()
def katalog(tmp_path, monkeypatch):
    katalog = tmp_path / "organisationer"
    katalog.mkdir()
    monkeypatch.setattr(config, "ORGANISATIONER_DIR", katalog)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "far-inte-finnas.db")
    yield katalog
    assert not (tmp_path / "far-inte-finnas.db").exists()


def _skapa(vard, namn="stilla-lax"):
    return skript.main(["skapa", vard, namn, "--losenord", "hemligt-losen"])


def _backup_alla(katalog, mal):
    # MINSTA_FRIA_MB=0: backup.sh kräver annars 200 MB ledigt, vilket en liten
    # tmpfs i CI inte alltid har.
    return subprocess.run(["bash", REPO / "scripts" / "backup_alla.sh", katalog, mal],
                          capture_output=True, text=True,
                          env={**os.environ, "MINSTA_FRIA_MB": "0"})


def test_skapa_ger_en_organisation_med_admin(katalog, capsys):
    assert _skapa("a.example.org") == 0
    assert "https://a.example.org/login" in capsys.readouterr().out
    assert organisationer.for_vard("a.example.org") is not None
    conn = appdb.connect(katalog / "a.example.org.db")
    rad = conn.execute("SELECT anvandarnamn, roll FROM forvaltare").fetchone()
    conn.close()
    assert tuple(rad) == ("stilla-lax", "admin")
    # Inget tillfälligt bygge blir kvar.
    assert sorted(p.name for p in katalog.iterdir()) == ["a.example.org.db"]


def test_skapa_foreslar_gemener(katalog, capsys):
    assert _skapa("A.Example.org") == 1
    assert "Menade du a.example.org?" in capsys.readouterr().err


def test_skapa_vagrar_ogiltigt_anvandarnamn(katalog, capsys):
    assert _skapa("a.example.org", "anna lindh") == 1
    assert "användarnamn" in capsys.readouterr().err
    assert list(katalog.iterdir()) == []


def test_skapa_avbruten_lamnar_ingen_organisation(katalog, monkeypatch):
    def trasig(conn):
        raise RuntimeError("avbruten")

    monkeypatch.setattr(appdb, "init_db", trasig)
    with pytest.raises(RuntimeError):
        _skapa("a.example.org")
    assert list(katalog.iterdir()) == []


@pytest.mark.parametrize("vard", ["A.example.org", "../x", "a_b.example.org", "a" * 64 + ".org"])
def test_skapa_vagrar_ogiltigt_hostnamn(katalog, vard):
    assert _skapa(vard) == 1
    assert list(katalog.iterdir()) == []


def test_skapa_vagrar_befintlig(katalog, capsys):
    assert _skapa("a.example.org") == 0
    assert _skapa("a.example.org", "annan") == 1
    assert "finns redan" in capsys.readouterr().err


def test_skapa_vagrar_kort_losenord(katalog):
    assert skript.main(["skapa", "a.example.org", "x", "--losenord", "kort"]) == 1
    assert not (katalog / "a.example.org.db").exists()


def test_kraver_flera_organisationer(monkeypatch, capsys):
    monkeypatch.setattr(config, "ORGANISATIONER_DIR", None)
    assert skript.main(["lista"]) == 1
    assert "ORGANISATIONER_DIR" in capsys.readouterr().err


def test_lista(katalog, capsys):
    _skapa("a.example.org")
    _skapa("b.example.org")
    capsys.readouterr()
    conn = appdb.connect(katalog / "b.example.org.db")
    conn.execute("DELETE FROM schema_migration WHERE version = (SELECT max(version) FROM schema_migration)")
    conn.commit()
    conn.close()
    assert skript.main(["lista"]) == 0
    ut = capsys.readouterr().out.splitlines()
    assert ut[1].startswith("a.example.org") and "aldrig" in ut[1]
    assert ut[2].startswith("b.example.org") and "migreras vid nästa start" in ut[2]


def test_lista_tal_avvikande_databaser(katalog, capsys):
    """En trasig eller främmande fil, ett äldre schema, ett tomt eller ett
    nyare: var och en blir en rad, aldrig en krasch för hela listningen."""
    _skapa("a.example.org")
    (katalog / "trasig.example.org.db").write_bytes(b"inte sqlite" * 100)
    _skapa("gammal.example.org")
    conn = sqlite3.connect(katalog / "gammal.example.org.db")
    conn.execute("ALTER TABLE forvaltare DROP COLUMN senast_inloggad")
    conn.execute("DELETE FROM schema_migration WHERE version >= 4")
    conn.commit()
    conn.close()
    _skapa("tom.example.org")
    conn = sqlite3.connect(katalog / "tom.example.org.db")
    conn.execute("DELETE FROM schema_migration")
    conn.commit()
    conn.close()
    _skapa("ny.example.org")
    conn = sqlite3.connect(katalog / "ny.example.org.db")
    conn.execute("INSERT INTO schema_migration (version) VALUES (9999)")
    conn.commit()
    conn.close()
    capsys.readouterr()

    assert skript.main(["lista"]) == 0
    ut = capsys.readouterr().out
    assert "a.example.org" in ut and "aldrig" in ut
    assert "trasig.example.org" in ut and "kan inte läsas" in ut
    assert "schema 0003, migreras vid nästa start" in ut
    assert "tom schema_migration" in ut
    assert "schema 9999 är nyare än koden" in ut


def test_lista_tom(katalog, capsys):
    assert skript.main(["lista"]) == 0
    assert "Inga organisationer" in capsys.readouterr().out


def test_ta_bort_kraver_bekraftelse(katalog, capsys):
    _skapa("a.example.org")
    assert skript.main(["ta-bort", "a.example.org"]) == 1
    assert skript.main(["ta-bort", "a.example.org", "--bekrafta", "b.example.org"]) == 1
    assert (katalog / "a.example.org.db").exists()


def test_ta_bort_sparar_kopia(katalog, capsys):
    _skapa("a.example.org")
    _skapa("b.example.org")
    assert skript.main(["ta-bort", "a.example.org", "--bekrafta", "a.example.org"]) == 0
    assert organisationer.for_vard("a.example.org") is None
    assert [o.nyckel for o in organisationer.alla()] == ["b.example.org"]
    kopior = list((katalog / "borttagna").glob("a.example.org.*.db"))
    assert len(kopior) == 1
    conn = sqlite3.connect(kopior[0])
    assert conn.execute("SELECT anvandarnamn FROM forvaltare").fetchone()[0] == "stilla-lax"
    conn.close()


def test_ta_bort_flyttar_kopior_fore_migration(katalog, capsys):
    """Kopiorna före migration har samma personuppgifter och följer med till
    borttagna/; lista påminner om dem."""
    _skapa("a.example.org")
    _skapa("a.example.org.se")             # annan organisation med samma prefix
    fore = katalog / "a.example.org.fore-0010-20261112T000000Z.db"
    fore.write_bytes(b"")
    annans = katalog / "a.example.org.se.fore-0010-20261112T000000Z.db"
    annans.write_bytes(b"")
    assert skript.main(["ta-bort", "a.example.org", "--bekrafta", "a.example.org"]) == 0
    assert not fore.exists() and (katalog / "borttagna" / fore.name).exists()
    assert annans.exists()
    assert "<mål>/a.example.org/" in capsys.readouterr().out
    skript.main(["lista"])
    assert "kopior av borttagna organisationer" in capsys.readouterr().out


def test_ta_bort_okand(katalog):
    assert skript.main(["ta-bort", "x.example.org", "--bekrafta", "x.example.org"]) == 1


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash saknas")
def test_backup_alla_en_katalog_per_organisation(katalog, tmp_path):
    _skapa("a.example.org")
    _skapa("b.example.org")
    (katalog / "a.example.org.fore-0011-20261113T000000Z.db").write_bytes(b"")
    mal = tmp_path / "backup"
    mal.mkdir()
    svar = _backup_alla(katalog, mal)
    assert svar.returncode == 0, svar.stderr
    assert "2 organisationer" in svar.stdout
    assert sorted(p.name for p in mal.iterdir()) == ["a.example.org", "b.example.org"]
    for vard in ("a.example.org", "b.example.org"):
        kopior = list((mal / vard / "dagliga").glob("teaball-*.db"))
        assert len(kopior) == 1


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash saknas")
def test_backup_alla_fortsatter_efter_ett_fel(katalog, tmp_path):
    """En organisation som inte går att backa upp stoppar inte de andra, men
    skriptet avslutas med fel så att övervakningen märker det."""
    _skapa("a.example.org")
    (katalog / "b.example.org.db").write_bytes(b"inte sqlite" * 100)
    _skapa("c.example.org")
    mal = tmp_path / "backup"
    mal.mkdir()
    svar = _backup_alla(katalog, mal)
    assert svar.returncode == 1
    assert "misslyckades för: b.example.org" in svar.stderr
    for vard in ("a.example.org", "c.example.org"):
        assert list((mal / vard / "dagliga").glob("teaball-*.db"))


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash saknas")
def test_backup_alla_utan_organisationer_ar_ett_fel(katalog, tmp_path):
    svar = _backup_alla(katalog, tmp_path)
    assert svar.returncode == 1
    assert "Inga organisationer" in svar.stderr
