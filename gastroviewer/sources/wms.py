"""Bodenrichtwert-Kartendienste der Länder — Phase 4.

Spec §4.5: „Falls ein WMS/WFS des Landes gefunden wird, gern als Kartenebene
nachrüsten." Und: **keine URL raten**.

Deshalb steht hier nur, was am 2026-08-01 vollständig verifiziert wurde: erst
``GetCapabilities`` abgerufen, dann ``GetMap`` mit einem Punkt im jeweiligen Land
aufgerufen und geprüft, dass ein PNG mit Inhalt zurückkommt, dann
``GetFeatureInfo`` gegen denselben Punkt. Für Länder ohne belegten Dienst bleibt
es beim Portallink aus ``boris.py`` — dort wird nichts geraten.

Die Kacheln holt der Browser direkt. Ein Proxy wie bei den übrigen Quellen wäre
hier verkehrt: Kartenbilder brauchen kein CORS, und jede Kachel im
Outbound-Protokoll zu zählen würde den Cache-Nachweis aus §7 unbrauchbar machen.
**Ausgenommen ist ``GetFeatureInfo``** — das ist ein Datenabruf per ``fetch`` und
scheitert ohne Proxy an CORS. Er läuft deshalb über das Backend.
"""

from __future__ import annotations

import html as html_mod
import json as json_mod
import math
import re
import time
from typing import Any

from ..config import Settings
from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, now_iso

# Maßstabsnenner der Web-Mercator-Zoomstufe 0. Daraus wird die kleinste
# brauchbare Zoomstufe abgeleitet, statt sie zu schätzen.
SCALE_Z0 = 559_082_264.028


def min_zoom_fuer(max_scale_denominator: float | None) -> int:
    """Ab welcher Zoomstufe zeichnet der Dienst überhaupt?

    Die Dienste liefern ``MaxScaleDenominator`` in ihren Capabilities. Ohne diese
    Ableitung würde die Ebene bei kleinen Zoomstufen stumm leer bleiben und wie
    ein Fehler aussehen.
    """
    if not max_scale_denominator:
        return 0
    return max(0, math.ceil(math.log2(SCALE_Z0 / max_scale_denominator)))


DIENSTE: dict[str, dict[str, Any]] = {
    "05": {
        "land": "Nordrhein-Westfalen",
        "titel": "BORIS-NRW Bodenrichtwerte",
        "url": "https://www.wms.nrw.de/boris/wms-t_nw_brw",
        "version": "1.3.0",
        "layers": (
            "brw_mehrgeschossige_bauweise,brw_ein_zweigeschossig,"
            "brw_gewerbe_industrie_sondergebiete,brw_sonstige_flaechen,"
            "brw_mehrgeschossige_bauweise_label,"
            "brw_gewerbe_industrie_sondergebiete_label"
        ),
        "query_layers": "brw_mehrgeschossige_bauweise",
        "info_format": "application/geo+json",
        "params": {"TIME": "2026-01-01"},
        "max_scale": 56696.428571,
        "lizenz": "Datenlizenz Deutschland – Zero – Version 2.0 (dl-de/zero-2-0)",
        "attribution": "Bodenrichtwerte © Geobasis NRW (dl-de/zero-2-0)",
        "stand": "jährlich zum 01.01., Dienst wöchentlich aktualisiert; Zeitreihe ab 2011",
        "portal": "https://www.boris.nrw.de/",
        "abfragbar": "voll",
        "abfrage_hinweis": "Der Dienst liefert alle beschreibenden Merkmale.",
    },
    "02": {
        "land": "Hamburg",
        "titel": "Bodenrichtwertzonen Hamburg",
        "url": "https://geodienste.hamburg.de/HH_WMS_Bodenrichtwerte",
        "version": "1.3.0",
        "layers": "lgv_brw_zonen_2026",
        # Die gezeichnete Ebene liefert per GetFeatureInfo nichts (deegree gibt
        # eine leere FeatureCollection zurück, unabhängig von der Boxgröße).
        # Die flächendeckende Ebene antwortet — aber ohne den €/m²-Wert.
        "query_layers": "v_brw_zonen_geom_flaeche_2026",
        "info_format": "text/xml",
        "params": {},
        "max_scale": None,
        "lizenz": "Es gelten keine Zugriffsbeschränkungen (Angabe des Dienstes)",
        "attribution": "Bodenrichtwerte © Landesbetrieb Geoinformation und Vermessung Hamburg",
        "stand": "Zonen 2026, Zeitreihe ab 1964",
        "portal": "https://www.hamburg.de/politik-und-verwaltung/behoerden/bsw/themen/geoinformation-vermessung/bodenrichtwerte-289348",
        "abfragbar": "eingeschraenkt",
        "abfrage_hinweis": "Die Klickabfrage liefert Zonennummer und Nutzungsarten, aber nicht den "
        "Bodenrichtwert selbst. Der Wert steht als Beschriftung in der Karte.",
    },
    "03": {
        "land": "Niedersachsen",
        "titel": "BORIS Niedersachsen",
        "url": "https://opendata.lgln.niedersachsen.de/doorman/noauth/boris_2025_wms",
        "version": "1.3.0",
        "layers": "Bauland",
        "query_layers": "Bauland",
        "info_format": "text/xml",
        "params": {},
        "max_scale": 5_000_000,
        "lizenz": "Datenlizenz Deutschland – Namensnennung – Version 2.0 (dl-de/by-2-0)",
        "attribution": "Bodenrichtwerte © GDI-NI / LGLN (dl-de/by-2-0)",
        "stand": "Dienstjahrgang 2025",
        "portal": "https://www.lgln.niedersachsen.de/",
        "abfragbar": "voll",
        "abfrage_hinweis": "Der Dienst liefert alle beschreibenden Merkmale.",
    },
    "15": {
        "land": "Sachsen-Anhalt",
        "titel": "BORIS Sachsen-Anhalt",
        "url": "https://www.geodatenportal.sachsen-anhalt.de/ows_st_lvermgeo_brw2026",
        "version": "1.3.0",
        "layers": "Bauland",
        "query_layers": "Bauland",
        "info_format": "text/xml;subtype=gml/3.2.1",
        "params": {},
        "max_scale": 5_000_000,
        "lizenz": (
            "Der Dienst nennt die Kostenverordnung für das amtliche Vermessungswesen "
            "Sachsen-Anhalt — Nutzungsbedingungen des Landes vor gewerblicher Nutzung prüfen"
        ),
        "attribution": "Bodenrichtwerte © LVermGeo Sachsen-Anhalt",
        "stand": "Stichtag 01.01.2026",
        "portal": "https://www.lvermgeo.sachsen-anhalt.de/de/nutzungsbedingungen.html",
        "abfragbar": "voll",
        "abfrage_hinweis": "Der Dienst liefert alle beschreibenden Merkmale.",
    },
    "16": {
        "land": "Thüringen",
        "titel": "BORIS-TH Bodenrichtwerte",
        "url": "https://www.geoproxy.geoportal-th.de/geoproxy/services/boris/boris_wms",
        "version": "1.3.0",
        "layers": "BODENRICHTWERTZONE_aktuell,BODENRICHTWERTZONE_aktuell_PTO",
        "query_layers": "BODENRICHTWERTZONE_aktuell",
        "info_format": "text/plain",
        "params": {},
        "max_scale": 100_001.0,
        "lizenz": "Datenlizenz Deutschland – Namensnennung – Version 2.0 (dl-de/by-2-0)",
        "attribution": "Bodenrichtwerte © GDI-Th (dl-de/by-2-0)",
        "stand": "Ebene „aktuell\"; Zeitreihe ab 2011 im Dienst",
        "portal": "https://www.geoportal-th.de/",
        "abfragbar": "voll",
        "abfrage_hinweis": "Der Dienst liefert alle beschreibenden Merkmale.",
    },
    "12": {
        "land": "Brandenburg",
        "titel": "BORIS Brandenburg, Bauland zonal",
        "url": "https://isk.geobasis-bb.de/ows/boris_wms",
        "version": "1.3.0",
        "layers": "bbv_pg_zobau_2026",
        "query_layers": "bbv_pg_zobau_2026",
        "info_format": "text/html",
        "params": {},
        "max_scale": 125_000,
        "lizenz": "Datenlizenz Deutschland – Namensnennung – Version 2.0 (dl-de/by-2-0)",
        "attribution": "Bodenrichtwerte © LGB Brandenburg (dl-de/by-2-0)",
        "stand": "Bauland zonal 2026, Zeitreihe ab 2011",
        "portal": "https://boris.brandenburg.de/",
        "abfragbar": "voll",
        "abfrage_hinweis": "Der Dienst liefert alle beschreibenden Merkmale.",
    },
    "07": {
        "land": "Rheinland-Pfalz",
        "titel": "Generalisierte Bodenrichtwerte Rheinland-Pfalz",
        "url": "https://geo5.service24.rlp.de/wms/genbori_rp.fcgi",
        "version": "1.1.1",
        "layers": "Wohnbauflaechen,Gemischte_Bauflaechen,Gewerbebauflaechen",
        "query_layers": "Gemischte_Bauflaechen",
        "info_format": "text/plain",
        "params": {},
        "max_scale": None,
        "lizenz": "geldleistungsfrei, Datenlizenz Deutschland – Namensnennung – Version 2.0",
        "attribution": "Generalisierte Bodenrichtwerte © GeoBasis-DE / LVermGeoRP (dl-de/by-2-0)",
        "stand": (
            "generalisierte Klassen, nicht die zonalen Einzelwerte — der zonale "
            "VBORIS-Dienst des Landes liefert über den Mapbender-Proxy kein GetMap"
        ),
        "portal": "https://www.geoportal.rlp.de/article/Bodenrichtwerte/",
        "abfragbar": "nein",
        "abfrage_hinweis": "Die generalisierte Karte trägt keine Sachdaten — die Klassen stehen nur in "
        "der Legende. Für Einzelwerte das Landesportal nutzen.",
    },
}

# Länder, für die am 2026-08-01 kein Dienst verifiziert werden konnte, mit dem
# jeweiligen Grund. Steht in der Oberfläche, damit „keine Ebene" nicht wie ein
# Fehler des Werkzeugs aussieht.
OHNE_DIENST: dict[str, str] = {
    "01": "Schleswig-Holstein ist aus rechtlichen Gründen nicht in den offenen "
    "Bodenrichtwert-Diensten enthalten.",
    "04": "Für Bremen wurde kein offener Kartendienst gefunden.",
    "06": "Für Hessen wurde kein offener Kartendienst gefunden.",
    "08": "Baden-Württemberg ist aus rechtlichen Gründen nicht in den offenen "
    "Bodenrichtwert-Diensten enthalten.",
    "09": "Bayern ist aus rechtlichen Gründen nicht in den offenen "
    "Bodenrichtwert-Diensten enthalten.",
    "10": "Das Saarland ist aus rechtlichen Gründen nicht in den offenen "
    "Bodenrichtwert-Diensten enthalten.",
    "11": "Berlin: Der Kartendienst war beim Test über die TLS-Zertifikatskette nicht "
    "prüfbar. Ohne Beleg wird er nicht eingebunden.",
    "13": "Mecklenburg-Vorpommern ist aus rechtlichen Gründen nicht in den offenen "
    "Bodenrichtwert-Diensten enthalten.",
    "14": "Sachsen: Der Kartendienst wies die Prüfabrufe mit HTTP 403 zurück.",
}

VERIFIZIERT_AM = "2026-08-01"


def fuer_bundesland(code: str | None) -> dict[str, Any]:
    """Konfiguration der Kartenebene für ein Bundesland."""
    if not code:
        return {
            "verfuegbar": False,
            "grund": "Ohne Bundesland (kein AGS aus dem Zensus-Gitter) lässt sich "
            "kein Landesdienst bestimmen.",
        }
    d = DIENSTE.get(code)
    if not d:
        return {
            "verfuegbar": False,
            "grund": OHNE_DIENST.get(
                code, "Für dieses Bundesland wurde kein offener Kartendienst verifiziert."
            ),
            "hinweis": "Es wird keine URL geraten. Der Portallink im Block darüber führt "
            "zum zuständigen Angebot.",
        }
    return {
        "verfuegbar": True,
        "bundesland_code": code,
        "land": d["land"],
        "titel": d["titel"],
        "url": d["url"],
        "version": d["version"],
        "layers": d["layers"],
        "params": d["params"],
        "min_zoom": min_zoom_fuer(d["max_scale"]),
        "max_scale": d["max_scale"],
        "lizenz": d["lizenz"],
        "attribution": d["attribution"],
        "stand": d["stand"],
        "portal": d["portal"],
        "abfragbar": d["abfragbar"],
        "abfrage_hinweis": d["abfrage_hinweis"],
        "verifiziert_am": VERIFIZIERT_AM,
    }


def alle() -> dict[str, Any]:
    return {
        "verifiziert_am": VERIFIZIERT_AM,
        "dienste": [fuer_bundesland(c) for c in sorted(DIENSTE)],
        "ohne_dienst": [
            {"bundesland_code": c, "grund": g} for c, g in sorted(OHNE_DIENST.items())
        ],
    }


# --------------------------------------------------------- GetFeatureInfo


def _bbox_3857(lat: float, lon: float, halbe_kante_m: float) -> tuple[float, float, float, float]:
    x = lon * 20037508.34 / 180.0
    y = math.log(math.tan((90.0 + lat) * math.pi / 360.0)) / (math.pi / 180.0)
    y = y * 20037508.34 / 180.0
    return (x - halbe_kante_m, y - halbe_kante_m, x + halbe_kante_m, y + halbe_kante_m)


def werte_aus_antwort(text: str, content_type: str) -> list[dict[str, str]]:
    """Zieht Schlüssel-Wert-Paare aus der Antwort — ohne etwas zu erfinden.

    Die sieben Dienste liefern fünf verschiedene Formate. Statt für jedes einen
    eigenen Parser zu pflegen, werden vier allgemeine Muster versucht. Was sich
    nicht sicher zerlegen lässt, bleibt als Rohtext stehen und wird so angezeigt
    — lieber der unverarbeitete Originaltext als ein falsch zugeordneter Wert.
    """
    text = (text or "").strip()
    if not text:
        return []

    # 1) GeoJSON / JSON
    if "json" in content_type or text.startswith("{"):
        try:
            d = json_mod.loads(text)
            felder: list[dict[str, str]] = []
            for f in d.get("features", []) or []:
                for k, v in (f.get("properties") or {}).items():
                    wert = str(v).strip() if v is not None else ""
                    if wert and wert.lower() not in ("null", "none", "-"):
                        felder.append({"feld": str(k), "wert": wert})
            if felder:
                return felder
        except ValueError:
            pass

    # 2) Thüringen-Stil: KEY=VALUE$#$KEY=VALUE
    if "$#$" in text:
        felder = []
        for teil in text.split("$#$"):
            if "=" in teil:
                k, _, v = teil.partition("=")
                k, v = k.strip(), v.strip()
                if k and v:
                    felder.append({"feld": k, "wert": v})
        if felder:
            return felder

    # 3) XML / GML: Blattknoten mit Text
    if text.startswith("<") and "html" not in content_type:
        felder = []
        for m in re.finditer(r"<([A-Za-z_][\w.:-]*)[^>]*>([^<>]+)</\1>", text):
            name = m.group(1).split(":")[-1]
            wert = html_mod.unescape(m.group(2)).strip()
            if wert and wert.lower() not in ("missing", "null") and name.lower() not in (
                "boundedby", "coordinates", "pos", "poslist", "null", "box"
            ):
                felder.append({"feld": name, "wert": wert})
        if felder:
            return felder

    # 4) HTML: Tabellenzeilen, sonst reiner Text
    if "html" in content_type or text.lower().startswith("<!doctype html"):
        felder = []
        for m in re.finditer(
            r"<t[dh][^>]*>(.*?)</t[dh]>\s*<t[dh][^>]*>(.*?)</t[dh]>", text, re.S | re.I
        ):
            k = html_mod.unescape(re.sub(r"<[^>]+>", " ", m.group(1))).strip(" :\xa0\n\t")
            v = html_mod.unescape(re.sub(r"<[^>]+>", " ", m.group(2))).strip(" \xa0\n\t")
            if k and v:
                felder.append({"feld": k, "wert": v})
        if felder:
            return felder

    return []


def _rohtext(text: str, content_type: str) -> str:
    if "html" in content_type:
        ohne = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
        ohne = re.sub(r"<[^>]+>", " ", ohne)
        return re.sub(r"\s+", " ", html_mod.unescape(ohne)).strip()[:4000]
    return text.strip()[:4000]


async def feature_info(
    out: Outbound,
    settings: Settings,
    lat: float,
    lon: float,
    bundesland_code: str | None,
) -> SourceResult:
    """Fragt den Bodenrichtwert am Punkt beim Landesdienst ab.

    Läuft über das Backend, weil ein ``fetch`` aus dem Browser an CORS scheitern
    würde. Die Antwort wird unverändert mitgeliefert — was sich nicht sicher
    zerlegen lässt, steht als Rohtext da.
    """
    started = time.perf_counter()
    cfg = fuer_bundesland(bundesland_code)
    if not cfg["verfuegbar"]:
        return SourceResult(
            name="bodenrichtwert",
            ok=True,
            data=None,
            warnings=[cfg["grund"]],
            provenance=Provenance(
                source="Bodenrichtwerte: kein verifizierter Landesdienst",
                license="—",
            ),
        )

    d = DIENSTE[bundesland_code]  # type: ignore[index]
    # 40 m Kantenlänge um den Punkt: groß genug, dass die Zone getroffen wird,
    # klein genug, dass nicht die Nachbarzone mitkommt.
    minx, miny, maxx, maxy = _bbox_3857(lat, lon, 20.0)
    achse = "CRS" if d["version"] == "1.3.0" else "SRS"
    params: dict[str, str] = {
        "SERVICE": "WMS",
        "VERSION": d["version"],
        "REQUEST": "GetFeatureInfo",
        "LAYERS": d["query_layers"],
        "QUERY_LAYERS": d["query_layers"],
        "STYLES": "",
        achse: "EPSG:3857",
        "BBOX": f"{minx},{miny},{maxx},{maxy}",
        "WIDTH": "101",
        "HEIGHT": "101",
        "FORMAT": "image/png",
        "INFO_FORMAT": d["info_format"],
        "FEATURE_COUNT": "5",
        **d["params"],
    }
    if d["version"] == "1.3.0":
        params["I"] = "50"
        params["J"] = "50"
    else:
        params["X"] = "50"
        params["Y"] = "50"

    try:
        resp = await out.request(
            "wms_bodenrichtwert",
            "GET",
            d["url"],
            params=params,
            timeout=45.0,
            limiter="wms",
            min_interval=0.5,
        )
    except SourceError as err:
        return SourceResult.failed(
            "bodenrichtwert", err, int((time.perf_counter() - started) * 1000)
        )

    content_type = resp.headers.get("content-type", "")
    text = resp.text
    felder = werte_aus_antwort(text, content_type)
    roh = _rohtext(text, content_type)

    warnungen: list[str] = []
    if not felder:
        warnungen.append(
            "Der Dienst hat an diesem Punkt keine auswertbaren Felder geliefert. "
            "Möglich ist beides: keine Bodenrichtwertzone an dieser Stelle, oder ein "
            "Antwortformat, das hier nicht sicher zerlegt werden kann. Der "
            "unveränderte Originaltext steht darunter."
        )

    return SourceResult(
        name="bodenrichtwert",
        ok=True,
        data={
            "land": d["land"],
            "titel": d["titel"],
            "felder": felder,
            "rohantwort": roh,
            "content_type": content_type,
            "abgefragte_ebene": d["query_layers"],
            "portal": d["portal"],
        },
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnungen,
        provenance=Provenance(
            source=f"{d['titel']} (WMS GetFeatureInfo)",
            license=d["lizenz"],
            endpoint=d["url"],
            stand=d["stand"],
            retrieved_at=now_iso(),
            note=(
                "Werte unverändert vom Landesdienst übernommen. Bodenrichtwerte sind "
                "Zonenwerte für ein fiktives Grundstück mit den angegebenen Merkmalen — "
                "nicht der Wert eines konkreten Grundstücks."
            ),
        ),
    )


async def pruefe_dienste(out: Outbound, settings: Settings) -> list[dict[str, Any]]:
    """Ruft bei jedem hinterlegten Dienst ``GetCapabilities`` ab.

    Für ``gastroviewer check-wms``: Landesdienste ändern ihre URLs (Brandenburg
    hat seine 2025 umgestellt). Ohne regelmäßige Gegenprobe merkt man das erst,
    wenn die Karte leer bleibt.
    """
    ergebnisse = []
    for code, d in sorted(DIENSTE.items()):
        eintrag: dict[str, Any] = {"bundesland_code": code, "land": d["land"], "url": d["url"]}
        try:
            resp = await out.request(
                "wms_check",
                "GET",
                d["url"],
                params={"SERVICE": "WMS", "REQUEST": "GetCapabilities",
                        "VERSION": d["version"]},
                timeout=45.0,
            )
            text = resp.text
            eintrag["status"] = resp.status_code
            eintrag["ist_wms"] = ("WMS_Capabilities" in text[:600]
                                  or "WMT_MS_Capabilities" in text[:600])
            fehlende = [
                lag for lag in d["layers"].split(",") if f"<Name>{lag}</Name>" not in text
            ]
            eintrag["fehlende_layer"] = fehlende
            eintrag["ok"] = bool(eintrag["ist_wms"]) and not fehlende
        except SourceError as err:
            eintrag["ok"] = False
            eintrag["fehler"] = err.message
        ergebnisse.append(eintrag)
    return ergebnisse
