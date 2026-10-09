"""Ren markdown (GFM-tabeller) av läsvyerna — syskon till confluence.py.

Samma fyra vyer som Confluence-exporten: Kravträd, Analys, Roadmap,
Medlemmar. Markdown är det format som passar överallt där Confluence inte
gör det — GitHub-wikis, Obsidian, ett repo, ett mail som renderas — så
exporten serveras som en .md-fil att ladda ner.

Funktionerna tar exportdatumet som argument så att utdata blir
deterministiskt och testbart; routern skickar in dagens datum.

Markdown saknar två saker Confluence-markupen lutar sig mot: celler kan inte
fällas ihop ({expand}) och tabellceller bevarar inte inledande blanksteg.
Beskrivningen får därför en egen kolumn, och trädindraget görs med
mittpunkter (· ) precis som i Confluence så att hierarkin går att läsa även
i råtexten."""

from app.services.analys import rankning, tackning
from app.services.confluence import koda_url
from app.services.roadmap import roadmap_data
from app.services.trad import TYP_LABEL

# Lokal kopia i stället för import från app.web så exportlagret slipper bero på
# mallmotorn; speglar etiketterna i app/web.py STATUS.
STATUS_ETIKETT = {
    "driftsatt": "Driftsatt", "planerad": "Planerad", "idé": "Idé",
    "utreds": "Utreds", "utgår": "Utgår",
}

# Tecken som skulle tolkas som formatering, länk eller HTML om de stod rått i
# en cell. Pipe måste alltid escapas — den avslutar kolumnen.
_ESCAPA = "\\|*_`[]<>#"


def _cell(varde) -> str:
    """Escape ett värde för en GFM-tabellcell. Radbrytningar avslutar raden,
    så de blir blanksteg. Tomt värde ger tom cell — GFM klarar det."""
    if varde is None or varde == "":
        return ""
    s = str(varde)
    for tecken in _ESCAPA:
        s = s.replace(tecken, "\\" + tecken)
    return s.replace("\r", " ").replace("\n", " ")


def _bold(s: str) -> str:
    return f"**{s}**"


def _lank(text: str, url) -> str:
    """En markdown-länk i en tabellcell. URL:er valideras som http(s) vid
    inmatning, men ')' avslutar länkmålet, '|' avslutar cellen och en
    radbrytning avslutar tabellraden — allt utanför URL-strukturen
    procentkodas (samma vitlista som Confluence-exporten) så länken fortsatt
    pekar rätt."""
    if not url:
        return ""
    return f"[{text}]({koda_url(url)})"


def _rad(celler) -> str:
    """En tabellrad. Cellerna ska redan vara escapade (via _cell) eller vara
    avsiktlig markup (indrag, fetstil, länk)."""
    return "| " + " | ".join(celler) + " |"


def _tabellhuvud(rubriker) -> list[str]:
    return [_rad(rubriker), _rad(["---"] * len(rubriker))]


def _namncell(namn, djup: int, typ: str) -> str:
    """Namncell i trädet: mittpunktsindrag per nivå, förmågor i fetstil."""
    text = _cell(namn)
    return "· " * djup + (_bold(text) if typ == "förmåga" else text)


def _dokument(rader) -> str:
    return "\n".join(rader) + "\n"


def kravtrad(conn, genererad: str) -> str:
    rader = ["# Behovsträd — Teaball", "", f"_Exporterad {genererad}._", ""]
    rader += _tabellhuvud(["Namn", "Typ", "Status", "Avgång", "Synlig för medlemmar",
                           "Beskrivning", "Jira", "Dokumentation"])
    for r in conn.execute("SELECT * FROM funktion_trad ORDER BY vag"):
        rader.append(_rad([
            _namncell(r["namn"], r["djup"], r["typ"]),
            _cell(TYP_LABEL[r["typ"]]),
            _cell(STATUS_ETIKETT.get(r["status"], r["status"])),
            _cell(r["fas"]),
            "ja" if r["synlig_stig"] else "nej",
            _cell(r["beskrivning"]),
            _lank("Jira", r["lank_jira"]),
            _lank("Dokumentation", r["lank_dokumentation"]),
        ]))
    return _dokument(rader)


def analys(conn, arvda: bool, genererad: str) -> str:
    tck = tackning(conn)
    titel = "Analys — blockerar-rankning" + (" (med ärvda svar)" if arvda else "")
    rader = [
        f"# {titel}", "", f"_Exporterad {genererad}._", "",
        f"> {tck['svarande']} av {tck['totalt']} medlemmar har lämnat minst ett svar. "
        "Obesvarat räknas inte som ”behövs ej” — endast direkta svar räknas för "
        "täckningen.", "",
    ]
    rader += _tabellhuvud(["Nod", "Status", "Avgång", "Go-live", "Kan vänta",
                           "Behövs ej", "Totalt", "Varning"])
    for r in rankning(conn, arvda):
        varning = "⚠ blockerar go-live men är idé/utreds/senare" if r["varning"] else ""
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
    rader = ["# Roadmap — Teaball", "", f"_Exporterad {genererad}._"]
    for fas, noder in roadmap_data(conn, visa_krav=visa_krav,
                                   dolj_formagor=dolj_formagor):
        # Bara första bokstaven höjs — capitalize() skulle gemena resten och
        # förvanska egennamn som "Medlem 1". Avgångsnamnet är fri admin-text
        # och escapas som en cell, annars blir [x](url) en länk i rubriken.
        rader += ["", f"## {_cell(fas[:1].upper() + fas[1:])}", ""]
        rader += _tabellhuvud(["Namn", "Typ", "Status"])
        for n in noder:
            rader.append(_rad([
                _namncell(n["namn"], n["djup"], n["typ"]),
                _cell(TYP_LABEL[n["typ"]]),
                # Förmågor är hierarkikontext i roadmapen — ingen status.
                "" if n["typ"] == "förmåga"
                else _cell(STATUS_ETIKETT.get(n["status"], n["status"])),
            ]))
    return _dokument(rader)


def medlemmar(conn, genererad: str) -> str:
    rader = ["# Medlemmar — Teaball", "", f"_Exporterad {genererad}._", ""]
    rader += _tabellhuvud(["Namn", "Kategori", "Har lämnat svar"])
    for r in conn.execute(
        "SELECT m.namn, m.kategori,"
        " EXISTS(SELECT 1 FROM bedomning WHERE medlem_id = m.id) AS svarat"
        " FROM medlem m ORDER BY m.namn"
    ):
        rader.append(_rad([_cell(r["namn"]), _cell(r["kategori"]),
                           "ja" if r["svarat"] else "nej"]))
    return _dokument(rader)
