"""HTTP-Routen, nach Themen getrennt.

Vorher hingen alle 71 Endpunkte als Closures in einer 1.100-Zeilen-Funktion
``create_app``. Jetzt je Thema ein ``APIRouter``; ``create_app`` in api.py
bindet sie in dieser Reihenfolge ein. Innerhalb von ``punkte`` zählt die
Reihenfolge: die festen Pfade (vergleich, export, import, kriterien,
kannibalisierung) müssen vor ``/api/points/{point_id}`` stehen — ein Test
in tests/test_routen.py hält das fest.

Was die Routen brauchen (Service, Settings, Bereichsregel), liegt in
``_gemeinsam``; die Pydantic-Modelle in ``modelle``.
"""

from . import punkt, punkte, region, schaetzung, system

ALLE_ROUTER = [system.router, punkt.router, region.router,
               schaetzung.router, punkte.router]

__all__ = ["ALLE_ROUTER"]
