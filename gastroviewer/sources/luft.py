"""Luftqualität am Punkt — Luftmessnetz von UBA und Ländern.

Für Außengastronomie an Verkehrsachsen der Begleiter zum Lärmblock:
**gemessene** Schadstoffwerte der nächsten Station statt Modellwerte.

Phase-0 am 2026-08-08 mit echten Abrufen verifiziert
(``luftdaten.umweltbundesamt.de/api/air-data/v3`` — offen, ohne
Schlüssel; die alte Adresse unter www.umweltbundesamt.de leitet dorthin
weiter):

* ``/stations/json?use=airquality&lang=de`` — alle Stationen des
  Luftqualitätsindex-Netzes mit Koordinaten (Feldreihenfolge laut
  ``indices``: id, code, name, city, synonym, aktiv von, aktiv bis,
  **lon**, **lat**, …). München: 5 Stationen, u. a. DEBY037
  München/Stachus (48.1373, 11.5649).
* ``/airquality/json?date_from=…&station=<id>`` — je Stunde
  ``[Endzeit, Gesamtindex, unvollständig-Flag, [Komponente, Wert,
  Teilindex, …]…]``. Beleg für die 0-basierte Indexskala: Stachus
  NO₂ = 13 µg/m³ trug Teilindex 0 — nach den veröffentlichten
  UBA-Schwellen (NO₂ 1h: bis 20 „sehr gut") ist 0 = sehr gut,
  4 = sehr schlecht.
* ``/components/json`` — Komponenten-Codes (1 PM₁₀, 3 O₃, 5 NO₂,
  9 PM₂,₅ …).

Die Stationsliste wird **einmal** geladen und gecacht; je Punkt wird nur
die nächstgelegene Station (mit Rückfall auf die zwei nächsten, falls
eine Station gerade keine Daten liefert) für den aktuellen Tag
abgefragt.
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any, Awaitable, Callable

from ..http import Outbound
from .base import (Provenance, SourceError, SourceResult, bearing_label,
                   haversine_m, now_iso)

BASE = "https://luftdaten.umweltbundesamt.de/api/air-data/v3"
STATIONS_URL = f"{BASE}/stations/json?use=airquality&lang=de"
PORTAL = "https://www.umweltbundesamt.de/daten/luft/luftdaten"
LIZENZ = (
    "Umweltbundesamt mit den Messnetzen der Länder und des Bundes — "
    "offene Schnittstelle ohne Zugriffsbeschränkung, Quellenangabe "
    "erforderlich"
)

INDEX_LABELS = {0: "sehr gut", 1: "gut", 2: "mäßig",
                3: "schlecht", 4: "sehr schlecht"}
KOMPONENTEN = {1: ("PM₁₀", "µg/m³"), 2: ("CO", "mg/m³"), 3: ("O₃", "µg/m³"),
               4: ("SO₂", "µg/m³"), 5: ("NO₂", "µg/m³"), 9: ("PM₂,₅", "µg/m³")}
MAX_DISTANZ_M = 15000


def parse_stationen(roh: Any) -> list[dict[str, Any]]:
    """Stationsantwort → reduzierte Liste. Die Feldreihenfolge kommt aus
    ``indices`` der echten Antwort; Stationen ohne Koordinaten fallen
    heraus, beendete Stationen (aktiv-bis in der Vergangenheit) bleiben
    drin — ob sie liefern, entscheidet der Datenabruf."""
    data = (roh or {}).get("data")
    if not isinstance(data, dict):
        raise SourceError(
            "parse", "UBA-Stationsliste ohne data-Objekt — Format geändert?")
    stationen = []
    for eintrag in data.values():
        if not isinstance(eintrag, list) or len(eintrag) < 9:
            continue
        try:
            lon, lat = float(eintrag[7]), float(eintrag[8])
        except (TypeError, ValueError):
            continue
        stationen.append({
            "id": str(eintrag[0]),
            "code": eintrag[1],
            "name": eintrag[2],
            "stadt": eintrag[3],
            "lat": lat,
            "lon": lon,
        })
    if not stationen:
        raise SourceError("parse", "UBA-Stationsliste ohne Stationen.")
    return stationen


def naechste_stationen(
    stationen: list[dict[str, Any]], lat: float, lon: float, n: int = 3
) -> list[dict[str, Any]]:
    mit_distanz = []
    for s in stationen:
        d = haversine_m(lat, lon, s["lat"], s["lon"])
        if d > MAX_DISTANZ_M:
            continue
        mit_distanz.append({**s, "distanz_m": round(d),
                            "richtung": bearing_label(lat, lon, s["lat"], s["lon"])})
    mit_distanz.sort(key=lambda s: s["distanz_m"])
    return mit_distanz[:n]


def aktuellster_eintrag(antwort: Any, station_id: str) -> dict[str, Any] | None:
    """Jüngster Stundeneintrag der airquality-Antwort — oder None."""
    stunden = ((antwort or {}).get("data") or {}).get(str(station_id)) or {}
    if not isinstance(stunden, dict) or not stunden:
        return None
    letzte = sorted(stunden)[-1]
    e = stunden[letzte]
    if not isinstance(e, list) or len(e) < 3:
        return None
    gesamt = e[1] if isinstance(e[1], int) else None
    komponenten = []
    for teil in e[3:]:
        if not isinstance(teil, list) or len(teil) < 3:
            continue
        code = KOMPONENTEN.get(teil[0])
        komponenten.append({
            "komponente": code[0] if code else f"Komponente {teil[0]}",
            "einheit": code[1] if code else None,
            "wert": teil[1],
            "teilindex": teil[2],
            "teilindex_label": INDEX_LABELS.get(teil[2]),
        })
    return {
        "stand": e[0],
        "index": gesamt,
        "index_label": INDEX_LABELS.get(gesamt),
        "unvollstaendig": bool(e[2]),
        "komponenten": komponenten,
    }


HINWEISE = [
    "Der Luftqualitätsindex bewertet die jeweils schlechteste Komponente "
    "der Stunde (Skala: sehr gut bis sehr schlecht, Schwellen des UBA).",
    "Es gilt der Wert der Messstation, nicht der Straße vor der Tür — "
    "eine Verkehrsstation (z. B. Landshuter Allee) misst die Achse, eine "
    "Hintergrundstation das Viertel. Entfernung und Name stehen dabei.",
]


async def load(
    out: Outbound, lat: float, lon: float,
    stationen_laden: Callable[[], Awaitable[list[dict[str, Any]]]],
) -> SourceResult:
    started = time.perf_counter()
    try:
        stationen = await stationen_laden()
    except SourceError as err:
        return SourceResult.failed(
            "luft", err, int((time.perf_counter() - started) * 1000))

    kandidaten = naechste_stationen(stationen, lat, lon)
    warnungen: list[str] = []
    if not kandidaten:
        return SourceResult(
            name="luft", ok=True, data=None,
            duration_ms=int((time.perf_counter() - started) * 1000),
            warnings=[
                f"Keine Luftmessstation innerhalb von "
                f"{MAX_DISTANZ_M // 1000} km — das Messnetz ist auf Städte "
                "und Belastungsschwerpunkte konzentriert."
            ],
            provenance=_provenance(),
        )

    heute = date.today().isoformat()
    daten = None
    station = None
    for kandidat in kandidaten:
        try:
            antwort = await out.get_json(
                "luft",
                f"{BASE}/airquality/json",
                params={"date_from": heute, "date_to": heute,
                        "time_from": "1", "time_to": "24",
                        "station": kandidat["id"]},
                timeout=30.0,
                limiter="luft",
                min_interval=1.0,
            )
        except SourceError as err:
            warnungen.append(
                f"Station {kandidat['name']}: {err.message}")
            continue
        eintrag = aktuellster_eintrag(antwort, kandidat["id"])
        if eintrag:
            daten, station = eintrag, kandidat
            break
        warnungen.append(
            f"Station {kandidat['name']} liefert heute (noch) keine "
            "Indexwerte — nächste Station versucht.")

    if daten is None or station is None:
        return SourceResult(
            name="luft", ok=True, data=None,
            duration_ms=int((time.perf_counter() - started) * 1000),
            warnings=warnungen + [
                "Keine der nahen Stationen lieferte heute Indexwerte."],
            provenance=_provenance(),
        )

    if daten["unvollstaendig"]:
        warnungen.append(
            "Der Stundenwert ist als unvollständig markiert — nicht alle "
            "Komponenten der Station haben schon gemeldet.")

    return SourceResult(
        name="luft",
        ok=True,
        data={
            "station": {k: station[k] for k in
                        ("code", "name", "stadt", "lat", "lon",
                         "distanz_m", "richtung")},
            **daten,
            "hinweise": HINWEISE,
            "portal": PORTAL,
        },
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnungen,
        provenance=_provenance(),
    )


def _provenance() -> Provenance:
    return Provenance(
        source="Luftmessnetz UBA/Länder — Luftqualitätsindex der "
               "nächsten Station",
        license=LIZENZ,
        endpoint=f"{BASE}/airquality/json",
        stand="stündlich",
        retrieved_at=now_iso(),
        note=(
            "Stationsliste einmal geladen; je Punkt wird nur die nächste "
            "Station abgefragt (mit Rückfall auf die zwei nächsten)."
        ),
    )
