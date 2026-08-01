"""Nominatim — Geocoding und Reverse-Geocoding.

Nutzungsbedingung: höchstens 1 Anfrage pro Sekunde, identifizierender User-Agent
mit Kontaktadresse. In Phase 0 geprüft: **ohne User-Agent antwortet der Dienst mit
HTTP 403**. Der Rate-Limiter ist damit Funktionsvoraussetzung, nicht Kür.

Phase-0-Befunde:

* ``addressdetails=1`` ist nötig, sonst fehlt das ``address``-Objekt und damit
  Gemeinde, Ortsteil und PLZ für die Kopfzeile. In den Spec-Beispielen fehlt der
  Parameter.
* Nominatim liefert **keinen** Gemeindeschlüssel. Der AGS kommt aus dem
  Zensus-Block. ``ISO3166-2-lvl4`` liefert aber das Bundesland als Gegenprobe.
* ``licence`` steht in jeder Antwort und wird durchgereicht statt hartkodiert.
"""

from __future__ import annotations

import time
from typing import Any

from ..config import Settings
from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, now_iso

FALLBACK_LICENSE = "Data © OpenStreetMap contributors, ODbL 1.0. http://osm.org/copyright"

# Reihenfolge = Vorrang. Nominatim füllt je nach Ort unterschiedliche Felder.
GEMEINDE_KEYS = ["city", "town", "village", "municipality", "borough", "county"]
ORTSTEIL_KEYS = ["suburb", "city_district", "quarter", "neighbourhood", "hamlet"]


def _first(address: dict[str, Any], keys: list[str]) -> str | None:
    for k in keys:
        v = address.get(k)
        if v:
            return str(v)
    return None


def shape(raw: dict[str, Any]) -> dict[str, Any]:
    address = raw.get("address") or {}
    iso = address.get("ISO3166-2-lvl4")
    return {
        "display_name": raw.get("display_name"),
        "name": raw.get("name"),
        "lat": float(raw["lat"]) if raw.get("lat") else None,
        "lon": float(raw["lon"]) if raw.get("lon") else None,
        "strasse": address.get("road"),
        "hausnummer": address.get("house_number"),
        "plz": address.get("postcode"),
        "gemeinde": _first(address, GEMEINDE_KEYS),
        "ortsteil": _first(address, ORTSTEIL_KEYS),
        "bundesland": address.get("state"),
        "bundesland_iso": iso,
        "land": address.get("country"),
        "osm_type": raw.get("osm_type"),
        "osm_id": raw.get("osm_id"),
        "adresse_roh": address,
        "licence": raw.get("licence") or FALLBACK_LICENSE,
    }


def _provenance(settings: Settings, endpoint: str, licence: str) -> Provenance:
    return Provenance(
        source="Nominatim (OpenStreetMap)",
        license=licence,
        endpoint=endpoint,
        stand="laufend aktualisiert",
        retrieved_at=now_iso(),
        note=(
            "Nominatim liefert keinen Gemeindeschlüssel (AGS). Der AGS in der Kopfzeile "
            "stammt aus dem Zensus-Gitter."
        ),
    )


async def reverse(
    out: Outbound, settings: Settings, lat: float, lon: float
) -> SourceResult:
    started = time.perf_counter()
    url = f"{settings.nominatim_base}/reverse"
    params = {
        "format": "jsonv2",
        "lat": f"{lat}",
        "lon": f"{lon}",
        "addressdetails": "1",
        "zoom": "18",
        "accept-language": "de",
    }
    try:
        raw = await out.get_json(
            "nominatim",
            url,
            params=params,
            timeout=settings.nominatim_timeout,
            limiter="nominatim",
            min_interval=settings.nominatim_min_interval,
        )
    except SourceError as err:
        return SourceResult.failed(
            "adresse", err, int((time.perf_counter() - started) * 1000)
        )

    if isinstance(raw, dict) and raw.get("error"):
        return SourceResult(
            name="adresse",
            ok=True,
            data=None,
            duration_ms=int((time.perf_counter() - started) * 1000),
            warnings=[
                f"Nominatim findet keine Adresse zu diesem Punkt: {raw.get('error')}. "
                "Auf freier Fläche oder im Wasser ist das normal."
            ],
            provenance=_provenance(settings, url, FALLBACK_LICENSE),
        )

    data = shape(raw)
    return SourceResult(
        name="adresse",
        ok=True,
        data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        provenance=_provenance(settings, url, data["licence"]),
    )


async def search(
    out: Outbound, settings: Settings, query: str, limit: int = 8
) -> SourceResult:
    started = time.perf_counter()
    url = f"{settings.nominatim_base}/search"
    params = {
        "format": "jsonv2",
        "q": query,
        "countrycodes": "de",
        "limit": str(limit),
        "addressdetails": "1",
        "accept-language": "de",
    }
    try:
        raw = await out.get_json(
            "nominatim",
            url,
            params=params,
            timeout=settings.nominatim_timeout,
            limiter="nominatim",
            min_interval=settings.nominatim_min_interval,
        )
    except SourceError as err:
        return SourceResult.failed(
            "suche", err, int((time.perf_counter() - started) * 1000)
        )

    items = [shape(r) for r in raw] if isinstance(raw, list) else []
    licence = items[0]["licence"] if items else FALLBACK_LICENSE
    return SourceResult(
        name="suche",
        ok=True,
        data=items,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=[] if items else [f"Keine Treffer für „{query}“ in Deutschland."],
        provenance=_provenance(settings, url, licence),
    )
