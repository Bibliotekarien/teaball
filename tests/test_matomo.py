"""Server-side Matomo tracking: the fire-and-forget hit must keep a strong
reference (so it is not garbage-collected before it is sent) and failures must
be visible in the log instead of silently swallowed."""

import asyncio
import logging

from app import config, matomo


class FakeResp:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


class FakeURL:
    def __init__(self, path, scheme="https", netloc="teaball.bibliotekarien.se"):
        self.path = path
        self.scheme = scheme
        self.netloc = netloc


class FakeClientAddr:
    host = "203.0.113.5"


class FakeReq:
    def __init__(self, path="/login", headers=None):
        self.method = "GET"
        self.url = FakeURL(path)
        self.headers = headers or {}
        self.client = FakeClientAddr()


def test_track_request_haller_task_referens(monkeypatch):
    """The regression: a bare create_task() result is only weakly held, so the
    hit could be GC'd before it ran. track_request must retain it until done."""
    monkeypatch.setattr(config, "MATOMO_URL", "https://matomo.example.org")
    monkeypatch.setattr(config, "MATOMO_SITE_ID", "7")
    skickat = []

    class FakeClient:
        async def post(self, url, data=None):
            skickat.append(data)
            return FakeResp(204)

    monkeypatch.setattr(matomo, "_client", FakeClient())

    async def kor():
        matomo._tasks.clear()
        matomo.track_request(FakeReq("/login"), 200)
        assert len(matomo._tasks) == 1               # strong ref held
        await asyncio.gather(*list(matomo._tasks))
        assert len(matomo._tasks) == 0               # done-callback cleaned up

    asyncio.run(kor())
    assert skickat and skickat[0]["url"] == "https://teaball.bibliotekarien.se/login"


def test_send_varnar_nar_matomo_avvisar(monkeypatch, caplog):
    class FakeClient:
        async def post(self, url, data=None):
            return FakeResp(400, "site id unknown")

    monkeypatch.setattr(matomo, "_client", FakeClient())
    with caplog.at_level(logging.WARNING, logger="teaball.matomo"):
        asyncio.run(matomo._send({"idsite": "7"}))
    assert any("avvisade" in r.getMessage() for r in caplog.records)


def test_send_varnar_vid_undantag(monkeypatch, caplog):
    class FakeClient:
        async def post(self, url, data=None):
            raise RuntimeError("nätfel")

    monkeypatch.setattr(matomo, "_client", FakeClient())
    with caplog.at_level(logging.WARNING, logger="teaball.matomo"):
        asyncio.run(matomo._send({"idsite": "7"}))
    assert any("misslyckades" in r.getMessage() for r in caplog.records)
