"""Markdown-exporter: tabellform, escaping, routes. Syskon till test_confluence."""

from app.services import markdown
from tests.conftest import (
    logga_in,
    satt_svar,
    seed_trad,
    skapa_funktion,
    skapa_medlem,
)

DATUM = "2026-10-07"


def test_kravtrad_markdown(conn):
    ids = seed_trad(conn)
    ut = markdown.kravtrad(conn, DATUM)
    assert ut.startswith("# Behovsträd — Teaball\n")
    assert f"_Exporterad {DATUM}._" in ut
    assert ("| Namn | Typ | Status | Avgång | Synlig för medlemmar"
            " | Beskrivning | Jira | Dokumentation |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- |") in ut
    # Förmåga i fetstil; ett barn indraget en mittpunktsnivå. Nodnumret står
    # efter namnet, utanför fetstilen, så noden kan citeras i löptext.
    assert f"| **Publicering** ({ids['publicering']}) | förmåga | Driftsatt |" in ut
    assert f"| · Registrera avhandling ({ids['registrera']}) | funktion |" in ut
    assert ut.endswith("|\n")


def test_kravtrad_lankar_och_beskrivning(conn):
    skapa_funktion(conn, "Inloggning via SSO", typ="funktion",
                   beskrivning="Stöd för SAML mot lärosätenas IdP:er.",
                   lank_jira="https://jira.example/DIVA-1|x)y",
                   lank_dokumentation="https://wiki.example/sso")
    utan = skapa_funktion(conn, "Utan länkar", typ="krav")
    conn.commit()
    ut = markdown.kravtrad(conn, DATUM)
    # Beskrivningen får en egen kolumn — markdown kan inte fälla ihop celler.
    assert "| Stöd för SAML mot lärosätenas IdP:er. | [Jira](" in ut
    # '|' och ')' i en URL procentkodas så länkmålet inte klipps av.
    assert "[Jira](https://jira.example/DIVA-1%7Cx%29y)" in ut
    assert "[Dokumentation](https://wiki.example/sso)" in ut
    # Noder utan länkar och beskrivning får tomma celler.
    assert f"| Utan länkar ({utan}) | behov |" in ut
    assert "|  |  |  |\n" in ut


def test_cell_escaping(conn):
    # Pipe skulle börja en ny kolumn; asterisk, understreck och hakparentes
    # skulle bli formatering eller länk.
    skapa_funktion(conn, "A|B *fet* [x]_y_", typ="förmåga", status="planerad")
    conn.commit()
    ut = markdown.kravtrad(conn, DATUM)
    assert "**A\\|B \\*fet\\* \\[x\\]\\_y\\_**" in ut


def test_analys_markdown_med_varning(conn):
    ids = seed_trad(conn)                     # Dubblettdetektering: krav, idé, fas senare
    medlem = skapa_medlem(conn, "Uppsala universitet")
    satt_svar(conn, medlem, ids["dubblett"], "golive_krav")
    conn.commit()
    ut = markdown.analys(conn, arvda=False, genererad=DATUM)
    assert ut.startswith("# Analys — blockerar-rankning\n")
    assert "> 1 av 1 medlemmar" in ut
    assert "| Nod | Status | Avgång |" in ut
    assert f"| Dubblettdetektering ({ids['dubblett']}) | Idé |" in ut
    # golive på en 'idé/senare'-nod ger N2-varningen.
    assert "⚠ blockerar go-live" in ut


def test_lank_kodar_allt_utanfor_url_strukturen(conn):
    # Säkerhetsgranskningen av PR #37: '<' '>' '"' och radbrytning i en URL
    # bröt cellen/raden. Strukturtecken och redan kodade sekvenser bevaras.
    skapa_funktion(conn, "Länkad", typ="funktion",
                   lank_jira='https://j.example/a b<c>"d\ne|f)g',
                   lank_dokumentation="https://w.example/p%20q?x=1&y=å#frag")
    conn.commit()
    ut = markdown.kravtrad(conn, DATUM)
    assert "[Jira](https://j.example/a%20b%3Cc%3E%22d%0Ae%7Cf%29g)" in ut
    assert "[Dokumentation](https://w.example/p%20q?x=1&y=%C3%A5#frag)" in ut
    assert all(rad.startswith("|") for rad in ut.splitlines()[4:])


def test_avgangsnamn_escapas_i_rubriken(conn):
    # Avgångsnamnet är fri admin-text; [x](url) får inte bli en länk i rubriken.
    skapa_funktion(conn, "Något", typ="funktion", fas="q2 [x](https://e.example) *fet*")
    conn.commit()
    ut = markdown.roadmap(conn, visa_krav=False, genererad=DATUM)
    assert "## Q2 \\[x\\](https://e.example) \\*fet\\*" in ut


def test_roadmap_markdown(conn):
    ids = seed_trad(conn)
    conn.execute("UPDATE funktion SET fas = NULL WHERE id = ?", (ids["dubblett"],))
    ut = markdown.roadmap(conn, visa_krav=True, genererad=DATUM)
    assert "# Roadmap — Teaball" in ut
    assert "## Avgång 1" in ut and "## Senare" in ut and "## Utan avgång" in ut
    assert "| Namn | Typ | Status |\n| --- | --- | --- |" in ut
    # Förmågeraden är hierarkikontext utan status; funktionerna behåller sin.
    assert f"| **Publicering** ({ids['publicering']}) | förmåga |  |" in ut
    assert "Driftsatt" not in ut and "driftsatt" not in ut
    utan_formagor = markdown.roadmap(conn, visa_krav=True, genererad=DATUM,
                                     dolj_formagor=True)
    assert "Publicering" not in utan_formagor
    assert "Registrera avhandling" in utan_formagor


def test_medlemmar_markdown(conn):
    ids = seed_trad(conn)
    a = skapa_medlem(conn, "Uppsala universitet", kategori="universitet")
    skapa_medlem(conn, "Riksarkivet")
    satt_svar(conn, a, ids["dubblett"], "golive_krav")
    conn.commit()
    ut = markdown.medlemmar(conn, DATUM)
    assert "| Namn | Kategori | Har lämnat svar |" in ut
    assert "| Uppsala universitet | universitet | ja |" in ut
    assert "| Riksarkivet |  | nej |" in ut


def test_markdown_route(client, app_db):
    seed_trad(app_db)
    logga_in(client, app_db)
    svar = client.get("/export/markdown/kravtrad")
    assert svar.status_code == 200
    assert svar.headers["content-type"] == "text/markdown; charset=utf-8"
    disposition = svar.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="behovstrad-')
    assert disposition.endswith('.md"')
    assert svar.text.startswith("# Behovsträd")
    # Roadmapens filter följer med precis som för Confluence.
    assert client.get("/export/markdown/roadmap?visa_krav=1").status_code == 200
    # Okänd vy är 404, inte 500.
    assert client.get("/export/markdown/finns-ej").status_code == 404


def test_markdown_route_kraver_forvaltare(client, app_db):
    seed_trad(app_db)
    svar = client.get("/export/markdown/kravtrad", follow_redirects=False)
    assert svar.status_code == 303 and svar.headers["location"] == "/login"
