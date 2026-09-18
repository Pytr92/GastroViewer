"""Klimanormalwerte Österreich — GeoSphere Austria, Datensatz ``klima-v2-1y``.

Gegenstück zu ``klima.py`` (DWD): dieselben fünf Kennzahlen der
Normalperiode 1991–2020 für die nächste Station, dieselbe Blockform
(``kennzahlen`` mit ``schluessel``, ``titel``, ``einheit``, ``stellen``,
``wert``, ``station``), damit die Oberfläche nichts unterscheiden muss.

Live belegt am 18.09.2026 (fixtures/at, AT-Probe):

* ``…/station/historical/klima-v2-1y/metadata`` → ``stations`` (id, name,
  state, lat, lon, altitude, valid_from, valid_to, is_active, has_sunshine)
  und ``parameters`` (``tage_sommer`` Sommertage ≥ 25 °C, ``tage_tropen``
  Tropentage ≥ 30 °C, ``so_h`` Sonnenscheindauer h, ``rr`` Niederschlag mm,
  ``tl_mittel`` Lufttemperatur 2 m °C).
* ``…/station/historical/klima-v2-1y?parameters=…&station_ids=…&start=…
  &end=…&output_format=geojson`` → ``timestamps`` (Jahresanfänge) und
  ``features[0].properties.parameters[<name>].data`` (eine Zahl je Jahr,
  ``null`` für Lücken).

Der Normalwert ist das Mittel der 30 Jahreswerte. GeoSphere führt kein
fertiges 1991–2020-Mittel je Station in diesem Datensatz; gerechnet wird
hier — und ausgewiesen, aus wie vielen Jahren. Gefragt wird die nächste
aktive Station, deren Reihe vor 1991 beginnt; Stationen, die erst nach 1991
begonnen haben, kämen mit weniger Jahren, was der Block dann sagt.
"""

from __future__ import annotations

import math
import time
from typing import Any, Awaitable, Callable

from ..config import Settings
from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, haversine_m, now_iso

BASIS = "https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1y"
LICENSE = "GeoSphere Austria, Datenhub — Creative Commons Namensnennung 4.0 (CC BY 4.0)"
NORMALPERIODE = "1991–2020"
MINDEST_JAHRE = 20

# Dieselben Schlüssel, Titel und Einheiten wie klima.PARAMETER (DWD).
PARAMETER: list[dict[str, Any]] = [
    {"schluessel": "sommertage", "name": "tage_sommer",
     "titel": "Sommertage (Höchstwert ≥ 25 °C)", "einheit": "Tage/Jahr", "stellen": 1},
    {"schluessel": "heisse_tage", "name": "tage_tropen",
     "titel": "Heiße Tage (Höchstwert ≥ 30 °C)", "einheit": "Tage/Jahr", "stellen": 1},
    {"schluessel": "sonnenschein", "name": "so_h",
     "titel": "Sonnenscheindauer", "einheit": "Stunden/Jahr", "stellen": 0},
    {"schluessel": "niederschlag", "name": "rr",
     "titel": "Niederschlag", "einheit": "mm/Jahr", "stellen": 0},
    {"schluessel": "temperatur", "name": "tl_mittel",
     "titel": "Lufttemperatur im Jahresmittel", "einheit": "°C", "stellen": 1},
]

HINWEISE = [
    "Normalwerte als Mittel der Jahreswerte 1991–2020 der nächsten GeoSphere-"
    "Station — nicht des Punktes. Name, Entfernung und Stationshöhe stehen dabei; "
    "im Gebirge kann die nächste Station in einer anderen Höhenlage liegen.",
]


def stationen_aus_metadata(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """Aktive Stationen mit Koordinaten; ``ab`` = Jahr des Reihenbeginns."""
    out = []
    for s in meta.get("stations") or []:
        try:
            lat, lon = float(s["lat"]), float(s["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not s.get("is_active"):
            continue
        ab = str(s.get("valid_from") or "9999")[:4]
        out.append({
            "id": s.get("id"), "name": s.get("name"), "bundesland": s.get("state"),
            "lat": lat, "lon": lon, "hoehe_m": s.get("altitude"),
            "ab": int(ab) if ab.isdigit() else 9999,
            "sonne": bool(s.get("has_sunshine")),
        })
    return out


def naechste_station(stationen: list[dict[str, Any]], lat: float, lon: float,
                     *, spaetestens_ab: int = 1991) -> tuple[dict[str, Any], float] | None:
    """Nächste Station, deren Reihe spätestens ``spaetestens_ab`` beginnt —
    sonst die nächste überhaupt (mit weniger Jahren, was der Block sagt)."""
    if not stationen:
        return None
    mit_dist = [(s, haversine_m(lat, lon, s["lat"], s["lon"])) for s in stationen]
    lang = [x for x in mit_dist if x[0]["ab"] <= spaetestens_ab]
    return min(lang or mit_dist, key=lambda x: x[1])


def normalwerte(antwort: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """GeoJSON-Antwort → je Parameter Mittel und Jahresanzahl."""
    features = antwort.get("features") or []
    if not features:
        return {}
    params = (features[0].get("properties") or {}).get("parameters") or {}
    out: dict[str, dict[str, Any]] = {}
    for name, eintrag in params.items():
        werte = [float(v) for v in (eintrag.get("data") or []) if isinstance(v, (int, float))]
        out[name] = {
            "wert": sum(werte) / len(werte) if werte else None,
            "jahre": len(werte),
            "einheit": eintrag.get("unit"),
        }
    return out


async def load(
    out: Outbound, settings: Settings, lat: float, lon: float,
    stationen_laden: Callable[[], Awaitable[list[dict[str, Any]]]],
) -> SourceResult:
    """``stationen_laden`` liefert die (vom Service stadt- bzw. landesweit
    gecachte) Stationsliste — die Metadaten sind 370 kB und ändern sich in
    Monaten."""
    started = time.perf_counter()
    stationen = await stationen_laden()
    wahl = naechste_station(stationen, lat, lon)
    if wahl is None:
        return SourceResult.failed(
            "klima", SourceError("api_error", "GeoSphere nennt keine aktive Station."),
            int((time.perf_counter() - started) * 1000))
    station, dist = wahl
    antwort = await out.get_json(
        "klima_at", BASIS,
        params={"parameters": ",".join(p["name"] for p in PARAMETER),
                "station_ids": str(station["id"]), "start": "1991-01-01",
                "end": "2020-12-31", "output_format": "geojson"},
        timeout=60.0, limiter="geosphere", min_interval=1.0,
    )
    werte = normalwerte(antwort if isinstance(antwort, dict) else {})
    kennzahlen = []
    hinweise: set[str] = set(HINWEISE)
    for p in PARAMETER:
        w = werte.get(p["name"]) or {}
        if w.get("wert") is None:
            hinweise.add(f"{p['titel']}: an der Station {station['name']} ohne Werte 1991–2020.")
            continue
        if w["jahre"] < MINDEST_JAHRE:
            hinweise.add(f"{p['titel']}: nur {w['jahre']} von 30 Jahren an der Station "
                         f"{station['name']} — Mittel entsprechend unsicher.")
        kennzahlen.append({
            "schluessel": p["schluessel"], "titel": p["titel"], "einheit": p["einheit"],
            "stellen": p["stellen"],
            "wert": round(w["wert"], p["stellen"]),
            "monate": None,
            "jahre": w["jahre"],
            "station": {"id": station["id"], "name": station["name"],
                        "distanz_m": round(dist), "hoehe_m": station.get("hoehe_m")},
        })
    if not kennzahlen:
        return SourceResult.failed(
            "klima", SourceError("api_error",
                                 f"GeoSphere liefert für Station {station['name']} keine "
                                 "auswertbaren Jahreswerte 1991–2020."),
            int((time.perf_counter() - started) * 1000))
    return SourceResult(
        name="klima", ok=True,
        data={"kennzahlen": kennzahlen, "station": {
            "id": station["id"], "name": station["name"], "bundesland": station.get("bundesland"),
            "distanz_m": round(dist), "hoehe_m": station.get("hoehe_m"), "reihe_ab": station["ab"]}},
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=sorted(hinweise),
        provenance=Provenance(
            source="GeoSphere Austria, Klimadaten Jahreswerte (klima-v2-1y), Mittel 1991–2020",
            license=LICENSE, endpoint=BASIS, stand=f"Normalperiode {NORMALPERIODE}",
            retrieved_at=now_iso(),
            note=("Mittel der Jahreswerte der nächsten aktiven Station, hier gerechnet; "
                  "GeoSphere weist die Jahre je Parameter aus, aus denen es besteht."),
        ),
    )


def distanz_km(lat: float, lon: float, s: dict[str, Any]) -> float:
    return haversine_m(lat, lon, s["lat"], s["lon"]) / 1000


__all__ = ["BASIS", "PARAMETER", "load", "naechste_station", "normalwerte",
           "stationen_aus_metadata", "distanz_km", "math"]
