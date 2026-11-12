"""Skriver en täckningsbadge som SVG till stdout.

    python3 .github/scripts/coverage_badge.py 92 > coverage.svg

Ritas här i stället för hos shields.io eller en täckningstjänst: ingen
tredje part behöver se repot eller få en token, och badgen är en vanlig fil
på grenen badges (se jobbet badge i tests.yml). Bara standardbiblioteket,
så CI behöver inte installera något för att köra den.
"""

import sys
from xml.sax.saxutils import escape

# Samma trappa som de flesta täckningsbadges, så färgen läses som väntat.
FARGER = [(90, "#4c1"), (80, "#97ca00"), (70, "#dfb317"), (60, "#fe7d37"), (0, "#e05d44")]


def farg(procent: int) -> str:
    return next(f for grans, f in FARGER if procent >= grans)


def textbredd(text: str) -> int:
    # Ungefärlig bredd i Verdana 11px; smala och breda tecken räcker för att
    # texten inte ska slå i kanten.
    smala, breda = set("iljtf.,:;!|' "), set("mwMW%")
    return sum(4 if t in smala else 10 if t in breda else 7 for t in text)


def badge(procent: int) -> str:
    etikett, varde = "coverage", f"{procent}%"
    vb, hb = textbredd(etikett) + 10, textbredd(varde) + 10
    bredd = vb + hb
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{bredd}" height="20" role="img" aria-label="{etikett}: {escape(varde)}">
<title>{etikett}: {escape(varde)}</title>
<linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" stop-opacity=".1"/><stop offset="1" stop-opacity=".1"/></linearGradient>
<clipPath id="r"><rect width="{bredd}" height="20" rx="3" fill="#fff"/></clipPath>
<g clip-path="url(#r)"><rect width="{vb}" height="20" fill="#555"/><rect x="{vb}" width="{hb}" height="20" fill="{farg(procent)}"/><rect width="{bredd}" height="20" fill="url(#s)"/></g>
<g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">
<text x="{vb / 2}" y="15" fill="#010101" fill-opacity=".3">{etikett}</text><text x="{vb / 2}" y="14">{etikett}</text>
<text x="{vb + hb / 2}" y="15" fill="#010101" fill-opacity=".3">{escape(varde)}</text><text x="{vb + hb / 2}" y="14">{escape(varde)}</text>
</g>
</svg>
"""


if __name__ == "__main__":
    procent = int(sys.argv[1])  # int() avvisar allt som inte är ett heltal
    if not 0 <= procent <= 100:
        sys.exit(f"Täckning utanför 0–100: {procent}")
    sys.stdout.write(badge(procent))
