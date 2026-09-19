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
    # Der Dienst filtert nach Rechteck, nicht nach Fläche: Ein Punkt knapp
    # außerhalb eines Gebiets bekäme dessen Verordnung zugeschrieben. Erst
    # der Punkt-in-Polygon-Test macht aus dem Treffer eine Aussage.
    from .baurecht import enthaelt_punkt

    drin = [f for f in features if enthaelt_punkt(f.get("geometry"), lat, lon)]
    return milieuschutz_aufbereiten(drin)


# ------------------------------------------------- Verkehrsmengen (Kfz)
# Live belegt 18.09.2026 (fixtures/de, Runde 6): OGC API Features
# ``verkehrsstaerken/collections/kfz_temporaere_zaehlungen`` (Punkte:
# ``zaehlstelle``, ``bezeichnung``, ``jahr``, ``dtv_kfz``, ``dtvw_kfz``,
# ``sv_anteil_dtvw``) und ``verkehrsmengen/collections/verkehrsmengen_dtv_hvs_2019``
# (Linien der Hauptverkehrsstraßen: ``dtv``, ``sv`` in Prozent).

VM_MAX_DISTANZ_M = 1500
VM_LIZENZ = LIZENZ


def _punkte_alle(geom: dict[str, Any] | None) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []

    def tief(c: Any) -> None:
        if isinstance(c, (list, tuple)) and len(c) >= 2 and all(isinstance(x, (int, float)) for x in c[:2]):
            out.append((float(c[1]), float(c[0])))
        elif isinstance(c, (list, tuple)):
            for x in c:
                tief(x)

    tief((geom or {}).get("coordinates"))
    return out


def verkehrsmengen_aufbereiten(zaehlungen: list[dict[str, Any]], hvs: list[dict[str, Any]],
                               lat: float, lon: float, radius: int) -> dict[str, Any]:
    treffer = []
    for f in zaehlungen:
        p = f.get("properties") or {}
        pkt = _punkt(f)
        if pkt is None:
            continue
        dist = haversine_m(lat, lon, *pkt)
        if dist > VM_MAX_DISTANZ_M:
            continue
        k = p.get("dtv_kfz") if isinstance(p.get("dtv_kfz"), (int, float)) else None
        anteil = p.get("sv_anteil_dtvw") if isinstance(p.get("sv_anteil_dtvw"), (int, float)) else None
        sv = round(k * anteil / 100) if k is not None and anteil is not None else None
        treffer.append({
            "strasse": p.get("bezeichnung") or "?",
            "zaehlstelle": f"{p.get('zaehlstelle')} · {p.get('richtung') or ''}".strip(" ·"),
            "zaehlart": f"Temporäre Zählung {p.get('jahr') or ''}".strip(),
            "lat": pkt[0], "lon": pkt[1], "distanz_m": round(dist),
            "richtung": bearing_label(lat, lon, *pkt), "im_radius": dist <= radius,
            "dtv_kfz": int(k) if k is not None else None,
            "dtv_leichtverkehr": (int(k) - sv if k is not None and sv is not None else None),
            "dtv_schwerverkehr": sv, "schwerverkehr_anteil": anteil,
            "dtv_werktag": int(p["dtvw_kfz"]) if isinstance(p.get("dtvw_kfz"), (int, float)) else None,
            "jahr": p.get("jahr"),
        })
    for f in hvs:
        p = f.get("properties") or {}
        punkte = _punkte_alle(f.get("geometry"))
        if not punkte:
            continue
        dist, naechst = min((haversine_m(lat, lon, a, b), (a, b)) for a, b in punkte)
        if dist > VM_MAX_DISTANZ_M:
            continue
        k = p.get("dtv") if isinstance(p.get("dtv"), (int, float)) else None
        anteil = p.get("sv") if isinstance(p.get("sv"), (int, float)) else None
        sv = round(k * anteil / 100) if k is not None and anteil is not None else None
        treffer.append({
            "strasse": f"Hauptverkehrsstraße ({p.get('strassenklasse') or 'HVS'})",
            "zaehlstelle": "Netzabschnitt DTV 2019", "zaehlart": "Verkehrsmengenkarte 2019 (Abschnitt)",
            "lat": naechst[0], "lon": naechst[1], "distanz_m": round(dist),
            "richtung": bearing_label(lat, lon, *naechst) if dist > 0 else None, "im_radius": dist <= radius,
            "dtv_kfz": int(k) if k is not None else None,
            "dtv_leichtverkehr": (int(k) - sv if k is not None and sv is not None else None),
            "dtv_schwerverkehr": sv, "schwerverkehr_anteil": anteil, "jahr": 2019,
        })
    treffer.sort(key=lambda s: s["distanz_m"])
    treffer = treffer[:12]
    mit_wert = [s for s in treffer if s["dtv_kfz"] is not None]
    return {
        "zaehlstellen": treffer, "naechste": treffer[0] if treffer else None,
        "staerkste": max(mit_wert, key=lambda s: s["dtv_kfz"]) if mit_wert else None,
        "im_radius": [s for s in treffer if s["im_radius"]], "max_distanz_m": VM_MAX_DISTANZ_M,
        "jahr": max((s["jahr"] for s in treffer if isinstance(s.get("jahr"), int)), default=2019),
        "dienst": "hamburg", "portal": "https://metaver.de/trefferanzeige?docuuid=verkehrsstaerken",
        "portal_titel": "Verkehrsstärken Hamburg (Urban Data Platform)",
        "netz_hinweis": ("Hamburg zählt temporär an Hauptstraßen (Jahr am Wert) und führt eine "
                         "Verkehrsmengenkarte 2019 für die Hauptverkehrsstraßen; Wohnstraßen fehlen. "),
        "stadt": "Hamburg",
    }


VM_HINWEISE = [
    "Temporäre Zählungen: DTV (Mo–So) und DTVw (werktags) am Querschnitt, Schwerverkehrsanteil in Prozent "
    "des DTVw — das Zähljahr steht an jeder Zeile und reicht bis 2013 zurück.",
]


async def verkehrsmengen_load(out: Outbound, settings: Settings, lat: float, lon: float, radius: int) -> SourceResult:
    started = time.perf_counter()
    bbox = _bbox_um(lat, lon, VM_MAX_DISTANZ_M)
    warnungen: list[str] = []
    try:
        zaehlungen = await _items(out, "verkehrsstaerken", "kfz_temporaere_zaehlungen", bbox, limit=100)
    except SourceError as err:
        return SourceResult.failed("verkehrsmenge", err, int((time.perf_counter() - started) * 1000))
    try:
        hvs = await _items(out, "verkehrsmengen", "verkehrsmengen_dtv_hvs_2019", bbox, limit=100)
    except SourceError as err:
        hvs, warnungen = [], [f"Verkehrsmengenkarte 2019: {err.message}"]
    data = verkehrsmengen_aufbereiten(zaehlungen, hvs, lat, lon, radius)
    data["hinweise"] = VM_HINWEISE
    if not data["zaehlstellen"]:
        warnungen.append(f"Keine Zählstelle und kein Hauptverkehrsstraßen-Abschnitt innerhalb von {VM_MAX_DISTANZ_M} m.")
    return SourceResult(
        name="verkehrsmenge", ok=True, data=data,
        duration_ms=int((time.perf_counter() - started) * 1000), warnings=warnungen,
        provenance=Provenance(source="Verkehrsstärken (temporäre Zählungen) und Verkehrsmengen DTV 2019 Hamburg (Urban Data Platform, OGC API)",
                              license=VM_LIZENZ, endpoint=f"{OAF_BASE}/verkehrsstaerken",
                              stand=f"jüngste Zählung {data['jahr']}", retrieved_at=now_iso()),
    )


# ------------------------------------------ Regionalstatistik der Stadtteile
# Live belegt 18.09.2026: ``regionalstatistische_daten_stadtteile`` — je
# Stadtteil und Jahr eine Zeile (MultiPolygon) mit rund 100 Kennzahlen
# (Bevölkerung, Haushalte, Arbeitsmarkt, SGB II, Wohnen, Infrastruktur, Pkw).

STADT_RAUM = "Hamburg gesamt"
STADTTEIL_INDIKATOREN = [
    {"schluessel": "einwohner", "feld": "bev_insgesamt", "label": "Einwohner", "einheit": "", "deutung": "Bevölkerung am 31.12."},
    {"schluessel": "einw_je_ha", "feld": "flaeche_einw_pro_ha", "label": "Einwohner je ha", "einheit": "Einw./ha", "deutung": "Bruttodichte"},
    {"schluessel": "unter18", "feld": "bev_u18_proz", "label": "Anteil unter 18", "einheit": "%", "deutung": "Familienlage"},
    {"schluessel": "ab65", "feld": "bev_ab65_proz", "label": "Anteil 65 und älter", "einheit": "%", "deutung": "Altersstruktur"},
    {"schluessel": "auslaenderanteil", "feld": "bev_auslaender_proz", "label": "Ausländeranteil", "einheit": "%", "deutung": "ausländische Staatsangehörige"},
    {"schluessel": "migrationshintergrund", "feld": "bev_migrationshintergrund_proz", "label": "Anteil mit Migrationshintergrund", "einheit": "%", "deutung": "Herkunftsvielfalt"},
    {"schluessel": "einpersonenhaushalte", "feld": "hau_einpersonenhaushalte_proz", "label": "Einpersonenhaushalte", "einheit": "%", "deutung": "Außer-Haus-Verzehr, kleine Portionen"},
    {"schluessel": "haushaltsgroesse", "feld": "hau_haushaltgroesse_avg", "label": "Haushaltsgröße", "einheit": "Pers.", "deutung": "Durchschnitt"},
    {"schluessel": "arbeitslose", "feld": "arb_arbeitslose_15_bis_64_proz", "label": "Arbeitslosenanteil 15–64", "einheit": "%", "deutung": "Kaufkraftrisiko"},
    {"schluessel": "sgb2", "feld": "sgb_anteil_lst_an_der_bevoelkerung_ins_proz", "label": "SGB-II-Leistungsempfänger", "einheit": "%", "deutung": "Anteil an der Bevölkerung"},
    {"schluessel": "beschaeftigte", "feld": "soz_sozverpflichtig_beschaeftigte_15_bis_64_ant", "label": "Sozialversicherungspflichtig Beschäftigte 15–64", "einheit": "%", "deutung": "Erwerbsbeteiligung"},
    {"schluessel": "sozialwohnungen", "feld": "wohn_ant_sozialwohnungen_an_allen_wohnungen", "label": "Sozialwohnungen", "einheit": "%", "deutung": "Anteil an allen Wohnungen"},
    {"schluessel": "wohnflaeche", "feld": "wohn_avg_wohnflaeche_in_qm_pro_einw", "label": "Wohnfläche je Einwohner", "einheit": "m²", "deutung": "Wohnstandard"},
    {"schluessel": "pkw_je_1000", "feld": "ver_private_pkw_je_1000_ew_anz", "label": "Private Pkw je 1.000 Einwohner", "einheit": "", "deutung": "Motorisierung"},
    {"schluessel": "zuzug_saldo", "feld": "bevb_diff_zuzuege_fortzuege_anz", "label": "Wanderungssaldo", "einheit": "", "deutung": "Zuzüge minus Fortzüge im Jahr"},
]


def _trend_hh(reihe: list[list[float]]) -> dict[str, Any] | None:
    if not reihe:
        return None
    jahr_neu, wert_neu = reihe[-1]
    frueher = [p for p in reihe if p[0] <= jahr_neu - 5]
    basis = frueher[-1] if frueher else reihe[0]
    if basis[0] == jahr_neu:
        return {"jahr": int(jahr_neu), "wert": wert_neu, "von_jahr": None, "von_wert": None, "delta": None}
    return {"jahr": int(jahr_neu), "wert": wert_neu, "von_jahr": int(basis[0]), "von_wert": basis[1],
            "delta": round(wert_neu - basis[1], 2)}


def stadtteil_aufbereiten(features: list[dict[str, Any]], lat: float, lon: float) -> dict[str, Any] | None:
    """Zeilen des Stadtteils, der den Punkt enthält, zu Jahresreihen; die
    übrigen Zeilen (Nachbar-Stadtteile im Kasten) dienen nicht als Stadtwert —
    einen Gesamtwert führt der Datensatz nicht."""
    from .baurecht import enthaelt_punkt

    zeilen = [f for f in features if enthaelt_punkt(f.get("geometry"), lat, lon)]
    if not zeilen:
        return None
    p0 = zeilen[0].get("properties") or {}
    name, nr, bezirk = p0.get("stadtteil"), p0.get("stadtteil_nr"), p0.get("bezirk")
    zeilen = [f for f in zeilen if (f.get("properties") or {}).get("stadtteil_nr") == nr]
    indikatoren = []
    for ind in STADTTEIL_INDIKATOREN:
        reihe = []
        for f in zeilen:
            p = f.get("properties") or {}
            try:
                jahr = int(str(p.get("jahr") or "")[:4])
            except ValueError:
                continue
            w = p.get(ind["feld"])
            if isinstance(w, (int, float)):
                reihe.append([jahr, float(w)])
        reihe.sort()
        # ein Jahr kann doppelt vorliegen (Seiten) — letzter Wert zählt
        kompakt: dict[int, float] = {int(j): w for j, w in reihe}
        reihe = [[j, w] for j, w in sorted(kompakt.items())]
        if not reihe:
            continue
        indikatoren.append({"schluessel": ind["schluessel"], "label": ind["label"], "einheit": ind["einheit"],
                            "deutung": ind["deutung"], "bezirk": _trend_hh(reihe), "stadt": None,
                            "reihe": reihe[-12:]})
    return {"bezirk": f"{name} (Bezirk {bezirk})" if bezirk else name, "bezirk_gesucht": name,
            "stadt_raum": STADT_RAUM, "stadtteil_nr": nr, "indikatoren": indikatoren,
            "hinweise": STADTTEIL_HINWEISE}


STADTTEIL_HINWEISE = [
    "Stadtteilebene (104 Stadtteile), jährlich fortgeschrieben — hier steht die **Entwicklung über "
    "die Jahre**; einen Hamburg-Gesamtwert führt der Datensatz nicht, die Spalte bleibt leer.",
    "Der Trendvergleich reicht ~5 Jahre zurück; Werte zum 31.12. des Jahres.",
]


async def stadtteil_load(out: Outbound, lat: float, lon: float) -> SourceResult:
    started = time.perf_counter()
    d = 0.0005
    bbox = f"{lon - d:.6f},{lat - d:.6f},{lon + d:.6f},{lat + d:.6f}"
    try:
        features = await _items(out, "regionalstatistische_daten_stadtteile", "regionalstatistische_daten_stadtteile",
                                bbox, limit=200)
    except SourceError as err:
        return SourceResult.failed("indikatoren", err, int((time.perf_counter() - started) * 1000))
    data = stadtteil_aufbereiten(features, lat, lon)
    warnungen = [] if data else ["Der Punkt liegt in keinem Hamburger Stadtteil des Datensatzes."]
    return SourceResult(
        name="indikatoren", ok=True, data=data,
        duration_ms=int((time.perf_counter() - started) * 1000), warnings=warnungen,
        provenance=Provenance(source="Regionalstatistische Daten der Stadtteile Hamburg (Statistikamt Nord, Urban Data Platform)",
                              license=LIZENZ, endpoint=f"{OAF_BASE}/regionalstatistische_daten_stadtteile",
                              stand=(f"Jahresreihen bis {max(i['bezirk']['jahr'] for i in data['indikatoren'])}"
                                     if data and data.get("indikatoren") else None),
                              retrieved_at=now_iso(), note="Punktkasten-Abfrage, Stadtteil über Punkt-in-Fläche; Jahresreihen lokal gebildet."),
    )


# -------------------------------------------------- Lage: Parken (Parkhäuser)
# Live belegt 18.09.2026: ``parkhaeuser/collections/parkhaeuser`` (Punkte mit
# Belegung ``frei``/``gesamt``, ``preise``, ``oeffnungszeit``) und
# ``parkraum/collections/parkraum`` (Flächen mit ``primaere_bewirtschaftung``).

LAGE_HINWEISE = [
    "Für Hamburg liegen offen die **Parkhäuser mit Live-Belegung** und die Parkraumbewirtschaftung "
    "am Punkt vor; Fußgängerzonen, Geschäftsstraßen und Realnutzung gibt die Stadt nicht als Dienst frei.",
]


async def lage_load(out: Outbound, lat: float, lon: float, radius: int) -> SourceResult:
    from .baurecht import enthaelt_punkt

    started = time.perf_counter()
    fehler: list[str] = []
    try:
        ph = await _items(out, "parkhaeuser", "parkhaeuser", _bbox_um(lat, lon, radius), limit=100)
    except SourceError as err:
        ph, fehler = [], fehler + [f"Parkhäuser: {err.message}"]
    try:
        d = 0.0005
        pr = await _items(out, "parkraum", "parkraum", f"{lon - d:.6f},{lat - d:.6f},{lon + d:.6f},{lat + d:.6f}", limit=20)
    except SourceError as err:
        pr, fehler = [], fehler + [f"Parkraum: {err.message}"]
    if len(fehler) == 2:
        return SourceResult.failed("lage", SourceError("api_error", "Urban Data Platform: " + fehler[0]),
                                   int((time.perf_counter() - started) * 1000))
    haeuser = []
    for f in ph:
        pkt = _punkt(f)
        if pkt is None:
            continue
        p = f.get("properties") or {}
        dist = haversine_m(lat, lon, *pkt)
        if dist > radius:
            continue
        haeuser.append({"name": p.get("name"), "art": p.get("art"), "adresse": " ".join(x for x in (p.get("strasse"), p.get("hausnr")) if x) or None,
                        "gesamt": p.get("gesamt") or p.get("stellplaetze_gesamt"), "frei": p.get("frei"),
                        "status": p.get("situation") or p.get("status"), "oeffnungszeit": p.get("oeffnungszeit"),
                        "preise": (str(p.get("preise") or "").split("\n")[0][:120] or None),
                        "link": p.get("link"), "lat": pkt[0], "lon": pkt[1], "distanz_m": round(dist),
                        "richtung": bearing_label(lat, lon, *pkt) if dist > 0 else None})
    haeuser.sort(key=lambda h: h["distanz_m"])
    am_punkt = next(((f.get("properties") or {}) for f in pr if enthaelt_punkt(f.get("geometry"), lat, lon)), None)
    parkraum = None
    if am_punkt is not None or pr:
        p = am_punkt if am_punkt is not None else (pr[0].get("properties") or {})
        parkraum = {"bewirtschaftung": p.get("primaere_bewirtschaftung"), "zeit": p.get("geltungszeit_primaerer_bewirtschaftung") or None,
                    "strasse": p.get("strassenname"), "ausrichtung": p.get("ausrichtung_zur_strasse"), "am_punkt": am_punkt is not None}
    data = {
        "stadt": "Hamburg",
        "kurzparkzone": ({"zeitraum": parkraum["zeit"], "dauer": None, "bezirk": parkraum["strasse"],
                          "art": f"Parkraumbewirtschaftung: {parkraum['bewirtschaftung']}"}
                         if parkraum and parkraum["bewirtschaftung"] and parkraum["am_punkt"] else None),
        "parkraum": parkraum,
        "parkhaeuser": haeuser[:15],
        "parkhaeuser_im_radius": len(haeuser), "stellplaetze_im_radius": sum(h["gesamt"] or 0 for h in haeuser if isinstance(h["gesamt"], (int, float))),
        "fussgaengerzonen": [], "begegnungszonen": [],
        "geschaeftsstrasse": {"am_punkt": None, "naechste": None, "im_radius": 0, "ohne_dienst": True},
        "realnutzung": None, "gebaeude": [], "hinweise": LAGE_HINWEISE,
    }
    return SourceResult(
        name="lage", ok=True, data=data, duration_ms=int((time.perf_counter() - started) * 1000), warnings=fehler,
        provenance=Provenance(source="Parkhäuser (Live-Belegung) und Parkraumbewirtschaftung Hamburg (Urban Data Platform, OGC API)",
                              license=LIZENZ, endpoint=f"{OAF_BASE}/parkhaeuser", retrieved_at=now_iso()),
    )
