"""Stadt-Adapter Berlin — Baustellen und Sperrungen der VIZ.

Die Verkehrsinformationszentrale Berlin veröffentlicht „Baustellen,
Sperrungen und sonstige Störungen von besonderem verkehrlichem
Interesse" als offenes GeoJSON. Am 2026-08-07 Ende-zu-Ende verifiziert:

* ``https://api.viz.berlin.de/daten/baustellen_sperrungen_viz.json``
  (die im Datenregister Berlin als Ressource geführte URL) — HTTP 200,
  0,5 MB, 231 Features: 144 Baustellen, 83 Sperrungen, dazu einzelne
  Störungen/Gefahren. Lizenz laut Datenregister ``dl-de-by-2.0``.
* Geometrien sind ``GeometryCollection`` (Punkte und Linienzüge);
  Gültigkeit als ISO-Zeitraum ``validity.from``/``to``; Texte in
  ``street``, ``section``, ``content``; Schwere in ``severity``,
  gesperrte Spuren in ``closed_lanes``/``total_lanes``.

Grenzen, offen benannt: Der Dienst führt Maßnahmen „von besonderem
verkehrlichem Interesse" — Gehwegbaustellen ohne Verkehrswirkung stehen
nicht darin. Die übrigen Berliner Stadtthemen (Wochenmärkte,
Milieuschutzgebiete, Rad-Zählstellen) liegen hinter ``gdi.berlin.de`` —
aus der Prüfumgebung nicht erreichbar (TLS-Abbruch, geprüft 08/2026),
deshalb hier nicht eingebunden statt ungeprüft verdrahtet.

Die Blockform entspricht dem Münchner Baustellen-Adapter.
"""

from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any

from ..config import Settings
from ..http import Outbound
from .base import (Provenance, SourceError, SourceResult, bearing_label,
                   haversine_m, now_iso)

FEED_URL = "https://api.viz.berlin.de/daten/baustellen_sperrungen_viz.json"
LIZENZ = (
    "Datenlizenz Deutschland Namensnennung 2.0 (dl-de/by-2-0) · "
    "© Verkehrsinformationszentrale Berlin (VIZ)"
)
ROHDATEN = (
    "https://daten.berlin.de/datensaetze/"
    "baustellen-sperrungen-und-sonstige-storungen-von-besonderem-"
    "verkehrlichem-interesse"
)

# Großzügiger Kasten um das Stadtgebiet (Süd, West, Nord, Ost).
STADT_BBOX = (52.33, 13.08, 52.68, 13.77)
MAX_LISTE = 40


def in_berlin(lat: float, lon: float) -> bool:
    sued, west, nord, ost = STADT_BBOX
    return sued <= lat <= nord and west <= lon <= ost


def _koordinaten(geom: Any) -> list[tuple[float, float]]:
    """Alle (lat, lon)-Paare einer (verschachtelten) Geometrie."""
    punkte: list[tuple[float, float]] = []

    def sammle(g: Any) -> None:
        if not isinstance(g, dict):
            return
        for teil in g.get("geometries") or []:
            sammle(teil)
        coords = g.get("coordinates")
        if coords is None:
            return

        def tief(c: Any) -> None:
            if (isinstance(c, (list, tuple)) and len(c) >= 2
                    and all(isinstance(x, (int, float)) for x in c[:2])):
                punkte.append((float(c[1]), float(c[0])))
            elif isinstance(c, (list, tuple)):
                for x in c:
                    tief(x)

        tief(coords)

    sammle(geom)
    return punkte


def _datum_iso(v: Any) -> date | None:
    t = str(v or "").strip()
    if not t:
        return None
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def aufbereiten(
    features: list[dict[str, Any]], lat: float, lon: float, radius: int,
    heute: date,
) -> dict[str, Any]:
    eintraege: list[dict[str, Any]] = []
    for f in features:
        punkte = _koordinaten(f.get("geometry"))
        if not punkte:
            continue
        p = f.get("properties") or {}
        gueltig = p.get("validity") or {}
        ende = _datum_iso(gueltig.get("to"))
        if ende is not None and ende < heute:
            continue
        dist = min(haversine_m(lat, lon, pl, po) for pl, po in punkte)
        if dist > radius:
            continue
        beginn = _datum_iso(gueltig.get("from"))
        status = "laufend"
        if beginn is not None and beginn > heute:
            status = "geplant"
        naechster = min(punkte,
                        key=lambda pk: haversine_m(lat, lon, pk[0], pk[1]))
        inhalt = str(p.get("content") or "").strip() or None
        if inhalt and len(inhalt) > 240:
            inhalt = inhalt[:237] + "…"
        severity = str(p.get("severity") or "").strip()
        eintraege.append({
            "ort": p.get("street") or "(ohne Ortsangabe)",
            "art": p.get("subtype") or "Baustelle",
            "status": status,
            "beginn": str(gueltig.get("from") or "")[:10] or None,
            "ende": str(gueltig.get("to") or "")[:10] or None,
            "distanz_m": round(dist),
            "richtung": (bearing_label(lat, lon, *naechster)
                         if dist > 0 else None),
            "gehweg_betroffen": False,
            "mit_sperrung": (p.get("subtype") == "Sperrung"
                             or ("sperrung" in severity.lower()
                                 and "keine" not in severity.lower())),
            "beeintraechtigung": severity or None,
            "betroffene_bereiche": (str(p.get("section") or "").strip()
                                    or None),
            "beschreibung": inhalt,
            "link": None,
            "lat": naechster[0],
            "lon": naechster[1],
            "umriss": None,
        })
    eintraege.sort(key=lambda e: (0 if e["status"] == "laufend" else 1,
                                  e["distanz_m"]))
    gesamt = len(eintraege)
    return {
        "gesamt": gesamt,
        "baumassnahmen": sum(1 for e in eintraege
                             if "Bau" in (e["art"] or "")),
        "haltverbote": 0,
        "laufend": sum(1 for e in eintraege if e["status"] == "laufend"),
        "geplant": sum(1 for e in eintraege if e["status"] == "geplant"),
        "gehweg_betroffen": 0,
        "liste": eintraege[:MAX_LISTE],
        "gekappt": gesamt > MAX_LISTE,
        "radius_m": radius,
        "stichtag": heute.isoformat(),
        "rohdaten": ROHDATEN,
        "stadt": "Berlin",
    }


HINWEISE = [
    "Die VIZ führt Maßnahmen „von besonderem verkehrlichem Interesse“ — "
    "Sperrungen und größere Baustellen. Reine Gehwegbaustellen ohne "
    "Verkehrswirkung stehen nicht im Datensatz; „0 Treffer“ heißt also "
    "„keine verkehrsrelevante Maßnahme“, nicht „keine Bautätigkeit“.",
    "Entfernung ab dem nächstgelegenen Geometriepunkt der Maßnahme.",
]


async def baustellen_load(
    out: Outbound, settings: Settings, lat: float, lon: float, radius: int,
    heute: date | None = None,
) -> SourceResult:
    started = time.perf_counter()
    heute = heute or date.today()
    try:
        payload = await out.get_json(
            "berlin_viz", FEED_URL, timeout=60.0,
            limiter="berlin", min_interval=1.0,
        )
    except SourceError as err:
        return SourceResult.failed(
            "baustellen", err, int((time.perf_counter() - started) * 1000))
    features = payload.get("features", []) if isinstance(payload, dict) else []
    data = aufbereiten(features, lat, lon, radius, heute)
    data["hinweise"] = HINWEISE
    warnungen = ([] if data["gesamt"] else
                 ["Keine verkehrsrelevante Maßnahme im Umkreis (VIZ-Daten)."])
    return SourceResult(
        name="baustellen", ok=True, data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnungen,
        provenance=Provenance(
            source=("Baustellen und Sperrungen Berlin "
                    "(Verkehrsinformationszentrale, offenes GeoJSON)"),
            license=LIZENZ,
            endpoint=FEED_URL,
            retrieved_at=now_iso(),
        ),
    )
