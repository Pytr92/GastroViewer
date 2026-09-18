"""Outbound gegen einen httpx-MockTransport: Semaphore über die ganze
Anfrage, Weiterleitungen ohne Zugangsdaten."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from gastroviewer.cache import AsyncCache
from gastroviewer.http import Outbound
from gastroviewer.sources import genesis
from gastroviewer.sources.base import SourceError


def _outbound(settings, handler) -> Outbound:
    settings.ensure_dirs()
    out = Outbound(settings, AsyncCache(settings.db_path))
    # Wie in Outbound.start(): Weiterleitungen sind global an, damit der
    # Test genau die Stelle prüft, an der ein Aufrufer sie abschaltet.
    out._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True)
    return out


async def test_overpass_anfragen_laufen_nacheinander(settings):
    """Drei Blöcke fragen gleichzeitig — beim Dienst kommt immer nur eine
    Abfrage an, die nächste startet erst, wenn die Antwort da ist."""
    in_flug = spitze = 0

    async def handler(request):
        nonlocal in_flug, spitze
        in_flug += 1
        spitze = max(spitze, in_flug)
        await asyncio.sleep(0.05)
        in_flug -= 1
        return httpx.Response(200, json={"elements": []})

    out = _outbound(settings, handler)
    try:
        await asyncio.gather(*[
            out.post_json("overpass", "https://overpass.example/api/interpreter",
                          data={"data": "x"}, limiter="overpass",
                          min_interval=0.0, max_concurrent=1)
            for _ in range(3)
        ])
    finally:
        await out.aclose()
    assert spitze == 1
    stats = out.limiters.stats()["overpass"]
    assert stats["in_flight"] == 0 and stats["acquisitions"] == 3


async def test_platz_wird_auch_bei_fehler_freigegeben(settings):
    async def handler(request):
        return httpx.Response(504, text="Gateway Timeout")

    out = _outbound(settings, handler)
    try:
        for _ in range(2):
            with pytest.raises(SourceError):
                await out.get_json("overpass", "https://overpass.example/x",
                                   limiter="overpass", min_interval=0.0,
                                   max_concurrent=1)
    finally:
        await out.aclose()
    assert out.limiters.stats()["overpass"]["in_flight"] == 0


async def test_genesis_kennung_folgt_keiner_weiterleitung(settings):
    """Kennung und Passwort gehen als eigene Header; httpx entfernt bei
    einer Weiterleitung nur "Authorization". Also: gar nicht folgen."""
    anfragen: list[httpx.Request] = []

    async def handler(request):
        anfragen.append(request)
        if request.url.host == "www.regionalstatistik.de":
            return httpx.Response(
                302, headers={"location": "https://wartung.example.org/login"})
        return httpx.Response(200, text="fremder Host")

    out = _outbound(settings, handler)
    try:
        with pytest.raises(SourceError) as info:
            await genesis.logincheck(out, {"kennung": "K123", "passwort": "geheim"})
    finally:
        await out.aclose()
    assert "leitet um" in info.value.message
    assert "wartung.example.org" in (info.value.detail or "")
    assert len(anfragen) == 1
    assert anfragen[0].url.host == "www.regionalstatistik.de"
    assert anfragen[0].headers.get("username") == "K123"


async def test_weiterleitung_bleibt_erlaubt_wo_niemand_sie_abschaltet(settings):
    async def handler(request):
        if request.url.path == "/alt":
            return httpx.Response(301, headers={"location": "https://d.example/neu"})
        return httpx.Response(200, json={"ok": True})

    out = _outbound(settings, handler)
    try:
        assert await out.get_json("test", "https://d.example/alt") == {"ok": True}
    finally:
        await out.aclose()
