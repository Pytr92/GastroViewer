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
import time


class RateLimiter:
    def __init__(self, min_interval: float) -> None:
        self.min_interval = float(min_interval)
        self._lock = asyncio.Lock()
        self._last = 0.0
        self.waits = 0
        self.acquisitions = 0

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
            "acquisitions": self.acquisitions,
            "throttled": self.waits,
        }


class Limiters:
    """Registry, damit jede Quelle ihren eigenen Abstand bekommt."""

    def __init__(self) -> None:
        self._limiters: dict[str, RateLimiter] = {}

    def get(self, name: str, min_interval: float) -> RateLimiter:
        limiter = self._limiters.get(name)
        if limiter is None:
            limiter = RateLimiter(min_interval)
            self._limiters[name] = limiter
        return limiter

    def stats(self) -> dict[str, dict]:
        return {name: lim.stats() for name, lim in self._limiters.items()}
