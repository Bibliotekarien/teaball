"""uvicorns accesslogg är på, men medlemmarnas token når den aldrig — och
robots.txt stänger ute sökmotorer som ett uttalat beslut."""

import logging

from app import accesslog

TOKEN = "Ab3_" + "x" * 39  # 43 tecken, som secrets.token_urlsafe(32)


def accessrad(path: str) -> logging.LogRecord:
    # Samma form som uvicorns: '%s - "%s %s HTTP/%s" %d'
    return logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 0,
        '%s - "%s %s HTTP/%s" %d', ("10.0.0.1:5000", "GET", path, "1.1", 303), None,
    )


def test_token_maskas_men_ovriga_svara_vagar_syns():
    f = accesslog.MaskSecretsFilter()
    for path, forvantat in [
        (f"/svara/{TOKEN}", "/svara/_token_"),
        (f"/svara/{TOKEN}?x=1", "/svara/_token_?x=1"),
        ("/svara/roadmap", "/svara/roadmap"),
        ("/svara/vaxla", "/svara/vaxla"),
        ("/svara/12/svar", "/svara/12/svar"),
    ]:
        rad = accessrad(path)
        assert f.filter(rad)
        assert rad.getMessage() == f'10.0.0.1:5000 - "GET {forvantat} HTTP/1.1" 303'


def test_filtret_installeras_en_gang(client):
    filter_ = [f for f in logging.getLogger("uvicorn.access").filters
               if isinstance(f, accesslog.MaskSecretsFilter)]
    assert len(filter_) == 1


def test_robots_txt_stanger_ute_allt(client):
    svar = client.get("/robots.txt")
    assert svar.status_code == 200
    rader = [r.strip() for r in svar.text.splitlines() if r.strip() and not r.startswith("#")]
    assert rader == ["User-agent: *", "Disallow: /"]
