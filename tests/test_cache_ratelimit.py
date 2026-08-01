"""Cache, Rate-Limiter und Fehlerklassifikation."""

from __future__ import annotations

import time

import httpx
import pytest

from gastroviewer.cache import Cache, cache_key
from gastroviewer.http import classify
from gastroviewer.ratelimit import RateLimiter
from gastroviewer.sources.base import SourceError, haversine_m


# ------------------------------------------------------------------ Cache


def test_schluessel_rundet_auf_vier_nachkommastellen():
    """Spec §2. ~11 m Auflösung — feiner als die 100-m-Zellen."""
    a = cache_key("zensus", 48.13341111, 11.56742222, 600)
    b = cache_key("zensus", 48.13339999, 11.56744444, 600)
    assert a == b == "zensus|48.1334|11.5674|600"


def test_schluessel_trennt_radius_und_quelle():
    assert cache_key("zensus", 48.1, 11.5, 600) != cache_key("zensus", 48.1, 11.5, 900)
    assert cache_key("zensus", 48.1, 11.5, 600) != cache_key("overpass", 48.1, 11.5, 600)


def test_treffer_und_ablauf(tmp_path):
    c = Cache(tmp_path / "t.sqlite")
    c.set("k", "zensus", {"a": 1}, ttl=60)
    hit = c.get("k")
    assert hit["payload"] == {"a": 1}

    c.set("kurz", "zensus", {"a": 2}, ttl=-1)
    assert c.get("kurz") is None, "abgelaufener Eintrag darf nicht geliefert werden"
    assert c.get("kurz") is None, "abgelaufener Eintrag muss entfernt sein"


def test_clear_nach_quelle(tmp_path):
    c = Cache(tmp_path / "t.sqlite")
    c.set("zensus|1", "zensus", {}, 60)
    c.set("zensus|2", "zensus", {}, 60)
    c.set("overpass|1", "overpass", {}, 60)
    assert c.clear("zensus") == 2
    assert c.get("overpass|1") is not None


def test_outbound_protokoll(tmp_path):
    c = Cache(tmp_path / "t.sqlite")
    assert c.outbound_count() == 0
    c.log_outbound("zensus", "https://x/y", status=200, duration_ms=12, size=99)
    c.log_outbound("overpass", "https://a/b", error="timeout: Zeitüberschreitung")
    assert c.outbound_count() == 2
    rows = c.outbound_since(0)
    assert rows[0]["status"] == 200 and rows[0]["bytes"] == 99
    assert rows[1]["error"].startswith("timeout")


def test_gemerkte_punkte(tmp_path):
    c = Cache(tmp_path / "t.sqlite")
    pid = c.save_point("Kandidat A", 48.1, 11.5, 600, {"punkt": {"lat": 48.1}})
    rows = c.list_points()
    assert len(rows) == 1 and rows[0]["label"] == "Kandidat A"
    assert rows[0]["payload"]["punkt"]["lat"] == 48.1
    assert c.delete_point(pid) is True
    assert c.delete_point(pid) is False


# ------------------------------------------------------------ Rate-Limit


async def test_mindestabstand_wird_eingehalten():
    lim = RateLimiter(0.2)
    t0 = time.monotonic()
    for _ in range(4):
        await lim.acquire()
    dauer = time.monotonic() - t0
    # Der erste Aufruf wartet nicht, danach je 0,2 s.
    assert dauer >= 0.6 - 0.02, f"zu schnell: {dauer:.3f}s"
    assert lim.waits == 3


async def test_parallele_aufrufe_werden_serialisiert():
    """Nominatim erlaubt 1 req/s — auch wenn zehn Anfragen gleichzeitig kommen."""
    import asyncio

    lim = RateLimiter(0.1)
    t0 = time.monotonic()
    await asyncio.gather(*[lim.acquire() for _ in range(5)])
    dauer = time.monotonic() - t0
    assert dauer >= 0.4 - 0.02, f"Parallelaufrufe nicht gedrosselt: {dauer:.3f}s"


# --------------------------------------------------- Fehlerklassifikation


@pytest.mark.parametrize(
    "exc,kind,teil",
    [
        (httpx.ConnectTimeout("x"), "timeout", "Zeitüberschreitung"),
        (httpx.ConnectError("x"), "connect", "nicht erreichbar"),
        (ValueError("kein json"), "parse", "JSON"),
    ],
)
def test_ursachen_werden_benannt(exc, kind, teil):
    """Spec §5: nicht „Dienst überlastet" schreiben, wenn es etwas anderes ist."""
    err = classify(exc)
    assert err.kind == kind
    assert teil in err.message


@pytest.mark.parametrize(
    "code,teil",
    [(429, "Anfragelimit"), (403, "User-Agent"), (504, "abgebrochen"), (500, "Serverfehler")],
)
def test_http_status_ursachen(code, teil):
    req = httpx.Request("GET", "https://x/y")
    resp = httpx.Response(code, request=req, text="details")
    err = classify(httpx.HTTPStatusError("x", request=req, response=resp))
    assert err.kind == "http_status"
    assert teil in err.message
    assert err.detail == "details"


def test_source_error_bleibt_serialisierbar():
    err = SourceError("timeout", "Zeitüberschreitung", detail="60s")
    assert err.to_dict() == {"kind": "timeout", "message": "Zeitüberschreitung", "detail": "60s"}


# ------------------------------------------------------------- Geometrie


def test_haversine_gegen_bekannte_distanz():
    # Sendlinger Tor -> Marienplatz, laut Karte rund 600 m
    d = haversine_m(48.1334, 11.5674, 48.1374, 11.5755)
    assert 600 < d < 800
