"""Lås från rankning (migration 0008): noden syns men kan inte bedömas —
knapparna är utgråade med förvaltarens kommentar, tjänsten spärrar svaret,
och räknaren, "dölj bedömda" och roadmapen behandlar noden som ej bedömbar."""

from tests.conftest import (
    csrf_fran,
    ge_token,
    klient_fabrik,  # noqa: F401  (fixture)
    logga_in,
    satt_svar,
    seed_trad,
    skapa_medlem,
)

KOMMENTAR = "Beslutat av styrgruppen"


def _nodformular(**extra):
    """Formulärfälten för Registrera avhandling, som det sparas från trädet."""
    return {"namn": "Registrera avhandling", "foralder_id": "", "typ": "funktion",
            "status": "planerad", "fas": "Avgång 1", "synlig_externt": "1", **extra}


def _las(client, app_db, ids):
    token = csrf_fran(client.get("/trad").text)
    data = _nodformular(foralder_id=str(ids["publicering"]),
                        rankning_last="1", rankning_last_kommentar=f"  {KOMMENTAR}  ",
                        csrf_token=token)
    svar = client.post(f"/trad/nod/{ids['registrera']}", data=data, follow_redirects=False)
    assert svar.status_code == 303
    return token


def _medlemsklient(app_db, klient_fabrik, medlem):
    klient = klient_fabrik()
    klient.get(f"/svara/{ge_token(app_db, medlem)}", follow_redirects=False)
    return klient


def test_lasning_sparas_och_syns_i_tradet(client, app_db):
    ids = seed_trad(app_db)
    logga_in(client, app_db)
    _las(client, app_db, ids)
    rad = app_db.execute("SELECT rankning_last, rankning_last_kommentar FROM funktion"
                         " WHERE id = ?", (ids["registrera"],)).fetchone()
    assert (rad[0], rad[1]) == (1, KOMMENTAR)
    sida = client.get("/trad").text
    assert f'title="Låst från rankning: {KOMMENTAR}"><svg' in sida
    assert '</svg> låst</span>' in sida
    # Formuläret visar läget, så en ny redigering inte råkar låsa upp.
    form = client.get(f"/trad/nod/{ids['registrera']}/redigera").text
    assert "checked" in form.split('name="rankning_last"', 1)[1].split(">", 1)[0]
    assert f'value="{KOMMENTAR}"' in form


def test_listans_redigering_behaller_och_tar_bort_laset(client, app_db):
    ids = seed_trad(app_db)
    logga_in(client, app_db)
    token = _las(client, app_db, ids)
    data = _nodformular(foralder_id=str(ids["publicering"]),
                        rankning_last="1", rankning_last_kommentar=KOMMENTAR,
                        beskrivning="Ny text", csrf_token=token)
    client.post(f"/lista/nod/{ids['registrera']}", data=data)
    assert app_db.execute("SELECT rankning_last FROM funktion WHERE id = ?",
                          (ids["registrera"],)).fetchone()[0] == 1
    # Urkryssad ruta låser upp; kommentaren ligger kvar till nästa lås.
    del data["rankning_last"]
    client.post(f"/lista/nod/{ids['registrera']}", data=data)
    rad = app_db.execute("SELECT rankning_last, rankning_last_kommentar FROM funktion"
                         " WHERE id = ?", (ids["registrera"],)).fetchone()
    assert (rad[0], rad[1]) == (0, KOMMENTAR)


def test_medlem_ser_utgraade_knappar_och_kan_inte_svara(client, app_db, klient_fabrik):
    ids = seed_trad(app_db)
    medlem = skapa_medlem(app_db, "Uppsala universitet")
    satt_svar(app_db, medlem, ids["registrera"], "kan_vanta")
    app_db.commit()
    logga_in(client, app_db)
    _las(client, app_db, ids)

    klient = _medlemsklient(app_db, klient_fabrik, medlem)
    sida = klient.get("/svara").text
    rad = sida.split(f'id="rad-{ids["registrera"]}"', 1)[1].split('id="rad-', 1)[0]
    # Alla tre knapparna finns men är inaktiverade; det tidigare svaret syns.
    assert rad.count("disabled") == 3
    intryckt = rad.split('aria-pressed="true"', 1)[1].split("</button>", 1)[0]
    assert intryckt.endswith(">Kan vänta")
    assert f"</svg> Låst från rankning: {KOMMENTAR}" in rad
    assert f'action="/svara/{ids["registrera"]}/svar"' not in rad
    # Tjänsten spärrar även en direkt POST, och svaret står kvar.
    svar = klient.post(f"/svara/{ids['registrera']}/svar", data={"svar": "golive_krav"},
                       headers={"X-CSRF-Token": csrf_fran(sida)})
    assert svar.status_code == 400
    assert app_db.execute("SELECT svar FROM bedomning WHERE funktion_id = ?",
                          (ids["registrera"],)).fetchone()[0] == "kan_vanta"


def test_last_nod_raknas_inte_och_doljs_inte_som_obedomd(app_db, klient_fabrik, client):
    ids = seed_trad(app_db)
    medlem = skapa_medlem(app_db, "Uppsala universitet")
    app_db.commit()
    logga_in(client, app_db)
    _las(client, app_db, ids)

    klient = _medlemsklient(app_db, klient_fabrik, medlem)
    # Fyra bedömbara noder i seeden; den låsta räknas inte längre.
    assert "<strong>0</strong> av 3 bedömda" in klient.get("/svara").text
    # "Dölj bedömda" visar bara det som går att bedöma — inte den låsta.
    assert f'id="rad-{ids["registrera"]}"' not in klient.get("/svara?dolj_bedomda=1").text
    # Roadmapen märker noden som låst i stället för "ej bedömd".
    roadmap = klient.get("/svara/roadmap").text
    rad = roadmap.split(f'id="rad-{ids["registrera"]}"', 1)[1].split("</li>", 1)[0]
    assert "</svg> låst" in rad and "ej bedömd" not in rad
