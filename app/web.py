"""Shared template setup and UI label maps (terminology per the prototype)."""

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app import config
from app.auth.csrf import csrf_token

templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))
templates.env.globals["csrf_token"] = csrf_token

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

STATUS = {
    "befintlig": {"label": "Befintlig", "cls": "bg-emerald-100 text-emerald-800"},
    "planerad": {"label": "Planerad", "cls": "bg-sky-100 text-sky-800"},
    "idé": {"label": "Idé", "cls": "bg-stone-200 text-stone-600"},
    # 'utgår' exists in the schema but not in the prototype; muted strike-through badge.
    "utgår": {"label": "Utgår", "cls": "bg-stone-100 text-stone-400 line-through"},
}

TYP_CLS = {
    "förmåga": "text-blue-900 font-semibold",
    "funktion": "text-stone-800 font-medium",
    "krav": "text-stone-700",
}

FASER = ["nu", "nästa", "senare"]

templates.env.globals["SVAR"] = SVAR
templates.env.globals["STATUS"] = STATUS
templates.env.globals["TYP_CLS"] = TYP_CLS
templates.env.globals["FASER"] = FASER


def is_htmx(request: Request) -> bool:
    return request.headers.get("hx-request") == "true"
