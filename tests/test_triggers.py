"""Database-level tests for the D1 cycle guard, the avgång rule and the D2
history triggers, plus the connection PRAGMAs required by the spec (§2)."""

import sqlite3

import pytest

from app import db as appdb
from tests.conftest import skapa_funktion, skapa_medlem, satt_svar


def test_pragmas(conn):
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


# --- D1: cycle protection ---------------------------------------------------

def test_insert_self_parent_rejected(conn):
    # fas ifylld: ordningen mellan flera BEFORE-triggers är odefinierad i
    # SQLite, så bara cykelvillkoret får kunna matcha här.
    with pytest.raises(sqlite3.IntegrityError, match="CYKEL"):
        conn.execute(
            "INSERT INTO funktion (id, namn, foralder_id, typ, status, fas)"
            " VALUES (99, 'Själv', 99, 'krav', 'planerad', 'nu')"
        )


def test_update_to_self_rejected(conn, trad):
    with pytest.raises(sqlite3.IntegrityError, match="CYKEL"):
        conn.execute("UPDATE funktion SET foralder_id = ? WHERE id = ?",
                     (trad["import"], trad["import"]))


def test_update_to_direct_child_rejected(conn, trad):
    with pytest.raises(sqlite3.IntegrityError, match="CYKEL"):
        conn.execute("UPDATE funktion SET foralder_id = ? WHERE id = ?",
                     (trad["wos"], trad["import"]))


def test_acceptance_9_1_move_and_cycle(conn, trad):
    """Spec §9.1: move Dubblettdetektering to root, back again, then try to make
    its former ancestor its child — the cycle must be rejected with a clear error."""
    conn.execute("UPDATE funktion SET foralder_id = NULL WHERE id = ?", (trad["dubblett"],))
    conn.execute("UPDATE funktion SET foralder_id = ? WHERE id = ?",
                 (trad["wos"], trad["dubblett"]))
    with pytest.raises(sqlite3.IntegrityError, match="CYKEL"):
        conn.execute("UPDATE funktion SET foralder_id = ? WHERE id = ?",
                     (trad["dubblett"], trad["import"]))


def test_legal_moves_pass(conn, trad):
    # Reparenting to an unrelated branch is fine.
    conn.execute("UPDATE funktion SET foralder_id = ? WHERE id = ?",
                 (trad["export"], trad["dubblett"]))
    # And an answered leaf may move to root level.
    conn.execute("UPDATE funktion SET foralder_id = NULL WHERE id = ?", (trad["wos"],))


# --- Avgångskravet ----------------------------------------------------------

def test_insert_planerad_utan_fas_avvisas(conn):
    with pytest.raises(sqlite3.IntegrityError, match="AVGÅNG"):
        skapa_funktion(conn, "Utan avgång", status="planerad", fas=None)


def test_insert_driftsatt_med_blank_fas_avvisas(conn):
    # Routrarna lagrar strip() or None, men rå SQL kan lagra blanksteg —
    # triggern TRIM:ar.
    with pytest.raises(sqlite3.IntegrityError, match="AVGÅNG"):
        skapa_funktion(conn, "Blank", status="driftsatt", fas="   ")


def test_statusbyte_till_planerad_kraver_fas(conn):
    nod = skapa_funktion(conn, "Än så länge idé", status="idé", fas=None)
    with pytest.raises(sqlite3.IntegrityError, match="AVGÅNG"):
        conn.execute("UPDATE funktion SET status = 'planerad' WHERE id = ?", (nod,))


def test_fas_kan_inte_tas_bort_fran_driftsatt(conn, trad):
    with pytest.raises(sqlite3.IntegrityError, match="AVGÅNG"):
        conn.execute("UPDATE funktion SET fas = NULL WHERE id = ?",
                     (trad["publicering"],))


def test_befintlig_rad_utan_fas_ar_giltig_i_vila(conn):
    """En rad från tiden före kravet: flytt, sortering och synlighet rör inte
    status/fas och ska fungera — men en ändring som gör det tvingar fram en
    avgång. Simuleras genom att smyga in raden utan insert-triggern och sedan
    återskapa triggarna med samma funktion som appstarten kör."""
    conn.execute("DROP TRIGGER funktion_avgang_insert")
    gammal = skapa_funktion(conn, "Legacy", status="planerad", fas=None)
    annan_rot = skapa_funktion(conn, "Rot", status="utreds", fas=None)
    appdb.create_views_and_triggers(conn)

    conn.execute("UPDATE funktion SET foralder_id = ? WHERE id = ?", (annan_rot, gammal))
    conn.execute("UPDATE funktion SET sortering = 30 WHERE id = ?", (gammal,))
    conn.execute("UPDATE funktion SET synlig_externt = 0 WHERE id = ?", (gammal,))
    with pytest.raises(sqlite3.IntegrityError, match="AVGÅNG"):
        conn.execute("UPDATE funktion SET status = 'driftsatt' WHERE id = ?", (gammal,))


# --- D2: history ------------------------------------------------------------

def _historik(conn):
    return conn.execute(
        "SELECT * FROM bedomning_historik ORDER BY id"
    ).fetchall()


def test_history_on_update(conn, trad):
    m = skapa_medlem(conn, "Uppsala universitet")
    satt_svar(conn, m, trad["wos"], "kan_vanta",
              workaround="Cron-skript tills vidare.", kommentar="Privat notis.")
    satt_svar(conn, m, trad["wos"], "golive_krav")

    rows = _historik(conn)
    assert len(rows) == 1
    gammal = rows[0]
    assert gammal["svar"] == "kan_vanta"
    assert gammal["workaround"] == "Cron-skript tills vidare."
    assert gammal["kommentar"] == "Privat notis."

    aktuell = conn.execute(
        "SELECT svar FROM bedomning WHERE medlem_id = ? AND funktion_id = ?",
        (m, trad["wos"]),
    ).fetchone()
    assert aktuell["svar"] == "golive_krav"


def test_history_on_delete(conn, trad):
    m = skapa_medlem(conn, "Umeå universitet")
    satt_svar(conn, m, trad["wos"], "behovs_ej", kommentar="Ej relevant för oss.")
    conn.execute("DELETE FROM bedomning WHERE medlem_id = ? AND funktion_id = ?",
                 (m, trad["wos"]))

    rows = _historik(conn)
    assert len(rows) == 1
    assert rows[0]["svar"] == "behovs_ej"
    assert rows[0]["kommentar"] == "Ej relevant för oss."


# --- FK behaviour -----------------------------------------------------------

def test_delete_node_with_children_restricted(conn, trad):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM funktion WHERE id = ?", (trad["import"],))


def test_delete_member_cascades_answers(conn, trad):
    m = skapa_medlem(conn, "Södertörns högskola")
    satt_svar(conn, m, trad["wos"], "golive_krav")
    conn.execute("DELETE FROM medlem WHERE id = ?", (m,))
    kvar = conn.execute("SELECT COUNT(*) FROM bedomning WHERE medlem_id = ?", (m,)).fetchone()[0]
    assert kvar == 0
