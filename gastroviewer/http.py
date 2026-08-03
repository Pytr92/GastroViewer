"""Ausgehende HTTP-Aufrufe: Rate-Limit, Protokoll, konkrete Fehler.

Jeder echte Netzaufruf läuft durch ``Outbound.request``. Damit gilt: was nicht hier
durchkommt, erzeugt keinen Traffic — die Grundlage für den Cache-Nachweis aus §7.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from .cache import AsyncCache
from .config import Settings
from .ratelimit import Limiters
from .sources.base import SourceError


def classify(exc: Exception) -> SourceError:
    """Übersetzt eine Ausnahme in eine benennbare Ursache (Spec §5)."""
    if isinstance(exc, httpx.TimeoutException):
        return SourceError(
            "timeout",
            "Zeitüberschreitung — der Dienst hat nicht rechtzeitig geantwortet.",
            detail=str(exc),
        )
    if isinstance(exc, httpx.ConnectError):
        return SourceError(
            "connect",
            "Verbindung nicht möglich — Dienst nicht erreichbar, DNS- oder Proxy-Problem.",
            detail=str(exc),
        )
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        body = (exc.response.text or "")[:300]
        if code == 429:
            msg = "HTTP 429 — Anfragelimit des Dienstes erreicht."
        elif code == 403:
            msg = "HTTP 403 — Zugriff abgelehnt (fehlender/abgelehnter User-Agent?)."
        elif code == 504:
            msg = "HTTP 504 — der Dienst hat die Abfrage abgebrochen (zu groß/zu langsam)."
        elif 500 <= code < 600:
            msg = f"HTTP {code} — Serverfehler beim Dienst."
        else:
            msg = f"HTTP {code} — Anfrage abgelehnt."
        return SourceError("http_status", msg, detail=body)
    if isinstance(exc, httpx.HTTPError):
        return SourceError("network", f"Netzwerkfehler: {type(exc).__name__}", detail=str(exc))
    if isinstance(exc, ValueError):
        return SourceError(
            "parse", "Antwort war kein gültiges JSON — Format des Dienstes geändert?",
            detail=str(exc)[:300],
        )
    return SourceError("unknown", f"Unerwarteter Fehler: {type(exc).__name__}", detail=str(exc))


class Outbound:
    def __init__(self, settings: Settings, cache: AsyncCache) -> None:
        self.settings = settings
        self.cache = cache
        self.limiters = Limiters()
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    "User-Agent": self.settings.user_agent,
                    "Accept-Language": "de,en;q=0.8",
                },
                follow_redirects=True,
                timeout=httpx.Timeout(30.0, connect=10.0),
            )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Outbound.start() wurde nicht aufgerufen")
        return self._client

    async def request(
        self,
        source: str,
        method: str,
        url: str,
        *,
        limiter: str | None = None,
        min_interval: float = 0.0,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Ein ausgehender Aufruf. Rate-Limit vorher, Protokoll immer."""
        if limiter:
            await self.limiters.get(limiter, min_interval).acquire()

        started = time.perf_counter()
        try:
            resp = await self.client.request(method, url, timeout=timeout, **kwargs)
        except Exception as exc:  # noqa: BLE001 — wird sofort klassifiziert
            ms = int((time.perf_counter() - started) * 1000)
            err = classify(exc)
            await self.cache.log_outbound(
                source, url, duration_ms=ms, error=f"{err.kind}: {err.message}"
            )
            raise err from exc

        ms = int((time.perf_counter() - started) * 1000)
        await self.cache.log_outbound(
            source, url, status=resp.status_code, duration_ms=ms, size=len(resp.content)
        )
        if resp.status_code >= 400:
            raise classify(httpx.HTTPStatusError("status", request=resp.request, response=resp))
        return resp

    async def get_json(self, source: str, url: str, **kwargs: Any) -> Any:
        resp = await self.request(source, "GET", url, **kwargs)
        return _json_or_raise(resp)

    async def post_json(self, source: str, url: str, **kwargs: Any) -> Any:
        resp = await self.request(source, "POST", url, **kwargs)
        return _json_or_raise(resp)

    async def get_text(
        self, source: str, url: str, *, encoding: str | None = None, **kwargs: Any
    ) -> str:
        """Für Dienste, die Textdateien statt JSON liefern (DWD Open Data).
        ``encoding`` überschreibt die geratene Kodierung — die DWD-Dateien
        sind Latin-1 und deklarieren das nicht."""
        resp = await self.request(source, "GET", url, **kwargs)
        if encoding:
            resp.encoding = encoding
        return resp.text


def _json_or_raise(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError as exc:
        head = (resp.text or "")[:200].replace("\n", " ")
        raise SourceError(
            "parse",
            "Antwort war kein gültiges JSON — Format des Dienstes geändert?",
            detail=f"{exc}; Anfang der Antwort: {head}",
        ) from exc
