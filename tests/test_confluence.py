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
    assert ("|| Namn || Typ || Status || Avgång || Synlig för medlemmar"
            " || Jira || Dokumentation ||") in ut
    # förmåga is bolded; a child is indented one middot level.
    assert "| *Publicering* | förmåga | Driftsatt |" in ut
    assert "| · Registrera avhandling | funktion |" in ut


def test_kravtrad_lankar_och_beskrivning(conn):
    skapa_funktion(conn, "Inloggning via SSO", typ="funktion",
                   beskrivning="Stöd för SAML mot lärosätenas IdP:er.",
                   lank_jira="https://jira.example/DIVA-1|x]y",
                   lank_dokumentation="https://wiki.example/sso")
    skapa_funktion(conn, "Utan länkar", typ="krav")
    conn.commit()
    ut = confluence.kravtrad(conn, DATUM)
    # The description folds into an {expand} in the name cell.
    assert ("| Inloggning via SSO \\\\ {expand:Beskrivning}"
            "Stöd för SAML mot lärosätenas IdP:er.{expand} |") in ut
    # Link cells; '|' and ']' in a URL are percent-encoded, not escaped.
    assert "| [Jira|https://jira.example/DIVA-1%7Cx%5Dy] |" in ut
    assert "| [Dokumentation|https://wiki.example/sso] |" in ut
    # Nodes without links get empty cells, and no empty expand appears.
    assert "| Utan länkar |" in ut
    assert "{expand:Beskrivning}{expand}" not in ut


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
    assert "|| Nod || Status || Avgång ||" in ut
    # golive on an 'idé/senare' node raises the N2 warning, rendered as (!).
    assert "(!) blockerar go-live" in ut


def test_roadmap_markup(conn):
    seed_trad(conn)
    ut = confluence.roadmap(conn, visa_krav=True, genererad=DATUM)
    assert "h1. Roadmap — Teaball" in ut
    # seed_trad only uses 'senare' and unphased nodes.
    assert "h2. Senare" in ut and "h2. Utan avgång" in ut
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
