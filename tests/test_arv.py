"""Tests for the inheritance rule (spec §4): the bedomning_effektiv view (A1/A4),
the source-node reference used by the "ärvt" label (A2), and column parity with
bedomning_direkt (the A3 toggle relies on the two views being interchangeable)."""

from tests.conftest import skapa_medlem, satt_svar


def effektiv(conn, medlem_id, funktion_id):
    return conn.execute(
        "SELECT * FROM bedomning_effektiv WHERE medlem_id = ? AND funktion_id = ?",
        (medlem_id, funktion_id),
    ).fetchone()


def test_answer_inherited_by_descendants(conn, trad):
    m = skapa_medlem(conn, "Uppsala universitet")
    satt_svar(conn, m, trad["import"], "kan_vanta")

    for nod in ("wos", "dubblett"):
        rad = effektiv(conn, m, trad[nod])
        assert rad["svar"] == "kan_vanta"
        assert rad["arvd"] == 1
        assert rad["kalla_funktion_id"] == trad["import"]

    # The answered node itself is direct, not inherited.
    egen = effektiv(conn, m, trad["import"])
    assert egen["arvd"] == 0 and egen["kalla_funktion_id"] == trad["import"]


def test_own_answer_overrides_inherited(conn, trad):
    m = skapa_medlem(conn, "Kungliga Tekniska högskolan")
    satt_svar(conn, m, trad["import"], "kan_vanta")
    satt_svar(conn, m, trad["wos"], "golive_krav")

    assert effektiv(conn, m, trad["wos"])["svar"] == "golive_krav"
    # Nearest ancestor wins for the grandchild: wos, not import.
    barn = effektiv(conn, m, trad["dubblett"])
    assert barn["svar"] == "golive_krav"
    assert barn["kalla_funktion_id"] == trad["wos"]


def test_no_answer_anywhere_means_absent(conn, trad):
    m = skapa_medlem(conn, "Högskolan i Gävle")
    satt_svar(conn, m, trad["export"], "golive_krav")
    # The Publicering branch has no answers for this member: absent, never a default.
    assert effektiv(conn, m, trad["publicering"]) is None
    assert effektiv(conn, m, trad["dubblett"]) is None


def test_removing_own_answer_reverts_to_inherited(conn, trad):
    m = skapa_medlem(conn, "Umeå universitet")
    satt_svar(conn, m, trad["import"], "kan_vanta")
    satt_svar(conn, m, trad["wos"], "behovs_ej")
    conn.execute("DELETE FROM bedomning WHERE medlem_id = ? AND funktion_id = ?",
                 (m, trad["wos"]))

    rad = effektiv(conn, m, trad["wos"])
    assert rad["svar"] == "kan_vanta"
    assert rad["arvd"] == 1 and rad["kalla_funktion_id"] == trad["import"]


def test_direct_view_parity_and_counts(conn, trad):
    """bedomning_direkt and bedomning_effektiv expose the same columns, and the
    A3 default (direct only) must not be inflated by inheritance."""
    m = skapa_medlem(conn, "Naturhistoriska riksmuseet")
    satt_svar(conn, m, trad["publicering"], "kan_vanta")

    kolumner = [d[0] for d in conn.execute("SELECT * FROM bedomning_direkt LIMIT 0").description]
    kolumner_eff = [d[0] for d in conn.execute("SELECT * FROM bedomning_effektiv LIMIT 0").description]
    assert kolumner == kolumner_eff == [
        "medlem_id", "funktion_id", "kalla_funktion_id", "svar", "arvd",
    ]

    direkt = conn.execute("SELECT COUNT(*) FROM bedomning_direkt WHERE medlem_id = ?", (m,)).fetchone()[0]
    effektivt = conn.execute("SELECT COUNT(*) FROM bedomning_effektiv WHERE medlem_id = ?", (m,)).fetchone()[0]
    assert direkt == 1          # only the answered node
    assert effektivt == 5       # the whole Publicering subtree (5 nodes), not Export
