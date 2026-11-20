"""Backup i två steg (#108): scripts/ogonblick.py tar ögonblickskopiorna inne i
containern, scripts/backup_kopiera.py kopierar dem på värden utan att följa
symlänkar eller öppna SQLite-filer som containern kan skriva i."""

import datetime
import os
import sqlite3
import subprocess
import time

import pytest

from app import config, db as appdb
from scripts import backup_kopiera as kopiera
from scripts import ogonblick


@pytest.fixture()
def katalog(tmp_path, monkeypatch):
    katalog = tmp_path / "data" / "organisationer"
    katalog.mkdir(parents=True)
    monkeypatch.setattr(config, "ORGANISATIONER_DIR", katalog)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "far-inte-finnas.db")
    return katalog


@pytest.fixture()
def agare(monkeypatch):
    """Testerna kör som den egna användaren, inte containerns uid 1505."""
    monkeypatch.setattr(kopiera, "AGARE", os.getuid())
    monkeypatch.setattr(kopiera, "MINSTA_FRIA_MB", 0)


def _organisation(katalog, vard):
    conn = appdb.connect(katalog / f"{vard}.db")
    appdb.init_db(conn)
    conn.execute("INSERT INTO forvaltare (anvandarnamn, losen_hash) VALUES (?, 'x')", (vard,))
    conn.commit()
    return conn


def test_ogonblick_en_fil_per_organisation(katalog):
    a = _organisation(katalog, "a.example.org")    # öppen, i WAL-läge
    _organisation(katalog, "b.example.org").close()
    assert ogonblick.main([]) == 0
    mal = katalog.parent / "ogonblick"
    assert sorted(p.name for p in mal.iterdir()) == ["a.example.org.db", "b.example.org.db"]
    kopia = sqlite3.connect(mal / "a.example.org.db")
    assert kopia.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert kopia.execute("SELECT anvandarnamn FROM forvaltare").fetchone()[0] == "a.example.org"
    kopia.close()
    a.close()


def test_ogonblick_rensar_det_som_inte_hor_hemma(katalog):
    """Det som ligger kvar i katalogen blir en backup; en borttagen
    organisation ska inte fortsätta backas upp."""
    _organisation(katalog, "a.example.org").close()
    mal = katalog.parent / "ogonblick"
    mal.mkdir()
    (mal / "borttagen.example.org.db").write_bytes(b"gammal")
    (mal / "lank.db").symlink_to(katalog / "a.example.org.db")
    (mal / "katalog").mkdir()
    assert ogonblick.main([]) == 0
    assert sorted(p.name for p in mal.iterdir()) == ["a.example.org.db"]
    assert (katalog / "a.example.org.db").exists()   # länkens mål rörs inte


def test_ogonblick_misslyckad_organisation(katalog, capsys):
    _organisation(katalog, "a.example.org").close()
    (katalog / "b.example.org.db").write_bytes(b"inte sqlite" * 100)
    mal = katalog.parent / "ogonblick"
    mal.mkdir()
    (mal / "b.example.org.db").write_bytes(b"gammal kopia")
    assert ogonblick.main([]) == 1
    assert "misslyckades för: b.example.org" in capsys.readouterr().err
    # De friska tas ändå, och den gamla kopian blir inte kvar som om den
    # vore dagens: värdjobbet får en markering i stället.
    assert sorted(p.name for p in mal.iterdir()) == ["a.example.org.db",
                                                     "b.example.org.misslyckad"]


def test_ogonblick_rensa(katalog):
    _organisation(katalog, "a.example.org").close()
    assert ogonblick.main([]) == 0
    assert ogonblick.main(["--rensa"]) == 0
    assert list((katalog.parent / "ogonblick").iterdir()) == []
    assert (katalog / "a.example.org.db").exists()


def test_ogonblick_vagrar_symlankad_katalog(katalog, capsys):
    """En symlänk till organisationskatalogen hade fått rensningen att ta
    bort databasernas -wal-filer."""
    org = _organisation(katalog, "a.example.org")
    (katalog.parent / "ogonblick").symlink_to(katalog)
    assert ogonblick.main([]) == 1
    assert ogonblick.main(["--rensa"]) == 1
    assert "är en symlänk" in capsys.readouterr().err
    assert (katalog / "a.example.org.db-wal").exists()
    org.close()


def test_ogonblick_med_en_organisation(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ORGANISATIONER_DIR", None)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "teaball.db")
    appdb.init_db(appdb.connect(tmp_path / "teaball.db"))
    assert ogonblick.main([]) == 0
    assert (tmp_path / "ogonblick" / "teaball.db").exists()


def _ogonblick(tmp_path, *vardar):
    kalla = tmp_path / "ogonblick"
    kalla.mkdir()
    for vard in vardar:
        conn = sqlite3.connect(kalla / f"{vard}.db")
        conn.execute("CREATE TABLE t (x)")
        conn.execute("INSERT INTO t VALUES (?)", (vard,))
        conn.commit()
        conn.close()
    mal = tmp_path / "backup"
    mal.mkdir()
    return kalla, mal


def test_kopiera_en_katalog_per_organisation(tmp_path, agare, capsys):
    kalla, mal = _ogonblick(tmp_path, "a.example.org", "b.example.org")
    assert kopiera.main(["x", str(kalla), str(mal)]) == 0
    assert "2 organisationer" in capsys.readouterr().out
    for vard in ("a.example.org", "b.example.org"):
        (kopia,) = (mal / vard / "dagliga").glob("teaball-*.db")
        assert sqlite3.connect(kopia).execute("SELECT x FROM t").fetchone()[0] == vard
        assert oct(kopia.stat().st_mode & 0o777) == "0o600"
    assert not list(kalla.glob("*-shm")) and not list(mal.rglob("*-journal"))


def test_kopiera_foljer_inte_symlankar(tmp_path, agare, capsys):
    """Värdjobbet kan läsa allt; en symlänk i containerns katalog får inte
    leda det till en annan apps databas eller värdens filer."""
    kalla, mal = _ogonblick(tmp_path, "a.example.org")
    annan = tmp_path / "annan-app.db"
    sqlite3.connect(annan).close()
    (kalla / "b.example.org.db").symlink_to(annan)
    assert kopiera.main(["x", str(kalla), str(mal)]) == 1
    assert "misslyckades för: b.example.org" in capsys.readouterr().err
    assert not (mal / "b.example.org").exists()
    assert list((mal / "a.example.org" / "dagliga").glob("teaball-*.db"))


def test_kopiera_foljer_inte_en_symlankad_katalog(tmp_path, agare, capsys):
    kalla, mal = _ogonblick(tmp_path, "a.example.org")
    lank = tmp_path / "lank"
    lank.symlink_to(kalla)
    assert kopiera.main(["x", str(lank), str(mal)]) == 1
    assert "Kan inte öppna" in capsys.readouterr().err


def test_kopiera_hoppar_over_fifo_utan_att_hanga(tmp_path, agare, capsys):
    kalla, mal = _ogonblick(tmp_path, "a.example.org")
    os.mkfifo(kalla / "b.example.org.db")
    assert kopiera.main(["x", str(kalla), str(mal)]) == 1
    assert "inte en vanlig fil" in capsys.readouterr().err


def test_kopiera_hoppar_over_hardlankar(tmp_path, agare, capsys):
    kalla, mal = _ogonblick(tmp_path, "a.example.org")
    os.link(kalla / "a.example.org.db", tmp_path / "annanstans.db")
    assert kopiera.main(["x", str(kalla), str(mal)]) == 1
    assert "hårda länkar" in capsys.readouterr().err


def test_kopiera_kraver_containerns_agare(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(kopiera, "MINSTA_FRIA_MB", 0)
    kalla, mal = _ogonblick(tmp_path, "a.example.org")
    assert kopiera.main(["x", str(kalla), str(mal)]) == 1   # AGARE = 1505
    assert "inte 1505" in capsys.readouterr().err


def test_kopiera_hoppar_over_konstiga_namn(tmp_path, agare, capsys):
    kalla, mal = _ogonblick(tmp_path, "a.example.org")
    (kalla / "x';.shell date'.db").write_bytes(b"")
    (kalla / "..db").write_bytes(b"")
    assert kopiera.main(["x", str(kalla), str(mal)]) == 1
    assert "namnet är inget hostnamn" in capsys.readouterr().err
    assert sorted(p.name for p in mal.iterdir()) == ["a.example.org"]


def test_kopiera_kontrollerar_integriteten(tmp_path, agare, capsys):
    kalla, mal = _ogonblick(tmp_path, "a.example.org")
    (kalla / "b.example.org.db").write_bytes(b"inte sqlite" * 100)
    assert kopiera.main(["x", str(kalla), str(mal)]) == 1
    assert "misslyckades för: b.example.org" in capsys.readouterr().err
    assert not list((mal / "b.example.org" / "dagliga").iterdir())


def test_kopiera_utan_ogonblick_ar_ett_fel(tmp_path, agare, capsys):
    kalla, mal = _ogonblick(tmp_path)
    assert kopiera.main(["x", str(kalla), str(mal)]) == 1
    assert "Inga ögonblickskopior" in capsys.readouterr().err


def test_kopiera_manatlig_och_rotation(tmp_path, agare):
    kalla, mal = _ogonblick(tmp_path, "a.example.org")
    fd = kopiera.oppna_katalog(str(kalla))
    try:
        dag = datetime.date(2026, 10, 1)
        for i in range(35):
            kopiera.kopiera(fd, "a.example.org.db", str(mal), dag + datetime.timedelta(days=i))
    finally:
        os.close(fd)
    dagliga = sorted(p.name for p in (mal / "a.example.org" / "dagliga").iterdir())
    assert len(dagliga) == 30 and dagliga[-1] == "teaball-2026-11-04.db"
    manatliga = sorted(p.name for p in (mal / "a.example.org" / "manatliga").iterdir())
    assert manatliga == ["teaball-2026-10.db", "teaball-2026-11.db"]


def test_kopiera_misslyckad_organisation_ar_ett_fel(tmp_path, agare, capsys):
    """De övriga kopieras, men jobbet avslutas med fel så att deploy.sh
    stoppas."""
    kalla, mal = _ogonblick(tmp_path, "a.example.org")
    (kalla / "b.example.org.misslyckad").write_text("x")
    assert kopiera.main(["x", str(kalla), str(mal)]) == 1
    assert "b.example.org: ögonblickskopian gick inte att ta" in capsys.readouterr().err
    assert list((mal / "a.example.org" / "dagliga").glob("teaball-*.db"))


def test_kopiera_vagrar_gammal_kopia(tmp_path, agare, capsys):
    """En kvarlämnad kopia ska inte sparas som dagens."""
    kalla, mal = _ogonblick(tmp_path, "a.example.org")
    gammal = time.time() - 7 * 3600
    os.utime(kalla / "a.example.org.db", (gammal, gammal))
    assert kopiera.main(["x", str(kalla), str(mal)]) == 1
    assert "äldre än sex timmar" in capsys.readouterr().err


def test_kopiera_vagrar_for_stor_fil(tmp_path, agare, monkeypatch, capsys):
    """En gles fil på hundratals GB kostar containern nästan inget men hade
    fyllt backupmålet."""
    monkeypatch.setattr(kopiera, "STORSTA_MB", 1)
    kalla, mal = _ogonblick(tmp_path, "a.example.org")
    with open(kalla / "b.example.org.db", "wb") as f:
        f.truncate(5 * kopiera.BLOCK)
    assert kopiera.main(["x", str(kalla), str(mal)]) == 1
    assert "större än 1 MB" in capsys.readouterr().err
    assert not (mal / "b.example.org").exists()


def test_kopiera_vagrar_manga_filer(tmp_path, agare, monkeypatch, capsys):
    monkeypatch.setattr(kopiera, "STORSTA_ANTAL", 2)
    kalla, mal = _ogonblick(tmp_path, "a.example.org", "b.example.org", "c.example.org")
    assert kopiera.main(["x", str(kalla), str(mal)]) == 1
    assert "fler än 2" in capsys.readouterr().err
    assert list(mal.iterdir()) == []


def test_integritetskontrollen_kor_utan_formagor(tmp_path, monkeypatch):
    """Kontrollen körs i en underprocess via setpriv, inte i processen som
    har CAP_DAC_READ_SEARCH."""
    anrop = []
    riktig = subprocess.run

    def spela_in(cmd, **kw):
        anrop.append(cmd)
        return riktig(cmd, **kw)

    monkeypatch.setattr(kopiera.subprocess, "run", spela_in)
    kalla, _ = _ogonblick(tmp_path, "a.example.org")
    assert kopiera.integritet(str(kalla / "a.example.org.db")) == "ok"
    assert anrop[0][1:3] == ["--inh-caps=-all", "--ambient-caps=-all"]
