"""Exports (spec E1 + the all-views Excel workbook + standalone-export data).

E1: whole database as JSON, tree + assessments as CSV.
kravtrad_rader feeds the standalone HTML/PDF exports rendered by the router.
XLSX: one workbook, one sheet per view (Kravträd, Bedömningar, Analys,
Migrering, Roadmap) with readable formatting — colored answer/status cells,
frozen header rows, tree indentation. Member token hashes never leave the
database in any export."""

import csv
import io
import json

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from app.services import analys as analys_tjanst
from app.services import roadmap as roadmap_tjanst
from app.services.bedomning import OPPEN_DELNING
from app.services.trad import TYP_LABEL, nodnamn

# Spreadsheet formula injection: Excel/LibreOffice execute a cell whose text
# starts with one of these. Member free-text (open and internal comments) and
# admin-set names reach both the CSV and XLSX exports, so a leading apostrophe
# neutralizes them — the tools then render the value as literal text. This is
# the only member→förvaltare escalation path in the system.
_FARLIGA_INLEDNINGAR = ("=", "+", "-", "@", "\t", "\r")


def _sakra(varde):
    if isinstance(varde, str) and varde[:1] in _FARLIGA_INLEDNINGAR:
        return "'" + varde
    return varde


def _sakra_rad(rad):
    return [_sakra(v) for v in rad]


SVAR_ETIKETT = {"golive_krav": "Go-live", "kan_vanta": "Kan vänta", "behovs_ej": "Behövs ej"}
# Light fill + dark text keeps the cells readable in Excel.
SVAR_STIL = {
    "golive_krav": ("FFE4E6", "9F1239"),
    "kan_vanta": ("FEF3C7", "92400E"),
    "behovs_ej": ("E7E5E4", "57534E"),
}
# Mirrors the STATUS scale in app/web.py (yellow planned, two blues undecided).
STATUS_STIL = {
    "driftsatt": ("D1FAE5", "065F46"),
    "planerad": ("FEF3C7", "92400E"),
    "utreds": ("BAE6FD", "0C4A6E"),
    "idé": ("E0F2FE", "075985"),
    "utgår": ("F5F5F4", "A8A29E"),
}


def kravtrad_rader(conn, endast_synliga: bool = False) -> list[dict]:
    """Tree rows for the standalone HTML and PDF exports. endast_synliga drops
    every node whose path is hidden (synlig_stig, T5), so the export matches
    exactly what members are allowed to see. Jinja autoescaping handles the
    free text — the formula guard is only for spreadsheet formats."""
    urval = "WHERE synlig_stig = 1" if endast_synliga else ""
    return [dict(r) for r in
            conn.execute(f"SELECT * FROM funktion_trad {urval} ORDER BY vag")]


def json_export(conn) -> str:
    ut = {}
    for tabell in ("funktion", "medlem", "bedomning", "bedomning_historik"):
        rows = [dict(r) for r in conn.execute(f"SELECT * FROM {tabell}")]  # fixed table list
        if tabell == "medlem":
            for rad in rows:
                rad.pop("token", None)
        ut[tabell] = rows
    return json.dumps(ut, ensure_ascii=False, indent=2)


def trad_csv(conn) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "namn", "foralder_id", "foralder_namn", "typ", "status",
                "fas", "synlig_externt", "djup", "lank_dokumentation", "lank_jira"])
    for r in conn.execute(
        """
        SELECT t.id, t.namn, t.foralder_id, f.namn AS foralder_namn,
               t.typ, t.status, t.fas, t.synlig_externt, t.djup,
               t.lank_dokumentation, t.lank_jira
        FROM funktion_trad t
        LEFT JOIN funktion f ON f.id = t.foralder_id
        ORDER BY t.vag
        """
    ):
        w.writerow(_sakra_rad([r["id"], r["namn"], r["foralder_id"], r["foralder_namn"],
                    r["typ"], r["status"], r["fas"], r["synlig_externt"], r["djup"],
                    r["lank_dokumentation"], r["lank_jira"]]))
    return buf.getvalue()


def bedomningar_csv(conn) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["medlem", "kategori", "funktion_id", "funktion", "svar",
                "oppen_kommentar", "oppen_delning", "intern_kommentar",
                "besvarat_av", "besvarat"])
    for r in conn.execute(
        """
        SELECT m.namn AS medlem, m.kategori, b.funktion_id, f.namn AS funktion,
               b.svar, b.oppen_kommentar, b.oppen_delning, b.intern_kommentar,
               b.besvarat_av, b.besvarat
        FROM bedomning b
        JOIN medlem m ON m.id = b.medlem_id
        JOIN funktion f ON f.id = b.funktion_id
        ORDER BY m.namn, f.namn
        """
    ):
        w.writerow(_sakra_rad([r["medlem"], r["kategori"], r["funktion_id"], r["funktion"],
                    r["svar"], r["oppen_kommentar"], r["oppen_delning"], r["intern_kommentar"],
                    r["besvarat_av"], r["besvarat"]]))
    return buf.getvalue()


# --- Excel workbook ---------------------------------------------------------

_RUBRIK = Font(bold=True, size=10)
_VANLIG = Font(size=10)
_FET = Font(size=10, bold=True)

# Style objects are shared across cells — openpyxl copies them into the
# stylesheet on assignment, and reuse keeps large exports fast.
_STILCACHE: dict[tuple[str, str], tuple[PatternFill, Font]] = {}


def _fyll(cell, stil):
    if stil not in _STILCACHE:
        fyllning, text = stil
        _STILCACHE[stil] = (
            PatternFill("solid", fgColor=fyllning),
            Font(size=10, color=text),
        )
    cell.fill, cell.font = _STILCACHE[stil]


def _rubrikrad(blad, rubriker, bredder, rad=1):
    for i, (rubrik, bredd) in enumerate(zip(rubriker, bredder), start=1):
        cell = blad.cell(row=rad, column=i, value=rubrik)
        cell.font = _RUBRIK
        blad.column_dimensions[get_column_letter(i)].width = bredd
    blad.freeze_panes = f"A{rad + 1}"


def _blad_trad(blad, conn):
    blad.title = "Behovsträd"
    _rubrikrad(blad, ["Namn", "Typ", "Status", "Avgång", "Synlig för medlemmar", "Beskrivning"],
               [55, 10, 11, 10, 19, 50])
    # blad.max_row is O(rows) in openpyxl — track the row number ourselves.
    for radnr, r in enumerate(conn.execute("SELECT * FROM funktion_trad ORDER BY vag"), start=2):
        blad.append(_sakra_rad(["    " * r["djup"] + nodnamn(r["namn"], r["id"]), TYP_LABEL[r["typ"]], r["status"], r["fas"],
                     "ja" if r["synlig_stig"] else "nej", r["beskrivning"]]))
        blad.cell(row=radnr, column=1).font = _FET if r["typ"] == "förmåga" else _VANLIG
        _fyll(blad.cell(row=radnr, column=3), STATUS_STIL[r["status"]])


def _blad_bedomningar(blad, conn):
    _rubrikrad(blad, ["Medlem", "Kategori", "Nod", "Svar", "Öppen kommentar", "Visas för",
                      "Intern kommentar", "Besvarat av", "Besvarat"],
               [28, 13, 40, 11, 40, 22, 40, 20, 18])
    rows = conn.execute(
        """
        SELECT m.namn AS medlem, m.kategori, f.namn AS funktion, b.*
        FROM bedomning b
        JOIN medlem m ON m.id = b.medlem_id
        JOIN funktion f ON f.id = b.funktion_id
        ORDER BY m.namn, f.namn
        """
    )
    for radnr, r in enumerate(rows, start=2):
        blad.append(_sakra_rad([r["medlem"], r["kategori"], nodnamn(r["funktion"], r["funktion_id"]), SVAR_ETIKETT[r["svar"]],
                     r["oppen_kommentar"], OPPEN_DELNING[r["oppen_delning"]],
                     r["intern_kommentar"], r["besvarat_av"], r["besvarat"]]))
        _fyll(blad.cell(row=radnr, column=4), SVAR_STIL[r["svar"]])


def _blad_analys(blad, conn):
    tackning = analys_tjanst.tackning(conn)
    info = blad.cell(row=1, column=1,
                     value=f"{tackning['svarande']} av {tackning['totalt']} medlemmar har "
                           "lämnat minst ett svar — obesvarat är inte ”behövs ej”. "
                           "Endast direkta svar räknas.")
    info.font = Font(size=10, italic=True)
    _rubrikrad(blad, ["Nod", "Status", "Avgång", "Go-live", "Kan vänta", "Behövs ej",
                      "Totalt", "Varning"], [45, 11, 10, 9, 10, 10, 8, 42], rad=2)
    for radnr, r in enumerate(analys_tjanst.rankning(conn, arvda=False), start=3):
        blad.append(_sakra_rad([nodnamn(r["namn"], r["id"]), r["status"], r["fas"], r["golive"], r["kan_vanta"],
                     r["behovs_ej"], r["totalt"],
                     "⚠ blockerar go-live men är idé/senare" if r["varning"] else None]))
        _fyll(blad.cell(row=radnr, column=2), STATUS_STIL[r["status"]])
        if r["golive"]:
            _fyll(blad.cell(row=radnr, column=4), SVAR_STIL["golive_krav"])


def _blad_migrering(blad, conn):
    _rubrikrad(blad, ["Medlem", "Kategori", "Utestående blockerare", "Har svarat"],
               [28, 14, 21, 11])
    for radnr, r in enumerate(analys_tjanst.migreringsoversikt(conn), start=2):
        blad.append(_sakra_rad([r["namn"], r["kategori"],
                     r["blockerare"] if r["har_svarat"] else None,
                     "ja" if r["har_svarat"] else "nej"]))
        if not r["har_svarat"]:
            _fyll(blad.cell(row=radnr, column=4), STATUS_STIL["utgår"])


def _blad_roadmap(blad, conn):
    _rubrikrad(blad, ["Avgång", "Namn", "Typ", "Status"], [12, 55, 10, 11])
    radnr = 1
    for fas, rader in roadmap_tjanst.roadmap_data(conn, visa_krav=True):
        for n in rader:
            radnr += 1
            blad.append(_sakra_rad([fas, "    " * n["djup"] + nodnamn(n["namn"], n["id"]), TYP_LABEL[n["typ"]], n["status"]]))
            blad.cell(row=radnr, column=2).font = (
                _FET if n["typ"] == "förmåga" else _VANLIG)
            _fyll(blad.cell(row=radnr, column=4), STATUS_STIL[n["status"]])


def xlsx_export(conn) -> bytes:
    wb = Workbook()
    _blad_trad(wb.active, conn)
    _blad_bedomningar(wb.create_sheet("Bedömningar"), conn)
    _blad_analys(wb.create_sheet("Analys"), conn)
    _blad_migrering(wb.create_sheet("Migrering"), conn)
    _blad_roadmap(wb.create_sheet("Roadmap"), conn)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
