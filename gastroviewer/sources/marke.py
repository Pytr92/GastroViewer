"""Gebietsschutz-Check: Wo ist der nächste Betrieb der eigenen Marke?

Für einen Franchisenehmer ist das eine Vertragsfrage: Gebietsschutz und
Kannibalisierung hängen an der Entfernung zum nächsten Betrieb des eigenen
Systems. Diese Abfrage beantwortet die Kartenseite davon — bewusst über einen
größeren Radius (Vorgabe 10 km) als die Punktanalyse, denn Gebietsschutz wird
in Kilometern gedacht, nicht in Gehminuten.

Aufbau in zwei Schichten, und warum:

1. **Basisabfrage** — alle gastronomischen Betriebe im großen Umkreis, ohne
   Markenfilter. Der erste Entwurf filterte per regulärem Ausdruck auf dem
   Server (``["brand"~…,i]``); das lief bei 10 km um den Marienplatz in den
   60-Sekunden-Timeout, weil Overpass für eine Regex ohne Groß-/Klein-
   schreibung nichts indizieren kann. Gemessen am 02.08.2026: die Basis ohne
   Regex sind 4.631 Betriebe, 2,6 MB, ~30 s — und sie ist **markenunabhängig**,
   liegt also im Cache und bedient jede weitere Markensuche am selben Punkt
   ohne neuen Abruf.
2. **Markensuche** — reine Python-Filterung der Basis (brand **und** Name,
   Groß-/Kleinschreibung egal). Kostet Millisekunden.

Ehrlichkeiten, die in der Antwort stehen: OSM ist eine Untergrenze — ein
fehlender Treffer belegt **kein** freies Gebiet. Die Namenssuche kann
gleichnamige Einzelbetriebe erwischen; solche Treffer sind markiert. Und was
der Gebietsschutz umfasst (Radius, Einwohner, Liefergebiet), steht im
Franchisevertrag — das hier ist die Karte, nicht der Vertrag.
"""

from __future__ import annotations

import time
from typing import Any

from ..config import Settings
from ..http import Outbound
from .base import (Provenance, SourceError, SourceResult, bearing_label,
                   haversine_m, now_iso)
from .overpass import GASTRO_AMENITIES, GASTRO_LABELS, LICENSE, element_coords, run_query

MIN_RADIUS_M = 1000
MAX_RADIUS_M = 20000
VORGABE_RADIUS_M = 10000
MAX_TREFFER = 50


def basis_query(lat: float, lon: float, radius: int, timeout: int = 90) -> str:
    """Alle Gastronomie im Umkreis — ohne Markenfilter, damit Overpass seinen
    Index nutzen kann und die Antwort für jede Marke wiederverwendbar ist."""
    g = "|".join(GASTRO_AMENITIES)
    return f"""[out:json][timeout:{timeout}];
nwr["amenity"~"^({g})$"](around:{radius},{lat},{lon});
out center tags;
"""


async def load_basis(
    out: Outbound, settings: Settings, lat: float, lon: float, radius: int
) -> SourceResult:
    """Lädt die Basis und dampft sie auf das Nötige ein, bevor sie in den
    Cache geht — 4.600 volle Tag-Sätze wären dort nur Ballast."""
    started = time.perf_counter()
    query = basis_query(lat, lon, radius, timeout=int(settings.overpass_timeout))
    try:
        payload, endpoint, probleme = await run_query(out, settings, query)
    except SourceError as err:
        return SourceResult.failed(
            "marke_basis", err, int((time.perf_counter() - started) * 1000)
        )

    betriebe: list[dict[str, Any]] = []
    for el in payload.get("elements", []) if isinstance(payload, dict) else []:
        tags = el.get("tags") or {}
        if tags.get("amenity") not in GASTRO_AMENITIES:
            continue
        coords = element_coords(el)
        if coords is None:
            continue
        betriebe.append({
            "name": tags.get("name"),
            "marke": tags.get("brand"),
            "typ": GASTRO_LABELS.get(tags["amenity"], tags["amenity"]),
            "lat": round(coords[0], 7),
            "lon": round(coords[1], 7),
            "osm_url": f"https://www.openstreetmap.org/{el.get('type')}/{el.get('id')}",
        })

    stand = None
    osm3s = payload.get("osm3s") if isinstance(payload, dict) else None
    if isinstance(osm3s, dict):
        stand = osm3s.get("timestamp_osm_base")

    return SourceResult(
        name="marke_basis",
        ok=True,
        data={"radius_m": radius, "anzahl": len(betriebe), "betriebe": betriebe,
              "stand": stand},
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=list(probleme),
        provenance=Provenance(
            source="OpenStreetMap über Overpass API (Gastronomie im großen Umkreis)",
            license=LICENSE,
            endpoint=endpoint,
            stand=f"OSM-Datenstand {stand}" if stand else None,
            retrieved_at=now_iso(),
        ),
    )


def suche(
    basis: SourceResult, marke: str, lat: float, lon: float, radius: int
) -> SourceResult:
    """Filtert die Basis nach der Marke — reine Rechnung, kein Abruf."""
    started = time.perf_counter()
    m = marke.strip().lower()
    treffer: list[dict[str, Any]] = []
    for b in (basis.data or {}).get("betriebe", []):
        brand = (b.get("marke") or "").lower()
        name = (b.get("name") or "").lower()
        if m not in brand and m not in name:
            continue
        dist = haversine_m(lat, lon, b["lat"], b["lon"])
        treffer.append({
            **b,
            "distanz_m": round(dist),
            "richtung": bearing_label(lat, lon, b["lat"], b["lon"]),
            "nur_namensgleich": m not in brand,
        })
    treffer.sort(key=lambda t: t["distanz_m"])
    abgeschnitten = len(treffer) > MAX_TREFFER
    treffer = treffer[:MAX_TREFFER]

    warnings: list[str] = []
    if abgeschnitten:
        warnings.append(f"Nur die {MAX_TREFFER} nächsten Treffer werden gezeigt.")
    if not treffer:
        warnings.append(
            f"Kein Betrieb mit „{marke.strip()}“ in Marke oder Name im Umkreis "
            f"von {radius / 1000:g} km gefunden. Das ist eine Aussage über "
            "OpenStreetMap, kein Beleg für ein freies Gebiet — kleine oder "
            "neue Betriebe fehlen dort häufig."
        )

    prov = None
    if basis.provenance:
        prov = Provenance(**{**basis.provenance.__dict__})
        prov.source = "OpenStreetMap über Overpass API (brand- und Namenssuche)"
    return SourceResult(
        name="marke",
        ok=True,
        data={
            "marke": marke.strip(),
            "radius_m": radius,
            "basis_betriebe": (basis.data or {}).get("anzahl"),
            "anzahl": len(treffer),
            "naechster_m": treffer[0]["distanz_m"] if treffer else None,
            "treffer": treffer,
            "hinweise": [
                "OSM ist eine Untergrenze — ein fehlender Treffer belegt kein "
                "freies Gebiet.",
                "Die Namenssuche kann gleichnamige Einzelbetriebe erwischen; "
                "solche Treffer sind als „nur namensgleich“ markiert.",
                "Was der Gebietsschutz umfasst (Radius, Einwohner, Liefergebiet), "
                "steht in deinem Franchisevertrag. Das hier ist die Karte, "
                "nicht der Vertrag.",
            ],
        },
        duration_ms=basis.duration_ms + int((time.perf_counter() - started) * 1000),
        warnings=list(basis.warnings or []) + warnings,
        provenance=prov,
    )
