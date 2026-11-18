"""Svarsläget i analysen: en stapel per medlem med andelen besvarade noder,
räknad som medlemmens egen räknare i svarsvyn."""

from app.services import analys
from tests.conftest import (
    huvuddel, logga_in, satt_svar, seed_trad, skapa_funktion, skapa_medlem,
)


def _per_namn(conn):
    return {r["namn"]: r for r in analys.svarsgrad(conn)}


def test_rakna_som_medlemmens_svarsvy(conn, trad):
    """seed_trad: Publicering och Export är driftsatta och räknas inte; kvar
    att besvara är Registrera, Import, WoS och Dubblett. En dold och en låst
    nod räknas inte heller."""
    dold = skapa_funktion(conn, "Dold", trad["import"], synlig_externt=0)
    skapa_funktion(conn, "Under dold", dold)
    last = skapa_funktion(conn, "Låst", trad["import"])
    conn.execute("UPDATE funktion SET rankning_last = 1 WHERE id = ?", (last,))
    klar = skapa_medlem(conn, "Klar")
    halv = skapa_medlem(conn, "Halv")
    skapa_medlem(conn, "Tyst")
    # Svaret på Import ärvs av WoS och Dubblett — samma som i svarsvyn.
    satt_svar(conn, klar, trad["registrera"], "behovs_ej")
    satt_svar(conn, klar, trad["import"], "golive_krav")
    satt_svar(conn, halv, trad["registrera"], "kan_vanta")
    satt_svar(conn, halv, trad["wos"], "kan_vanta")
    conn.commit()

    rader = _per_namn(conn)
    assert (rader["Klar"]["bedomda"], rader["Klar"]["totalt"]) == (4, 4)
    assert rader["Klar"]["lage"] == "klar" and rader["Klar"]["andel"] == 100
    assert (rader["Halv"]["bedomda"], rader["Halv"]["totalt"]) == (3, 4)
    assert rader["Halv"]["lage"] == "påbörjad" and rader["Halv"]["andel"] == 75
    assert rader["Tyst"]["lage"] == "ej påbörjad" and rader["Tyst"]["andel"] == 0
    # Fallande andel — trappan.
    assert [r["namn"] for r in analys.svarsgrad(conn)] == ["Klar", "Halv", "Tyst"]


def test_tomt_trad_ger_inga_noder_att_besvara(conn):
    skapa_medlem(conn, "Ensam")
    conn.commit()
    rad = analys.svarsgrad(conn)[0]
    assert rad["totalt"] == 0 and rad["lage"] == "ej påbörjad"


def test_sidan_visar_staplar_och_tabell(client, app_db):
    ids = seed_trad(app_db)
    klar = skapa_medlem(app_db, "Klar")
    halv = skapa_medlem(app_db, "Halv")
    skapa_medlem(app_db, "Tyst")
    for nod in ("registrera", "import"):
        satt_svar(app_db, klar, ids[nod], "golive_krav")
    satt_svar(app_db, halv, ids["registrera"], "kan_vanta")
    app_db.commit()
    logga_in(client, app_db, "ivar", roll="intern")

    sida = huvuddel(client.get("/analys/svarslage").text)
    assert "de 4 noder som går" in sida
    assert 'aria-label="Klar: 100 procent, har svarat på allt"' in sida
    assert 'aria-label="Halv: 25 procent, har börjat svara"' in sida
    assert 'aria-label="Tyst: 0 procent, har inte börjat"' in sida
    assert "bg-emerald-600" in sida and "bg-amber-400" in sida
    # Bara den klara stapeln bär ✓ — färgen skiljer inte ensam 98 från 100 %.
    assert sida.count(">✓</span>") == 1
    assert "1 av 4" in sida  # tabellen
    # Ärvda svar räknas alltid här, så sidan har ingen arvsväxel.
    assert 'name="arvda"' not in sida
    assert 'href="/analys/svarslage"' in huvuddel(client.get("/analys").text)


def test_extern_nar_inte_sidan(client, app_db):
    logga_in(client, app_db, "erik", roll="extern")
    assert client.get("/analys/svarslage", follow_redirects=False).status_code in (303, 403)
