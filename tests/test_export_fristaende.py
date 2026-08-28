"""Standalone tree HTML export and the combined PDF report (tree + ranking).

WeasyPrint needs Pango system libraries; on machines without them the PDF
tests flip — the render test skips and the 503 test runs instead, so the suite
is green both on dev boxes and in the Docker image."""

import pytest

from app.services.analys import rankning
from tests.conftest import logga_in, satt_svar, seed_trad, skapa_funktion, skapa_medlem

try:
    import weasyprint  # noqa: F401 — probe only

    HAR_WEASYPRINT = True
except Exception:  # ImportError, or OSError when Pango is missing
    HAR_WEASYPRINT = False


def test_kravtrad_html_fullstandig(client, app_db):
    ids = seed_trad(app_db)
    app_db.execute(
        "UPDATE funktion SET beskrivning = 'Dubbletter ska flaggas vid import.',"
        " lank_jira = 'https://jira.example/DIVA-1',"
        " lank_dokumentation = 'https://wiki.example/dubbletter'"
        " WHERE id = ?",
        (ids["dubblett"],),
    )
    app_db.execute("UPDATE funktion SET synlig_externt = 0 WHERE id = ?", (ids["import"],))
    skapa_funktion(app_db, "Namn med <b>taggar</b>", typ="förmåga")
    app_db.commit()
    logga_in(client, app_db)

    export = client.get("/export/kravtrad.html")
    assert export.status_code == 200
    assert 'attachment; filename="kravtrad-' in export.headers["content-disposition"]
    # The full variant keeps hidden branches but tags them "intern".
    assert "Import från Web of Science" in export.text
    assert "intern" in export.text
    assert "Dubbletter ska flaggas vid import." in export.text
    assert 'href="https://jira.example/DIVA-1"' in export.text
    assert 'href="https://wiki.example/dubbletter"' in export.text
    # Script-free and autoescaped, like the R2 roadmap export.
    assert "<script" not in export.text
    assert "&lt;b&gt;taggar&lt;/b&gt;" in export.text


def test_kravtrad_html_endast_synliga(client, app_db):
    ids = seed_trad(app_db)
    app_db.execute("UPDATE funktion SET synlig_externt = 0 WHERE id = ?", (ids["import"],))
    app_db.commit()
    logga_in(client, app_db)

    export = client.get("/export/kravtrad.html?endast_synliga=1")
    assert export.status_code == 200
    assert 'filename="kravtrad-' in export.headers["content-disposition"]
    assert '-extern.html"' in export.headers["content-disposition"]
    # The hidden node and its whole subtree are gone (T5), siblings remain.
    assert "Import från Web of Science" not in export.text
    assert "Dubblettdetektering" not in export.text
    assert "Registrera avhandling" in export.text
    assert ">intern<" not in export.text


def test_kravtrad_html_kraver_forvaltare(client, app_db):
    seed_trad(app_db)
    svar = client.get("/export/kravtrad.html", follow_redirects=False)
    assert svar.status_code == 303 and svar.headers["location"] == "/login"


def test_rankning_endast_synliga(conn):
    ids = seed_trad(conn)
    medlem = skapa_medlem(conn, "Uppsala universitet")
    satt_svar(conn, medlem, ids["dubblett"], "golive_krav")
    satt_svar(conn, medlem, ids["registrera"], "kan_vanta")
    conn.execute("UPDATE funktion SET synlig_externt = 0 WHERE id = ?", (ids["import"],))
    conn.commit()

    alla = {r["namn"] for r in rankning(conn)}
    synliga = {r["namn"] for r in rankning(conn, endast_synliga=True)}
    # Dubblettdetektering sits under the hidden Import branch (T5) …
    assert "Dubblettdetektering" in alla
    assert "Dubblettdetektering" not in synliga
    # … while answers on visible nodes stay in the filtered ranking.
    assert "Registrera avhandling" in synliga


def test_rapport_mall_renderar(conn):
    """The PDF source template rendered directly — without this, a Jinja error
    in rapport.html would only surface in the Docker image, since the endpoint
    503:ar before rendering on machines where WeasyPrint cannot load."""
    from app.services.analys import tackning
    from app.services.exportera import kravtrad_rader
    from app.web import templates

    ids = seed_trad(conn)
    medlem = skapa_medlem(conn, "Uppsala universitet")
    satt_svar(conn, medlem, ids["dubblett"], "golive_krav")
    conn.commit()
    html = templates.get_template("exportera/rapport.html").render({
        "noder": kravtrad_rader(conn),
        "rankning": rankning(conn),
        "tackning": tackning(conn),
        "endast_synliga": False,
        "genererad": "2026-08-28",
    })
    assert "Blockerar-rankning" in html
    assert "Dubblettdetektering" in html
    assert "1 av 1 medlemmar" in html
    # The N2 warning badge follows the analys view's wording.
    assert "blockerar go-live men ligger i ”senare”" in html


@pytest.mark.skipif(not HAR_WEASYPRINT, reason="WeasyPrint/Pango saknas i miljön")
def test_rapport_pdf(client, app_db):
    ids = seed_trad(app_db)
    medlem = skapa_medlem(app_db, "Uppsala universitet")
    satt_svar(app_db, medlem, ids["dubblett"], "golive_krav")
    app_db.commit()
    logga_in(client, app_db)

    export = client.get("/export/rapport.pdf?endast_synliga=1")
    assert export.status_code == 200
    assert export.headers["content-type"] == "application/pdf"
    assert 'attachment; filename="teaball-rapport-' in export.headers["content-disposition"]
    assert '-extern.pdf"' in export.headers["content-disposition"]
    assert export.content.startswith(b"%PDF")


@pytest.mark.skipif(HAR_WEASYPRINT, reason="WeasyPrint finns — 503-vägen nås inte")
def test_rapport_pdf_utan_motor(client, app_db):
    seed_trad(app_db)
    logga_in(client, app_db)
    svar = client.get("/export/rapport.pdf")
    assert svar.status_code == 503
    assert "WeasyPrint" in svar.json()["detail"]
