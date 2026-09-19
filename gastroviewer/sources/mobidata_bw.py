"""Baden-Württemberg: MobiData BW (Landes-Mobilitätsdatenplattform) und
Stadt Stuttgart.

Live belegt am 18.09.2026 (fixtures/de, Runden 6 und 7):

* **Baustellen** ``roadworks_geojson.json`` (1,2 MB, landesweit, alle
  Straßenklassen): LineStrings mit ``type`` (CONSTRUCTION / ROAD_CLOSED),
  ``subtype``, ``description``, ``street``, ``direction``, ``starttime``,
  ``endtime``. Einmal geladen, lokal nach Entfernung gefiltert.
* **Stuttgart** Baustellen-WFS (GeoServer ``geoserver.stuttgart.de``),
  Layer ``A66_BAUM_BAUSTELLEN_DATE_WEB_im_Bau_EPSG25832``, Punkte mit
  ``STRASSENNAME``, ``DETAILS_STANDORT``, ``ART_ARBEIT``, ``ANFANG``/``ENDE``
  (dd.mm.yyyy), ``VERKEHRSAUSWIRKUNG``, ``STATUS`` — feiner als MobiData.
* **Straßenverkehrszählung 2024** ``SVZ-Zaehlstellen_…_augmented_SVZ2024.csv``
  (660 KB, ~5 000 Zählstellen A/B/L/K): ``svznr, zstart (TM/MZ/DZ),
  klasse, nummer, gpsx1, gpsy1, RI, RII, DTV2024, DTVSV``. Dichter als BASt
  (auch Landes- und Kreisstraßen) — Blockform von ``bast.aufbereiten``.
* **Eco-Counter Radzähler** ``fahrradzaehler_tageswerten.csv`` (230 KB,
  laufende Woche je Zählstelle): ``counter_site, counter_site_id,
  longitude, latitude, iso_timestamp, channels_in/out/all``. Blockform des
  Radzählungs-Blocks (Hamburg-Variante ohne Jahresgang).
* **Ladesäulen** WFS ``MobiData-BW:charge_points`` (GeoServer, WFS 1.0.0,
  bbox EPSG:4326): ``operator_name, address, max_electric_power,
  chargepoint_static_count, chargepoint_available_count, last_updated``.
"""

from __future__ import annotations

import csv
import io
import math
import re
import time
from datetime import date, datetime
from typing import Any, Awaitable, Callable

from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, bearing_label, haversine_m, now_iso

ROADWORKS_URL = "https://api.mobidata-bw.de/datasets/traffic/roadworks/roadworks_geojson.json"
SVZ_URL = "https://mobidata-bw.de/vm/Karte_Strassenverkehrszaehlung_BW/SVZ-Zaehlstellen_2026-06-26_augmented_SVZ2024.csv"
ECO_URL = "https://mobidata-bw.de/daten/eco-counter/v2/fahrradzaehler_tageswerten.csv"
WFS_URL = "https://api.mobidata-bw.de/geoserver/MobiData-BW/ows"
STUTTGART_WFS_URL = "https://geoserver.stuttgart.de/gdc/Verkehr_Mobilitaet/ows"
STUTTGART_TYP = "Verkehr_Mobilitaet:A66_BAUM_BAUSTELLEN_DATE_WEB_im_Bau_EPSG25832"
PORTAL = "https://www.mobidata-bw.de/"
LIZENZ = "Datenlizenz Deutschland – Namensnennung – Version 2.0 (dl-de/by-2-0) · MobiData BW / NVBW"
STUTTGART_LIZENZ = "Datenlizenz Deutschland – Namensnennung – Version 2.0 (dl-de/by-2-0) · Landeshauptstadt Stuttgart"
SVZ_JAHR = 2024
MAX_DISTANZ_M = 3000   # klassifiziertes Netz, in Innenstädten weiter weg
MAX_RAD_DISTANZ_M = 3000
MAX_LISTE = 40

# Baden-Württemberg grob; die Entscheidung trifft das Bundesland aus der
# Adresse (``DE-BW``), der Kasten spart nur Netzaufrufe.
BW_BBOX = (47.52, 7.50, 49.80, 10.50)
STUTTGART_BBOX = (48.68, 9.04, 48.87, 9.32)


def in_bw(lat: float, lon: float) -> bool:
    return BW_BBOX[0] <= lat <= BW_BBOX[2] and BW_BBOX[1] <= lon <= BW_BBOX[3]


def in_stuttgart(lat: float, lon: float) -> bool:
    return STUTTGART_BBOX[0] <= lat <= STUTTGART_BBOX[2] and STUTTGART_BBOX[1] <= lon <= STUTTGART_BBOX[3]


def _bbox_um(lat: float, lon: float, radius_m: float) -> str:
    rand = radius_m + 250
    dlat = rand / 111_320.0
    dlon = rand / (111_320.0 * max(0.2, math.cos(math.radians(lat))))
    return f"{lon - dlon:.6f},{lat - dlat:.6f},{lon + dlon:.6f},{lat + dlat:.6f},EPSG:4326"


def _zahl(v: Any) -> float | None:
    try:
        t = str(v).strip()
        return float(t) if t not in ("", "na", "NA", "-") else None
    except (TypeError, ValueError):
        return None


def _punkte(geom: dict[str, Any] | None) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []

    def tief(c: Any) -> None:
        if isinstance(c, (list, tuple)) and len(c) >= 2 and all(isinstance(x, (int, float)) for x in c[:2]):
            out.append((float(c[1]), float(c[0])))
        elif isinstance(c, (list, tuple)):
            for x in c:
                tief(x)

    tief((geom or {}).get("coordinates"))
    return out


# ------------------------------------------------------- Baustellen (BW)

TYP_TEXT = {"CONSTRUCTION": "Baustelle", "ROAD_CLOSED": "Sperrung", "ROAD_CLOSED_CONSTRUCTION": "Sperrung wegen Bauarbeiten",
            "ROAD_CLOSED_HAZARD": "Sperrung (Gefahr)", "ROAD_CLOSED_EVENT": "Sperrung (Veranstaltung)"}
RICHTUNG = {"BOTH_DIRECTIONS": "beide Richtungen", "ONE_DIRECTION": "eine Richtung"}


def _iso_datum(v: Any) -> date | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def roadworks_aufbereiten(features: list[dict[str, Any]], lat: float, lon: float, radius: int,
                          heute: date) -> dict[str, Any]:
    eintraege: list[dict[str, Any]] = []
    for f in features:
        p = f.get("properties") or {}
        punkte = _punkte(f.get("geometry"))
        if not punkte:
            continue
        ende = _iso_datum(p.get("endtime"))
        if ende is not None and ende < heute:
            continue
        # Grobfilter vor der Haversine: 0,05° ≈ 5 km
        if all(abs(a - lat) > 0.05 or abs(b - lon) > 0.08 for a, b in punkte):
            continue
        dist, naechst = min((haversine_m(lat, lon, a, b), (a, b)) for a, b in punkte)
        if dist > radius:
            continue
        beginn = _iso_datum(p.get("starttime"))
        text = re.sub(r"\s+", " ", str(p.get("description") or "")).strip() or None
        typ = TYP_TEXT.get(p.get("subtype") or "", None) or TYP_TEXT.get(p.get("type") or "", p.get("type") or "Baustelle")
        eintraege.append({
            "ort": p.get("street") or "(ohne Ortsangabe)",
            "art": typ, "status": "geplant" if beginn is not None and beginn > heute else "laufend",
            "beginn": str(p.get("starttime") or "")[:10] or None, "ende": str(p.get("endtime") or "")[:10] or None,
            "distanz_m": round(dist), "richtung": bearing_label(lat, lon, *naechst) if dist > 0 else None,
            "gehweg_betroffen": bool(text and re.search(r"gehweg|fußgänger|fussgänger", text, re.I)),
            "mit_sperrung": (p.get("type") == "ROAD_CLOSED") or "sperr" in (text or "").lower(),
            "beeintraechtigung": (RICHTUNG.get(p.get("direction") or "", p.get("direction")) or None),
            "betroffene_bereiche": None,
            "beschreibung": (text[:237] + "…" if text and len(text) > 240 else text),
            "link": None, "antragsteller": p.get("reference"),
            "lat": naechst[0], "lon": naechst[1], "umriss": None,
            "linie": [[a, b] for a, b in punkte[:200]],
        })
    eintraege.sort(key=lambda e: (0 if e["status"] == "laufend" else 1, e["distanz_m"]))
    gesamt = len(eintraege)
    return {
        "gesamt": gesamt, "baumassnahmen": sum(1 for e in eintraege if not e["mit_sperrung"] or e["art"] != "Sperrung"),
        "haltverbote": 0,
        "laufend": sum(1 for e in eintraege if e["status"] == "laufend"),
        "geplant": sum(1 for e in eintraege if e["status"] == "geplant"),
        "gehweg_betroffen": sum(1 for e in eintraege if e["gehweg_betroffen"]),
        "liste": eintraege[:MAX_LISTE], "gekappt": gesamt > MAX_LISTE,
        "radius_m": radius, "stichtag": heute.isoformat(), "rohdaten": ROADWORKS_URL, "stadt": "Baden-Württemberg",
    }


ROADWORKS_HINWEISE = [
    "MobiData BW führt **Baustellen und Sperrungen auf klassifizierten Straßen** landesweit "
    "(Bundes-, Landes-, Kreisstraßen, größere Stadtstraßen) — innerstädtische Kleinbaustellen "
    "fehlen, außer in Stuttgart (eigener Dienst).",
    "Entfernung zum nächsten Stützpunkt der Baustellentrasse; Beginn und Ende laut Meldung.",
]


async def roadworks_load(out: Outbound, lat: float, lon: float, radius: int,
                         features_laden: Callable[[], Awaitable[list[dict[str, Any]]]],
                         heute: date | None = None) -> SourceResult:
    started = time.perf_counter()
    try:
        features = await features_laden()
    except SourceError as err:
        return SourceResult.failed("baustellen", err, int((time.perf_counter() - started) * 1000))
    data = roadworks_aufbereiten(features, lat, lon, radius, heute or date.today())
    data["hinweise"] = ROADWORKS_HINWEISE
    warnungen = [] if data["gesamt"] else ["Keine gemeldete Baustelle oder Sperrung im Umkreis (MobiData BW)."]
    if data["gekappt"]:
        warnungen.append(f"{data['gesamt']} Maßnahmen im Radius — die Liste zeigt die {MAX_LISTE} nächsten.")
    return SourceResult(
        name="baustellen", ok=True, data=data,
        duration_ms=int((time.perf_counter() - started) * 1000), warnings=warnungen,
        provenance=Provenance(source="Baustellen und Sperrungen Baden-Württemberg (MobiData BW, GeoJSON)",
                              license=LIZENZ, endpoint=ROADWORKS_URL, stand="laufend gepflegt", retrieved_at=now_iso(),
                              note="Landesdatei einmal geladen, lokal nach Entfernung gefiltert."),
    )


# -------------------------------------------------- Baustellen Stuttgart

def _datum_de(v: Any) -> date | None:
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", str(v or ""))
    return date(int(m[3]), int(m[2]), int(m[1])) if m else None


def stuttgart_aufbereiten(features: list[dict[str, Any]], lat: float, lon: float, radius: int,
                          heute: date) -> dict[str, Any]:
    eintraege: list[dict[str, Any]] = []
    for f in features:
        p = f.get("properties") or {}
        punkte = _punkte(f.get("geometry"))
        if not punkte:
            continue
        ende = _datum_de(p.get("ENDE"))
        if ende is not None and ende < heute:
            continue
        dist, naechst = min((haversine_m(lat, lon, a, b), (a, b)) for a, b in punkte)
        if dist > radius:
            continue
        beginn = _datum_de(p.get("ANFANG"))
        wirkung = re.sub(r"\s+", " ", str(p.get("VERKEHRSAUSWIRKUNG") or "")).strip() or None
        eintraege.append({
            "ort": " ".join(x for x in (p.get("STRASSENNAME"), p.get("DETAILS_STANDORT")) if x) or "(ohne Ortsangabe)",
            "art": p.get("ART_ARBEIT") or "Baustelle",
            "status": "geplant" if (beginn is not None and beginn > heute) or (p.get("STATUS") or "").lower().startswith("geplant") else "laufend",
            "beginn": beginn.isoformat() if beginn else None, "ende": ende.isoformat() if ende else None,
            "distanz_m": round(dist), "richtung": bearing_label(lat, lon, *naechst) if dist > 0 else None,
            "gehweg_betroffen": bool(re.search(r"gehweg|fußgänger", (wirkung or "") + " " + str(p.get("ART_ARBEIT") or ""), re.I)),
            "mit_sperrung": "sperr" in (wirkung or "").lower(),
            "beeintraechtigung": wirkung, "betroffene_bereiche": p.get("ZEITL_REGELUNG") or None,
            "beschreibung": None, "link": None, "antragsteller": None,
            "lat": naechst[0], "lon": naechst[1], "umriss": None, "linie": None,
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
        "rohdaten": f"{STUTTGART_WFS_URL}?service=WFS&request=GetCapabilities", "stadt": "Stuttgart",
    }


STUTTGART_HINWEISE = [
    "Die Landeshauptstadt Stuttgart meldet **Baustellen im Bau** mit Art der Arbeit, Zeitraum und "
    "Verkehrsauswirkung (Tiefbauamt) — Punktlage je Maßnahme.",
]


async def stuttgart_baustellen_load(out: Outbound, lat: float, lon: float, radius: int,
                                    heute: date | None = None) -> SourceResult:
    started = time.perf_counter()
    params = {"service": "WFS", "version": "1.0.0", "request": "GetFeature", "typeName": STUTTGART_TYP,
              "srsName": "EPSG:4326", "outputFormat": "application/json", "maxFeatures": 200,
              "bbox": _bbox_um(lat, lon, radius)}
    try:
        payload = await out.get_json("stuttgart_baustellen", STUTTGART_WFS_URL, params=params, timeout=45.0,
                                     limiter="stuttgart", min_interval=0.5)
    except SourceError as err:
        return SourceResult.failed("baustellen", err, int((time.perf_counter() - started) * 1000))
    features = payload.get("features") or [] if isinstance(payload, dict) else []
    data = stuttgart_aufbereiten(features, lat, lon, radius, heute or date.today())
    data["hinweise"] = STUTTGART_HINWEISE
    warnungen = [] if data["gesamt"] else ["Keine Baustelle im Bau im Umkreis (Stadt Stuttgart)."]
    return SourceResult(
        name="baustellen", ok=True, data=data,
        duration_ms=int((time.perf_counter() - started) * 1000), warnings=warnungen,
        provenance=Provenance(source="Baustellen im Bau, Landeshauptstadt Stuttgart (GeoServer WFS)",
                              license=STUTTGART_LIZENZ, endpoint=STUTTGART_WFS_URL, stand="laufend gepflegt",
                              retrieved_at=now_iso(), note="Punktabfrage über bbox; nur Stadtgebiet Stuttgart."),
    )


# ------------------------------------------- Straßenverkehrszählung (SVZ)

ZAEHLART = {"DZ": "Dauerzählstelle", "TM": "Temporäre Zählung (Modell)", "MZ": "Manuelle Zählung"}


def svz_parsen(csv_text: str) -> list[dict[str, Any]]:
    stellen = []
    for r in csv.DictReader(io.StringIO(csv_text)):
        lat, lon = _zahl(r.get("gpsy1")), _zahl(r.get("gpsx1"))
        if lat is None or lon is None:
            continue
        stellen.append({
            "nr": r.get("svznr"), "art": (r.get("zstart") or "").strip(), "klasse": (r.get("klasse") or "").strip(),
            "strasse": f"{(r.get('klasse') or '').strip()} {(r.get('nummer') or '').strip()}".strip(),
            "von": r.get("RI"), "nach": r.get("RII"), "lat": lat, "lon": lon,
            "dtv_kfz": _zahl(r.get(f"DTV{SVZ_JAHR}")), "dtv_schwerverkehr": _zahl(r.get("DTVSV")),
        })
    return stellen


def svz_aufbereiten(stellen: list[dict[str, Any]], lat: float, lon: float, radius: int) -> dict[str, Any]:
    treffer = []
    for s in stellen:
        if abs(s["lat"] - lat) > 0.03 or abs(s["lon"] - lon) > 0.05:
            continue
        dist = haversine_m(lat, lon, s["lat"], s["lon"])
        if dist > MAX_DISTANZ_M:
            continue
        kfz, sv = s["dtv_kfz"], s["dtv_schwerverkehr"]
        kfz = int(kfz) if kfz is not None else None
        sv = int(sv) if sv is not None else None
        treffer.append({
            "strasse": s["strasse"],
            "zaehlstelle": f"{s['nr']} · {s['von']} – {s['nach']}",
            "zaehlart": ZAEHLART.get(s["art"], s["art"]),
            "lat": s["lat"], "lon": s["lon"], "distanz_m": round(dist),
            "richtung": bearing_label(lat, lon, s["lat"], s["lon"]), "im_radius": dist <= radius,
            "dtv_kfz": kfz, "dtv_leichtverkehr": (kfz - sv if kfz is not None and sv is not None else None),
            "dtv_schwerverkehr": sv,
            "schwerverkehr_anteil": (round(sv / kfz * 100, 1) if kfz and sv is not None and kfz > 0 else None),
        })
    treffer.sort(key=lambda s: s["distanz_m"])
    treffer = treffer[:12]
    mit_wert = [s for s in treffer if s["dtv_kfz"] is not None]
    return {
        "zaehlstellen": treffer, "naechste": treffer[0] if treffer else None,
        "staerkste": max(mit_wert, key=lambda s: s["dtv_kfz"]) if mit_wert else None,
        "im_radius": [s for s in treffer if s["im_radius"]], "max_distanz_m": MAX_DISTANZ_M,
        "jahr": SVZ_JAHR, "dienst": "svz_bw", "portal": "https://www.mobidata-bw.de/dataset/strassenverkehrszahlung",
        "portal_titel": "Straßenverkehrszählung Baden-Württemberg (MobiData BW)",
        "netz_hinweis": ("Gezählt wird das klassifizierte Netz Baden-Württembergs (Autobahnen, Bundes-, "
                         "Landes- und Kreisstraßen; Dauer-, temporäre und manuelle Zählstellen). "
                         "Gemeindestraßen fehlen. "),
        "stadt": "Baden-Württemberg",
    }


SVZ_HINWEISE = [
    f"Straßenverkehrszählung {SVZ_JAHR}: DTV aller Kfz und Schwerverkehr je Querschnitt; temporäre "
    "Zählstellen (TM) sind auf Jahreswerte hochgerechnet, manuelle (MZ) einmal gezählt.",
]


async def svz_load(out: Outbound, lat: float, lon: float, radius: int,
                   stellen_laden: Callable[[], Awaitable[list[dict[str, Any]]]]) -> SourceResult:
    started = time.perf_counter()
    try:
        stellen = await stellen_laden()
    except SourceError as err:
        return SourceResult.failed("verkehrsmenge", err, int((time.perf_counter() - started) * 1000))
    data = svz_aufbereiten(stellen, lat, lon, radius)
    data["hinweise"] = SVZ_HINWEISE
    warnungen = [] if data["zaehlstellen"] else [f"Keine SVZ-Zählstelle innerhalb von {MAX_DISTANZ_M} m."]
    return SourceResult(
        name="verkehrsmenge", ok=True, data=data,
        duration_ms=int((time.perf_counter() - started) * 1000), warnings=warnungen,
        provenance=Provenance(source=f"Straßenverkehrszählung {SVZ_JAHR} Baden-Württemberg (MobiData BW, CSV)",
                              license=LIZENZ, endpoint=SVZ_URL, stand=f"SVZ {SVZ_JAHR}", retrieved_at=now_iso(),
                              note="Landesdatei einmal geladen, lokal nach Entfernung ausgewertet; Blockform wie BASt."),
    )


# ------------------------------------------------ Eco-Counter Radzähler

def eco_parsen(csv_text: str) -> dict[str, dict[str, Any]]:
    """Tageswerte → je Zählstelle: Lage, Betreiber, Tage (Datum → Summe)."""
    sites: dict[str, dict[str, Any]] = {}
    for r in csv.DictReader(io.StringIO(csv_text)):
        sid = (r.get("counter_site_id") or "").strip()
        lat, lon = _zahl(r.get("latitude")), _zahl(r.get("longitude"))
        if not sid or lat is None or lon is None:
            continue
        s = sites.setdefault(sid, {"id": sid, "name": (r.get("counter_site") or "").strip(),
                                   "betreiber": (r.get("domain_name") or "").strip(), "lat": lat, "lon": lon, "tage": {}})
        alle = _zahl(r.get("channels_all"))
        if alle is None:
            ein, aus = _zahl(r.get("channels_in")), _zahl(r.get("channels_out"))
            alle = (ein or 0) + (aus or 0) if ein is not None or aus is not None else None
        if alle is not None:
            s["tage"][str(r.get("iso_timestamp") or "")[:10]] = int(alle)
    return sites


def eco_aufbereiten(sites: dict[str, dict[str, Any]], lat: float, lon: float, radius: int) -> dict[str, Any]:
    stellen = []
    for s in sites.values():
        dist = haversine_m(lat, lon, s["lat"], s["lon"])
        if dist > MAX_RAD_DISTANZ_M:
            continue
        tage = sorted(s["tage"].items())
        werte = [w for _, w in tage]
        stellen.append({
            "name": s["name"], "kurzname": s["name"], "lat": s["lat"], "lon": s["lon"],
            "distanz_m": round(dist), "richtung": bearing_label(lat, lon, s["lat"], s["lon"]),
            "im_radius": dist <= radius, "richtungen": [],
            "summe_vorjahr": None, "summe_vorjahr_jahr": None, "summe_laufender_monat": None,
            "seit_jahresbeginn": None, "vortag": werte[-1] if werte else None,
            "je_tag_vorjahr": None,
            "je_tag_basis": f"Mittel der letzten {len(werte)} Tage" if werte else None,
            "je_tag_letzte_woche": round(sum(werte) / len(werte)) if werte else None,
            "letzter_tag": tage[-1][0] if tage else None,
            "besonderheiten": f"Betreiber: {s['betreiber']}" if s["betreiber"] else None, "stoerung": None,
        })
    stellen.sort(key=lambda s: s["distanz_m"])
    return {"stadtweit": len(sites), "in_reichweite": stellen, "naechste": stellen[0] if stellen else None,
            "max_distanz_m": MAX_RAD_DISTANZ_M, "rohdaten": ECO_URL, "stadt": "Baden-Württemberg"}


ECO_HINWEISE = [
    "Eco-Counter-Radzähler der Kommunen und Landkreise in Baden-Württemberg (über MobiData BW); "
    "die Landesdatei enthält **die laufende Woche** — hier das Tagesmittel dieser Tage und der "
    "letzte Tageswert, kein Vorjahr.",
]


async def eco_load(out: Outbound, lat: float, lon: float, radius: int,
                   sites_laden: Callable[[], Awaitable[dict[str, dict[str, Any]]]]) -> SourceResult:
    started = time.perf_counter()
    try:
        sites = await sites_laden()
    except SourceError as err:
        return SourceResult.failed("radzaehlung", err, int((time.perf_counter() - started) * 1000))
    data = eco_aufbereiten(sites, lat, lon, radius)
    data["hinweise"] = ECO_HINWEISE
    warnungen = [] if data["in_reichweite"] else [f"Kein Radzähler innerhalb von {MAX_RAD_DISTANZ_M} m (MobiData BW)."]
    return SourceResult(
        name="radzaehlung", ok=True, data=data,
        duration_ms=int((time.perf_counter() - started) * 1000), warnings=warnungen,
        provenance=Provenance(source="Eco-Counter Radzähler Baden-Württemberg, Tageswerte (MobiData BW, CSV)",
                              license=LIZENZ, endpoint=ECO_URL, stand="laufende Woche", retrieved_at=now_iso(),
                              note="Landesdatei einmal geladen, lokal nach Entfernung ausgewertet."),
    )


# ------------------------------------------------------------ Ladesäulen

async def ladesaeulen(out: Outbound, lat: float, lon: float, radius: int) -> dict[str, Any]:
    """Teilblock ``lage["ladesaeulen"]``: Ladepunkte im Radius (WFS
    ``charge_points``, Quelle BNetzA-Register über MobiData BW)."""
    params = {"service": "WFS", "version": "1.0.0", "request": "GetFeature", "typeName": "MobiData-BW:charge_points",
              "srsName": "EPSG:4326", "outputFormat": "application/json", "maxFeatures": 200,
              "bbox": _bbox_um(lat, lon, radius)}
    payload = await out.get_json("mobidata_ladesaeulen", WFS_URL, params=params, timeout=45.0,
                                 limiter="mobidata", min_interval=0.5)
    features = payload.get("features") or [] if isinstance(payload, dict) else []
    standorte = []
    for f in features:
        punkte = _punkte(f.get("geometry"))
        if not punkte:
            continue
        p = f.get("properties") or {}
        dist = haversine_m(lat, lon, *punkte[0])
        if dist > radius:
            continue
        leistung = _zahl(p.get("max_electric_power"))
        standorte.append({
            "betreiber": p.get("operator_name"), "adresse": " ".join(x for x in (p.get("address"), p.get("postal_code"), p.get("city")) if x) or None,
            "ladepunkte": int(_zahl(p.get("chargepoint_static_count")) or 0),
            "frei": (int(_zahl(p.get("chargepoint_available_count")) or 0)
                     if p.get("chargepoint_available_count") is not None and p.get("realtime_data_outdated") is not True else None),
            "leistung_kw": round(leistung / 1000, 1) if leistung else None,
            "schnell": bool(leistung and leistung >= 50_000),
            "seit": str(p.get("go_live_date") or "")[:10] or None,
            "lat": punkte[0][0], "lon": punkte[0][1], "distanz_m": round(dist),
            "richtung": bearing_label(lat, lon, *punkte[0]) if dist > 0 else None,
        })
    standorte.sort(key=lambda s: s["distanz_m"])
    return {
        "standorte": standorte[:20], "im_radius": len(standorte),
        "ladepunkte": sum(s["ladepunkte"] for s in standorte),
        "schnelllader": sum(1 for s in standorte if s["schnell"]),
        "naechste": standorte[0] if standorte else None, "radius_m": radius,
        "quelle": "MobiData BW (Ladesäulenregister der Bundesnetzagentur)",
    }


__all__ = ["ROADWORKS_URL", "SVZ_URL", "ECO_URL", "WFS_URL", "STUTTGART_WFS_URL", "in_bw", "in_stuttgart",
           "roadworks_aufbereiten", "roadworks_load", "stuttgart_aufbereiten", "stuttgart_baustellen_load",
           "svz_parsen", "svz_aufbereiten", "svz_load", "eco_parsen", "eco_aufbereiten", "eco_load", "ladesaeulen"]
