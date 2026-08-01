"""Verkehrsmengen aus der bayerischen Straßenverkehrszählung (BAYSIS).

Für einen Schnellgastronomie-Standort an einer Ausfallstraße, mit Drive-through
oder mit Parkplatz ist die **durchschnittliche tägliche Verkehrsstärke** die
aussagekräftigste Frequenzgröße überhaupt — und anders als Passantenströme ist
sie amtlich gemessen und frei verfügbar.

Verifiziert am 2026-08-01:
``https://gisportal-stmb.bayern.de/server/services/WFS/BAYSIS_Verkehrsdaten/MapServer/WFSServer``
· WFS 2.0.0 · GeoJSON · **9.441 Zählstellen in Bayern** · CC BY 4.0.

Gelieferte Felder je Zählstelle:

* ``DTV_Kfz`` — alle Kraftfahrzeuge je Tag
* ``DTV_LV``  — Leichtverkehr
* ``DTV_SV``  — Schwerverkehr
* ``Straße``, ``Zählstelle``, ``Zählart``

Was die Zahlen **nicht** sind: eine Passantenzählung und keine flächendeckende
Erhebung des innerstädtischen Netzes. Gezählt wird das klassifizierte Straßennetz
— Autobahnen, Bundes-, Staats- und Kreisstraßen. Eine Fußgängerzone taucht darin
nicht auf, eine Ausfallstraße sehr wohl.
"""

from __future__ import annotations

import time
from typing import Any

from ..config import Settings
from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, bearing_label, haversine_m, now_iso

WFS_URL = (
    "https://gisportal-stmb.bayern.de/server/services/WFS/"
    "BAYSIS_Verkehrsdaten/MapServer/WFSServer"
)
TYPENAME = "BAYSIS_Verkehrsdaten:svz2021_zaehlstellen"

LIZENZ = (
    "Creative Commons Namensnennung 4.0 (CC BY 4.0) · "
    "Datenquelle: Bayerische Straßenbauverwaltung – BAYSIS (https://www.baysis.bayern.de)"
)
STAND = "Straßenverkehrszählung 2021"

# Zählstellen liegen im klassifizierten Netz, also weit auseinander (9.441 für
# ganz Bayern ≈ eine je 7,5 km²). Über dieser Entfernung sagt eine Zählstelle
# über den Standort nichts mehr aus.
MAX_DISTANZ_M = 2000

# Bayern grob, als Vorabprüfung: außerhalb spart der Check den Netzaufruf.
BAYERN_BBOX = (47.20, 8.90, 50.60, 13.90)


def in_bayern(lat: float, lon: float) -> bool:
    return (
        BAYERN_BBOX[0] <= lat <= BAYERN_BBOX[2]
        and BAYERN_BBOX[1] <= lon <= BAYERN_BBOX[3]
    )


def _zahl(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def aufbereiten(
    features: list[dict[str, Any]], lat: float, lon: float, radius: int
) -> dict[str, Any]:
    stellen = []
    for f in features:
        p = f.get("properties") or {}
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if geom.get("type") != "Point" or len(coords) < 2:
            continue
        slon, slat = float(coords[0]), float(coords[1])
        dist = haversine_m(lat, lon, slat, slon)
        if dist > MAX_DISTANZ_M:
            continue
        kfz = _zahl(p.get("DTV_Kfz"))
        sv = _zahl(p.get("DTV_SV"))
        stellen.append(
            {
                "strasse": p.get("Straße") or p.get("Strasse"),
                "zaehlstelle": p.get("Zählstelle") or p.get("Zaehlstelle"),
                "zaehlart": p.get("Zählart") or p.get("Zaehlart"),
                "lat": slat,
                "lon": slon,
                "distanz_m": round(dist),
                "richtung": bearing_label(lat, lon, slat, slon),
                "im_radius": dist <= radius,
                "dtv_kfz": kfz,
                "dtv_leichtverkehr": _zahl(p.get("DTV_LV")),
                "dtv_schwerverkehr": sv,
                "schwerverkehr_anteil": (
                    round(sv / kfz * 100, 1) if kfz and sv is not None and kfz > 0 else None
                ),
            }
        )
    stellen.sort(key=lambda s: s["distanz_m"])
    mit_wert = [s for s in stellen if s["dtv_kfz"] is not None]
    return {
        "zaehlstellen": stellen,
        "naechste": stellen[0] if stellen else None,
        "staerkste": max(mit_wert, key=lambda s: s["dtv_kfz"]) if mit_wert else None,
        "im_radius": [s for s in stellen if s["im_radius"]],
        "max_distanz_m": MAX_DISTANZ_M,
        "portal": "https://www.baysis.bayern.de/internet/verdat/svz/index.html",
    }


HINWEISE = [
    "Gezählt wird das **klassifizierte Straßennetz** — Autobahnen, Bundes-, Staats- "
    "und Kreisstraßen. Innerstädtische Gemeindestraßen und Fußgängerzonen sind nicht "
    "erfasst.",
    "Der DTV ist ein Jahresmittel über alle Wochentage. Für ein Mittagsgeschäft ist "
    "der Werktagsverkehr relevanter — den gibt der Datensatz nicht her.",
    "Vorbeifahrender Verkehr ist keine Kundschaft. Ohne Zufahrt, Parkplatz oder "
    "Drive-through nutzt eine hohe Verkehrsstärke wenig und schadet der "
    "Außengastronomie eher.",
]


async def verkehrsmengen(
    out: Outbound, settings: Settings, lat: float, lon: float, radius: int
) -> SourceResult:
    started = time.perf_counter()
    if not in_bayern(lat, lon):
        return SourceResult(
            name="verkehrsmenge",
            ok=True,
            data=None,
            warnings=[
                "Die Straßenverkehrszählung BAYSIS deckt nur Bayern ab. Für andere "
                "Länder führen die Straßenbauverwaltungen eigene Erhebungen; im "
                "Werkzeug ist keine davon eingebunden."
            ],
            provenance=Provenance(
                source="BAYSIS Straßenverkehrszählung (außerhalb Bayerns)", license=LIZENZ
            ),
        )

    # Bounding-Box um den Punkt, großzügig genug für MAX_DISTANZ_M.
    d_lat = MAX_DISTANZ_M / 111_320.0
    d_lon = d_lat * 1.6  # grobe Aufweitung für die Länge auf 48° Nord
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": TYPENAME,
        "outputFormat": "GEOJSON",
        "srsName": "EPSG:4326",
        "bbox": (
            f"{lat - d_lat},{lon - d_lon},{lat + d_lat},{lon + d_lon},"
            "urn:ogc:def:crs:EPSG::4326"
        ),
    }
    try:
        payload = await out.get_json(
            "baysis",
            WFS_URL,
            params=params,
            timeout=60.0,
            limiter="baysis",
            min_interval=1.0,
        )
    except SourceError as err:
        return SourceResult.failed(
            "verkehrsmenge", err, int((time.perf_counter() - started) * 1000)
        )

    features = payload.get("features", []) if isinstance(payload, dict) else []
    data = aufbereiten(features, lat, lon, radius)

    warnungen: list[str] = []
    if not data["zaehlstellen"]:
        warnungen.append(
            f"Keine Zählstelle innerhalb von {MAX_DISTANZ_M} m. Gezählt wird nur das "
            "klassifizierte Straßennetz — in reinen Wohnvierteln und Fußgängerzonen "
            "gibt es dort keine Messpunkte."
        )

    return SourceResult(
        name="verkehrsmenge",
        ok=True,
        data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnungen,
        provenance=Provenance(
            source="Straßenverkehrszählung 2021, BAYSIS (Bayerische Straßenbauverwaltung)",
            license=LIZENZ,
            endpoint=WFS_URL,
            stand=STAND,
            retrieved_at=now_iso(),
            note=(
                "Durchschnittliche tägliche Verkehrsstärke (DTV) als Jahresmittel über "
                "alle Wochentage, gemessen im klassifizierten Straßennetz. Keine "
                "Passantenzählung."
            ),
        ),
    )
