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
from .schaetzung import Eingaben, rechne, vorgaben_aus_punkt
from .service import GRENZEN, PointService
from .sources import boris, gtfs, links, muenchen, wms

STATIC_DIR = __import__("pathlib").Path(__file__).parent / "static"

RADIUS_CHOICES = (300, 600, 900, 1400)


class SchaetzEingaben(BaseModel):
    """Alle Annahmen der Umsatzschätzung — jede einzelne kommt aus der Oberfläche.
    Es gibt keinen Wert, den der Server hinter dem Rücken des Nutzers setzt."""

    # Vorbelegt mit 0, damit ein Punkt ohne Zensuszelle bzw. ohne OSM-Objekte
    # rechenbar bleibt statt mit einem Pflichtfeldfehler abzubrechen.
    einwohner: float = Field(0, ge=0)
    wettbewerber: int = Field(0, ge=0)
    besuche_je_einwohner: float = Field(..., gt=0)
    bon_min: float = Field(..., gt=0)
    bon_max: float = Field(..., gt=0)
    marktanteil_min_prozent: float | None = Field(None, ge=0, le=100)
    marktanteil_max_prozent: float | None = Field(None, ge=0, le=100)
    unsicherheitsfaktor: float = Field(2.0, ge=1)
    oeffnungstage: int = Field(360, gt=0, le=366)
    oeffnungsstunden: float = Field(12.0, gt=0, le=24)
    mietanteil_min_prozent: float = Field(10.0, ge=0, le=100)
    mietanteil_max_prozent: float = Field(14.0, ge=0, le=100)
    # Prüfstein gegen die Wirklichkeit. Geht in keine Rechnung ein und wird
    # nicht gespeichert — er wird nur gegenübergestellt.
    kalibrierung_umsatz_eur: float | None = Field(None, ge=0)
    kalibrierung_bezeichnung: str | None = Field(None, max_length=120)


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

    @app.get("/api/point/radzaehlung")
    async def point_radzaehlung(request: Request, lat: float, lon: float, r: int = 600):
        """Gemessene Radverkehrszahlen der Landeshauptstadt München."""
        _validate(lat, lon, r)
        return (await svc(request).radzaehlung(lat, lon, r)).to_dict()

    @app.get("/api/point/verkehrsmenge")
    async def point_verkehrsmenge(request: Request, lat: float, lon: float, r: int = 600):
        """Durchschnittliche tägliche Verkehrsstärke aus der bayerischen
        Straßenverkehrszählung."""
        _validate(lat, lon, r)
        return (await svc(request).verkehrsmenge(lat, lon, r)).to_dict()

    @app.get("/api/point/gehweg")
    async def point_gehweg(
        request: Request, lat: float, lon: float, r: int = 600, refresh: bool = False
    ):
        """Gehstrecken statt Luftlinie.

        Bewusst nicht Teil von ``/api/point``: das Fußwegenetz ist die größte
        Overpass-Antwort des Werkzeugs und wird nur auf Anforderung geladen.
        """
        _validate(lat, lon, r)
        return (await svc(request).gehweg(lat, lon, r, refresh)).to_dict()

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
    async def geocode(
        request: Request,
        q: str = Query(..., min_length=2),
        refresh: bool = Query(False),
    ):
        return (await svc(request).suche(q, refresh)).to_dict()

    # ------------------------------- Bodenrichtwert-Kartendienste (Phase 4)

    @app.get("/api/wms")
    async def wms_dienste(request: Request, bundesland_code: str | None = None):
        """Konfiguration der Kartenebene. Ohne verifizierten Dienst wird der
        Grund genannt statt einer geratenen URL."""
        if bundesland_code:
            return wms.fuer_bundesland(bundesland_code)
        return wms.alle()

    @app.get("/api/wms/ebenen")
    async def wms_ebenen(request: Request, bundesland_code: str | None = None):
        """Zusätzliche amtliche Kartenebenen des Landes (Luftbild, Flurstücke)."""
        return {"ebenen": wms.zusatzebenen(bundesland_code)}

    @app.get("/api/wms/bodenrichtwert")
    async def wms_bodenrichtwert(
        request: Request, lat: float, lon: float, bundesland_code: str | None = None
    ):
        """GetFeatureInfo beim Landesdienst — über das Backend, weil ein fetch
        aus dem Browser an CORS scheitern würde."""
        _validate(lat, lon, 600)
        out: Outbound = request.app.state.outbound
        res = await wms.feature_info(out, cfg(request), lat, lon, bundesland_code)
        return res.to_dict()

    # ------------------------------------------------ Umsatzschätzung (§9)

    @app.get("/api/schaetzung/vorgaben")
    async def schaetzung_vorgaben(
        request: Request, lat: float, lon: float, r: int = 600
    ):
        """Füllt die Eingabefelder aus den Daten des Punktes vor — vorbefüllt,
        nicht festgelegt. Jeder Wert nennt seine Herkunft."""
        _validate(lat, lon, r)
        punkt = await svc(request).point(lat, lon, r)
        return vorgaben_aus_punkt(punkt)

    @app.post("/api/schaetzung")
    async def schaetzung(body: SchaetzEingaben):
        ergebnis = rechne(Eingaben(**body.model_dump()))
        if not ergebnis["ok"]:
            raise HTTPException(422, "; ".join(ergebnis["fehler"]))
        return ergebnis

    # ------------------------------------------------------- Vergleich

    @app.get("/api/points")
    async def list_points(request: Request):
        cache: AsyncCache = request.app.state.cache
        rows = await asyncio.to_thread(cache.sync.list_points)
        return {"anzahl": len(rows), "punkte": rows}

    @app.post("/api/points")
    async def save_point(request: Request, body: SavePoint):
        _validate(body.lat, body.lon, body.radius)
        service = svc(request)
        payload = await service.point(body.lat, body.lon, body.radius)
        # Gehstrecken nur übernehmen, wenn sie schon berechnet sind — das Merken
        # eines Punktes darf keine 1–3-MB-Abfrage auslösen.
        gw = await service.gehweg_aus_cache(body.lat, body.lon, body.radius)
        if gw is not None:
            payload["bloecke"]["gehweg"] = gw.to_dict()
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
        return {
            "spalten": VERGLEICH_SPALTEN,
            "gruppen": VERGLEICH_GRUPPEN,
            "zeilen": [_row_for(r) for r in rows],
        }

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


def je_bezugsgroesse(
    zaehler: Any, nenner: Any, faktor: float = 1.0, stellen: int = 1
) -> float | None:
    """Verhältniszahl aus zwei gemessenen Größen.

    Beide Bestandteile stammen aus echten Antworten; hier wird nur geteilt, es
    kommt kein gewählter Faktor hinzu. Fehlt eine Seite oder ist der Nenner 0,
    ist das Ergebnis ``None`` und nicht 0 — eine Lage ohne Einwohnerdaten hat
    keine Wettbewerbsdichte von null, sie hat gar keine.
    """
    if not isinstance(zaehler, (int, float)) or not isinstance(nenner, (int, float)):
        return None
    if isinstance(zaehler, bool) or isinstance(nenner, bool) or nenner <= 0:
        return None
    return round(zaehler / nenner * faktor, stellen)


# Spaltengruppen. Die Tabelle ist über die Ausbaustufen auf 37 Spalten
# gewachsen; ohne Gruppierung scrollt man an der Bezeichnung vorbei und findet
# nichts wieder. "vorgabe" bestimmt, welche Gruppen beim Öffnen sichtbar sind —
# ausgeschaltet werden nur Gruppen, nie einzelne Spalten, damit die Tabelle
# nicht in beliebig viele Zustände zerfällt.
VERGLEICH_GRUPPEN = [
    {"key": "standort", "titel": "Standort", "vorgabe": True, "fest": True},
    {"key": "bevoelkerung", "titel": "Bevölkerung & Wohnen", "vorgabe": True},
    {"key": "wettbewerb", "titel": "Wettbewerb", "vorgabe": True},
    {"key": "erreichbarkeit", "titel": "Erreichbarkeit zu Fuß", "vorgabe": False},
    {"key": "verkehr", "titel": "Verkehr & ÖPNV", "vorgabe": True},
    {"key": "sonstiges", "titel": "Weiteres", "vorgabe": False},
]

VERGLEICH_SPALTEN = [
    # --- Standort (immer sichtbar, erste Spalte bleibt beim Scrollen stehen) ---
    {"key": "label", "titel": "Bezeichnung", "gruppe": "standort"},
    {"key": "adresse", "titel": "Adresse", "gruppe": "standort"},
    {"key": "gemeinde", "titel": "Gemeinde", "gruppe": "standort"},
    {"key": "radius", "titel": "Radius (m)", "gruppe": "standort"},

    # --- Bevölkerung und Wohnen ---
    {"key": "einwohner", "titel": "Einwohner", "gruppe": "bevoelkerung"},
    {"key": "durchschnittsalter", "titel": "Durchschnittsalter", "gruppe": "bevoelkerung"},
    {"key": "haushaltsgroesse", "titel": "Haushaltsgröße", "gruppe": "bevoelkerung"},
    # "stellen" legt die Nachkommastellen in Tabelle und Export fest. Ohne die
    # Angabe rundet die Oberfläche auf eine Stelle — bei kleinen Verhältniszahlen
    # verschwindet damit genau der Unterschied, den man vergleichen will.
    {"key": "miete_qm", "titel": "Nettokaltmiete €/m²", "stellen": 2,
     "gruppe": "bevoelkerung"},
    {"key": "leerstandsquote", "titel": "Leerstandsquote %", "stellen": 2,
     "gruppe": "bevoelkerung"},

    # --- Wettbewerb ---
    {"key": "gastro_gesamt", "titel": "Gastronomie gesamt", "gruppe": "wettbewerb"},
    {"key": "fast_food", "titel": "davon Schnellrestaurants", "gruppe": "wettbewerb"},
    {"key": "gastro_bis_150", "titel": "Gastronomie bis 150 m", "gruppe": "wettbewerb"},
    {"key": "gastro_bis_300", "titel": "Gastronomie bis 300 m", "gruppe": "wettbewerb"},
    {"key": "naechster_wettbewerber", "titel": "Nächster Betrieb (m)",
     "gruppe": "wettbewerb"},
    {"key": "wettbewerb_je_1000", "titel": "Wettbewerber je 1.000 Einw. (berechnet)",
     "stellen": 1, "gruppe": "wettbewerb"},
    {"key": "fastfood_je_1000", "titel": "Schnellrestaurants je 1.000 Einw. (berechnet)",
     "stellen": 2, "gruppe": "wettbewerb"},

    # --- Erreichbarkeit zu Fuß (nur belegt, wenn Block 4b geladen war) ---
    {"key": "einwohner_gehweg", "titel": "Einwohner zu Fuß erreichbar",
     "gruppe": "erreichbarkeit"},
    {"key": "erschliessung_einwohner", "titel": "Erschließungsgrad Einwohner %",
     "stellen": 1, "gruppe": "erreichbarkeit"},
    {"key": "gastro_gehweg", "titel": "Gastronomie zu Fuß erreichbar",
     "gruppe": "erreichbarkeit"},
    {"key": "umwegfaktor", "titel": "Umwegfaktor (Median)", "stellen": 2,
     "gruppe": "erreichbarkeit"},

    # --- Verkehr und ÖPNV ---
    {"key": "frequenzbringer", "titel": "Frequenzbringer", "gruppe": "verkehr"},
    {"key": "haltestellen", "titel": "Haltestellen", "gruppe": "verkehr"},
    {"key": "linien", "titel": "Linien (eindeutig)", "gruppe": "verkehr"},
    {"key": "abfahrten", "titel": "Abfahrten/Tag (GTFS)", "gruppe": "verkehr"},
    {"key": "abfahrten_mittag", "titel": "Abfahrten 11–14 Uhr", "gruppe": "verkehr"},
    {"key": "mittagsanteil", "titel": "Anteil Mittag % (berechnet)", "stellen": 1,
     "gruppe": "verkehr"},
    {"key": "abfahrten_je_einwohner", "titel": "Abfahrten je Einwohner (berechnet)",
     "stellen": 2, "gruppe": "verkehr"},
    {"key": "dtv_kfz", "titel": "Kfz/Tag stärkste Zählstelle", "gruppe": "verkehr"},
    {"key": "dtv_sv_anteil", "titel": "Schwerverkehr %", "gruppe": "verkehr"},
    {"key": "rad_je_tag", "titel": "Radfahrende/Tag (Messung)", "gruppe": "verkehr"},

    # --- Weiteres ---
    {"key": "ags", "titel": "Gemeindeschlüssel", "gruppe": "sonstiges"},
    {"key": "ketten", "titel": "davon Ketten", "gruppe": "sonstiges"},
    {"key": "rad_entfernung", "titel": "Entfernung Zählstelle (m)", "gruppe": "sonstiges"},
    {"key": "neubau_anteil", "titel": "Gebäude ab 2020 %", "stellen": 1,
     "gruppe": "sonstiges"},
    {"key": "leerstand_osm", "titel": "Leerstände (OSM)", "gruppe": "sonstiges"},
    {"key": "erzeugt", "titel": "Abgerufen am", "gruppe": "sonstiges"},
]


def _row_for(saved: dict[str, Any]) -> dict[str, Any]:
    p = saved.get("payload") or {}
    punkt = p.get("punkt") or {}
    bl = p.get("bloecke") or {}
    z = (bl.get("zensus") or {}).get("data") or {}
    o = (bl.get("osm") or {}).get("data") or {}
    g = (bl.get("gtfs") or {}).get("data") or {}
    rad = ((bl.get("radzaehlung") or {}).get("data") or {}).get("naechste") or {}
    gw = ((bl.get("gehweg") or {}).get("data") or {}) or {}
    gw_gas = gw.get("gastronomie") or {}
    gw_zen = gw.get("zensus") or {}
    vm = ((bl.get("verkehrsmenge") or {}).get("data") or {}) or {}
    vms = vm.get("staerkste") or {}
    bev = z.get("bevoelkerung") or {}
    woh = z.get("wohnen") or {}
    zus = o.get("zusammenfassung") or {}
    gas = zus.get("gastronomie") or {}
    einwohner = _wert(bev.get("einwohner"))
    abfahrten = (g or {}).get("abfahrten_gesamt")
    mittag = (g or {}).get("abfahrten_mittag")
    fastfood = (gas.get("nach_typ") or {}).get("Schnellrestaurant")
    stufen = {s["bis_m"]: s["anzahl"] for s in (gas.get("nach_entfernung") or [])}
    return {
        "id": saved.get("id"),
        "label": saved.get("label"),
        "adresse": punkt.get("adresse"),
        "gemeinde": punkt.get("gemeinde"),
        "ags": punkt.get("ags"),
        "radius": saved.get("radius"),
        "einwohner": einwohner,
        "durchschnittsalter": _wert(bev.get("durchschnittsalter")),
        "haushaltsgroesse": _wert(bev.get("haushaltsgroesse")),
        "miete_qm": _wert(woh.get("miete_qm")),
        "leerstandsquote": _wert(woh.get("leerstandsquote")),
        "gastro_gesamt": gas.get("gesamt"),
        "fast_food": fastfood,
        "ketten": gas.get("ketten"),
        # Ein Betrieb in 50 m konkurriert anders als einer am Rand des Umkreises.
        "gastro_bis_150": stufen.get(150),
        "gastro_bis_300": stufen.get(300),
        "naechster_wettbewerber": gas.get("naechster_m"),
        # Sättigung: wie viele Betriebe teilen sich die Wohnbevölkerung. Sagt
        # nichts über Zulauf von außen — in der Innenstadt deshalb hoch, ohne
        # dass der Standort schlecht wäre.
        "wettbewerb_je_1000": je_bezugsgroesse(gas.get("gesamt"), einwohner, 1000, 1),
        # Für einen Imbiss sind 30 Cafés kein Wettbewerb — die engere Zahl.
        "fastfood_je_1000": je_bezugsgroesse(fastfood, einwohner, 1000, 2),
        "frequenzbringer": (zus.get("frequenzbringer") or {}).get("gesamt"),
        "haltestellen": (zus.get("oepnv") or {}).get("haltestellen"),
        "linien": (zus.get("oepnv") or {}).get("linien_eindeutig"),
        "abfahrten": abfahrten,
        # Eine Pendlerhaltestelle hat ihre Spitzen um 8 und um 18 Uhr und ist
        # mittags leer — das trennt die beiden Fälle.
        "abfahrten_mittag": mittag,
        "mittagsanteil": je_bezugsgroesse(mittag, abfahrten, 100, 1),
        # Näherung für Zulauf, den der Zensus nicht sieht: viele Abfahrten bei
        # wenig Wohnbevölkerung heißt, die Leute kommen von woanders.
        "abfahrten_je_einwohner": je_bezugsgroesse(abfahrten, einwohner, 1, 2),
        "dtv_kfz": vms.get("dtv_kfz"),
        "dtv_sv_anteil": vms.get("schwerverkehr_anteil"),
        "rad_je_tag": rad.get("je_tag_vorjahr"),
        "rad_entfernung": rad.get("distanz_m"),
        "neubau_anteil": woh.get("neubau_anteil"),
        "einwohner_gehweg": gw_zen.get("einwohner_gehweg"),
        "erschliessung_einwohner": gw_zen.get("erschliessungsgrad"),
        "gastro_gehweg": gw_gas.get("im_gehradius"),
        "umwegfaktor": gw_gas.get("umwegfaktor_median"),
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
    rad = ((bl.get("radzaehlung") or {}).get("data") or {}).get("naechste") or {}
    vm = ((bl.get("verkehrsmenge") or {}).get("data") or {}) or {}
    vms = vm.get("staerkste") or {}
    if g:
        w.writerow(["Verkehr", "Abfahrten gesamt", g.get("abfahrten_gesamt"), "je Tag",
                    g.get("referenzdatum", ""), gsrc, gstand, glic])
        for h, n in (g.get("abfahrten_je_stunde") or {}).items():
            w.writerow(["Verkehr", f"Abfahrten {h}:00", n, "je Stunde",
                        g.get("referenzdatum", ""), gsrc, gstand, glic])

    rsrc, rstand, rlic = prov("radzaehlung")
    r = (bl.get("radzaehlung") or {}).get("data") or {}
    for s_ in r.get("in_reichweite") or []:
        w.writerow(["Radverkehr", f"Zählstelle {s_['name']}", s_.get("je_tag_vorjahr"),
                    "Radfahrende je Tag", f"{s_['distanz_m']} m entfernt",
                    rsrc, rstand, rlic])

    vsrc, vstand, vlic = prov("verkehrsmenge")
    v = (bl.get("verkehrsmenge") or {}).get("data") or {}
    for z in v.get("zaehlstellen") or []:
        w.writerow(["Verkehrsmenge", f"{z['strasse']} (Zählstelle {z['zaehlstelle']})",
                    z.get("dtv_kfz"), "Kfz je Tag", f"{z['distanz_m']} m entfernt",
                    vsrc, vstand, vlic])

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
