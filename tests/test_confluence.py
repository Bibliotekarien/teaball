"""Confluence wiki-markup exports (first sweep): markup shape, escaping, routes."""

from app.services import confluence
from tests.conftest import (
    logga_in,
    satt_svar,
    seed_trad,
    skapa_funktion,
    skapa_medlem,
)

DATUM = "2026-08-27"


def test_kravtrad_markup(conn):
    seed_trad(conn)
    ut = confluence.kravtrad(conn, DATUM)
    assert ut.startswith("h1. Kravträd — Teaball")
    assert f"_Exporterad {DATUM}._" in ut
    assert "|| Namn || Typ || Status || Fas || Synlig för medlemmar ||" in ut
    # förmåga is bolded; a child is indented one middot level.
    assert "| *Publicering* | förmåga | Driftsatt |" in ut
    assert "| · Registrera avhandling | funktion |" in ut


def test_cell_escaping_av_pipe(conn):
    # A pipe in a name would otherwise start a new table column.
    skapa_funktion(conn, "A|B{macro}", typ="förmåga", status="planerad")
    conn.commit()
    ut = confluence.kravtrad(conn, DATUM)
    assert "A\\|B\\{macro\\}" in ut


def test_analys_markup_med_varning(conn):
    ids = seed_trad(conn)                     # Dubblettdetektering: krav, idé, fas senare
    medlem = skapa_medlem(conn, "Uppsala universitet")
    satt_svar(conn, medlem, ids["dubblett"], "golive_krav")
    conn.commit()
    ut = confluence.analys(conn, arvda=False, genererad=DATUM)
    assert ut.startswith("h1. Analys — blockerar-rankning")
    assert "{info}1 av 1 medlemmar" in ut
    assert "|| Nod || Status || Fas ||" in ut
    # golive on an 'idé/senare' node raises the N2 warning, rendered as (!).
    assert "(!) blockerar go-live" in ut


def test_roadmap_markup(conn):
    seed_trad(conn)
    ut = confluence.roadmap(conn, visa_krav=True, genererad=DATUM)
    assert "h1. Roadmap — Teaball" in ut
    # seed_trad only uses 'senare' and unphased nodes.
    assert "h2. Senare" in ut and "h2. Utan fas" in ut
    assert "|| Namn || Typ || Status ||" in ut


def test_medlemmar_markup(conn):
    ids = seed_trad(conn)
    a = skapa_medlem(conn, "Uppsala universitet", kategori="universitet")
    skapa_medlem(conn, "Riksarkivet")
    satt_svar(conn, a, ids["dubblett"], "golive_krav")
    conn.commit()
    ut = confluence.medlemmar(conn, DATUM)
    assert "|| Namn || Kategori || Har lämnat svar ||" in ut
    assert "| Uppsala universitet | universitet | ja |" in ut
    assert "| Riksarkivet |   | nej |" in ut           # empty kategori → single space


def test_confluence_route(client, app_db):
    seed_trad(app_db)
    logga_in(client, app_db)
    svar = client.get("/export/confluence/kravtrad")
    assert svar.status_code == 200
    assert svar.headers["content-type"] == "text/plain; charset=utf-8"
    assert svar.text.startswith("h1. Kravträd")
    # Unknown view is a 404, not a 500.
    assert client.get("/export/confluence/finns-ej").status_code == 404


def test_confluence_route_kraver_forvaltare(client, app_db):
    seed_trad(app_db)
    # No admin session → the admin-only export redirects to login, never served.
    svar = client.get("/export/confluence/kravtrad", follow_redirects=False)
    assert svar.status_code == 303 and svar.headers["location"] == "/login"
