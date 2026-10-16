"""Migration 0002: a production database on the old status vocabulary must
survive the funktion/bedomning rebuild with every row, relation and trigger
intact. Migration 0003: staff accounts gain a role; pre-existing accounts
must come out as admin so nobody is locked out at deploy."""

import sqlite3
from pathlib import Path

import pytest

from app import db

ROT = Path(__file__).resolve().parent.parent


def gammal_produktionsdb(tmp_path) -> sqlite3.Connection:
    """A database exactly as production looked before 0002: schema 0001,
    views/triggers in place, data using the old status names."""
    conn = db.connect(tmp_path / "gammal.db")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migration ("
        " version INTEGER PRIMARY KEY,"
        " applied TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    sql = (ROT / "db" / "migrations" / "0001_init.sql").read_text("utf-8")
    conn.executescript(
        "BEGIN;\n" + sql + "\nINSERT INTO schema_migration (version) VALUES (1);\nCOMMIT;"
    )
    # Stand-ins for the old view/trigger definitions (today's views_triggers.sql
    # no longer compiles against the 0001 schema). The migration only needs
    # objects with these names to exist — it drops them before the renames.
    conn.executescript(
        """
        CREATE VIEW funktion_trad AS
            SELECT f.*, 0 AS djup, '' AS vag, 1 AS synlig_stig FROM funktion f;
        CREATE VIEW bedomning_direkt AS SELECT * FROM bedomning;
        CREATE VIEW bedomning_effektiv AS SELECT * FROM bedomning;
        CREATE TRIGGER bedomning_hist_update BEFORE UPDATE ON bedomning BEGIN
            INSERT INTO bedomning_historik (medlem_id, funktion_id, svar)
            VALUES (OLD.medlem_id, OLD.funktion_id, OLD.svar);
        END;
        CREATE TRIGGER funktion_cykel_insert BEFORE INSERT ON funktion
        WHEN NEW.foralder_id = NEW.id BEGIN
            SELECT RAISE(ABORT, 'CYKEL: egen förälder.');
        END;
        """
    )

    # Parent with a HIGHER id than its child: the rebuild copies rows in id
    # order, so the child is inserted before its parent — this only works
    # because the migration defers FK checks to COMMIT.
    conn.execute("INSERT INTO funktion (id, namn, typ, status, fas) VALUES"
                 " (5, 'Publicering', 'förmåga', 'befintlig', 'nu')")
    conn.execute("INSERT INTO funktion (id, namn, foralder_id, typ, status) VALUES"
                 " (2, 'Spikblad', 5, 'krav', 'planerad')")
    conn.execute("INSERT INTO funktion (id, namn, typ, status) VALUES"
                 " (7, 'Statistik', 'funktion', 'idé')")
    conn.execute("INSERT INTO funktion (id, namn, typ, status) VALUES"
                 " (8, 'Gammal exportmodul', 'funktion', 'utgår')")
    conn.execute("INSERT INTO forvaltare (anvandarnamn, losen_hash) VALUES ('anna', 'hash')")
    conn.execute("INSERT INTO medlem (id, namn) VALUES (1, 'Uppsala universitet')")
    conn.execute("INSERT INTO bedomning (medlem_id, funktion_id, svar, workaround,"
                 " workaround_delas) VALUES (1, 2, 'kan_vanta', 'Manuellt.', 1)")
    conn.execute("INSERT INTO bedomning (medlem_id, funktion_id, svar) VALUES"
                 " (1, 7, 'golive_krav')")
    conn.execute("INSERT INTO bedomning_historik (medlem_id, funktion_id, svar)"
                 " VALUES (1, 2, 'behovs_ej')")
    conn.commit()
    return conn


def test_0002_bevarar_data_och_relationer(tmp_path):
    conn = gammal_produktionsdb(tmp_path)
    db.init_db(conn)  # applies 0002 and recreates views/triggers, as at startup

    status = {r["namn"]: r["status"] for r in conn.execute("SELECT namn, status FROM funktion")}
    assert status == {"Publicering": "driftsatt", "Spikblad": "planerad",
                      "Statistik": "idé", "Gammal exportmodul": "utgår"}

    # Ids, the parent relation and the assessments survived.
    barn = conn.execute("SELECT foralder_id FROM funktion WHERE id = 2").fetchone()
    assert barn["foralder_id"] == 5
    bed = conn.execute("SELECT * FROM bedomning ORDER BY funktion_id").fetchall()
    assert [(r["funktion_id"], r["svar"]) for r in bed] == [(2, "kan_vanta"), (7, "golive_krav")]
    assert bed[0]["workaround"] == "Manuellt." and bed[0]["workaround_delas"] == 1
    assert conn.execute("SELECT COUNT(*) FROM bedomning_historik").fetchone()[0] == 1

    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    index = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND name LIKE 'idx_%'")}
    assert {"idx_funktion_foralder", "idx_funktion_fas", "idx_bedomning_funktion"} <= index
    versioner = {r["version"] for r in conn.execute("SELECT version FROM schema_migration")}
    assert 2 in versioner


def test_0002_nya_vokabularet_och_kolumnerna(tmp_path):
    conn = gammal_produktionsdb(tmp_path)
    db.init_db(conn)

    conn.execute("INSERT INTO funktion (namn, typ, status, lank_dokumentation, lank_jira)"
                 " VALUES ('Ny', 'krav', 'utreds', 'https://dok.example', 'https://jira.example')")
    rad = conn.execute("SELECT * FROM funktion WHERE namn = 'Ny'").fetchone()
    assert rad["lank_dokumentation"] == "https://dok.example"

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO funktion (namn, typ, status) VALUES ('X', 'krav', 'befintlig')")

    # Old rows got NULL in the new columns.
    assert conn.execute("SELECT lank_jira FROM funktion WHERE id = 5").fetchone()[0] is None


def test_migration_tar_sakerhetskopia_fore(tmp_path):
    conn = gammal_produktionsdb(tmp_path)
    db.init_db(conn)

    # The copy is named for the highest pending version in the batch.
    kopior = list(tmp_path.glob("gammal.fore-0006-*.db"))
    assert len(kopior) == 1
    gammal = sqlite3.connect(kopior[0])
    gammal.row_factory = sqlite3.Row
    status = {r["status"] for r in gammal.execute("SELECT status FROM funktion")}
    gammal.close()
    # The copy holds the pre-migration state, ready to be copied back.
    assert "befintlig" in status and "driftsatt" not in status

    # Nothing pending on rerun → no second copy.
    db.migrate(conn)
    assert len(list(tmp_path.glob("gammal.fore-*.db"))) == 1


def test_farsk_databas_far_ingen_kopia(tmp_path):
    conn = db.connect(tmp_path / "ny.db")
    db.init_db(conn)
    conn.close()
    assert list(tmp_path.glob("ny.fore-*.db")) == []


def test_0002_triggers_och_vyer_fungerar_efterat(tmp_path):
    conn = gammal_produktionsdb(tmp_path)
    db.init_db(conn)

    # D2 history trigger fires on the rebuilt bedomning ...
    conn.execute("UPDATE bedomning SET svar = 'golive_krav' WHERE funktion_id = 2")
    assert conn.execute("SELECT COUNT(*) FROM bedomning_historik").fetchone()[0] == 2
    # ... the D1 cycle guard is armed on the rebuilt funktion ...
    with pytest.raises(sqlite3.IntegrityError, match="CYKEL"):
        conn.execute("UPDATE funktion SET foralder_id = 2 WHERE id = 5")
    # ... and the tree view sees the copied hierarchy.
    djup = {r["namn"]: r["djup"] for r in conn.execute("SELECT namn, djup FROM funktion_trad")}
    assert djup["Publicering"] == 0 and djup["Spikblad"] == 1

    # Rerunning migrations is a no-op.
    db.migrate(conn)
    assert conn.execute("SELECT COUNT(*) FROM funktion").fetchone()[0] == 4


def test_0003_befintliga_konton_blir_admin(tmp_path):
    conn = gammal_produktionsdb(tmp_path)
    db.init_db(conn)  # applies 0002 + 0003

    rad = conn.execute(
        "SELECT roll, senast_inloggad FROM forvaltare WHERE anvandarnamn = 'anna'"
    ).fetchone()
    assert rad["roll"] == "admin"
    # 0004: the activity stamp starts empty ("never") for pre-existing rows.
    assert rad["senast_inloggad"] is None
    # New rows without an explicit role also default to admin.
    conn.execute("INSERT INTO forvaltare (anvandarnamn, losen_hash) VALUES ('ny', 'hash')")
    assert conn.execute(
        "SELECT roll FROM forvaltare WHERE anvandarnamn = 'ny'"
    ).fetchone()["roll"] == "admin"


def test_0005_stamplar_startar_tomma(tmp_path):
    conn = gammal_produktionsdb(tmp_path)
    db.init_db(conn)  # applies 0002–0005

    # Pre-existing rows keep NULL ("before tracking") rather than a fake
    # migration-moment stamp; the list view sorts them last.
    rad = conn.execute("SELECT skapad, uppdaterad FROM funktion WHERE id = 5").fetchone()
    assert rad["skapad"] is None and rad["uppdaterad"] is None
    # New rows are stamped by the trigger.
    conn.execute("INSERT INTO funktion (namn, typ, status) VALUES ('Ny', 'krav', 'utreds')")
    ny = conn.execute("SELECT skapad, uppdaterad FROM funktion WHERE namn = 'Ny'").fetchone()
    assert ny["skapad"] is not None and ny["uppdaterad"] == ny["skapad"]


def test_0003_roll_utanfor_vokabularet_avvisas(tmp_path):
    conn = db.connect(tmp_path / "ny.db")
    db.init_db(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO forvaltare (anvandarnamn, losen_hash, roll)"
                     " VALUES ('x', 'hash', 'chef')")
    conn.close()
