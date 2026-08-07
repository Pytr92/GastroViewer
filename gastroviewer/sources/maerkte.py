"""Märkte der Landeshauptstadt München — Frequenzbringer mit Terminen.

Ein Wochenmarkt vor der Tür bringt an seinen Markttagen Laufkundschaft ins
Viertel; der Viktualienmarkt zieht sie täglich. OSM kennt zwar
``amenity=marketplace``, aber die städtische Liste trägt zusätzlich die
**Öffnungszeiten** und die Rubrik — und sie ist gepflegt.

Verifiziert am 2026-08-07:
``https://geoportal.muenchen.de/geoserver/gsm_wfs/ows`` ·
``typeName=gsm_wfs:maerkte`` · WFS · GeoJSON · 54 Punkte
(34 Wochenmärkte, 10 Bauernmärkte, 5 ständige Märkte, 5 Großmärkte) ·
Datenlizenz Deutschland Namensnennung 2.0 (CKAN ``license_id``
``dl-by-de/2.0``). Name und Öffnungszeiten stehen gemeinsam im Feld
``inhalt`` („Wochenmarkt Messestadt Riem, Öffnungszeiten: Freitag, 10:00 …")
und werden hier getrennt.
"""

from __future__ import annotations

import re
import time
from typing import Any

from ..config import Settings
from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, bearing_label, haversine_m, now_iso
from .baustellen import STADT_BBOX

WFS_URL = "https://geoportal.muenchen.de/geoserver/gsm_wfs/ows"
TYPENAME = "gsm_wfs:maerkte"

LIZENZ = (
    "Datenlizenz Deutschland Namensnennung 2.0 (dl-de/by-2-0) · "
    "© Landeshauptstadt München, GeodatenService"
)
ROHDATEN = "https://opendata.muenchen.de/dataset/maerkte"

# Jenseits davon prägt ein Markt den Standort nicht mehr (gewählter Wert:
# ein Wochenmarkt wirkt aufs Viertel, nicht auf die ganze Stadt).
MAX_DISTANZ_M = 2000


def name_und_zeiten(inhalt: Any) -> tuple[str | None, str | None]:
    """„Viktualienmarkt, Öffnungszeiten: Mo–Sa …" → Name und Zeiten getrennt."""
    text = re.sub(r"\s+", " ", str(inhalt or "")).strip()
    if not text:
        return None, None
    m = re.split(r",?\s*Öffnungszeiten:\s*", text, maxsplit=1)
    name = m[0].strip().rstrip(",") or None
    zeiten = m[1].strip().rstrip(",") if len(m) > 1 else None
    return name, zeiten or None


def aufbereiten(
    features: list[dict[str, Any]], lat: float, lon: float, radius: int
) -> dict[str, Any]:
    maerkte: list[dict[str, Any]] = []
    for f in features:
        geom = f.get("geometry") or {}
        koords = geom.get("coordinates") or []
        if geom.get("type") != "Point" or len(koords) < 2:
            continue
        p = f.get("properties") or {}
        mlon, mlat = float(koords[0]), float(koords[1])
        dist = haversine_m(lat, lon, mlat, mlon)
        name, zeiten = name_und_zeiten(p.get("inhalt"))
        maerkte.append(
            {
                "name": name or "(ohne Namen)",
                "rubrik": p.get("rubrik") or "Markt",
                "oeffnungszeiten": zeiten,
                "adresse": p.get("adresse"),
                "link": p.get("link"),
                "lat": mlat,
                "lon": mlon,
                "distanz_m": round(dist),
                "richtung": bearing_label(lat, lon, mlat, mlon),
                "im_radius": dist <= radius,
            }
        )
    maerkte.sort(key=lambda m: m["distanz_m"])
    nah = [m for m in maerkte if m["distanz_m"] <= MAX_DISTANZ_M]
    nach_rubrik: dict[str, int] = {}
    for m in nah:
        nach_rubrik[m["rubrik"]] = nach_rubrik.get(m["rubrik"], 0) + 1
    return {
        "stadtweit": len(maerkte),
        "in_reichweite": nah,
        "im_radius": sum(1 for m in maerkte if m["im_radius"]),
        "naechster": nah[0] if nah else None,
        "nach_rubrik": nach_rubrik,
        "max_distanz_m": MAX_DISTANZ_M,
        "rohdaten": ROHDATEN,
    }


HINWEISE = [
    "Ein Markt bringt Frequenz **an seinen Markttagen** — die Öffnungszeiten "
    "stehen deshalb direkt dabei (aus dem städtischen Datensatz, nicht "
    "interpretiert).",
    "Großmärkte sind Handelsplätze, keine Laufkundschaft-Bringer — sie "
    "zählen mit, sind aber an der Rubrik erkennbar.",
]


async def load(
    out: Outbound,
    settings: Settings,
    lat: float,
    lon: float,
    radius: int,
) -> SourceResult:
    started = time.perf_counter()
    sued, west, nord, ost = STADT_BBOX
    if not (sued <= lat <= nord and west <= lon <= ost):
        return SourceResult(
            name="maerkte",
            ok=True,
            data=None,
            warnings=[
                "Die Marktliste gibt es nur für die Stadt München. Wochen- "
                "und Bauernmärkte anderswo zeigt allenfalls der "
                "OSM-Frequenzbringer-Block (amenity=marketplace)."
            ],
        )
    params = {
        "service": "WFS",
        "version": "1.1.0",
        "request": "GetFeature",
        "typeName": TYPENAME,
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
    }
    try:
        payload = await out.get_json(
            "muenchen_maerkte",
            WFS_URL,
            params=params,
            timeout=45.0,
            limiter="muenchen",
            min_interval=1.0,
        )
    except SourceError as err:
        return SourceResult.failed(
            "maerkte", err, int((time.perf_counter() - started) * 1000)
        )

    features = payload.get("features", []) if isinstance(payload, dict) else []
    data = aufbereiten(features, lat, lon, radius)
    data["hinweise"] = HINWEISE

    warnungen: list[str] = []
    if not data["in_reichweite"]:
        warnungen.append(
            f"Kein städtischer Markt innerhalb von {MAX_DISTANZ_M} m."
        )
    return SourceResult(
        name="maerkte",
        ok=True,
        data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnungen,
        provenance=Provenance(
            source="Märkte der Landeshauptstadt München (GeodatenService, WFS)",
            license=LIZENZ,
            endpoint=WFS_URL,
            stand="laufend gepflegte Stadtliste",
            retrieved_at=now_iso(),
            note=(
                "54 städtische Märkte mit Rubrik und Öffnungszeiten. "
                "Nur Stadtgebiet München."
            ),
        ),
    )
