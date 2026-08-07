"""Stadt-Adapter Hamburg — Urban Data Platform (OGC API Features).

Hamburg stellt seine Fachdaten einheitlich über „OGC API - Features"
bereit (``api.hamburg.de/datasets/v1``), Lizenz je Datensatz Datenlizenz
Deutschland Namensnennung 2.0. Vier Themen, die das Werkzeug für München
schon kennt, am 2026-08-07 Ende-zu-Ende mit bbox-Abfragen verifiziert:

===========================  ===============================================
Wochenmärkte                 ``einzelhandel`` → ``wochenmarkt`` — 80 Punkte
                             stadtweit; St. Pauli: 4 im Umkreis. Nur Name
                             und Bezirk — **keine Öffnungszeiten** (ehrlich
                             benannt, anders als die Münchner Liste).
Baustellen                   ``baustellen`` → ``baustelle`` — Steckbriefe
                             der Plattform „Bauweiser" (130 stadtweit),
                             Punktgeometrie, Baubeginn/-ende, Umfangstext,
                             ``istzugangeingeschraenkt``. Keine
                             Vier-Wochen-Vorschau wie München, sondern
                             gepflegte Groß-Maßnahmen.
Rad-Dauerzählstellen         ``dauerzaehlstellen_rad`` → gleichnamig —
                             Zählsäulen mit Jahressumme Vorjahr,
                             Zählung seit Jahresbeginn und Tageslinie
                             (Gurlittinsel als Beleg).
Soziale Erhaltungsverordn.   ``soz_erh_vo`` → ``sozerhvo_inkraft`` —
                             16 Gebiete in Kraft, MultiPolygon, mit
                             Verordnungs-PDF (St. Georg als Beleg).
===========================  ===============================================

Die Blockformen entsprechen den Münchner Adaptern, damit Anzeige und
Bericht nichts unterscheiden müssen.
"""

from __future__ import annotations

import math
import time
from datetime import date
from typing import Any

from ..config import Settings
from ..http import Outbound
from .base import (Provenance, SourceError, SourceResult, bearing_label,
                   haversine_m, now_iso)

OAF_BASE = "https://api.hamburg.de/datasets/v1"
LIZENZ = (
    "Datenlizenz Deutschland Namensnennung 2.0 (dl-de/by-2-0) · "
    "© Freie und Hansestadt Hamburg, Urban Data Platform"
)

# Großzügiger Kasten um das Stadtgebiet (Süd, West, Nord, Ost).
STADT_BBOX = (53.38, 9.63, 53.76, 10.34)

MAX_MARKT_DISTANZ_M = 2000
MAX_RAD_DISTANZ_M = 3000
MAX_LISTE = 40


def in_hamburg(lat: float, lon: float) -> bool:
    sued, west, nord, ost = STADT_BBOX
    return sued <= lat <= nord and west <= lon <= ost


def _bbox_um(lat: float, lon: float, radius_m: float) -> str:
    rand = radius_m + 250
    dlat = rand / 111_320.0
    dlon = rand / (111_320.0 * max(0.2, math.cos(math.radians(lat))))
    return f"{lon - dlon},{lat - dlat},{lon + dlon},{lat + dlat}"


async def _items(
    out: Outbound, dataset: str, collection: str,
    bbox: str | None, limit: int = 200,
) -> list[dict[str, Any]]:
    params: dict[str, str] = {"f": "json", "limit": str(limit)}
    if bbox:
        params["bbox"] = bbox
    payload = await out.get_json(
        "hamburg",
        f"{OAF_BASE}/{dataset}/collections/{collection}/items",
        params=params,
        timeout=45.0,
        limiter="hamburg",
        min_interval=1.0,
    )
    return payload.get("features", []) if isinstance(payload, dict) else []


def _punkt(f: dict[str, Any]) -> tuple[float, float] | None:
    geom = f.get("geometry") or {}
    coords = geom.get("coordinates") or []
    if geom.get("type") != "Point" or len(coords) < 2:
        return None
    return float(coords[1]), float(coords[0])


# ------------------------------------------------------------ Märkte

MARKT_HINWEISE = [
    "Ein Markt bringt Frequenz **an seinen Markttagen**. Der Hamburger "
    "Datensatz führt — anders als der Münchner — keine Öffnungszeiten; "
    "die Termine nennt die Bezirksseite bzw. der Aushang vor Ort.",
]


def maerkte_aufbereiten(
    features: list[dict[str, Any]], lat: float, lon: float, radius: int,
    stadtweit: int,
) -> dict[str, Any]:
    maerkte: list[dict[str, Any]] = []
    for f in features:
        pkt = _punkt(f)
        if pkt is None:
            continue
        p = f.get("properties") or {}
        dist = haversine_m(lat, lon, *pkt)
        maerkte.append({
            "name": p.get("wochenmarkt") or "(ohne Namen)",
            "rubrik": "Wochenmarkt",
            "oeffnungszeiten": None,
            "adresse": (f"Bezirk {p.get('bezirk')}"
                        if p.get("bezirk") else None),
            "link": None,
            "lat": pkt[0],
            "lon": pkt[1],
            "distanz_m": round(dist),
            "richtung": bearing_label(lat, lon, *pkt),
            "im_radius": dist <= radius,
        })
    maerkte.sort(key=lambda m: m["distanz_m"])
    nah = [m for m in maerkte if m["distanz_m"] <= MAX_MARKT_DISTANZ_M]
    nach_rubrik: dict[str, int] = {}
    for m in nah:
        nach_rubrik[m["rubrik"]] = nach_rubrik.get(m["rubrik"], 0) + 1
    return {
        "stadtweit": stadtweit,
        "in_reichweite": nah,
        "im_radius": sum(1 for m in maerkte if m["im_radius"]),
        "naechster": nah[0] if nah else None,
        "nach_rubrik": nach_rubrik,
        "max_distanz_m": MAX_MARKT_DISTANZ_M,
        "rohdaten": f"{OAF_BASE}/einzelhandel",
        "stadt": "Hamburg",
    }


async def maerkte_load(
    out: Outbound, settings: Settings, lat: float, lon: float, radius: int,
) -> SourceResult:
    started = time.perf_counter()
    try:
        features = await _items(
            out, "einzelhandel", "wochenmarkt",
            _bbox_um(lat, lon, MAX_MARKT_DISTANZ_M), limit=100)
        stadtweit = len(await _items(out, "einzelhandel", "wochenmarkt",
                                     None, limit=500))
    except SourceError as err:
        return SourceResult.failed(
            "maerkte", err, int((time.perf_counter() - started) * 1000))
    data = maerkte_aufbereiten(features, lat, lon, radius, stadtweit)
    data["hinweise"] = MARKT_HINWEISE
    warnungen = ([] if data["in_reichweite"] else
                 [f"Kein städtischer Markt innerhalb von "
                  f"{MAX_MARKT_DISTANZ_M} m."])
    return SourceResult(
        name="maerkte", ok=True, data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnungen,
        provenance=Provenance(
            source="Wochenmärkte Hamburg (Urban Data Platform, "
                   "OGC API Features „einzelhandel“)",
            license=LIZENZ,
            endpoint=f"{OAF_BASE}/einzelhandel",
            retrieved_at=now_iso(),
        ),
    )


# --------------------------------------------------------- Baustellen

BAUSTELLEN_HINWEISE = [
    "Der Hamburger Dienst führt die **Steckbriefe der großen Maßnahmen** "
    "(Plattform „Bauweiser“) — gepflegt von den Realisierungsträgern, mit "
    "Laufzeiten oft über Jahre. Kurzfristige Kleinbaustellen und "
    "Haltverbote enthält er nicht.",
    "Entfernung ab Standort-Punkt der Maßnahme (der Dienst führt Punkte, "
    "keine Umrisse).",
]


def _datum_de(v: Any) -> date | None:
    t = str(v or "").strip()
    try:
        tag, monat, jahr = t.split(".")
        return date(int(jahr), int(monat), int(tag))
    except (ValueError, AttributeError):
        return None


def baustellen_aufbereiten(
    features: list[dict[str, Any]], lat: float, lon: float, radius: int,
    heute: date,
) -> dict[str, Any]:
    eintraege: list[dict[str, Any]] = []
    for f in features:
        pkt = _punkt(f)
        if pkt is None:
            continue
        p = f.get("properties") or {}
        ende = _datum_de(p.get("bauende"))
        if ende is not None and ende < heute:
            continue
        dist = haversine_m(lat, lon, *pkt)
        if dist > radius:
            continue
        beginn = _datum_de(p.get("baubeginn"))
        umfang = str(p.get("umfang") or "").strip() or None
        if umfang and len(umfang) > 240:
            umfang = umfang[:237] + "…"
        status = "laufend"
        if beginn is not None and beginn > heute:
            status = "geplant"
        # ``iststoerung`` heißt „verursacht eine Verkehrsstörung" — alle
        # Bauweiser-Steckbriefe sind Baumaßnahmen (live nachgemessen:
        # das Flag steht auch an gewöhnlichen Baustellen).
        eintraege.append({
            "ort": p.get("titel") or "(ohne Ortsangabe)",
            "art": "Baumaßnahme",
            "status": status,
            "beginn": p.get("baubeginn"),
            "ende": p.get("bauende"),
            "distanz_m": round(dist),
            "richtung": bearing_label(lat, lon, *pkt) if dist > 0 else None,
            "gehweg_betroffen": bool(p.get("istzugangeingeschraenkt")),
            "mit_sperrung": "sperr" in (umfang or "").lower(),
            "beeintraechtigung": umfang,
            "betroffene_bereiche": None,
            "beschreibung": (str(p.get("anlass") or "").strip()[:240] or None),
            "link": (p.get("internetlink") or None),
            "lat": pkt[0],
            "lon": pkt[1],
            "umriss": None,
        })
    eintraege.sort(key=lambda e: (0 if e["status"] == "laufend" else 1,
                                  e["distanz_m"]))
    gesamt = len(eintraege)
    return {
        "gesamt": gesamt,
        "baumassnahmen": sum(1 for e in eintraege if e["art"] == "Baumaßnahme"),
        "haltverbote": 0,
        "laufend": sum(1 for e in eintraege if e["status"] == "laufend"),
        "geplant": sum(1 for e in eintraege if e["status"] == "geplant"),
        "gehweg_betroffen": sum(1 for e in eintraege if e["gehweg_betroffen"]),
        "liste": eintraege[:MAX_LISTE],
        "gekappt": gesamt > MAX_LISTE,
        "radius_m": radius,
        "stichtag": heute.isoformat(),
        "rohdaten": f"{OAF_BASE}/baustellen",
        "stadt": "Hamburg",
    }


async def baustellen_load(
    out: Outbound, settings: Settings, lat: float, lon: float, radius: int,
    heute: date | None = None,
) -> SourceResult:
    started = time.perf_counter()
    heute = heute or date.today()
    try:
        features = await _items(
            out, "baustellen", "baustelle",
            _bbox_um(lat, lon, radius), limit=200)
    except SourceError as err:
        return SourceResult.failed(
            "baustellen", err, int((time.perf_counter() - started) * 1000))
    data = baustellen_aufbereiten(features, lat, lon, radius, heute)
    data["hinweise"] = BAUSTELLEN_HINWEISE
    warnungen = ([] if data["gesamt"] else
                 ["Keine der gepflegten Groß-Maßnahmen im Umkreis — über "
                  "kurzfristige Kleinbaustellen sagt der Dienst nichts."])
    return SourceResult(
        name="baustellen", ok=True, data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnungen,
        provenance=Provenance(
            source="Baustellen Hamburg („Bauweiser“-Steckbriefe, "
                   "Urban Data Platform)",
            license=LIZENZ,
            endpoint=f"{OAF_BASE}/baustellen",
            retrieved_at=now_iso(),
        ),
    )


# ------------------------------------------------- Rad-Dauerzählstellen

RAD_HINWEISE = [
    "Zählsäulen des Hamburger Radverkehrs — gemessene Frequenz, keine "
    "Schätzung. Radfahrende sind nicht Fußgänger, aber ein belastbares "
    "Lagesignal für Wege, die am Standort vorbeiführen.",
]


def _wert_mit_label(v: Any) -> tuple[str | None, int | None]:
    """Die Zählsäulen-Felder tragen „Label|Wert" („2025|1926930",
    „06.08.2026|8277") — live nachgemessen."""
    t = str(v or "").strip()
    if "|" in t:
        label, _, zahl = t.rpartition("|")
    else:
        label, zahl = None, t
    zahl = zahl.strip().replace(".", "")
    return (label or None), (int(zahl) if zahl.isdigit() else None)


def rad_aufbereiten(
    features: list[dict[str, Any]], lat: float, lon: float, radius: int,
) -> dict[str, Any]:
    stellen = []
    vorjahr = date.today().year - 1
    for f in features:
        pkt = _punkt(f)
        if pkt is None:
            continue
        p = f.get("properties") or {}
        dist = haversine_m(lat, lon, *pkt)
        jahr_label, jahr = _wert_mit_label(p.get("radfahrende_vorjahr"))
        _, seit_jahresbeginn = _wert_mit_label(
            p.get("radfahrende_seit_jahresbeginn"))
        _, vortag_wert = _wert_mit_label(p.get("radfahrende_vortag"))
        stellen.append({
            "name": p.get("name"),
            "kurzname": p.get("name"),
            "lat": pkt[0],
            "lon": pkt[1],
            "distanz_m": round(dist),
            "richtung": bearing_label(lat, lon, *pkt),
            "im_radius": dist <= radius,
            "richtungen": [],
            "summe_vorjahr": jahr,
            "summe_vorjahr_jahr": (
                int(jahr_label) if jahr_label and jahr_label.isdigit()
                else (vorjahr if jahr is not None else None)),
            "summe_laufender_monat": None,
            "seit_jahresbeginn": seit_jahresbeginn,
            "vortag": vortag_wert,
            "je_tag_vorjahr": round(jahr / 365) if jahr is not None else None,
            "besonderheiten": (f"Zähltyp: {p.get('typ')}"
                               if p.get("typ") else None),
            "stoerung": None,
        })
    stellen.sort(key=lambda s: s["distanz_m"])
    nah = [s for s in stellen if s["distanz_m"] <= MAX_RAD_DISTANZ_M]
    return {
        "stadtweit": len(stellen),
        "in_reichweite": nah,
        "naechste": nah[0] if nah else None,
        "max_distanz_m": MAX_RAD_DISTANZ_M,
        "rohdaten": f"{OAF_BASE}/dauerzaehlstellen_rad",
        "stadt": "Hamburg",
    }


async def rad_load(
    out: Outbound, settings: Settings, lat: float, lon: float, radius: int,
) -> SourceResult:
    started = time.perf_counter()
    try:
        features = await _items(
            out, "dauerzaehlstellen_rad", "dauerzaehlstellen_rad",
            _bbox_um(lat, lon, MAX_RAD_DISTANZ_M), limit=200)
    except SourceError as err:
        return SourceResult.failed(
            "radzaehlung", err, int((time.perf_counter() - started) * 1000))
    data = rad_aufbereiten(features, lat, lon, radius)
    data["hinweise"] = RAD_HINWEISE
    warnungen = ([] if data["in_reichweite"] else
                 [f"Keine Rad-Zählsäule innerhalb von "
                  f"{MAX_RAD_DISTANZ_M} m."])
    return SourceResult(
        name="radzaehlung", ok=True, data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnungen,
        provenance=Provenance(
            source="Dauerzählstellen (Rad) Hamburg (Urban Data Platform)",
            license=LIZENZ,
            endpoint=f"{OAF_BASE}/dauerzaehlstellen_rad",
            retrieved_at=now_iso(),
        ),
    )


# --------------------------------- Soziale Erhaltungsverordnungen

def milieuschutz_aufbereiten(
    features: list[dict[str, Any]],
) -> dict[str, Any]:
    gebiete = []
    for f in features:
        p = f.get("properties") or {}
        gebiete.append({
            "name": p.get("gebietsname"),
            "gueltig_ab": str(p.get("datum") or "")[:10] or None,
            "plan_pdf": None,
            "text_pdf": p.get("fundstelle"),
            "info_pdf": p.get("internet"),
            "rohwerte": p,
        })
    return {"betroffen": bool(gebiete), "gebiete": gebiete}


async def milieuschutz(
    out: Outbound, lat: float, lon: float,
) -> dict[str, Any]:
    """Punktabfrage der in Kraft befindlichen Sozialen
    Erhaltungsverordnungen — für den Planungsrecht-Block."""
    features = await _items(
        out, "soz_erh_vo", "sozerhvo_inkraft",
        _bbox_um(lat, lon, 0), limit=20)
    return milieuschutz_aufbereiten(features)
