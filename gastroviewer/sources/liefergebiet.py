"""Rad-Liefergebiet — wie viele Menschen erreicht ein Lieferrad in X Minuten?

Für ein Liefer-Franchise ist nicht der 600-m-Umkreis die Kernzahl, sondern:
Wie viele Haushalte liegen innerhalb der Lieferzeit? Dieses Modul rechnet
das mit demselben Rechenwerk wie die Erreichbarkeit zu Fuß (``gehweg.py``):
OSM-Wegenetz über Overpass, Dijkstra vom Standort, Zensuszellen im
erreichten Gebiet aufsummiert — kein Routing-Dienst, keine zusätzliche
Abhängigkeit.

Was anders ist als zu Fuß:

* **Radprofil** statt Fußprofil: Treppen, reine Fußwege und Korridore
  fehlen; ``bicycle=no`` schließt aus. Fußgängerzonen bleiben drin, denn
  Lieferräder dürfen dort meist schieben — das steht als Hinweis dabei.
* **Tempo**: gerechnet mit 15 km/h (250 m/min) — ein gewählter Wert für
  ein beladenes Lieferrad im Stadtverkehr, kein Messwert, und so steht er
  auch in der Ausgabe. Ampeln und Wartezeiten kennt die Rechnung nicht;
  real ist das erreichte Gebiet eher kleiner.
* **Reichweite**: Lieferzeit wählbar 5–15 Minuten. 10 Minuten × 250 m/min
  sind 2.500 m Netzstrecke — das Wegenetz dafür ist eine große
  Overpass-Abfrage und läuft wie der Gehweg-Block nur auf Knopfdruck.

Die Einwohnerzahl kommt aus dem Zensus-2022-Gitter (Wohnbevölkerung,
Stichtag 15.05.2022) — Zellmittelpunkt-Näherung wie beim Gehweg-Block.
"""

from __future__ import annotations

import time
from typing import Any

from ..config import Settings
from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, now_iso
from .gehweg import (MAX_ANBINDUNG_M, NETZ_PUFFER, Wegenetz, baue_netz,
                     erreichbare_flaeche, gehstrecken)
from .overpass import LICENSE, run_query

# Wege, auf denen ein Lieferrad fahren kann. Gegenüber dem Fußprofil fehlen
# Treppen (steps), Korridore und Bahnsteige; reine Fußwege (footway) fehlen
# ebenfalls — wo sie die einzige Verbindung sind, erscheint das Gebiet
# entsprechend kleiner, und das ist die ehrlichere Richtung des Fehlers.
RADWEGE = (
    "cycleway|residential|living_street|service|unclassified|tertiary|"
    "tertiary_link|secondary|secondary_link|primary|primary_link|track|"
    "road|path|pedestrian"
)

# Gewählte Werte, keine Messwerte — sie stehen in der Ausgabe mit dabei.
RADTEMPO_M_PRO_MIN = 250.0  # 15 km/h
MIN_MINUTEN, MAX_MINUTEN = 5, 15
VORGABE_MINUTEN = 10


def _befahrbar(tags: dict[str, str]) -> bool:
    if tags.get("bicycle") in ("no", "private"):
        return False
    if tags.get("access") in ("no", "private") and tags.get("bicycle") not in (
        "yes", "designated", "permissive",
    ):
        return False
    return True


def build_query(lat: float, lon: float, minuten: int, timeout: int = 90) -> str:
    reichweite = int(minuten * RADTEMPO_M_PRO_MIN * NETZ_PUFFER)
    return (
        f"[out:json][timeout:{timeout}];\n"
        f'way["highway"~"^({RADWEGE})$"](around:{reichweite},{lat},{lon});\n'
        f"out geom;"
    )


def baue_radnetz(elements: list[dict[str, Any]]) -> Wegenetz:
    """Wie ``gehweg.baue_netz``, aber mit Rad- statt Fußregeln."""
    befahrbare = []
    gesperrt = 0
    for el in elements:
        if el.get("type") != "way":
            continue
        if _befahrbar(el.get("tags") or {}):
            befahrbare.append(el)
        else:
            gesperrt += 1
    netz = baue_netz(befahrbare)
    netz.uebersprungen += gesperrt
    return netz


HINWEISE = [
    "Gerechnet wird die kürzeste Strecke im OSM-Netz mit pauschal 15 km/h — "
    "ohne Ampeln, Einbahnregelungen für Räder, Steigung und Wartezeiten. "
    "Real ist das Gebiet eher kleiner.",
    "Fußgängerzonen zählen mit (Lieferräder dürfen dort meist schieben oder "
    "zu Randzeiten fahren) — reine Fußwege und Treppen nicht. Wo ein Fußweg "
    "die einzige Verbindung ist, erscheint das Gebiet zu klein.",
    "Die Einwohner sind Wohnbevölkerung (Zensus 2022, Stichtag 15.05.2022), "
    "angesetzt am Mittelpunkt der 100-m-Zelle — eine Näherung.",
    "Die Rückfahrt und die Zeit in der Küche gehören zur Lieferzeit dazu — "
    "das hier ist nur die einfache Fahrstrecke.",
]


async def load(
    out: Outbound,
    settings: Settings,
    lat: float,
    lon: float,
    minuten: int,
    zellen: list[dict[str, Any]] | None,
) -> SourceResult:
    started = time.perf_counter()
    minuten = max(MIN_MINUTEN, min(MAX_MINUTEN, int(minuten)))
    radius = minuten * RADTEMPO_M_PRO_MIN

    query = build_query(lat, lon, minuten, timeout=int(settings.overpass_timeout))
    try:
        payload, endpoint, problems = await run_query(out, settings, query)
    except SourceError as err:
        return SourceResult.failed(
            "liefergebiet", err, int((time.perf_counter() - started) * 1000)
        )

    elements = payload.get("elements", []) if isinstance(payload, dict) else []
    netz = baue_radnetz(elements)
    warnungen = list(problems)

    if not len(netz):
        return SourceResult(
            name="liefergebiet", ok=True, data=None,
            duration_ms=int((time.perf_counter() - started) * 1000),
            warnings=warnungen + [
                "Im Umfeld ist kein befahrbares Wegenetz erfasst."
            ],
            provenance=Provenance(
                source="OpenStreetMap Wegenetz über Overpass", license=LICENSE,
                endpoint=endpoint,
            ),
        )

    start, anbindung = netz.naechster_knoten(lat, lon)
    if start is None:
        return SourceResult(
            name="liefergebiet", ok=True, data=None,
            duration_ms=int((time.perf_counter() - started) * 1000),
            warnings=warnungen + [
                f"Der Punkt liegt mehr als {MAX_ANBINDUNG_M:.0f} m vom nächsten "
                "erfassten Weg entfernt."
            ],
            provenance=Provenance(
                source="OpenStreetMap Wegenetz über Overpass", license=LICENSE,
                endpoint=endpoint,
            ),
        )

    t0 = time.perf_counter()
    dist = gehstrecken(netz, start, float(radius))
    rechenzeit = int((time.perf_counter() - t0) * 1000)

    # Einwohner im erreichten Gebiet — Zellmittelpunkt-Näherung.
    einwohner = None
    zellen_drin = None
    if zellen:
        summe = 0.0
        drin = 0
        for z in zellen:
            mitte = z.get("_center") or []
            zlat, zlon = (mitte + [None, None])[:2] if mitte else (z.get("lat"), z.get("lon"))
            ew = z.get("Einwohner")
            if zlat is None or zlon is None or not isinstance(ew, (int, float)):
                continue
            knoten, anschluss = netz.naechster_knoten(zlat, zlon)
            d = dist.get(knoten) if knoten is not None else None
            if d is not None and d + anschluss + anbindung <= radius:
                summe += ew
                drin += 1
        einwohner = round(summe)
        zellen_drin = drin

    data: dict[str, Any] = {
        "minuten": minuten,
        "tempo_m_pro_min": RADTEMPO_M_PRO_MIN,
        "tempo_kmh": round(RADTEMPO_M_PRO_MIN * 60 / 1000, 1),
        "radius_m": round(radius),
        "knoten": len(netz),
        "wege_gesperrt": netz.uebersprungen,
        "anbindung_m": round(anbindung),
        "erreichbare_knoten": len(dist),
        "rechenzeit_ms": rechenzeit,
        "einwohner_liefergebiet": einwohner,
        "zellen_im_liefergebiet": zellen_drin,
        "flaeche": erreichbare_flaeche(dist, anbindung, int(radius)),
        "hinweise": HINWEISE,
    }
    return SourceResult(
        name="liefergebiet",
        ok=True,
        data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnungen,
        provenance=Provenance(
            source="OpenStreetMap Wegenetz über Overpass · Zensus 2022",
            license=LICENSE,
            endpoint=endpoint,
            stand=(payload.get("osm3s") or {}).get("timestamp_osm_base"),
            retrieved_at=now_iso(),
            note=(
                f"Kürzeste Strecke im OSM-Netz, Radprofil, pauschal "
                f"{RADTEMPO_M_PRO_MIN * 60 / 1000:.0f} km/h — gewählte Werte, "
                "keine Messwerte."
            ),
        ),
    )
