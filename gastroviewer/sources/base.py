"""Gemeinsame Bausteine der Datenquellen.

Jede Quelle liefert ein ``SourceResult``. Das Ergebnis trägt immer:

* ``ok``          — hat die Quelle geliefert?
* ``data``        — die aufbereiteten Werte
* ``provenance``  — Quelle, Stand, Lizenz, Abrufzeitpunkt, Endpunkt
* ``error``       — bei Ausfall eine **konkrete** Ursache

Spec §5 verlangt ausdrücklich konkrete Fehlermeldungen: nicht „Dienst überlastet"
schreiben, wenn in Wahrheit ein Timeout, ein HTTP-Status oder ein fehlendes Feld
das Problem ist. Deshalb trägt jeder Fehler eine Kategorie mit.
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any


class SourceError(Exception):
    """Fehler mit konkreter, für den Nutzer verwertbarer Ursache."""

    def __init__(self, kind: str, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "message": self.message, "detail": self.detail}


@dataclass
class Provenance:
    """Quellenangabe je Block — Spec §5: „Quelle · Stand · Lizenz"."""

    source: str
    license: str
    endpoint: str | None = None
    stand: str | None = None  # Stichtag / Datenstand der Quelle selbst
    retrieved_at: str | None = None  # Abrufzeitpunkt (ISO 8601)
    cached: bool = False
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class SourceResult:
    name: str
    ok: bool
    data: Any = None
    provenance: Provenance | None = None
    error: dict[str, Any] | None = None
    duration_ms: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "data": self.data,
            "provenance": self.provenance.to_dict() if self.provenance else None,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "warnings": self.warnings,
        }

    @classmethod
    def failed(cls, name: str, err: SourceError, duration_ms: int = 0) -> "SourceResult":
        return cls(name=name, ok=False, error=err.to_dict(), duration_ms=duration_ms)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


EARTH_RADIUS_M = 6371008.8


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanz in Metern. Für Radien bis wenige Kilometer mehr als genau genug."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def bearing_label(lat1: float, lon1: float, lat2: float, lon2: float) -> str:
    """Himmelsrichtung als Kürzel — hilft beim Einordnen der Trefferliste."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    y = math.sin(dlam) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlam)
    deg = (math.degrees(math.atan2(y, x)) + 360) % 360
    names = ["N", "NO", "O", "SO", "S", "SW", "W", "NW"]
    return names[int((deg + 22.5) // 45) % 8]
