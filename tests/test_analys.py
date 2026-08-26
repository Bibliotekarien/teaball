"""Tests for the analysis views (5.3): N1 ranking, N2 flag, N3 coverage,
the A3 toggle, N5 outstanding blockers, N6 ordering and N7 — including the
scenario in acceptance test §9.5 (3 of 6 members have answered)."""

from app.services import analys as tjanst
from tests.conftest import logga_in, satt_svar, seed_trad, skapa_medlem


def _scenario(app_db):
    ids = seed_trad(app_db)
    m = {
        "uu": skapa_medlem(app_db, "Uppsala universitet", "universitet"),
        "kth": skapa_medlem(app_db, "Kungliga Tekniska högskolan", "universitet"),
        "hig": skapa_medlem(app_db, "Högskolan i Gävle", "högskola"),
        "umu": skapa_medlem(app_db, "Umeå universitet", "universitet"),
        "sh": skapa_medlem(app_db, "Södertörns högskola", "högskola"),
        "nrm": skapa_medlem(app_db, "Naturhistoriska riksmuseet", "museum"),
    }
    # 3 of 6 answer. Dubblettdetektering has status 'idé' and fas 'senare' → N2.
    satt_svar(app_db, m["uu"], ids["dubblett"], "golive_krav")
    satt_svar(app_db, m["uu"], ids["import"], "kan_vanta", workaround="Manuell dedupe.", workaround_delas=0)
    satt_svar(app_db, m["uu"], ids["export"], "golive_krav")   # status driftsatt → not a blocker
    satt_svar(app_db, m["kth"], ids["dubblett"], "golive_krav")
    satt_svar(app_db, m["kth"], ids["wos"], "golive_krav")     # status planerad → blocker
    satt_svar(app_db, m["hig"], ids["publicering"], "kan_vanta")
    app_db.commit()
    return ids, m


def test_n1_n2_n3_via_sidan(client, app_db):
    _scenario(app_db)
    logga_in(client, app_db)
    sida = client.get("/analys").text
    assert "3 av 6" in sida                                # N3 (§9.5)
    assert "Umeå universitet" in sida                      # listed as non-responder
    assert "blockerar go-live men ligger i" in sida        # N2 flag (§9.5)
    assert "Workaround-bank:" in sida                      # N4, with names + unshared
    assert "Manuell dedupe." in sida
    assert "(ej delad)" in sida
    assert "Uppsala universitet" in sida


def test_n1_ordning_och_n2_villkor(app_db):
    ids, _ = _scenario(app_db)
    rader = tjanst.rankning(app_db, arvda=False)
    assert rader[0]["id"] == ids["dubblett"] and rader[0]["golive"] == 2
    assert rader[0]["varning"] is True                     # idé + senare
    export_rad = next(r for r in rader if r["id"] == ids["export"])
    assert export_rad["varning"] is False                  # driftsatt, fas nu


def test_n2_varnar_aven_for_utreds(app_db):
    """'utreds' behaves exactly like 'idé' in the N2 warning: identified in
    Classic but undecided, so a go-live demand on it must be flagged."""
    ids, m = _scenario(app_db)
    from tests.conftest import skapa_funktion
    classic = skapa_funktion(app_db, "Classic-avisering", typ="funktion", status="utreds")
    satt_svar(app_db, m["uu"], classic, "golive_krav")
    app_db.commit()
    rader = {r["id"]: r for r in tjanst.rankning(app_db)}
    assert rader[classic]["varning"] is True
    # ... and it stays an outstanding blocker until driftsatt.
    _, blockerare = tjanst.medlemsprofil(app_db, m["uu"])
    assert classic in {b["id"] for b in blockerare}


def test_a3_vaxel_direkta_mot_arvda(app_db):
    ids, _ = _scenario(app_db)
    direkt = {r["id"]: r for r in tjanst.rankning(app_db, arvda=False)}
    arvda = {r["id"]: r for r in tjanst.rankning(app_db, arvda=True)}
    # Registrera avhandling has no direct answers, but inherits HiG's kan_vanta
    # from Publicering when the toggle is on.
    assert ids["registrera"] not in direkt
    assert arvda[ids["registrera"]]["kan_vanta"] == 1
    # Direct counting (the default) must not be inflated.
    assert direkt[ids["publicering"]]["kan_vanta"] == 1
    assert arvda[ids["dubblett"]]["golive"] == 2


def test_n5_utestaende_blockerare(app_db):
    ids, m = _scenario(app_db)
    _, blockerare = tjanst.medlemsprofil(app_db, m["kth"])
    assert {b["id"] for b in blockerare} == {ids["dubblett"], ids["wos"]}
    _, blockerare_uu = tjanst.medlemsprofil(app_db, m["uu"])
    # Export & spridning is 'driftsatt' — not an outstanding blocker.
    assert {b["id"] for b in blockerare_uu} == {ids["dubblett"]}


def test_n6_migreringsordning(app_db, client):
    _, m = _scenario(app_db)
    oversikt = tjanst.migreringsoversikt(app_db)
    namn = [r["namn"] for r in oversikt]
    # Responders ascending by blockers: HiG (0), UU (1), KTH (2); silent members last.
    assert namn[:3] == ["Högskolan i Gävle", "Uppsala universitet", "Kungliga Tekniska högskolan"]
    assert all(not r["har_svarat"] for r in oversikt[3:])
    logga_in(client, app_db)
    assert "har inte svarat" in client.get("/analys/medlemmar").text


def test_n7_gemensamma_namnare(app_db, client):
    ids, m = _scenario(app_db)
    kraver = tjanst.kraver_noden(app_db, ids["dubblett"])
    assert {k["namn"] for k in kraver} == {"Uppsala universitet", "Kungliga Tekniska högskolan"}
    assert {k["kategori"] for k in kraver} == {"universitet"}

    delade = tjanst.gemensamma_krav(app_db, [m["uu"], m["kth"]])
    assert [d["id"] for d in delade] == [ids["dubblett"]]

    logga_in(client, app_db)
    sida = client.get("/analys/gemensamt",
                      params={"funktion_id": ids["dubblett"],
                              "medlem_id": [m["uu"], m["kth"]]}).text
    assert "2 medlemmar kräver ”Dubblettdetektering”" in sida
    assert "delas av alla 2 valda" in sida
