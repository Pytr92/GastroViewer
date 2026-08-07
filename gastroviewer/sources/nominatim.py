"""Nominatim — Geocoding und Reverse-Geocoding, mit Photon-Rückfall.

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

Rückfall (Phase-0 am 2026-08-07): Scheitert Nominatim (Timeout, 403, 5xx),
übernimmt **Photon** (Komoot, ``photon.komoot.io`` — OSM-Daten, ODbL).
Verifiziert: die Suche findet „Sendlinger Str 10 München" hausnummerngenau
(GeoJSON, Felder ``street``/``housenumber``/``city``/``state``/``postcode``),
``/reverse`` liefert die Adresse am Sendlinger Tor. Photon führt kein
Bundesland-ISO und keine ``licence`` in der Antwort — dafür stehen
Konstanten; die Herkunft (Photon statt Nominatim) steht in Quelle und
Warnung, damit der Rückfall nie stillschweigend passiert.
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


PHOTON_BASE = "https://photon.komoot.io"


def photon_shape(feature: dict[str, Any]) -> dict[str, Any]:
    """Photon-GeoJSON-Feature → dieselbe Form wie :func:`shape`."""
    p = feature.get("properties") or {}
    coords = (feature.get("geometry") or {}).get("coordinates") or []
    strasse = p.get("street") or (p.get("name") if p.get("housenumber") else None)
    teile = [" ".join(x for x in (strasse, p.get("housenumber")) if x),
             " ".join(x for x in (p.get("postcode"), p.get("city")) if x)]
    display = ", ".join(t for t in teile if t) or p.get("name")
    return {
        "display_name": display,
        "name": p.get("name"),
        "lat": float(coords[1]) if len(coords) >= 2 else None,
        "lon": float(coords[0]) if len(coords) >= 2 else None,
        "strasse": strasse,
        "hausnummer": p.get("housenumber"),
        "plz": p.get("postcode"),
        "gemeinde": p.get("city") or p.get("county"),
        "ortsteil": p.get("district") or p.get("locality"),
        "bundesland": p.get("state"),
        "bundesland_iso": None,  # führt Photon nicht
        "land": p.get("country"),
        "osm_type": p.get("osm_type"),
        "osm_id": p.get("osm_id"),
        "adresse_roh": p,
        "licence": FALLBACK_LICENSE,
    }


def _photon_provenance(endpoint: str) -> Provenance:
    return Provenance(
        source="Photon (Komoot) — Rückfall, OpenStreetMap-Daten",
        license=FALLBACK_LICENSE,
        endpoint=endpoint,
        stand="laufend aktualisiert",
        retrieved_at=now_iso(),
        note=(
            "Nominatim war nicht erreichbar; die Adresse kommt vom "
            "Photon-Geocoder (gleiche OSM-Datenbasis). Photon führt kein "
            "Bundesland-ISO — die Gegenprobe entfällt für diesen Abruf."
        ),
    )


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
        return await _photon_reverse(out, settings, lat, lon, err, started)

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
        return await _photon_search(out, settings, query, limit, err, started)

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


# ------------------------------------------------- Photon-Rückfall

async def _photon_reverse(
    out: Outbound, settings: Settings, lat: float, lon: float,
    nominatim_fehler: SourceError, started: float,
) -> SourceResult:
    url = f"{PHOTON_BASE}/reverse"
    try:
        raw = await out.get_json(
            "photon", url,
            params={"lat": f"{lat}", "lon": f"{lon}", "lang": "de"},
            timeout=settings.nominatim_timeout,
            limiter="photon",
            min_interval=1.0,
        )
    except SourceError:
        # Beide Geocoder tot: der ursprüngliche Nominatim-Fehler zählt.
        return SourceResult.failed(
            "adresse", nominatim_fehler,
            int((time.perf_counter() - started) * 1000))
    features = (raw or {}).get("features") or []
    if not features:
        return SourceResult.failed(
            "adresse", nominatim_fehler,
            int((time.perf_counter() - started) * 1000))
    return SourceResult(
        name="adresse",
        ok=True,
        data=photon_shape(features[0]),
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=[
            "Nominatim war nicht erreichbar "
            f"({nominatim_fehler.message}) — die Adresse kommt vom "
            "Photon-Rückfall (gleiche OSM-Datenbasis)."
        ],
        provenance=_photon_provenance(url),
    )


async def _photon_search(
    out: Outbound, settings: Settings, query: str, limit: int,
    nominatim_fehler: SourceError, started: float,
) -> SourceResult:
    url = f"{PHOTON_BASE}/api"
    try:
        raw = await out.get_json(
            "photon", url,
            params={"q": query, "limit": str(limit), "lang": "de"},
            timeout=settings.nominatim_timeout,
            limiter="photon",
            min_interval=1.0,
        )
    except SourceError:
        return SourceResult.failed(
            "suche", nominatim_fehler,
            int((time.perf_counter() - started) * 1000))
    features = (raw or {}).get("features") or []
    # Photon kennt keinen countrycodes-Filter — Deutschland-Filter im Code.
    items = [photon_shape(f) for f in features
             if ((f.get("properties") or {}).get("countrycode") or "").upper()
             in ("DE", "")]
    return SourceResult(
        name="suche",
        ok=True,
        data=items,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=[
            "Nominatim war nicht erreichbar "
            f"({nominatim_fehler.message}) — die Treffer kommen vom "
            "Photon-Rückfall (gleiche OSM-Datenbasis)."
        ] + ([] if items else [f"Keine Treffer für „{query}“ in Deutschland."]),
        provenance=_photon_provenance(url),
    )
