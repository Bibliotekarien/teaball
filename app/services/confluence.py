"""Confluence wiki-markup exports of the read views (first sweep).

Each view renders to raw Confluence wiki markup as plain text. The förvaltare
opens the link, selects all, copies, and pastes into Confluence via
"Insert → Markup → Confluence Wiki" — tables, headings and status become a real
Confluence page. Covered so far: Kravträd, Analys (blockerar-rankning),
Roadmap, Medlemmar. Bedömning and the member view are not yet covered.

Functions take the export date as an argument so the markup is deterministic
(easy to test); the router passes today's date."""

from urllib.parse import quote

from app.services.analys import rankning, tackning
from app.services.roadmap import roadmap_data

# Kept local rather than importing app.web so the export layer stays decoupled
# from the template engine; mirrors the labels in app/web.py STATUS.
STATUS_ETIKETT = {
    "driftsatt": "Driftsatt", "planerad": "Planerad", "idé": "Idé",
    "utreds": "Utreds", "utgår": "Utgår",
}


def _cell(varde) -> str:
    """Escape a value for a wiki-markup table cell. Pipes end a column and
    newlines end a row; braces/brackets can start a macro or link. An empty
    cell must hold at least a space or the table collapses it."""
    if varde is None or varde == "":
        return " "
    s = str(varde).replace("\\", "\\\\")
    for tecken in ("|", "{", "}", "[", "]"):
        s = s.replace(tecken, "\\" + tecken)
    return s.replace("\r", " ").replace("\n", " ")


def _bold(s: str) -> str:
    return f"*{s}*"


# Tecken som får stå okodade i ett länkmål: URL-strukturen (schema, värd,
# sökväg, fråga, fragment) och redan procentkodade sekvenser. Allt annat —
# '|' och ']' som avslutar wiki-länken, '<' '>' '"' blanksteg och
# radbrytningar som bryter cellen eller tabellraden — procentkodas. Delas med
# markdown.py så båda exporterna kodar lika.
URL_SAKRA_TECKEN = ":/?#@!$&'*+,;=%~"


def koda_url(url) -> str:
    return quote(str(url), safe=URL_SAKRA_TECKEN)


def _lank(text: str, url) -> str:
    """A wiki-markup link cell. URLs are validated as http(s) on input, but a
    '|' or ']' inside one would still end the link markup early, and a
    newline would end the table row — percent-encode instead of
    backslash-escaping, so the link target stays a valid URL."""
    if not url:
        return " "
    return f"[{text}|{koda_url(url)}]"


def _rad(celler, header: bool = False) -> str:
    """A wiki-markup table row. Cells must already be escaped (via _cell) or be
    intentional markup (indent, bold)."""
    d = "||" if header else "|"
    return d + " " + f" {d} ".join(celler) + " " + d


def _namncell(namn, djup: int, typ: str, beskrivning=None) -> str:
    """Tree name cell: middot indent per level, förmåga names bolded. A
    beskrivning goes under the name in the same cell, folded away in an
    {expand} macro so the table stays compact until the reader clicks."""
    text = _cell(namn)
    cell = "· " * djup + (_bold(text) if typ == "förmåga" else text)
    if beskrivning:
        # \\ is a line break inside the cell; _cell has already escaped braces,
        # so the description cannot terminate the macro.
        cell += " \\\\ {expand:Beskrivning}" + _cell(beskrivning) + "{expand}"
    return cell


def _dokument(rader) -> str:
    return "\n".join(rader)


def kravtrad(conn, genererad: str) -> str:
    rader = ["h1. Kravträd — Teaball", f"_Exporterad {genererad}._", "",
             _rad(["Namn", "Typ", "Status", "Avgång", "Synlig för medlemmar",
                   "Jira", "Dokumentation"], header=True)]
    for r in conn.execute("SELECT * FROM funktion_trad ORDER BY vag"):
        rader.append(_rad([
            _namncell(r["namn"], r["djup"], r["typ"], r["beskrivning"]),
            _cell(r["typ"]),
            _cell(STATUS_ETIKETT.get(r["status"], r["status"])),
            _cell(r["fas"]),
            "ja" if r["synlig_stig"] else "nej",
            _lank("Jira", r["lank_jira"]),
            _lank("Dokumentation", r["lank_dokumentation"]),
        ]))
    return _dokument(rader)


def analys(conn, arvda: bool, genererad: str) -> str:
    tck = tackning(conn)
    titel = "Analys — blockerar-rankning" + (" (med ärvda svar)" if arvda else "")
    rader = [
        f"h1. {titel}", f"_Exporterad {genererad}._", "",
        "{info}" + (f"{tck['svarande']} av {tck['totalt']} medlemmar har lämnat minst "
                    "ett svar. Obesvarat räknas inte som ”behövs ej” — endast direkta "
                    "svar räknas för täckningen.") + "{info}", "",
        _rad(["Nod", "Status", "Avgång", "Go-live", "Kan vänta", "Behövs ej", "Totalt",
              "Varning"], header=True),
    ]
    for r in rankning(conn, arvda):
        varning = "(!) blockerar go-live men är idé/utreds/senare" if r["varning"] else " "
        rader.append(_rad([
            _cell(r["namn"]),
            _cell(STATUS_ETIKETT.get(r["status"], r["status"])),
            _cell(r["fas"]),
            _cell(r["golive"]), _cell(r["kan_vanta"]), _cell(r["behovs_ej"]),
            _cell(r["totalt"]), varning,
        ]))
    return _dokument(rader)


def roadmap(conn, visa_krav: bool, genererad: str,
            dolj_formagor: bool = False) -> str:
    rader = ["h1. Roadmap — Teaball", f"_Exporterad {genererad}._"]
    for fas, noder in roadmap_data(conn, visa_krav=visa_krav,
                                   dolj_formagor=dolj_formagor):
        # Bara första bokstaven höjs — capitalize() skulle gemena resten och
        # förvanska egennamn som "Medlem 1". Avgångsnamnet är fri admin-text
        # och escapas som en cell, annars blir {x} eller [x] markup i rubriken.
        rader += ["", f"h2. {_cell(fas[:1].upper() + fas[1:])}",
                  _rad(["Namn", "Typ", "Status"], header=True)]
        for n in noder:
            rader.append(_rad([
                _namncell(n["namn"], n["djup"], n["typ"]),
                _cell(n["typ"]),
                # Förmågor är hierarkikontext i roadmapen — ingen status.
                " " if n["typ"] == "förmåga"
                else _cell(STATUS_ETIKETT.get(n["status"], n["status"])),
            ]))
    return _dokument(rader)


def medlemmar(conn, genererad: str) -> str:
    rader = ["h1. Medlemmar — Teaball", f"_Exporterad {genererad}._", "",
             _rad(["Namn", "Kategori", "Har lämnat svar"], header=True)]
    for r in conn.execute(
        "SELECT m.namn, m.kategori,"
        " EXISTS(SELECT 1 FROM bedomning WHERE medlem_id = m.id) AS svarat"
        " FROM medlem m ORDER BY m.namn"
    ):
        rader.append(_rad([_cell(r["namn"]), _cell(r["kategori"]),
                           "ja" if r["svarat"] else "nej"]))
    return _dokument(rader)
