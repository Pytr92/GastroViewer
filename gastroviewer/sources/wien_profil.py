"""Wien, zweiter Teil: Zählbezirks-Steckbrief und Lage-Indikatoren.

Beides über denselben GeoServer wie ``wien.py`` (``ogdwien:*``, CC BY 4.0,
Datenquelle: Stadt Wien – data.wien.gv.at) und die OGD-CSV der MA 23.
Live belegt am 18.09.2026 (fixtures/at, AT-Probe Runde 5 und 6):

**Zählbezirks-Steckbrief** (Blockform von ``indikatoren.py``, dem Münchner
Viertel-Steckbrief): ``ZAEHLBEZIRKOGD`` liefert am Punkt den Zählbezirk
(``ZBEZ`` ``0101`` → Code ``90101``); die CSV
``l9ogdviezbzpopsexagr3stknatgeo22008f`` (1,3 MB) führt seit 2008 je
Zählbezirk, Jahr, Geschlecht und drei Altersgruppen (``AGR3`` 1 = unter
15, 2 = 15–64, 3 = 65 und älter) die Bevölkerung nach Nationalität
(``AUT``, ``FOR``). Daraus: Einwohner, Ausländeranteil, Anteil unter 15
und ab 65 — als Jahresreihe des Zählbezirks gegen ganz Wien.

**Lage** (eigener Block): ``KURZPARKZONEOGD`` (Polygon mit ``ZEITRAUM``,
``DAUER``), ``FUSSGEHERZONEOGD`` (``ADRESSE``, ``ZEITRAUM``,
``AUSN_TEXT``), ``BEGEGNUNGSZONEOGD`` (``ADRESSE``), ``STRUKGESCHSTROGD``
(Geschäftsstraßen des Stadtstrukturplans, ``TYP``/``TYP_TXT``),
``REALNUT2024OGD`` (Realnutzungskartierung, Felder ``LEV1..3``;
  der Vorgänger 2022 hieß sie ``NUTZUNG_LEVEL1..3`` — beide werden gelesen),
``GEBAEUDEINFOOGD`` (Kulturgut-Gebäudeinventar: ``BAUJAHR``, ``GESCH_ANZ``,
``L_NUTZUNG``, ``L_BAUTYP`` — nicht flächendeckend). Am Stephansplatz:
Kurzparkzone „Mo.–Fr. 9–22 Uhr, 2 h“, 60 Fußgängerzonen im 400-m-Kasten,
Realnutzung „dichtes Wohn(misch)gebiet“.
"""

from __future__ import annotations

import csv
import io
import re
import time
from typing import Any, Awaitable, Callable

from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, bearing_label, haversine_m, now_iso
from .wien import LIZENZ, WFS_URL, _enthaelt, _features, _punkt, _punkt_box, _bbox_um, in_wien

ZB_CSV_URL = "https://www.wien.gv.at/gogv/l9ogdviezbzpopsexagr3stknatgeo22008f"
ZB_ROHDATEN = "https://www.data.gv.at/katalog/dataset/9ecf5866-dbe8-4cb2-b156-5097c7eec01f"
STADT_RAUM = "Wien gesamt"

INDIKATOREN = [
    {"schluessel": "einwohner", "label": "Einwohner", "einheit": "Personen",
     "deutung": "Hauptwohnsitzbevölkerung am 1. Jänner (MA 23)."},
    {"schluessel": "auslaenderanteil", "label": "Ausländeranteil", "einheit": "%",
     "deutung": "Anteil der Bevölkerung mit nicht-österreichischer Staatsangehörigkeit."},
    {"schluessel": "unter15", "label": "unter 15 Jahre", "einheit": "%",
     "deutung": "Anteil der unter 15-Jährigen — Familienlage oder nicht."},
    {"schluessel": "ab65", "label": "65 Jahre und älter", "einheit": "%",
     "deutung": "Anteil der ab 65-Jährigen — Tagesgastronomie-Publikum, Abendlage eher nicht."},
]

ZB_HINWEISE = [
    "Zählbezirksebene (250 in Wien), feiner als das 1-km-Raster und gröber als "
    "der Zensus in Deutschland — hier steht die **Entwicklung über die Jahre**.",
    "Der Trendvergleich reicht ~5 Jahre zurück; die Werte gelten zum 1. Jänner "
    "des Jahres.",
]


def zaehlbezirk_code(feature: dict[str, Any] | None) -> str | None:
    """``ZBEZ`` ``0101`` → ``90101`` (Bezirk 01, Zählbezirk 01)."""
    p = (feature or {}).get("properties") or {}
    z = str(p.get("ZBEZ") or "")
    return f"9{z}" if len(z) == 4 and z.isdigit() else None


def zb_reduzieren(csv_text: str) -> dict[str, dict[str, dict[str, float]]]:
    """CSV → je Zählbezirk-Code (und ``STADT_RAUM``) je Jahr die vier Kennzahlen."""
    zeilen = csv_text.lstrip("﻿").splitlines()
    start = next((i for i, z in enumerate(zeilen) if z.startswith("NUTS;")), None)
    if start is None:
        raise SourceError("parse", "Zählbezirks-CSV ohne Kopfzeile NUTS;DISTRICT_CODE;…")
    reader = csv.DictReader(io.StringIO("\n".join(zeilen[start:])), delimiter=";")
    summen: dict[tuple[str, str], dict[str, float]] = {}
    for r in reader:
        code, jahr = (r.get("SUB_DISTRICT_CODE") or "").strip(), (r.get("REF_YEAR") or "").strip()
        if not code or not jahr.isdigit():
            continue
        try:
            aut, for_ = float(r.get("AUT") or 0), float(r.get("FOR") or 0)
            agr = int(r.get("AGR3") or 0)
        except ValueError:
            continue
        for raum in (code, STADT_RAUM):
            s = summen.setdefault((raum, jahr), {"ges": 0.0, "for": 0.0, "u15": 0.0, "ab65": 0.0})
            s["ges"] += aut + for_
            s["for"] += for_
            if agr == 1:
                s["u15"] += aut + for_
            elif agr == 3:
                s["ab65"] += aut + for_
    out: dict[str, dict[str, dict[str, float]]] = {}
    for (raum, jahr), s in summen.items():
        if not s["ges"]:
            continue
        out.setdefault(raum, {})[jahr] = {
            "einwohner": s["ges"],
            "auslaenderanteil": round(s["for"] / s["ges"] * 100, 1),
            "unter15": round(s["u15"] / s["ges"] * 100, 1),
            "ab65": round(s["ab65"] / s["ges"] * 100, 1),
        }
    return out


def _trend(reihe: list[tuple[int, float]]) -> dict[str, Any] | None:
    if not reihe:
        return None
    jahr, wert = reihe[-1]
    basis = next(((j, w) for j, w in reversed(reihe) if j <= jahr - 5), None)
    if basis is None or basis[0] == jahr:
        return {"jahr": jahr, "wert": wert, "von_jahr": None, "von_wert": None, "delta": None}
    return {"jahr": jahr, "wert": wert, "von_jahr": basis[0], "von_wert": basis[1],
            "delta": round(wert - basis[1], 2)}


def zb_auswerten(daten: dict[str, dict[str, dict[str, float]]], code: str | None,
                 bezirk_name: str | None) -> dict[str, Any]:
    zeilen = []
    for ind in INDIKATOREN:
        k = ind["schluessel"]
        stadt = sorted((int(j), w[k]) for j, w in (daten.get(STADT_RAUM) or {}).items())
        bez = sorted((int(j), w[k]) for j, w in (daten.get(code) or {}).items()) if code else []
        zeilen.append({
            "schluessel": k, "label": ind["label"], "einheit": ind["einheit"], "deutung": ind["deutung"],
            "bezirk": _trend(bez), "stadt": _trend(stadt),
            "reihe": [[j, w] for j, w in bez[-12:]],
        })
    return {
        "bezirk": (f"Zählbezirk {code[1:3]}.{code[3:]} ({bezirk_name})" if code and bezirk_name
                   else f"Zählbezirk {code[1:3]}.{code[3:]}" if code else None),
        "bezirk_gesucht": bezirk_name, "stadt_raum": STADT_RAUM,
        "indikatoren": zeilen, "hinweise": ZB_HINWEISE, "stadt": "Wien",
    }


async def zaehlbezirk_load(out: Outbound, lat: float, lon: float, ortsteil: str | None,
                           daten_laden: Callable[[], Awaitable[dict[str, Any]]]) -> SourceResult:
    started = time.perf_counter()
    try:
        features = await _features(out, "wien_zaehlbezirk", "ZAEHLBEZIRKOGD", _punkt_box(lat, lon), 5)
    except SourceError as err:
        return SourceResult.failed("indikatoren", err, int((time.perf_counter() - started) * 1000))
    treffer = next((f for f in features if _enthaelt(f, lat, lon)), features[0] if features else None)
    code = zaehlbezirk_code(treffer)
    try:
        daten = await daten_laden()
    except SourceError as err:
        return SourceResult.failed("indikatoren", err, int((time.perf_counter() - started) * 1000))
    data = zb_auswerten(daten, code if code in daten else None, ortsteil)
    warnungen = [] if code and code in daten else [
        "Der Zählbezirk am Punkt ließ sich nicht zuordnen — angezeigt sind die Werte für ganz Wien."]
    return SourceResult(
        name="indikatoren", ok=True, data=data,
        duration_ms=int((time.perf_counter() - started) * 1000), warnings=warnungen,
        provenance=Provenance(
            source="Stadt Wien, MA 23 — Bevölkerung nach Nationalität, Alter und Geschlecht je Zählbezirk",
            license=LIZENZ, endpoint=ZB_CSV_URL, stand="jährlich zum 1. Jänner, ab 2008",
            retrieved_at=now_iso(), note="Zählbezirk am Punkt über WFS, Reihe aus der OGD-CSV."),
    )


# ---------------------------------------------------------------- Lage

LAGE_HINWEISE = [
    "Kurzparkzone, Fußgänger- und Begegnungszonen sind **Verkehrsrecht**, kein "
    "Frequenzmaß: Eine Fußgängerzone bringt Laufkundschaft, nimmt aber Anlieferung "
    "und Parkplätze — beides steht hier mit Zeiten und Ausnahmen.",
    "Geschäftsstraßen des Stadtstrukturplans (MA 18) sind planerisch ausgewiesene "
    "Einkaufslagen; die Realnutzungskartierung beschreibt, was auf dem Baublock "
    "tatsächlich steht.",
    "Die Gebäudeinformation stammt aus dem Kulturgut-Inventar der Stadt und ist "
    "nicht flächendeckend — fehlt sie, heißt das nichts über das Gebäude.",
]


def _naechste(features: list[dict[str, Any]], lat: float, lon: float, felder: dict[str, str],
              radius: int) -> list[dict[str, Any]]:
    """Punkt- oder Flächenobjekte nach Entfernung (Fläche: 0 m, wenn der Punkt
    drin liegt, sonst Abstand zum nächsten Stützpunkt)."""
    out = []
    for f in features:
        g = f.get("geometry") or {}
        p = f.get("properties") or {}
        eintrag = {ziel: p.get(quelle) for ziel, quelle in felder.items()}
        pkt = _punkt(f)
        if pkt is not None:
            dist = haversine_m(lat, lon, *pkt)
            eintrag.update({"lat": pkt[0], "lon": pkt[1]})
        elif _enthaelt(f, lat, lon):
            dist = 0.0
        else:
            koords = g.get("coordinates") or []
            punkte: list[tuple[float, float]] = []
            stapel = [koords]
            while stapel:
                k = stapel.pop()
                if isinstance(k, list) and k and isinstance(k[0], (int, float)) and len(k) >= 2:
                    punkte.append((float(k[1]), float(k[0])))
                elif isinstance(k, list):
                    stapel.extend(k)
            if not punkte:
                continue
            dist = min(haversine_m(lat, lon, a, b) for a, b in punkte)
        eintrag["distanz_m"] = round(dist)
        eintrag["im_radius"] = dist <= radius
        if pkt is not None and dist > 0:
            eintrag["richtung"] = bearing_label(lat, lon, *pkt)
        out.append(eintrag)
    out.sort(key=lambda e: e["distanz_m"])
    return out


#: Die Stadt kartiert die Realnutzung alle zwei Jahre und legt jeden
#: Jahrgang als eigenen Layer ab. Mit dem Jahrgang 2024 hat sie die Felder
#: umbenannt (``NUTZUNG_LEVEL1`` → ``LEV1``) und den Baublock durch das
#: Zählgebiet ersetzt — deshalb liest ``realnutzung_aufbereiten`` beide
#: Schemata. Live belegt am 19.09.2026 (Probe-Runde 9).
REALNUT_TYP = "REALNUT2024OGD"
REALNUT_JAHR = 2024


def realnutzung_aufbereiten(feature: dict[str, Any]) -> dict[str, Any]:
    p = feature.get("properties") or {}
    return {
        "stufe1": p.get("LEV1") or p.get("NUTZUNG_LEVEL1"),
        "stufe2": p.get("LEV2") or p.get("NUTZUNG_LEVEL2"),
        "stufe3": p.get("LEV3") or p.get("NUTZUNG_LEVEL3"),
        "baublock": p.get("BLK"),
        "zaehlgebiet": p.get("ZGEB"),
        "jahr": REALNUT_JAHR,
    }


async def lage_load(out: Outbound, lat: float, lon: float, radius: int) -> SourceResult:
    started = time.perf_counter()
    if not in_wien(lat, lon):
        return SourceResult(name="lage", ok=True, data=None,
                            warnings=["Die Lage-Indikatoren (Kurzparkzone, Fußgängerzonen, Geschäftsstraßen, "
                                      "Realnutzung, Gebäudeinfo) sind hier nur für Wien eingebunden."])
    bbox = _bbox_um(lat, lon, radius)
    data: dict[str, Any] = {"stadt": "Wien", "hinweise": LAGE_HINWEISE}
    fehler: list[str] = []

    async def hol(typ: str, box: str | None, n: int) -> list[dict[str, Any]]:
        try:
            return await _features(out, "wien_lage", typ, box, n)
        except SourceError as err:
            fehler.append(f"{typ}: {err.message}")
            return []

    kpz = [f for f in await hol("KURZPARKZONEOGD", _punkt_box(lat, lon), 5) if _enthaelt(f, lat, lon)]
    data["kurzparkzone"] = ({"zeitraum": (kpz[0]["properties"] or {}).get("ZEITRAUM"),
                             "dauer": (kpz[0]["properties"] or {}).get("DAUER"),
                             "bezirk": (kpz[0]["properties"] or {}).get("BEZIRK"),
                             "gueltig_von": str((kpz[0]["properties"] or {}).get("GUELTIG_VON") or "")[:10] or None}
                            if kpz else None)
    data["fussgaengerzonen"] = _naechste(await hol("FUSSGEHERZONEOGD", bbox, 200), lat, lon,
                                         {"adresse": "ADRESSE", "zeitraum": "ZEITRAUM", "ausnahme": "AUSN_TEXT"}, radius)[:25]
    data["begegnungszonen"] = _naechste(await hol("BEGEGNUNGSZONEOGD", bbox, 100), lat, lon,
                                        {"adresse": "ADRESSE"}, radius)[:15]
    gs = _naechste(await hol("STRUKGESCHSTROGD", bbox, 200), lat, lon, {"typ": "TYP", "typ_text": "TYP_TXT"}, radius)
    data["geschaeftsstrasse"] = {"am_punkt": next((g for g in gs if g["distanz_m"] == 0), None),
                                 "naechste": gs[0] if gs else None, "im_radius": sum(1 for g in gs if g["im_radius"])}
    rn = [f for f in await hol(REALNUT_TYP, _punkt_box(lat, lon), 5) if _enthaelt(f, lat, lon)]
    data["realnutzung"] = realnutzung_aufbereiten(rn[0]) if rn else None
    geb = _naechste(await hol("GEBAEUDEINFOOGD", _bbox_um(lat, lon, 150), 60), lat, lon,
                    {"strasse": "STRNAML", "von": "VONN", "bis": "BISN", "name": "HA_NAME", "baujahr": "BAUJAHR",
                     "geschosse": "GESCH_ANZ", "nutzung": "L_NUTZUNG", "bautyp": "L_BAUTYP", "architekt": "ARCHITEKT"}, 150)
    for g in geb:
        if isinstance(g.get("architekt"), str):
            teile = [t.strip() for t in re.split(r"[\r\n;]+", g["architekt"]) if t.strip()]
            g["architekt"] = "; ".join(dict.fromkeys(teile)) or None
    data["gebaeude"] = geb[:5]
    if len(fehler) >= 6:
        return SourceResult.failed("lage", SourceError("api_error", "Wiener WFS nicht erreichbar: " + fehler[0]),
                                   int((time.perf_counter() - started) * 1000))
    return SourceResult(
        name="lage", ok=True, data=data, duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=fehler,
        provenance=Provenance(
            source="Stadt Wien — Kurzparkzonen, Fußgänger-/Begegnungszonen (MA 46), Stadtstrukturplan und "
                   "Realnutzungskartierung (MA 18), Gebäudeinformation (MA 19)",
            license=LIZENZ, endpoint=WFS_URL, stand=f"laufend gepflegt (Realnutzung {REALNUT_JAHR})",
            retrieved_at=now_iso(), note="Punkt-in-Fläche für Zonen und Nutzung, Umkreis für Fußgängerzonen und Gebäude."),
    )
