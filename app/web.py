"""Shared template setup and UI label maps (terminology per the prototype)."""

import hashlib
from functools import lru_cache

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app import config
from app.auth.csrf import csrf_token

templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))
templates.env.globals["csrf_token"] = csrf_token


@lru_cache(maxsize=None)
def _statisk_version(relativ: str) -> str:
    """Short content hash of a file under static/. Cached for the process
    lifetime: the files only change with a deploy, which restarts the app."""
    try:
        return hashlib.sha256((config.STATIC_DIR / relativ).read_bytes()).hexdigest()[:10]
    except OSError:
        return "0"


def static_url(relativ: str) -> str:
    """URL for a static asset with a content-hash query string, so browsers
    fetch the new file after a deploy instead of serving a stale copy from
    cache. Static responses carry no Cache-Control, so without this a browser
    is free to reuse an old app.css for days (heuristic freshness from
    Last-Modified) and renders new templates with old styles."""
    return f"/static/{relativ}?v={_statisk_version(relativ)}"


templates.env.globals["static_url"] = static_url

# Answer labels and colors follow formagekarta-prototyp.jsx (SVAR map).
SVAR = {
    "golive_krav": {
        "label": "Ja, för go-live",
        "kort": "Go-live",
        "dot": "bg-rose-600",
        "pill": "bg-rose-600 text-white border-rose-600",
        "ghost": "text-rose-700 border-rose-200 hover:bg-rose-50",
    },
    "kan_vanta": {
        "label": "Ja, kan vänta 6–12 mån",
        "kort": "Kan vänta",
        "dot": "bg-amber-500",
        # Deliberate deviation from the prototype: white on amber-500 is 2.15:1
        # (WCAG fail); dark amber text reads at 6.99:1.
        "pill": "bg-amber-500 text-amber-950 border-amber-500",
        "ghost": "text-amber-700 border-amber-200 hover:bg-amber-50",
    },
    "behovs_ej": {
        "label": "Behövs ej",
        "kort": "Behövs ej",
        "dot": "bg-stone-400",
        "pill": "bg-stone-500 text-white border-stone-500",
        "ghost": "text-stone-500 border-stone-200 hover:bg-stone-100",
    },
}

# The beskrivning texts feed the legend partial and the pill tooltips.
# Dict order = lifecycle order (done → dropped); the tree's distribution bar,
# the legend and the filter checkboxes all iterate it, so the order is part of
# the design: the bar reads left-to-right as a progress bar.
# One scale everywhere: cls (pill) and stapel (bar segment) are the same hue
# per status — green done, yellow planned, two blues for the undecided pair
# (deliberately not red: idé/utreds are neutral states, not problems), gray out.
# Bar steps are validated (dataviz palette checks): adjacent pairs separate for
# normal and CVD vision; utgår is intentionally gray (= outside the pipeline).
STATUS = {
    "driftsatt": {"label": "Driftsatt", "cls": "bg-emerald-100 text-emerald-800",
                  "stapel": "bg-emerald-600",
                  "beskrivning": "Finns och fungerar i nya plattformen — räknas inte som blockerare."},
    "planerad": {"label": "Planerad", "cls": "bg-amber-100 text-amber-800",
                 "stapel": "bg-amber-500",
                 "beskrivning": "Beslutad att byggas; avgången i roadmapen anger när."},
    "utreds": {"label": "Utreds", "cls": "bg-sky-200 text-sky-900",
               "stapel": "bg-sky-700",
               "beskrivning": "Finns i DiVA Classic; identifierad men ännu inte beslutad."},
    "idé": {"label": "Idé", "cls": "bg-sky-100 text-sky-800",
            "stapel": "bg-sky-400",
            "beskrivning": "Nytt förslag som ännu inte är beslutat."},
    # 'utgår' exists in the schema but not in the prototype; muted strike-through badge.
    "utgår": {"label": "Utgår", "cls": "bg-stone-100 text-stone-400 line-through",
              "stapel": "bg-stone-400",
              "beskrivning": "Byggs inte — tas inte vidare till nya plattformen."},
}

TYP_CLS = {
    "förmåga": "text-blue-900 font-semibold",
    "funktion": "text-stone-800 font-medium",
    "krav": "text-stone-700",
}

TYP_BESKRIVNING = {
    "förmåga": "Ett sammanhållet område av vad systemet ska klara — rubriknivån i kartan.",
    "funktion": "Något systemet gör: en avgränsad byggsten inom en förmåga.",
    "krav": "Ett testbart villkor som ska vara uppfyllt — det medlemmarna bedömer.",
}

# UI-termen är "avgång"; kolumnen och koden heter fortfarande fas.
FASER = ["Medlem 1", "senare"]

templates.env.globals["SVAR"] = SVAR
templates.env.globals["STATUS"] = STATUS
templates.env.globals["TYP_CLS"] = TYP_CLS
templates.env.globals["TYP_BESKRIVNING"] = TYP_BESKRIVNING
templates.env.globals["FASER"] = FASER


def is_htmx(request: Request) -> bool:
    return request.headers.get("hx-request") == "true"
