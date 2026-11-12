"""Which client IP the app sees behind a proxy (login throttle, Matomo).

docker-compose.standalone.yml trusts X-Forwarded-For only from Docker's own
networks, so uvicorn walks the header from the right. These tests feed the
compose file's actual default through uvicorn's middleware: a client must not
be able to choose its own IP by sending the header, even when the operator's
proxy appends to it instead of overwriting."""

import asyncio
import re
from pathlib import Path

import yaml
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

ROT = Path(__file__).resolve().parent.parent


def _standardvarde() -> str:
    compose = yaml.safe_load((ROT / "docker-compose.standalone.yml").read_text())
    rad = compose["services"]["web"]["environment"]["FORWARDED_ALLOW_IPS"]
    return re.fullmatch(r"\$\{FORWARDED_ALLOW_IPS:-(.+)\}", rad).group(1)


def _klient(betrodda: str, avsandare: str, xff: str | None) -> str:
    sett = {}

    async def app(scope, receive, send):
        sett["klient"] = scope["client"][0]

    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    scope = {"type": "http", "client": (avsandare, 50000), "headers": headers,
             "scheme": "http"}
    asyncio.run(ProxyHeadersMiddleware(app, trusted_hosts=betrodda)(scope, None, None))
    return sett["klient"]


def test_appendande_proxy_ger_riktig_klient():
    # nginx with $proxy_add_x_forwarded_for: the client's own header first,
    # the address nginx saw last. The gateway is Docker's (172.18.0.1).
    assert _klient(_standardvarde(), "172.18.0.1", "6.6.6.6, 203.0.113.7") == "203.0.113.7"


def test_overskrivande_proxy_ger_riktig_klient():
    assert _klient(_standardvarde(), "172.18.0.1", "203.0.113.7") == "203.0.113.7"


def test_obetrodd_avsandare_far_inte_satta_headern():
    # Someone reaching the container from outside Docker's networks.
    assert _klient(_standardvarde(), "203.0.113.9", "6.6.6.6") == "203.0.113.9"


def test_dockerfilens_stjarna_tar_vanstra_adressen():
    """Why the standalone default must not be "*": uvicorn then trusts the
    leftmost address, which the client wrote itself."""
    assert _klient("*", "172.18.0.1", "6.6.6.6, 203.0.113.7") == "6.6.6.6"
