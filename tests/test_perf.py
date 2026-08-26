"""Performance guard (spec I3): key pages under 500 ms with ~500 nodes,
50 members and 10 000 assessments. Marked slow — run with `pytest -m slow`
or the full unfiltered suite."""

import time

import pytest

from scripts.seed_demo import seed
from tests.conftest import ge_token, logga_in

pytestmark = pytest.mark.slow

BUDGET_SEKUNDER = 0.5


@pytest.fixture()
def stor_databas(app_db):
    seed(app_db)
    return app_db


def _tidta(client, adress):
    start = time.perf_counter()
    svar = client.get(adress)
    tid = time.perf_counter() - start
    assert svar.status_code == 200, adress
    assert tid < BUDGET_SEKUNDER, f"{adress} tog {tid:.3f}s (budget {BUDGET_SEKUNDER}s)"


def test_adminsidor_inom_budget(client, stor_databas):
    logga_in(client, stor_databas)
    medlem = stor_databas.execute("SELECT id FROM medlem LIMIT 1").fetchone()["id"]
    for adress in (
        "/trad",
        "/trad?q=krav",
        f"/bedomning?medlem_id={medlem}",
        "/analys",
        "/analys?arvda=1",
        "/analys/medlemmar",
        "/roadmap?visa_krav=1",
    ):
        _tidta(client, adress)


def test_medlemsvy_inom_budget(stor_databas, klient_fabrik):
    medlem = stor_databas.execute("SELECT id FROM medlem LIMIT 1").fetchone()["id"]
    token = ge_token(stor_databas, medlem)
    klient = klient_fabrik()
    assert klient.get(f"/svara/{token}", follow_redirects=False).status_code == 303
    _tidta(klient, "/svara")
