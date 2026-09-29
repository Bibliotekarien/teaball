"""Regressionsvakt för static/js/trad.js. Testsviten har ingen DOM att köra
skriptet i, så vakten läser källan och kontrollerar de egenskaper som
minnesläckan och skrivsegheten i kravträdet hängde på (2026-09-29: en flik
på 2,5 GB efter en redigeringssession, och trögt att skriva i nodformuläret).
Strängtester är trubbiga — de finns för att ändringarna inte ska städas bort
av misstag, inte som bevis på beteendet."""

import re
from pathlib import Path

TRAD_JS = (Path(__file__).resolve().parent.parent / "static" / "js" / "trad.js").read_text()


def test_sortable_destroyas_nar_htmx_stadar_bort_listan():
    # Sortable håller ett globalt register över sina listor som bara destroy()
    # rensar. Utan destroy vid htmx:beforeCleanupElement pekar registret via
    # föräldrakedjan på hela det utbytta trädet — en trädkopia per swap.
    lyssnare = re.search(
        r'addEventListener\("htmx:beforeCleanupElement",(.*?)\n  \}\);', TRAD_JS, re.S
    )
    assert lyssnare, "trad.js saknar städlyssnare för Sortable"
    assert "_sortable.destroy()" in lyssnare.group(1)
    assert "_sortable = null" in lyssnare.group(1)


def test_kompaktminnet_satter_open_bara_vid_andring():
    # Att tilldela samma värde räknas som attributändring och tvingar, med
    # details[open] i stilmallen, en stilomräkning av grenen.
    assert "if (d.open !== oppen) d.open = oppen;" in TRAD_JS
    assert not re.search(r"d\.open = !kompakterade\.has", TRAD_JS)


def test_kompaktminnet_hoppar_over_swappar_utan_grenar():
    # htmx:load kommer även för dubblettkollens span vid varje tangentpaus i
    # skapa-formuläret; den får inte utlösa en trädgenomgång.
    assert "htmx.onLoad(aterstall)" not in TRAD_JS
    assert 'el.querySelector("details")' in TRAD_JS
