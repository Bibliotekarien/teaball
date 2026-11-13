import base64
import re

import pytest
from fastapi.testclient import TestClient

from app import config
from app import db as appdb


@pytest.fixture(autouse=True)
def utan_instanstexter_i_miljon(monkeypatch):
    """Tests must not depend on the process environment: with ORGANISATION
    etc. set (a sourced .env, the prod container) init_db could seed them and
    tests expecting neutral texts would fail."""
    for namn in ("ORGANISATION", "NUVARANDE_SYSTEM", "PERSONUPPGIFTSANSVARIG",
                 "DATASKYDD_KONTAKT"):
        monkeypatch.setattr(config, namn, "")


@pytest.fixture()
def conn(tmp_path):
    """A migrated file-backed database (WAL mode needs a real file)."""
    connection = appdb.connect(tmp_path / "test.db")
    appdb.init_db(connection)
    yield connection
    connection.close()


@pytest.fixture()
def app_db(tmp_path, monkeypatch):
    """A migrated database that the app fixture ('client') also uses:
    config.DB_PATH is pointed at the same temp file, so per-request connections
    opened by app.db.get_conn hit this database."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")
    connection = appdb.connect()
    appdb.init_db(connection)
    yield connection
    connection.close()


@pytest.fixture()
def client(app_db):
    from app.main import create_app

    with TestClient(create_app()) as testclient:
        yield testclient


@pytest.fixture()
def klient_fabrik(app_db):
    """Extra clients with their own cookie jars — one per member session."""
    from app.main import create_app

    skapade = []

    def fabrik():
        klient = TestClient(create_app())
        klient.__enter__()
        skapade.append(klient)
        return klient

    yield fabrik
    for klient in skapade:
        klient.__exit__(None, None, None)


def ge_token(conn, medlem_id) -> str:
    """Store a token hash for the member and return the raw token."""
    from app.auth.token import generera

    token, tokenhash = generera()
    conn.execute("UPDATE medlem SET token = ? WHERE id = ?", (tokenhash, medlem_id))
    conn.commit()
    return token


def skapa_forvaltare(conn, namn="anna", losenord="hemligt-losen", roll="admin"):
    from app.auth.password import hash_losen

    conn.execute(
        "INSERT INTO forvaltare (anvandarnamn, losen_hash, roll) VALUES (?, ?, ?)"
        " ON CONFLICT (anvandarnamn) DO NOTHING",
        (namn, hash_losen(losenord), roll),
    )
    conn.commit()


def huvuddel(sida: str) -> str:
    """The page's <main> only. The glossary panel sits outside it and repeats
    every answer and status label, so 'label not on the page' assertions
    must look at the content, not the whole document."""
    return sida.split("<main", 1)[1].split("</main>", 1)[0]


def csrf_fran(html: str) -> str:
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def sessionsinnehall(client) -> str:
    """The session cookie decoded. Starlette signs it but does not encrypt it
    (base64 JSON before the first dot), so anything placed in the session is
    readable by whoever holds the cookie — secrets must never end up here."""
    kaka = client.cookies.get("teaball_session", "")
    data = kaka.split(".", 1)[0]
    return base64.b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")


def logga_in(client, conn, namn="anna", losenord="hemligt-losen", roll="admin"):
    """Create the staff account if needed and establish a session. Role tests
    use distinct usernames so ON CONFLICT DO NOTHING never masks a role."""
    skapa_forvaltare(conn, namn, losenord, roll)
    token = csrf_fran(client.get("/login").text)
    svar = client.post(
        "/login",
        data={"anvandarnamn": namn, "losenord": losenord, "csrf_token": token},
        follow_redirects=False,
    )
    assert svar.status_code == 303, svar.text


def skapa_funktion(conn, namn, foralder_id=None, typ="krav", status="planerad",
                   fas="Avgång 1", synlig_externt=1, sortering=0, beskrivning=None,
                   lank_dokumentation=None, lank_jira=None):
    """Default fas is filled in because default status is planerad and the
    avgång trigger requires one; pass fas=None only with an exempt status."""
    cur = conn.execute(
        "INSERT INTO funktion (namn, foralder_id, typ, status, fas, synlig_externt,"
        " sortering, beskrivning, lank_dokumentation, lank_jira)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (namn, foralder_id, typ, status, fas, synlig_externt, sortering,
         beskrivning, lank_dokumentation, lank_jira),
    )
    return cur.lastrowid


def skapa_medlem(conn, namn, kategori=None):
    cur = conn.execute("INSERT INTO medlem (namn, kategori) VALUES (?, ?)", (namn, kategori))
    return cur.lastrowid


def satt_svar(conn, medlem_id, funktion_id, svar, oppen_kommentar=None,
              oppen_delning="privat", intern_kommentar=None, besvarat_av=None):
    conn.execute(
        "INSERT INTO bedomning (medlem_id, funktion_id, svar, oppen_kommentar, oppen_delning,"
        " intern_kommentar, besvarat_av) VALUES (?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT (medlem_id, funktion_id) DO UPDATE SET"
        " svar=excluded.svar, oppen_kommentar=excluded.oppen_kommentar,"
        " oppen_delning=excluded.oppen_delning, intern_kommentar=excluded.intern_kommentar,"
        " besvarat_av=excluded.besvarat_av, besvarat=datetime('now')",
        (medlem_id, funktion_id, svar, oppen_kommentar, oppen_delning, intern_kommentar,
         besvarat_av),
    )


def seed_trad(conn):
    """A small tree mirroring the acceptance-test scenario (spec §9.1):

    Publicering (förmåga)
    ├── Registrera avhandling (funktion)
    └── Import (funktion)
        └── Import från Web of Science (funktion)
            └── Dubblettdetektering (krav)
    Export & spridning (förmåga)
    """
    ids = {}
    ids["publicering"] = skapa_funktion(conn, "Publicering", typ="förmåga", status="driftsatt", sortering=10)
    ids["registrera"] = skapa_funktion(conn, "Registrera avhandling", ids["publicering"], typ="funktion", sortering=10)
    ids["import"] = skapa_funktion(conn, "Import", ids["publicering"], typ="funktion", sortering=20)
    ids["wos"] = skapa_funktion(conn, "Import från Web of Science", ids["import"], typ="funktion", fas="senare", sortering=10)
    ids["dubblett"] = skapa_funktion(conn, "Dubblettdetektering", ids["wos"], typ="krav", status="idé", fas="senare", sortering=10)
    ids["export"] = skapa_funktion(conn, "Export & spridning", typ="förmåga", status="driftsatt", sortering=20)
    conn.commit()
    return ids


@pytest.fixture()
def trad(conn):
    return seed_trad(conn)
