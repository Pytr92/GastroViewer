"""Baustellen und Haltverbote der Landeshauptstadt München.

Eine monatelange Baustelle vor der Tür ist einer der häufigsten kurzfristigen
Umsatzkiller im Gastgewerbe — Gehwegsperrung, Lärm, wegfallende Parkplätze.
Die Stadt veröffentlicht ihre Servicekarte „Baustellen" als offenen
WFS-Dienst: alle Maßnahmen, die **jetzt laufen oder in den nächsten vier
Wochen beginnen**, mit Umriss-Polygon, Zeitraum und der genauen
Beeinträchtigung („Gehweg gesperrt", „Wegfall einer Fahrspur", …).

Verifiziert am 2026-08-07:
``https://geoportal.muenchen.de/geoserver/mor_wfs/ows`` ·
``typeName=mor_wfs:baustellen_opendata`` · WFS 1.1.0 · GeoJSON ·
5 533 Features stadtweit, 210 im Innenstadt-Kilometer · bbox-Filter in
``lon,lat``-Reihenfolge mit ``EPSG:4326`` · Datenlizenz Deutschland
Namensnennung 2.0.

Grenzen, offen benannt:

* Der Dienst ist eine **Vier-Wochen-Vorschau**. Eine Baustelle, die erst in
  drei Monaten beginnt, kennt er noch nicht — für die Standortwahl heißt
  das: kurz vor der Vertragsunterschrift noch einmal nachsehen.
* Nur Stadtgebiet München. Außerhalb bleibt der Block bewusst leer, statt
  „keine Baustellen" zu behaupten.
* „Vorübergehende Haltverbote" sind meist Umzüge oder Krantage — für die
  Standortwahl zählen vor allem die Baumaßnahmen; beide werden getrennt
  gezählt.
"""

from __future__ import annotations

import math
import re
import time
from datetime import date
from typing import Any

from ..config import Settings
from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, bearing_label, haversine_m, now_iso

WFS_URL = "https://geoportal.muenchen.de/geoserver/mor_wfs/ows"
TYPENAME = "mor_wfs:baustellen_opendata"

LIZENZ = (
    "Datenlizenz Deutschland Namensnennung 2.0 (dl-de/by-2-0) · "
    "© Landeshauptstadt München, Mobilitätsreferat"
)
ROHDATEN = "https://opendata.muenchen.de/dataset/baustellen_4_weeks_opendata"

# Großzügiger Kasten um das Stadtgebiet (Süd, West, Nord, Ost). Nur innerhalb
# wird überhaupt angefragt — für Punkte außerhalb gäbe „0 Treffer" sonst
# fälschlich Entwarnung, obwohl der Dienst dort schlicht nichts kennt.
STADT_BBOX = (48.04, 11.33, 48.27, 11.77)

# Mehr Einträge trägt keine Liste im Block; die Kappung steht im Ergebnis.
MAX_LISTE = 40


def _datum(v: Any) -> date | None:
    """„01.05.2026" → date. Alles andere → None."""
    m = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", str(v or "").strip())
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _href(v: Any) -> str | None:
    m = re.search(r'href="(https?://[^"]+)"', str(v or ""))
    return m.group(1) if m else None


def _aussenringe(geom: dict[str, Any] | None) -> list[list[list[float]]]:
    """Äußere Ringe als ``[[lon, lat], …]`` — Löcher spielen hier keine Rolle."""
    if not geom:
        return []
    typ = geom.get("type")
    koords = geom.get("coordinates") or []
    if typ == "Polygon" and koords:
        return [koords[0]]
    if typ == "MultiPolygon":
        return [p[0] for p in koords if p]
    if typ == "Point" and len(koords) >= 2:
        return [[koords]]
    return []


def _im_ring(lat: float, lon: float, ring: list[list[float]]) -> bool:
    """Strahl-Test (even-odd). Ring in ``[lon, lat]``-Reihenfolge."""
    drin = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > lat) != (y2 > lat):
            schnitt = (x2 - x1) * (lat - y1) / (y2 - y1) + x1
            if lon < schnitt:
                drin = not drin
    return drin


def _distanz_m(lat: float, lon: float, ringe: list[list[list[float]]]) -> float:
    """0, wenn der Punkt im Umriss liegt; sonst kürzeste Entfernung zu den
    Stützpunkten. Die Umrisse sind Straßenabschnitte von wenigen hundert
    Metern — die Stützpunkt-Näherung reicht für eine Umkreis-Sortierung."""
    beste = math.inf
    for ring in ringe:
        if len(ring) >= 3 and _im_ring(lat, lon, ring):
            return 0.0
        for punkt in ring:
            d = haversine_m(lat, lon, punkt[1], punkt[0])
            if d < beste:
                beste = d
    return beste


def _schwerpunkt(ringe: list[list[list[float]]]) -> tuple[float, float] | None:
    punkte = [p for ring in ringe for p in ring]
    if not punkte:
        return None
    lat = sum(p[1] for p in punkte) / len(punkte)
    lon = sum(p[0] for p in punkte) / len(punkte)
    return lat, lon


def aufbereiten(
    features: list[dict[str, Any]],
    lat: float,
    lon: float,
    radius: int,
    heute: date,
) -> dict[str, Any]:
    eintraege: list[dict[str, Any]] = []
    for f in features:
        p = f.get("properties") or {}
        ringe = _aussenringe(f.get("geometry"))
        if not ringe:
            continue
        ende = _datum(p.get("ende_datum_kombiniert"))
        if ende is not None and ende < heute:
            continue
        dist = _distanz_m(lat, lon, ringe)
        if dist > radius:
            continue
        beginn = _datum(p.get("beginn_datum_kombiniert"))
        beeintr = str(p.get("beeintraechtigung") or "").strip()
        bereiche = str(p.get("betroffene_bereiche") or "").strip()
        gehweg = "gehweg" in (beeintr + " " + bereiche).lower()
        sperrung = "sperr" in beeintr.lower()
        sp = _schwerpunkt(ringe)
        status = "laufend"
        if beginn is not None and beginn > heute:
            status = "geplant"
        beschreibung = str(p.get("beschreibung") or "").strip() or None
        if beschreibung and len(beschreibung) > 240:
            beschreibung = beschreibung[:237] + "…"
        eintraege.append(
            {
                "ort": p.get("strasse_hausnr") or "(ohne Ortsangabe)",
                "art": p.get("art") or "unbekannt",
                "status": status,
                "beginn": p.get("beginn_datum_kombiniert"),
                "ende": p.get("ende_datum_kombiniert"),
                "distanz_m": round(dist),
                "richtung": (
                    bearing_label(lat, lon, sp[0], sp[1]) if sp and dist > 0 else None
                ),
                "gehweg_betroffen": gehweg,
                "mit_sperrung": sperrung,
                "beeintraechtigung": beeintr or None,
                "betroffene_bereiche": bereiche or None,
                "beschreibung": beschreibung,
                "link": _href(p.get("weitere_info")),
                "lat": sp[0] if sp else None,
                "lon": sp[1] if sp else None,
                "umriss": [[pkt[1], pkt[0]] for pkt in ringe[0]],
            }
        )

    eintraege.sort(key=lambda e: (0 if e["status"] == "laufend" else 1, e["distanz_m"]))
    gesamt = len(eintraege)
    gekappt = gesamt > MAX_LISTE
    return {
        "gesamt": gesamt,
        "baumassnahmen": sum(1 for e in eintraege if e["art"] == "Baumaßnahme"),
        "haltverbote": sum(1 for e in eintraege if "Haltverbot" in e["art"]),
        "laufend": sum(1 for e in eintraege if e["status"] == "laufend"),
        "geplant": sum(1 for e in eintraege if e["status"] == "geplant"),
        "gehweg_betroffen": sum(1 for e in eintraege if e["gehweg_betroffen"]),
        "liste": eintraege[:MAX_LISTE],
        "gekappt": gekappt,
        "radius_m": radius,
        "stichtag": heute.isoformat(),
        "rohdaten": ROHDATEN,
    }


HINWEISE = [
    "Der Dienst ist eine **Vier-Wochen-Vorschau**: angezeigt wird, was läuft "
    "oder in den nächsten vier Wochen beginnt. Eine Baustelle, die später "
    "startet, kennt er noch nicht — kurz vor einer Vertragsunterschrift lohnt "
    "der zweite Blick.",
    "„Vorübergehende Haltverbote“ sind meist Umzüge oder Krantage von wenigen "
    "Tagen. Für die Standortwahl zählen vor allem die Baumaßnahmen.",
    "Entfernung ab Umriss der Maßnahme (0 m = der Punkt liegt im "
    "Baustellenbereich), Näherung über die Stützpunkte des Polygons.",
]


def _bbox_um(lat: float, lon: float, radius: int) -> tuple[float, float, float, float]:
    """(west, süd, ost, nord) — Radius plus Rand, damit Umrisse, deren
    Schwerpunkt knapp außerhalb liegt, nicht abgeschnitten werden."""
    rand = radius + 250
    dlat = rand / 111_320.0
    dlon = rand / (111_320.0 * max(0.2, math.cos(math.radians(lat))))
    return lon - dlon, lat - dlat, lon + dlon, lat + dlat


async def load(
    out: Outbound,
    settings: Settings,
    lat: float,
    lon: float,
    radius: int,
    heute: date | None = None,
) -> SourceResult:
    started = time.perf_counter()
    sued, west, nord, ost = STADT_BBOX
    if not (sued <= lat <= nord and west <= lon <= ost):
        return SourceResult(
            name="baustellen",
            ok=True,
            data=None,
            warnings=[
                "Die Baustellen-Servicekarte gibt es nur für das Stadtgebiet "
                "München. Für diesen Punkt liegt keine vergleichbare offene "
                "Quelle vor — das ist eine Datenlücke, keine Entwarnung."
            ],
        )

    w, s, o, n = _bbox_um(lat, lon, radius)
    params = {
        "service": "WFS",
        "version": "1.1.0",
        "request": "GetFeature",
        "typeName": TYPENAME,
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
        # GeoServer erwartet bei EPSG:4326 hier lon,lat — am 2026-08-07 mit
        # 210 Treffern um den Marienplatz verifiziert (lat,lon ergab 0).
        "bbox": f"{w:.6f},{s:.6f},{o:.6f},{n:.6f},EPSG:4326",
    }
    try:
        payload = await out.get_json(
            "muenchen_baustellen",
            WFS_URL,
            params=params,
            timeout=45.0,
            limiter="muenchen",
            min_interval=1.0,
        )
    except SourceError as err:
        return SourceResult.failed(
            "baustellen", err, int((time.perf_counter() - started) * 1000)
        )

    features = payload.get("features", []) if isinstance(payload, dict) else []
    data = aufbereiten(features, lat, lon, radius, heute or date.today())
    data["hinweise"] = HINWEISE

    warnungen: list[str] = []
    if data["gekappt"]:
        warnungen.append(
            f"{data['gesamt']} Maßnahmen im Radius — die Liste zeigt die "
            f"{MAX_LISTE} nächsten, die Zählwerte umfassen alle."
        )
    return SourceResult(
        name="baustellen",
        ok=True,
        data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnungen,
        provenance=Provenance(
            source="Servicekarte Baustellen (Landeshauptstadt München, WFS)",
            license=LIZENZ,
            endpoint=WFS_URL,
            stand="laufend gepflegt; Vorschau auf die kommenden vier Wochen",
            retrieved_at=now_iso(),
            note=(
                "Baumaßnahmen und vorübergehende Haltverbote mit Umriss, "
                "Zeitraum und Beeinträchtigung. Vier-Wochen-Horizont, nur "
                "Stadtgebiet München."
            ),
        ),
    )
