"""Leerstandsmelder.de — bürgerschaftlich gemeldete Leerstände.

Zweite Leerstandsquelle neben dem OSM-Block: unabhängig erhoben (Meldungen
von Anwohnerinnen und Initiativen statt OSM-Mapping), deshalb als
Gegenprobe wertvoll — zwei Untergrenzen sind besser als eine.

Phase-0 am 2026-08-08 mit echten Abrufen verifiziert:

* Die Website ist eine reine JavaScript-Anwendung; die Datenquelle steht
  im Anwendungs-Bundle: ``https://api.leerstandsmelder.de/api/v1/places``
  — HTTP 200, 3,0 MB JSON, **9 318 Meldungen weltweit** (der Dienst kennt
  keinen Regionalfilter, deshalb wird hier lokal nach Entfernung
  gefiltert).
* Felder je Meldung: ``title``, ``road``, ``lat``/``lon`` (Strings!),
  ``slug``, ``created_at``, ``startdate``/``enddate``, ``published``.
  Alle 9 318 Meldungen tragen Koordinaten, alle sind ``published``.
* Absprung je Meldung: ``https://leerstandsmelder.de/places/<slug>``
  (Pfadmuster aus dem Anwendungs-Bundle).
* Gegenprobe Sendlinger Tor (48.1334, 11.5674): 32 Meldungen < 2 km,
  nächste „Leerstand am Sendlinger Tor" in 126 m.

Lizenzlage, ehrlich: Die Seite nennt maschinell **keine Datenlizenz** für
die Meldungen. Eingebaut auf ausdrücklichen Wunsch des Nutzers — mit
Warnung am Block: ungeprüfte Bürgermeldungen, Lizenz ungeklärt, nur
Hinweischarakter. Der Weltbestand wird **einmal** geladen und gecacht;
jeder Punkt filtert danach lokal.
"""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from .base import (Provenance, SourceError, SourceResult, bearing_label,
                   haversine_m, now_iso)

API_URL = "https://api.leerstandsmelder.de/api/v1/places"
PORTAL = "https://www.leerstandsmelder.de/"
LIZENZ = (
    "Keine maschinenlesbare Datenlizenz ausgewiesen (nachgeprüft "
    "08/2026) — bürgerschaftliche Meldungen, Leerstandsmelder.de "
    "(Gängeviertel e.V. Hamburg). Nur Hinweischarakter."
)
MAX_DISTANZ_M = 1500


def parse_meldungen(roh: Any) -> list[dict[str, Any]]:
    """API-Antwort → reduzierte Meldungsliste. Koordinaten kommen als
    Strings und werden hier einmal in Zahlen gewandelt."""
    if not isinstance(roh, list):
        raise SourceError(
            "parse",
            "Leerstandsmelder-Antwort ist keine Liste — Format geändert?",
        )
    meldungen = []
    for m in roh:
        try:
            lat, lon = float(m["lat"]), float(m["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not m.get("published", True):
            continue
        meldungen.append({
            "titel": (m.get("title") or "").strip() or None,
            "strasse": (m.get("road") or "").strip() or None,
            "lat": lat,
            "lon": lon,
            "slug": m.get("slug"),
            "gemeldet_am": (m.get("created_at") or "")[:10] or None,
            "beendet_am": (m.get("enddate") or "")[:10] or None,
        })
    return meldungen


def aufbereiten(
    meldungen: list[dict[str, Any]], lat: float, lon: float, radius: int
) -> dict[str, Any]:
    treffer = []
    for m in meldungen:
        dist = haversine_m(lat, lon, m["lat"], m["lon"])
        if dist > MAX_DISTANZ_M:
            continue
        treffer.append({
            **m,
            "distanz_m": round(dist),
            "richtung": bearing_label(lat, lon, m["lat"], m["lon"]),
            "im_radius": dist <= radius,
            "url": (f"https://leerstandsmelder.de/places/{m['slug']}"
                    if m.get("slug") else PORTAL),
        })
    treffer.sort(key=lambda m: m["distanz_m"])
    offen = [m for m in treffer if not m["beendet_am"]]
    return {
        "meldungen": treffer[:15],
        "gesamt_im_umfeld": len(treffer),
        "offen_im_umfeld": len(offen),
        "im_radius": sum(1 for m in treffer if m["im_radius"]),
        "max_distanz_m": MAX_DISTANZ_M,
        "portal": PORTAL,
    }


HINWEISE = [
    "Bürgerschaftlich gemeldet und nicht amtlich geprüft: Meldungen können "
    "veraltet, doppelt oder falsch verortet sein — als Spur für die "
    "Begehung nutzen, nicht als Beleg.",
    "Die Plattform weist keine Datenlizenz aus. Die Meldungen werden hier "
    "nur lokal angezeigt — für die eigene Standortsuche, nicht zur "
    "Weiterveröffentlichung.",
    "Zweite Untergrenze neben dem OSM-Leerstand: beide Quellen sind "
    "lückenhaft, aber unabhängig voneinander — was in beiden fehlt, kann "
    "trotzdem leer stehen.",
]


async def load(
    lat: float, lon: float, radius: int,
    meldungen_laden: Callable[[], Awaitable[list[dict[str, Any]]]],
) -> SourceResult:
    """Blockergebnis. ``meldungen_laden`` liefert den (gecachten)
    Weltbestand — hier wird nur noch lokal gefiltert."""
    started = time.perf_counter()
    try:
        meldungen = await meldungen_laden()
    except SourceError as err:
        return SourceResult.failed(
            "leerstandsmelder", err, int((time.perf_counter() - started) * 1000)
        )

    data = aufbereiten(meldungen, lat, lon, radius)
    data["hinweise"] = HINWEISE

    warnungen: list[str] = []
    if not data["meldungen"]:
        warnungen.append(
            f"Keine Meldung innerhalb von {MAX_DISTANZ_M} m. Der Dienst lebt "
            "von Freiwilligen — außerhalb der aktiven Städte heißt leer "
            "nicht leerstandsfrei."
        )

    return SourceResult(
        name="leerstandsmelder",
        ok=True,
        data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnungen,
        provenance=Provenance(
            source="Leerstandsmelder.de — bürgerschaftliche Meldungen",
            license=LIZENZ,
            endpoint=API_URL,
            stand="laufend gemeldet, Bestand einmal geladen",
            retrieved_at=now_iso(),
            note=(
                "Der Dienst liefert nur den Weltbestand ohne Regionalfilter; "
                "die Entfernungsauswahl rechnet dieses Werkzeug lokal."
            ),
        ),
    )
