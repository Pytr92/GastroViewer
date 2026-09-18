"""Was alle Routen brauchen: Service und Settings aus dem App-Zustand,
die Bereichsregel für Koordinaten und Radius."""

from __future__ import annotations

from fastapi import HTTPException, Request

from ..cache import pruefe_punkt
from ..config import Settings
from ..service import PointService

# 2000/3000 sind bewusst dabei, aber teuer: r=3000 am dichtesten Punkt
# Münchens sind ~9.750 OSM-Elemente und 4,5 MB (gemessen 01.08.2026).
RADIUS_CHOICES = (300, 600, 900, 1400, 2000, 3000)


def svc(request: Request) -> PointService:
    service = getattr(request.app.state, "service", None)
    if service is None:
        # Passiert, wenn die App ohne Lifespan läuft (z. B. TestClient ohne
        # `with`). Ohne diese Meldung käme ein nacktes AttributeError.
        raise HTTPException(
            503,
            "Der Dienst ist nicht initialisiert — der Lifespan der Anwendung "
            "wurde nicht gestartet.",
        )
    return service


def cfg(request: Request) -> Settings:
    return request.app.state.settings


def validiere_punkt(lat: float, lon: float, r: int) -> None:
    """Bereichsregel aus cache.pruefe_punkt — eine Stelle für Anfragen
    und Sicherungen."""
    try:
        pruefe_punkt(lat, lon, r)
    except ValueError as err:
        raise HTTPException(422, str(err)) from err
