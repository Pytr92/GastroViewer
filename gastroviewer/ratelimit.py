"""Rate-Limiter mit Mindestabstand je Dienst.

Nominatim erlaubt höchstens eine Anfrage pro Sekunde. Das ist Bedingung für die
Nutzung, nicht Empfehlung (Spec §4.3) — in Phase 0 bestätigt: ohne ``User-Agent``
antwortet der Dienst mit HTTP 403.

Umsetzung als serialisierte Warteschlange: der Lock stellt sicher, dass immer nur
ein Aufrufer im kritischen Abschnitt ist, und ``last`` erzwingt den Mindestabstand.
Damit kann auch bei parallelen Anfragen kein zweiter Aufruf innerhalb des Intervalls
hinausgehen.
"""

from __future__ import annotations

import asyncio
import contextlib
import time


class RateLimiter:
    """Mindestabstand zwischen Starts — und optional eine Obergrenze für
    gleichzeitig laufende Anfragen.

    Der Abstand allein reicht bei Overpass nicht: eine Abfrage läuft 10–90 s,
    ein Startabstand von 1 s ließe also Dutzende parallel in Flug. Das
    Versprechen „höchstens eine Abfrage gleichzeitig" hält erst das
    Semaphore in :meth:`slot`, das die **ganze** Anfrage umschließt."""

    def __init__(self, min_interval: float, max_concurrent: int | None = None) -> None:
        self.min_interval = float(min_interval)
        self.max_concurrent = int(max_concurrent) if max_concurrent else None
        self._lock = asyncio.Lock()
        self._semaphore = (
            asyncio.Semaphore(self.max_concurrent) if self.max_concurrent else None
        )
        self._last = 0.0
        self.waits = 0
        self.acquisitions = 0
        self.in_flight = 0

    @contextlib.asynccontextmanager
    async def slot(self):
        """Ein Platz für eine ganze Anfrage. Ohne ``max_concurrent`` nur der
        Zähler ``in_flight`` — sichtbar unter ``/api/outbound``."""
        if self._semaphore is not None:
            await self._semaphore.acquire()
        self.in_flight += 1
        try:
            yield
        finally:
            self.in_flight -= 1
            if self._semaphore is not None:
                self._semaphore.release()

    async def acquire(self) -> float:
        """Blockiert, bis der Mindestabstand eingehalten ist.
        Gibt die tatsächlich gewartete Zeit in Sekunden zurück."""
        async with self._lock:
            now = time.monotonic()
            delta = now - self._last
            waited = 0.0
            if self._last and delta < self.min_interval:
                waited = self.min_interval - delta
                self.waits += 1
                await asyncio.sleep(waited)
            self._last = time.monotonic()
            self.acquisitions += 1
            return waited

    def stats(self) -> dict[str, float | int]:
        return {
            "min_interval_s": self.min_interval,
            "max_concurrent": self.max_concurrent,
            "in_flight": self.in_flight,
            "acquisitions": self.acquisitions,
            "throttled": self.waits,
        }


class Limiters:
    """Registry, damit jede Quelle ihren eigenen Abstand bekommt."""

    def __init__(self) -> None:
        self._limiters: dict[str, RateLimiter] = {}

    def get(
        self, name: str, min_interval: float, max_concurrent: int | None = None,
    ) -> RateLimiter:
        limiter = self._limiters.get(name)
        if limiter is None:
            limiter = RateLimiter(min_interval, max_concurrent)
            self._limiters[name] = limiter
        elif max_concurrent is not None and limiter.max_concurrent != int(max_concurrent):
            raise ValueError(
                f"Limiter {name!r} ist mit höchstens {limiter.max_concurrent} "
                f"gleichzeitigen Anfragen angelegt, jetzt werden {max_concurrent} "
                "verlangt — eine Obergrenze je Dienst.")
        elif abs(limiter.min_interval - float(min_interval)) > 1e-9:
            # Ein Limiter hat genau einen Abstand. Vorher gewann der erste
            # Aufrufer stillschweigend — Photon lief dann je nach Reihenfolge
            # mit 0,3 s oder 1,0 s. Ein Programmierfehler soll laut sein.
            raise ValueError(
                f"Limiter {name!r} ist mit {limiter.min_interval} s angelegt, "
                f"jetzt werden {float(min_interval)} s verlangt — ein Abstand je Dienst.")
        return limiter

    def stats(self) -> dict[str, dict]:
        return {name: lim.stats() for name, lim in self._limiters.items()}
