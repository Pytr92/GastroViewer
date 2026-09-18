"""Router-Aufteilung: verhaltensneutral — dieselben Routen, dieselbe
Reihenfolge, wo sie zählt."""

from __future__ import annotations

from conftest import api_routen

from gastroviewer.api import create_app
from gastroviewer.config import Settings


def _pfade():
    app = create_app(Settings())
    return [r.path for r in api_routen(app) if r.path.startswith("/api")]


def test_feste_pfade_stehen_vor_dem_pfadparameter():
    """Starlette prüft Pfad vor Methode: ein GET auf /api/points/vergleich
    darf nicht vorher an GET /api/points/{point_id} hängen bleiben (422,
    weil „vergleich" keine Zahl ist). PATCH/DELETE auf {point_id} dürfen
    früher stehen — andere Methode, kein Konflikt."""
    routen = [r for r in api_routen(create_app(Settings())) if r.path.startswith("/api")]
    parameter = next(i for i, r in enumerate(routen)
                     if r.path == "/api/points/{point_id}" and "GET" in r.methods)
    pfade = [r.path for r in routen]
    for fest in ("/api/points/vergleich", "/api/points/export", "/api/points/import",
                 "/api/points/kriterien", "/api/points/kannibalisierung"):
        assert pfade.index(fest) < parameter, f"{fest} muss vor dem Pfadparameter stehen"


def test_jede_route_genau_einmal_je_methode():
    app = create_app(Settings())
    gesehen = set()
    for r in api_routen(app):
        for m in getattr(r, "methods", None) or ():
            if m in ("HEAD", "OPTIONS"):
                continue
            assert (m, r.path) not in gesehen, (m, r.path)
            gesehen.add((m, r.path))
    assert len({p for _, p in gesehen if p.startswith("/api")}) >= 60


def test_alle_router_eingebunden():
    from gastroviewer.routen import ALLE_ROUTER

    pfade = set(_pfade())
    for router in ALLE_ROUTER:
        for r in router.routes:
            assert r.path in pfade, r.path
    assert {"/api/health", "/api/point", "/api/points", "/api/schaetzung", "/api/wms"} <= pfade
