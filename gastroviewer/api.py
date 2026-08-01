"""HTTP-Schnittstelle.

Neben ``/api/point`` (alles auf einmal) gibt es je Quelle einen eigenen Endpunkt.
Das Frontend ruft die einzeln auf, damit jeder Block seinen eigenen Ladezustand
und seine eigene Fehlermeldung bekommt (Spec §5) — und damit der Ausfall einer
Quelle die übrigen nicht aufhält.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .cache import AsyncCache
from .config import Settings, get_settings
from .http import Outbound
from .service import GRENZEN, PointService
from .sources import boris, gtfs, links

STATIC_DIR = __import__("pathlib").Path(__file__).parent / "static"

RADIUS_CHOICES = (300, 600, 900, 1400)


class SavePoint(BaseModel):
    """Muss auf Modulebene stehen: mit ``from __future__ import annotations`` sind
    Annotationen Strings, die FastAPI nur im Modul-Namensraum auflösen kann. In einer
    Funktion definiert, hielte FastAPI das Modell für einen Query-Parameter."""

    label: str = Field(..., min_length=1, max_length=120)
    lat: float
    lon: float
    radius: int = 600


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    settings.ensure_dirs()
    cache = AsyncCache(settings.db_path)
    outbound = Outbound(settings, cache)
    await outbound.start()
    app.state.cache = cache
    app.state.outbound = outbound
    app.state.service = PointService(settings, cache, outbound)
    try:
        yield
    finally:
        await outbound.aclose()


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(
        title="Standort-Datenterminal",
        description="Offene Daten zu einem Punkt in Deutschland. Daten-Browser, kein Prognose-Tool.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings or get_settings()

    def svc(request: Request) -> PointService:
        return request.app.state.service

    def cfg(request: Request) -> Settings:
        return request.app.state.settings

    # ------------------------------------------------------------- Basis

    @app.get("/api/health")
    async def health(request: Request):
        s = cfg(request)
        return {
            "status": "ok",
            "version": s.version,
            "user_agent": s.user_agent,
            "datenverzeichnis": str(s.data_dir),
            "gtfs": gtfs.status(s),
            "radien": list(RADIUS_CHOICES),
        }

    @app.get("/api/stats")
    async def stats(request: Request):
        cache: AsyncCache = request.app.state.cache
        out: Outbound = request.app.state.outbound
        data = await cache.stats()
        data["rate_limiter"] = out.limiters.stats()
        data["endpunkte"] = {
            "overpass": list(cfg(request).overpass_endpoints),
            "nominatim": cfg(request).nominatim_base,
            "zensus": cfg(request).zensus_base,
        }
        return data

    @app.get("/api/outbound")
    async def outbound_log(request: Request, seit: float = Query(0, description="Unix-Zeit")):
        cache: AsyncCache = request.app.state.cache
        rows = await asyncio.to_thread(cache.sync.outbound_since, seit)
        return {"anzahl": len(rows), "eintraege": rows}

    # ------------------------------------------------------------ Punkte

    def _validate(lat: float, lon: float, r: int) -> None:
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            raise HTTPException(422, "Koordinaten außerhalb des gültigen Bereichs.")
        # Deutschland grob; außerhalb liefern Zensus und BORIS ohnehin nichts.
        if not (47.0 <= lat <= 55.5 and 5.5 <= lon <= 15.5):
            raise HTTPException(
                422,
                "Punkt liegt außerhalb Deutschlands. Zensus 2022 und die "
                "Bodenrichtwert-Portale decken nur Deutschland ab.",
            )
        if not (50 <= r <= 5000):
            raise HTTPException(422, "Radius muss zwischen 50 und 5000 Metern liegen.")

    @app.get("/api/point")
    async def point(
        request: Request,
        lat: float = Query(...),
        lon: float = Query(...),
        r: int = Query(600),
        refresh: bool = Query(False),
    ):
        _validate(lat, lon, r)
        return await svc(request).point(lat, lon, r, refresh)

    @app.get("/api/point/adresse")
    async def point_adresse(
        request: Request, lat: float, lon: float, refresh: bool = False
    ):
        _validate(lat, lon, 600)
        return (await svc(request).adresse(lat, lon, refresh)).to_dict()

    @app.get("/api/point/zensus")
    async def point_zensus(
        request: Request, lat: float, lon: float, r: int = 600, refresh: bool = False
    ):
        _validate(lat, lon, r)
        return (await svc(request).zensus(lat, lon, r, refresh)).to_dict()

    @app.get("/api/point/osm")
    async def point_osm(
        request: Request, lat: float, lon: float, r: int = 600, refresh: bool = False
    ):
        _validate(lat, lon, r)
        return (await svc(request).osm(lat, lon, r, refresh)).to_dict()

    @app.get("/api/point/gtfs")
    async def point_gtfs(request: Request, lat: float, lon: float, r: int = 600):
        _validate(lat, lon, r)
        return (await svc(request).gtfs(lat, lon, r)).to_dict()

    @app.get("/api/point/links")
    async def point_links(
        request: Request,
        lat: float,
        lon: float,
        r: int = 600,
        gemeinde: str | None = None,
        plz: str | None = None,
        ags: str | None = None,
        bundesland_code: str | None = None,
    ):
        _validate(lat, lon, r)
        return {
            "bodenrichtwerte": boris.links_for(bundesland_code, gemeinde),
            "weiterfuehrend": links.build(
                lat, lon, r, gemeinde=gemeinde, plz=plz, ags=ags
            ),
            "grenzen": GRENZEN,
        }

    @app.get("/api/geocode")
    async def geocode(request: Request, q: str = Query(..., min_length=2)):
        return (await svc(request).suche(q)).to_dict()

    # ------------------------------------------------------- Vergleich

    @app.get("/api/points")
    async def list_points(request: Request):
        cache: AsyncCache = request.app.state.cache
        rows = await asyncio.to_thread(cache.sync.list_points)
        return {"anzahl": len(rows), "punkte": rows}

    @app.post("/api/points")
    async def save_point(request: Request, body: SavePoint):
        _validate(body.lat, body.lon, body.radius)
        payload = await svc(request).point(body.lat, body.lon, body.radius)
        cache: AsyncCache = request.app.state.cache
        pid = await asyncio.to_thread(
            cache.sync.save_point,
            body.label,
            body.lat,
            body.lon,
            body.radius,
            _compact(payload),
        )
        return {"id": pid, "label": body.label}

    @app.delete("/api/points/{point_id}")
    async def delete_point(request: Request, point_id: int):
        cache: AsyncCache = request.app.state.cache
        ok = await asyncio.to_thread(cache.sync.delete_point, point_id)
        if not ok:
            raise HTTPException(404, "Punkt nicht gefunden.")
        return {"geloescht": point_id}

    @app.get("/api/points/vergleich")
    async def vergleich(request: Request):
        cache: AsyncCache = request.app.state.cache
        rows = await asyncio.to_thread(cache.sync.list_points)
        return {"spalten": VERGLEICH_SPALTEN, "zeilen": [_row_for(r) for r in rows]}

    # ---------------------------------------------------------- Export

    @app.get("/api/export/point.json")
    async def export_json(request: Request, lat: float, lon: float, r: int = 600):
        _validate(lat, lon, r)
        data = await svc(request).point(lat, lon, r)
        name = f"standort_{lat:.5f}_{lon:.5f}_{r}m.json"
        return Response(
            content=json.dumps(data, ensure_ascii=False, indent=2),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    @app.get("/api/export/point.csv")
    async def export_csv(request: Request, lat: float, lon: float, r: int = 600):
        _validate(lat, lon, r)
        data = await svc(request).point(lat, lon, r)
        csv_text = point_to_csv(data)
        name = f"standort_{lat:.5f}_{lon:.5f}_{r}m.csv"
        return PlainTextResponse(
            csv_text,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    @app.get("/api/export/vergleich.csv")
    async def export_vergleich(request: Request):
        cache: AsyncCache = request.app.state.cache
        rows = await asyncio.to_thread(cache.sync.list_points)
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow([c["titel"] for c in VERGLEICH_SPALTEN])
        for r in rows:
            vals = _row_for(r)
            w.writerow([vals.get(c["key"], "") for c in VERGLEICH_SPALTEN])
        return PlainTextResponse(
            buf.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="standortvergleich.csv"'},
        )

    # ----------------------------------------------------------- Cache

    @app.delete("/api/cache")
    async def clear_cache(request: Request, quelle: str | None = None):
        cache: AsyncCache = request.app.state.cache
        n = await asyncio.to_thread(cache.sync.clear, quelle)
        return {"geloescht": n, "quelle": quelle or "alle"}

    # --------------------------------------------------------- Frontend

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

        @app.get("/")
        async def index():
            return FileResponse(STATIC_DIR / "index.html")

    @app.exception_handler(500)
    async def on_error(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={"fehler": f"{type(exc).__name__}: {exc}"},
        )

    return app


# ------------------------------------------------------------- Helfer


def _wert(node: Any) -> Any:
    """Aggregate liegen als {"wert": …, "zellen": …} vor."""
    if isinstance(node, dict) and "wert" in node:
        return node["wert"]
    return node


VERGLEICH_SPALTEN = [
    {"key": "label", "titel": "Bezeichnung"},
    {"key": "adresse", "titel": "Adresse"},
    {"key": "gemeinde", "titel": "Gemeinde"},
    {"key": "ags", "titel": "Gemeindeschlüssel"},
    {"key": "radius", "titel": "Radius (m)"},
    {"key": "einwohner", "titel": "Einwohner"},
    {"key": "durchschnittsalter", "titel": "Durchschnittsalter"},
    {"key": "haushaltsgroesse", "titel": "Haushaltsgröße"},
    {"key": "miete_qm", "titel": "Nettokaltmiete €/m²"},
    {"key": "leerstandsquote", "titel": "Leerstandsquote %"},
    {"key": "gastro_gesamt", "titel": "Gastronomie gesamt"},
    {"key": "fast_food", "titel": "davon Schnellrestaurants"},
    {"key": "ketten", "titel": "davon Ketten"},
    {"key": "frequenzbringer", "titel": "Frequenzbringer"},
    {"key": "haltestellen", "titel": "Haltestellen"},
    {"key": "linien", "titel": "Linien (eindeutig)"},
    {"key": "abfahrten", "titel": "Abfahrten/Tag (GTFS)"},
    {"key": "leerstand_osm", "titel": "Leerstände (OSM)"},
    {"key": "erzeugt", "titel": "Abgerufen am"},
]


def _row_for(saved: dict[str, Any]) -> dict[str, Any]:
    p = saved.get("payload") or {}
    punkt = p.get("punkt") or {}
    bl = p.get("bloecke") or {}
    z = (bl.get("zensus") or {}).get("data") or {}
    o = (bl.get("osm") or {}).get("data") or {}
    g = (bl.get("gtfs") or {}).get("data") or {}
    bev = z.get("bevoelkerung") or {}
    woh = z.get("wohnen") or {}
    zus = o.get("zusammenfassung") or {}
    gas = zus.get("gastronomie") or {}
    return {
        "id": saved.get("id"),
        "label": saved.get("label"),
        "adresse": punkt.get("adresse"),
        "gemeinde": punkt.get("gemeinde"),
        "ags": punkt.get("ags"),
        "radius": saved.get("radius"),
        "einwohner": _wert(bev.get("einwohner")),
        "durchschnittsalter": _wert(bev.get("durchschnittsalter")),
        "haushaltsgroesse": _wert(bev.get("haushaltsgroesse")),
        "miete_qm": _wert(woh.get("miete_qm")),
        "leerstandsquote": _wert(woh.get("leerstandsquote")),
        "gastro_gesamt": gas.get("gesamt"),
        "fast_food": (gas.get("nach_typ") or {}).get("Schnellrestaurant"),
        "ketten": gas.get("ketten"),
        "frequenzbringer": (zus.get("frequenzbringer") or {}).get("gesamt"),
        "haltestellen": (zus.get("oepnv") or {}).get("haltestellen"),
        "linien": (zus.get("oepnv") or {}).get("linien_eindeutig"),
        "abfahrten": (g or {}).get("abfahrten_gesamt"),
        "leerstand_osm": (zus.get("leerstand") or {}).get("gesamt"),
        "erzeugt": (p.get("meta") or {}).get("erzeugt"),
        "lat": saved.get("lat"),
        "lon": saved.get("lon"),
    }


def _compact(payload: dict[str, Any]) -> dict[str, Any]:
    """Für die Ablage: Rohlisten kürzen, Kennzahlen und Quellen behalten."""
    import copy

    p = copy.deepcopy(payload)
    z = ((p.get("bloecke") or {}).get("zensus") or {}).get("data")
    if isinstance(z, dict):
        z.pop("zellen", None)
    return p


def point_to_csv(data: dict[str, Any]) -> str:
    """Ein Punkt als CSV — je Zeile eine Kennzahl mit Quelle und Stand (Spec §5)."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Block", "Kennzahl", "Wert", "Einheit", "Zellen/Basis", "Quelle", "Stand", "Lizenz"])

    punkt = data.get("punkt") or {}
    meta = data.get("meta") or {}
    for k, v in punkt.items():
        w.writerow(["Kopf", k, v, "", "", "abgeleitet", meta.get("erzeugt", ""), ""])

    bl = data.get("bloecke") or {}

    def prov(name: str) -> tuple[str, str, str]:
        p = (bl.get(name) or {}).get("provenance") or {}
        return p.get("source", ""), p.get("stand", ""), p.get("license", "")

    zsrc, zstand, zlic = prov("zensus")
    z = (bl.get("zensus") or {}).get("data") or {}
    for block, felder in (("Bevölkerung", z.get("bevoelkerung")), ("Wohnen", z.get("wohnen"))):
        for key, node in (felder or {}).items():
            if isinstance(node, dict) and "wert" in node:
                einheit = _einheit(key)
                w.writerow(
                    [block, key, node["wert"], einheit,
                     f"{node.get('zellen', '')}/{node.get('zellen_gesamt', '')} Zellen",
                     zsrc, zstand, zlic]
                )
            elif isinstance(node, dict):
                for sub, snode in node.items():
                    if isinstance(snode, dict) and "wert" in snode:
                        w.writerow(
                            [block, f"{key}: {sub}", snode["wert"], "",
                             f"{snode.get('zellen', '')}/{snode.get('zellen_gesamt', '')} Zellen",
                             zsrc, zstand, zlic]
                        )

    osrc, ostand, olic = prov("osm")
    o = (bl.get("osm") or {}).get("data") or {}
    zus = o.get("zusammenfassung") or {}
    for block, felder in zus.items():
        for key, val in (felder or {}).items():
            if isinstance(val, dict):
                for sub, sval in val.items():
                    w.writerow([block, f"{key}: {sub}", sval, "", "", osrc, ostand, olic])
            else:
                w.writerow([block, key, val, "", "", osrc, ostand, olic])

    gsrc, gstand, glic = prov("gtfs")
    g = (bl.get("gtfs") or {}).get("data") or {}
    if g:
        w.writerow(["Verkehr", "Abfahrten gesamt", g.get("abfahrten_gesamt"), "je Tag",
                    g.get("referenzdatum", ""), gsrc, gstand, glic])
        for h, n in (g.get("abfahrten_je_stunde") or {}).items():
            w.writerow(["Verkehr", f"Abfahrten {h}:00", n, "je Stunde",
                        g.get("referenzdatum", ""), gsrc, gstand, glic])

    for i, hinweis in enumerate(data.get("grenzen") or [], 1):
        w.writerow(["Grenzen", f"Hinweis {i}", hinweis, "", "", "", "", ""])

    return buf.getvalue()


def _einheit(key: str) -> str:
    if key.startswith("anteil") or key.endswith("quote"):
        return "%"
    if key == "miete_qm":
        return "€/m²"
    if key.startswith("flaeche"):
        return "m²"
    if key == "durchschnittsalter":
        return "Jahre"
    if key == "haushaltsgroesse":
        return "Personen"
    if key == "einwohner":
        return "Personen"
    return ""
