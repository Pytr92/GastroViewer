"""Stadt Salzburg — WFS ``data.stadt-salzburg.at/geodaten/wfs`` (GeoServer).

Nach Wien die zweite österreichische Stadt mit offenen, punktgenauen
Diensten. Live belegt am 18.09.2026 (fixtures/at, Runden 5–7):

* ``ogdsbg:flaechenwidmung`` — **nur der Mappenblatt-Umring** mit Link
  zum Plan-PDF (``MAPPENBLATTNUMMER``, ``PLANURL``); die Widmung selbst
  steht nur im PDF. Der Baurecht-Block sagt das ehrlich: Stufe
  ``kein_plan`` mit Planlink statt einer erfundenen Gebietsart.
* ``ogdsbg:bebauungsplan_rechtswirksam`` — Umgriffe mit ``TITEL``,
  ``NUMMER``, ``TYP`` (Grundstufe/Aufbaustufe), ``WIRKSAM_AB``,
  ``PLANURL``. Punkt-in-Fläche → Pläne am Punkt.
* ``ogdsbg:altstadtschutzzone`` — Zonen I/II nach dem Salzburger
  Altstadterhaltungsgesetz (``ZONE_NUMMER``); im Planungsblock als
  Gegenstück zur Erhaltungssatzung/Wiener Schutzzone.
* ``ogdsbg:kurzparkzone`` — ``NAME``, ``ART``, ``MAXIMALE_PARKDAUER``,
  ``GEBUEHRENPFLICHT``, ``GILT_VON``; Punkt-in-Fläche für den Lage-Block.
* ``ogdsbg:markt`` — 15 Märkte stadtweit mit ``KATEGORIE``,
  ``OEFFNUNGSZEITEN``, ``ADRESSE``, ``ANGEBOT``, ``HOMEPAGE``.
* ``ogdsbg:baustelle_aktuell`` — Punkte und Linien mit ``MASSNAHME``,
  ``BEHINDERUNG``, ``BEGINN``/``ENDE`` (dd.mm.yyyy), ``KATEGORIE``
  (aktuell/geplant), ``BAUBEREICH``, ``STATUS``.
"""

from __future__ import annotations

import math
import re
import time
from datetime import date
from typing import Any

from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, bearing_label, haversine_m, now_iso
from .wien import _enthaelt, _linie, _punkt

WFS_URL = "https://data.stadt-salzburg.at/geodaten/wfs"
LIZENZ = "Creative Commons Namensnennung 4.0 (CC BY 4.0) · Datenquelle: Stadt Salzburg – data.stadt-salzburg.at"
PORTAL = "https://data.stadt-salzburg.at/"
# Stadtgebiet grob (Süd, West, Nord, Ost).
STADT_BBOX = (47.745, 12.975, 47.865, 13.135)
PUNKT_BOX = 0.0005
MAX_MARKT_DISTANZ_M = 2000
MAX_LISTE = 40


def in_salzburg(lat: float, lon: float) -> bool:
    s, w, n, o = STADT_BBOX
    return s <= lat <= n and w <= lon <= o


def _bbox_um(lat: float, lon: float, radius_m: float) -> str:
    rand = radius_m + 250
    dlat = rand / 111_320.0
    dlon = rand / (111_320.0 * max(0.2, math.cos(math.radians(lat))))
    return f"{lon - dlon:.6f},{lat - dlat:.6f},{lon + dlon:.6f},{lat + dlat:.6f},EPSG:4326"


def _punkt_box(lat: float, lon: float) -> str:
    return (f"{lon - PUNKT_BOX:.6f},{lat - PUNKT_BOX:.6f},"
            f"{lon + PUNKT_BOX:.6f},{lat + PUNKT_BOX:.6f},EPSG:4326")


async def _features(out: Outbound, quelle: str, typ: str, bbox: str | None = None,
                    max_features: int | None = None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "service": "WFS", "request": "GetFeature", "version": "1.1.0",
        "typeName": f"ogdsbg:{typ}", "srsName": "EPSG:4326", "outputFormat": "application/json",
    }
    if bbox:
        params["bbox"] = bbox
    if max_features:
        params["maxFeatures"] = max_features
    payload = await out.get_json(quelle, WFS_URL, params=params, timeout=45.0,
                                 limiter="salzburg", min_interval=0.5)
    return payload.get("features") or [] if isinstance(payload, dict) else []


def _datum(v: Any) -> date | None:
    """``28.02.2027`` oder ISO — beides kommt vor."""
    if not v:
        return None
    s = str(v).strip()
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", s)
    if m:
        return date(int(m[3]), int(m[2]), int(m[1]))
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _iso(v: Any) -> str | None:
    d = _datum(v)
    return d.isoformat() if d else None


# ------------------------------------------------------------ Baurecht

def widmung_aufbereiten(widmung: list[dict[str, Any]], bplaene: list[dict[str, Any]],
                        lat: float, lon: float) -> dict[str, Any]:
    blaetter = [f.get("properties") or {} for f in widmung if _enthaelt(f, lat, lon)]
    plaene = []
    for f in bplaene:
        if not _enthaelt(f, lat, lon):
            continue
        p = f.get("properties") or {}
        plaene.append({
            "plan": p.get("TITEL"), "art": f"Bebauungsplan ({p.get('TYP') or 'Stufe unbekannt'})",
            "rechtsstand": "rechtswirksam", "bereich": None, "bezirk": None,
            "festgesetzt_am": _iso(p.get("WIRKSAM_AB")), "inhalt_planweit": p.get("NUMMER"),
            "pdf": p.get("PLANURL") or None,
        })
    plaene.sort(key=lambda p: (0 if "Aufbau" in (p["art"] or "") else 1, p["festgesetzt_am"] or ""), reverse=False)
    return {"blaetter": blaetter, "plaene": plaene}


async def baurecht_load(out: Outbound, lat: float, lon: float) -> SourceResult:
    """Baurecht-Block für Salzburg in der Blockform von ``baurecht.py``:
    Bebauungspläne am Punkt mit PDF, Flächenwidmung nur als Planblatt."""
    from .baurecht import HINWEISE as BAURECHT_HINWEISE

    started = time.perf_counter()
    daten: dict[str, Any] = {
        "stufe": None, "gebiet": "Salzburg", "baugebiete": [], "plaene": [],
        "sanierungsgebiete": [], "denkmale": [], "paragraf_34": False,
        "hinweise": BAURECHT_HINWEISE[:1] + [
            "Die Stadt Salzburg gibt die **Flächenwidmung nur als Planblatt (PDF)** frei — die "
            "Widmungsart am Punkt steht dort, nicht in den offenen Daten. Rechtswirksame "
            "Bebauungspläne (Grund-/Aufbaustufe) liegen dagegen als Umgriff mit Plan-PDF vor.",
            "**Sperrstunde** und Gastgarten-Genehmigung sind Landes- und Gemeinderecht (Salzburger "
            "Sperrzeitenverordnung, Gebrauchsabgabe) — nicht in offenen Daten."],
    }
    fehler: list[str] = []
    try:
        widmung = await _features(out, "salzburg_baurecht", "flaechenwidmung", _punkt_box(lat, lon), 10)
    except SourceError as err:
        widmung, fehler = [], fehler + [f"Flächenwidmung: {err.message}"]
    try:
        bplaene = await _features(out, "salzburg_baurecht", "bebauungsplan_rechtswirksam", _punkt_box(lat, lon), 20)
    except SourceError as err:
        bplaene, fehler = [], fehler + [f"Bebauungsplan: {err.message}"]
    if len(fehler) == 2:
        return SourceResult.failed("baurecht", SourceError("api_error", "WFS der Stadt Salzburg: " + fehler[0]),
                                   int((time.perf_counter() - started) * 1000))
    erg = widmung_aufbereiten(widmung, bplaene, lat, lon)
    daten["plaene"] = erg["plaene"]
    daten["planblatt"] = ({"nummer": erg["blaetter"][0].get("MAPPENBLATTNUMMER"),
                           "pdf": erg["blaetter"][0].get("PLANURL")} if erg["blaetter"] else None)
    warnungen = list(fehler)
    if daten["plaene"]:
        daten["stufe"] = "plan"
    else:
        daten["stufe"] = "kein_plan"
        warnungen.append("Am Punkt liegt kein rechtswirksamer Bebauungsplan — die Widmung steht im "
                         "Flächenwidmungs-Planblatt (PDF-Link im Block).")
    return SourceResult(
        name="baurecht", ok=True, data=daten,
        duration_ms=int((time.perf_counter() - started) * 1000), warnings=warnungen,
        provenance=Provenance(
            source="Bebauungspläne (rechtswirksam) und Flächenwidmungs-Planblätter der Stadt Salzburg (WFS)",
            license=LIZENZ, endpoint=WFS_URL, stand="laufend fortgeschrieben", retrieved_at=now_iso(),
            note="Punktabfrage über WFS mit Punkt-in-Fläche-Prüfung; Widmungsart nur im Plan-PDF."),
    )


# ---------------------------------------------------------- Planung

async def altstadtschutzzone(out: Outbound, lat: float, lon: float) -> dict[str, Any]:
    """Teilblock ``erhaltungssatzung`` des Planungsblocks (Form wie Wiener
    Schutzzone / Erhaltungssatzung)."""
    features = await _features(out, "salzburg_planung", "altstadtschutzzone", _punkt_box(lat, lon), 10)
    gebiete = []
    for f in features:
        if not _enthaelt(f, lat, lon):
            continue
        p = f.get("properties") or {}
        zone = p.get("ZONE_NUMMER")
        gebiete.append({
            "name": f"Altstadtschutzzone {'I' if zone == 1 else 'II' if zone == 2 else zone or '?'}",
            "gueltig_ab": None, "plan_pdf": None, "text_pdf": None,
            "info_pdf": "https://www.stadt-salzburg.at/altstadterhaltung/",
            "rohwerte": {k: v for k, v in p.items() if v not in (None, "")},
        })
    return {"betroffen": bool(gebiete), "gebiete": gebiete,
            "titel": "Altstadtschutzzone (Salzburger Altstadterhaltungsgesetz)"}


# ------------------------------------------------------------ Märkte

def maerkte_aufbereiten(features: list[dict[str, Any]], lat: float, lon: float, radius: int) -> dict[str, Any]:
    maerkte: list[dict[str, Any]] = []
    for f in features:
        pkt = _punkt(f)
        if pkt is None:
            continue
        p = f.get("properties") or {}
        dist = haversine_m(lat, lon, *pkt)
        zeiten = re.sub(r"\s*[\r\n]+\s*", " · ", str(p.get("OEFFNUNGSZEITEN") or "")).strip() or None
        maerkte.append({
            "name": (p.get("NAME") or "(ohne Namen)").strip(),
            "rubrik": p.get("KATEGORIE") or "Markt",
            "oeffnungszeiten": zeiten,
            "adresse": p.get("ADRESSE") or p.get("BEMERKUNG") or None,
            "angebot": p.get("ANGEBOT") or None,
            "link": p.get("HOMEPAGE") or None,
            "lat": pkt[0], "lon": pkt[1],
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
        "stadtweit": len(maerkte), "in_reichweite": nah,
        "im_radius": sum(1 for m in maerkte if m["im_radius"]),
        "naechster": nah[0] if nah else None,
        "nach_rubrik": nach_rubrik, "max_distanz_m": MAX_MARKT_DISTANZ_M,
        "rohdaten": f"{WFS_URL}?service=WFS&request=GetCapabilities",
        "stadt": "Salzburg",
    }


MARKT_HINWEISE = [
    "Salzburg führt Ganzjahres-, Saison- und Adventmärkte in einem Datensatz — die "
    "**Öffnungszeiten** stammen aus dem Datensatz und sind teils Jahre alt (Adventmärkte 2019); "
    "Markttage vor Ort prüfen.",
    "Der Schrannenmarkt (Donnerstag) und der Grünmarkt (täglich) bringen Frequenz in die Altstadt; "
    "Adventmärkte nur in der Saison.",
]


async def maerkte_load(out: Outbound, lat: float, lon: float, radius: int) -> SourceResult:
    started = time.perf_counter()
    try:
        features = await _features(out, "salzburg_maerkte", "markt", None, 100)
    except SourceError as err:
        return SourceResult.failed("maerkte", err, int((time.perf_counter() - started) * 1000))
    data = maerkte_aufbereiten(features, lat, lon, radius)
    data["hinweise"] = MARKT_HINWEISE
    warnungen = [] if data["in_reichweite"] else [f"Kein städtischer Markt innerhalb von {MAX_MARKT_DISTANZ_M} m."]
    return SourceResult(
        name="maerkte", ok=True, data=data,
        duration_ms=int((time.perf_counter() - started) * 1000), warnings=warnungen,
        provenance=Provenance(
            source="Märkte der Stadt Salzburg (WFS data.stadt-salzburg.at)", license=LIZENZ,
            endpoint=WFS_URL, stand="Datensatz der Stadt, Öffnungszeiten teils 2019", retrieved_at=now_iso(),
            note="Stadtweite Liste, lokal nach Entfernung sortiert."),
    )


# --------------------------------------------------------- Baustellen

_GEHWEG = re.compile(r"gehsteig|gehweg|fußgänger|fussgänger|gehbereich", re.I)


def baustellen_aufbereiten(features: list[dict[str, Any]], lat: float, lon: float,
                           radius: int, heute: date) -> dict[str, Any]:
    eintraege: list[dict[str, Any]] = []
    gesehen: set[Any] = set()
    for f in features:
        p = f.get("properties") or {}
        pkt = _punkt(f)
        linie = _linie(f) if pkt is None else []
        if pkt is None and not linie:
            continue
        ende = _datum(p.get("ENDE") or p.get("VORAUSSICHTL_DAUER_BIS"))
        if ende is not None and ende < heute:
            continue
        if pkt is not None:
            dist, naechst = haversine_m(lat, lon, *pkt), pkt
        else:
            dist, naechst = min((haversine_m(lat, lon, *q), q) for q in linie)
        if dist > radius:
            continue
        # Punkt- und Linienobjekt derselben Baustelle: das nähere zählt.
        kennung = p.get("NUMMER") or p.get("AKTENZAHL") or p.get("ID")
        if kennung in gesehen:
            continue
        gesehen.add(kennung)
        beginn = _datum(p.get("BEGINN"))
        text = re.sub(r"\s+", " ", str(p.get("MASSNAHME") or "")).strip() or None
        behinderung = re.sub(r"\s+", " ", str(p.get("BEHINDERUNG") or "")).strip() or None
        status = "geplant" if (p.get("KATEGORIE") == "geplant" or (beginn is not None and beginn > heute)) else "laufend"
        eintraege.append({
            "ort": p.get("BAUSTELLENEINRICHTUNG") or p.get("BAUBEREICH") or "(ohne Ortsangabe)",
            "art": p.get("GRABUNGSART") or "Baustelle",
            "status": status,
            "beginn": _iso(p.get("BEGINN")), "ende": _iso(p.get("ENDE") or p.get("VORAUSSICHTL_DAUER_BIS")),
            "distanz_m": round(dist),
            "richtung": bearing_label(lat, lon, *naechst) if dist > 0 else None,
            "gehweg_betroffen": bool((text or behinderung) and _GEHWEG.search((text or "") + " " + (behinderung or ""))),
            "mit_sperrung": "sperr" in ((behinderung or "") + (text or "")).lower(),
            "beeintraechtigung": behinderung,
            "betroffene_bereiche": p.get("BAUBEREICH") or None,
            "beschreibung": (text[:237] + "…" if text and len(text) > 240 else text),
            "link": p.get("LINK_WEITERE_INFO") or None,
            "antragsteller": p.get("AKT_KOMMENTAR") or p.get("ZUSTAENDIGE_ORGEINHEIT"),
            "lat": naechst[0], "lon": naechst[1],
            "umriss": None,
            "linie": [[q[0], q[1]] for q in linie] or None,
        })
    eintraege.sort(key=lambda e: (0 if e["status"] == "laufend" else 1, e["distanz_m"]))
    gesamt = len(eintraege)
    return {
        "gesamt": gesamt, "baumassnahmen": gesamt, "haltverbote": 0,
        "laufend": sum(1 for e in eintraege if e["status"] == "laufend"),
        "geplant": sum(1 for e in eintraege if e["status"] == "geplant"),
        "gehweg_betroffen": sum(1 for e in eintraege if e["gehweg_betroffen"]),
        "liste": eintraege[:MAX_LISTE], "gekappt": gesamt > MAX_LISTE,
        "radius_m": radius, "stichtag": heute.isoformat(),
        "rohdaten": f"{WFS_URL}?service=WFS&request=GetCapabilities",
        "stadt": "Salzburg",
    }


BAUSTELLEN_HINWEISE = [
    "Die Stadt Salzburg führt **aktuelle und angekündigte Grabungen und Baustellen** mit "
    "Behinderung und voraussichtlichem Ende; dieselbe Maßnahme kann als Punkt und Linie "
    "vorliegen — hier zählt sie einmal.",
    "Entfernung zum nächsten Stützpunkt der Baustelle; Linienbaustellen liegen als Trasse vor.",
]


async def baustellen_load(out: Outbound, lat: float, lon: float, radius: int,
                          heute: date | None = None) -> SourceResult:
    started = time.perf_counter()
    try:
        features = await _features(out, "salzburg_baustellen", "baustelle_aktuell", _bbox_um(lat, lon, radius), 200)
    except SourceError as err:
        return SourceResult.failed("baustellen", err, int((time.perf_counter() - started) * 1000))
    data = baustellen_aufbereiten(features, lat, lon, radius, heute or date.today())
    data["hinweise"] = BAUSTELLEN_HINWEISE
    warnungen = []
    if data["gekappt"]:
        warnungen.append(f"{data['gesamt']} Baustellen im Radius — die Liste zeigt die "
                         f"{MAX_LISTE} nächsten, die Zählwerte umfassen alle.")
    return SourceResult(
        name="baustellen", ok=True, data=data,
        duration_ms=int((time.perf_counter() - started) * 1000), warnings=warnungen,
        provenance=Provenance(
            source="Baustellen und Grabungen der Stadt Salzburg (Verkehrs- und Straßenrechtsamt, WFS)",
            license=LIZENZ, endpoint=WFS_URL, stand="laufend gepflegt", retrieved_at=now_iso(),
            note="Punkt- und Linienbaustellen mit Maßnahme, Behinderung und Zeitraum. Nur Stadtgebiet."),
    )


# --------------------------------------------------------------- Lage

LAGE_HINWEISE = [
    "Für Salzburg liegen offen die **Kurzparkzonen** vor (Gruppe, Höchstparkdauer, Gebührenpflicht); "
    "Fußgängerzonen, Geschäftsstraßen und Realnutzung gibt die Stadt nicht als Dienst frei — "
    "diese Zeilen bleiben leer.",
]


async def lage_load(out: Outbound, lat: float, lon: float, radius: int) -> SourceResult:
    started = time.perf_counter()
    try:
        kpz = [f for f in await _features(out, "salzburg_lage", "kurzparkzone", _punkt_box(lat, lon), 5)
               if _enthaelt(f, lat, lon)]
    except SourceError as err:
        return SourceResult.failed("lage", err, int((time.perf_counter() - started) * 1000))
    p = (kpz[0].get("properties") or {}) if kpz else {}
    data = {
        "stadt": "Salzburg",
        "kurzparkzone": ({"zeitraum": p.get("GEBUEHRENPFLICHT"), "dauer": p.get("MAXIMALE_PARKDAUER"),
                          "bezirk": p.get("NAME"), "art": p.get("ART"), "gruppe": p.get("GRUPPE"),
                          "gueltig_von": _iso(p.get("GILT_VON"))} if kpz else None),
        "fussgaengerzonen": [], "begegnungszonen": [],
        "geschaeftsstrasse": {"am_punkt": None, "naechste": None, "im_radius": 0, "ohne_dienst": True},
        "realnutzung": None, "gebaeude": [],
        "hinweise": LAGE_HINWEISE,
    }
    return SourceResult(
        name="lage", ok=True, data=data, duration_ms=int((time.perf_counter() - started) * 1000),
        provenance=Provenance(
            source="Kurzparkzonen der Stadt Salzburg (WFS data.stadt-salzburg.at)", license=LIZENZ,
            endpoint=WFS_URL, stand="laufend gepflegt", retrieved_at=now_iso(),
            note="Punkt-in-Fläche-Abfrage; weitere Lage-Layer gibt Salzburg nicht frei."),
    )


__all__ = ["WFS_URL", "LIZENZ", "in_salzburg", "baurecht_load", "altstadtschutzzone", "maerkte_load",
           "baustellen_load", "lage_load", "widmung_aufbereiten", "maerkte_aufbereiten", "baustellen_aufbereiten"]
