"""Planungsrecht und Hochwasserrisiko am Punkt.

Zwei Fragen, die eine Standortentscheidung kippen können und die keine der
bisherigen Quellen beantwortet:

* **Liegt die Fläche in einem Hochwassergefahrengebiet?** Für Keller, Lager,
  Kühltechnik und die Versicherungsprämie ist das entscheidend.
* **Gilt für die Fläche ein Bebauungsplan?** Gastronomie in einem reinen
  Wohngebiet ist ein Genehmigungsproblem, kein Standortproblem — aber es kippt
  die Entscheidung. Wo ein Plan gilt, muss man ihn lesen.

Seit 2026-08-07 zusätzlich: **Liegt die Fläche in einem Gebiet mit
Erhaltungssatzung (Milieuschutz, § 172 BauGB)?** Dort ist jede
Nutzungsänderung — etwa Wohnung zu Gastraum — genehmigungspflichtig und
regelmäßig aussichtslos; auch Umbauten werden strenger geprüft. Verifiziert
per GetFeatureInfo auf ``geoserver/plan/wms``, Layer ``satz_erhalt_poly``
(queryable, führt ``CRS:84``): Haidhausen liefert Gebietsname, Gültig-ab-Datum
und die PDF-Links zu Plan und Satzungstext, der Marienplatz korrekt nichts.

Am 01.08.2026 geprüft, mit Befund:

===================================  ==========================================
Hochwassergefahrenflächen (LfU)      **funktioniert** — liefert Gewässername,
                                     Jährlichkeit und Ermittlungsdatum
Bebauungsplan-Umgriffe (München)     **funktioniert** — liefert die Plannummer
Flächennutzungsplan (München)        nur Kartenebene, ``queryable`` ist nicht
                                     gesetzt — keine Punktabfrage möglich
Lärmwert am Punkt (LfU)              **geht nicht.** Der Dienst antwortet, gibt
                                     aber über 81 Rasterpunkte quer über die
                                     Landshuter Allee durchgehend ``NoData``
                                     zurück. Bleibt Kartenebene.
===================================  ==========================================

Wichtig für die Abfrage: beide Dienste führen **EPSG:4326 nicht** in ihrer
CRS-Liste. Mit ``EPSG:4326`` antworten sie mit einer leeren Trefferliste statt
mit einem Fehler — was wie „nicht betroffen" aussieht und es nicht ist.
Verwendet wird deshalb ``CRS:84`` (WGS84 mit lon,lat-Reihenfolge).
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from typing import Any

from ..config import Settings
from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, SourceResult as _SR, now_iso

# --- Hochwassergefahrenflächen, Bayerisches Landesamt für Umwelt ---
HOCHWASSER_URL = "https://www.lfu.bayern.de/gdi/wms/wasser/ueberschwemmungsgebiete"
HOCHWASSER_LAYER = "hwgf_hqhaeufig,hwgf_hq100,hwgf_hqextrem"
HOCHWASSER_LIZENZ = (
    "Creative Commons Namensnennung 4.0 (CC BY 4.0) · "
    "Bayerisches Landesamt für Umwelt (https://www.lfu.bayern.de)"
)

# --- Bebauungsplan-Umgriffe, Landeshauptstadt München ---
BPLAN_URL = (
    "https://geoportal.muenchen.de/geoserver/gsm_wfs/"
    "vagrund_baug_umgriff_opendata/ows"
)
BPLAN_LAYER = "vagrund_baug_umgriff_opendata"
BPLAN_LIZENZ = (
    "Datenlizenz Deutschland Namensnennung 2.0 (dl-de/by-2-0) · "
    "Landeshauptstadt München, Geoportal"
)

# --- Erhaltungssatzungen (Milieuschutz), Landeshauptstadt München ---
ERHALT_URL = "https://geoportal.muenchen.de/geoserver/plan/wms"
ERHALT_LAYER = "satz_erhalt_poly"

# --- Hochwassergefahren bundesweit: BfG INSPIRE „Natural Risk Zones" ---
# Phase-0 am 2026-08-07: GetFeatureInfo auf ``NZ.HazardArea`` liefert am
# Passauer Rathausplatz drei Treffer (LikelihoodOfOccurrence high, medium,
# low/extrem — also HQhäufig, HQ100, HQextrem in einem Aufruf), am Kölner
# Rheinufer nur low/extrem (hinter der Schutzlinie plausibel) und am
# trockenen Kölner Ring eine leere Antwort. Antwortformat: ESRI-XML
# (``FeatureInfoResponse`` mit ``FIELDS``-Attributen). AccessConstraints:
# „Es gelten keine Zugriffsbeschränkungen".
BUND_HOCHWASSER_URL = (
    "https://geoportal.bafg.de/arcgis1/services/INSPIRE/NZ/MapServer/WMSServer"
)
BUND_HOCHWASSER_LAYER = "NZ.HazardArea"
BUND_HOCHWASSER_LIZENZ = (
    "Bundesanstalt für Gewässerkunde (BfG) / LAWA — INSPIRE View Service "
    "Natural Risk Zones DE; Hochwassergefahrenkarten der Länder nach "
    "HWRM-Richtlinie. „Es gelten keine Zugriffsbeschränkungen“"
)

# Bayern grob — außerhalb spart der Check den Netzaufruf.
BAYERN_BBOX = (47.20, 8.90, 50.60, 13.90)
# München grob, für den städtischen Bebauungsplandienst.
MUENCHEN_BBOX = (48.05, 11.35, 48.25, 11.73)

# Kantenlänge der Abfragebox in Grad. Rund 45 m — klein genug, dass der Treffer
# wirklich am Punkt liegt, groß genug für die Rasterung der Dienste.
BOX = 0.0004


def _im_kasten(kasten: tuple[float, float, float, float], lat: float, lon: float) -> bool:
    return kasten[0] <= lat <= kasten[2] and kasten[1] <= lon <= kasten[3]


def in_bayern(lat: float, lon: float) -> bool:
    return _im_kasten(BAYERN_BBOX, lat, lon)


def in_muenchen(lat: float, lon: float) -> bool:
    return _im_kasten(MUENCHEN_BBOX, lat, lon)


def feature_info_params(layers: str, lat: float, lon: float, box: float = BOX) -> dict[str, str]:
    """GetFeatureInfo mitten in einer kleinen Box.

    ``CRS:84`` statt ``EPSG:4326``: beide Dienste führen 4326 nicht in ihrer
    CRS-Liste und antworten damit mit einer leeren Trefferliste — was wie
    „nicht betroffen" aussieht und es nicht ist.
    """
    return {
        "service": "WMS",
        "version": "1.3.0",
        "request": "GetFeatureInfo",
        "layers": layers,
        "query_layers": layers,
        "styles": "",
        "format": "image/png",
        # Der LfU-Hochwasserdienst kennt nur „geojson", die Münchner
        # GeoServer-Dienste nur „json" — beides live nachgemessen.
        "info_format": "application/geojson"
        if layers == HOCHWASSER_LAYER
        else "application/json",
        "width": "101",
        "height": "101",
        "i": "50",
        "j": "50",
        "crs": "CRS:84",
        "bbox": f"{lon - box},{lat - box},{lon + box},{lat + box}",
        "feature_count": "10",
    }


def _eigenschaften(payload: Any) -> list[dict[str, Any]]:
    features = (payload or {}).get("features") or []
    out = []
    for f in features:
        p = {k: v for k, v in (f.get("properties") or {}).items() if v not in (None, "")}
        if p:
            out.append(p)
    return out


def hochwasser_aufbereiten(payload: Any) -> dict[str, Any]:
    """Die Treffer nach Jährlichkeit ordnen — HQhäufig ist das ernstere Signal."""
    treffer = _eigenschaften(payload)
    gebiete = []
    for p in treffer:
        gebiete.append(
            {
                "gewaesser": p.get("Gewässername") or p.get("Gewaessername"),
                "jaehrlichkeit": p.get("Jährlichkeit") or p.get("Jaehrlichkeit"),
                "ermittelt": p.get("Ermittlungsdatum"),
                "amt": p.get("link_Zuständiges Wasserwirtschaftsamt")
                or p.get("Zuständiges Wasserwirtschaftsamt"),
                "rohwerte": p,
            }
        )
    stufen = {(g["jaehrlichkeit"] or "").upper().replace(" ", "") for g in gebiete}
    return {
        "betroffen": bool(gebiete),
        "gebiete": gebiete,
        "hq_haeufig": any("HÄUFIG" in s or "HAEUFIG" in s for s in stufen),
        "hq_100": any("HQ100" in s for s in stufen),
        "hq_extrem": any("EXTREM" in s for s in stufen),
    }


# Zuordnung der INSPIRE-Wahrscheinlichkeitsstufen zu den HQ-Szenarien der
# Hochwassergefahrenkarten (HWRM-RL): high = häufig, medium = HQ100,
# low/extrem = Extremereignis.
_BUND_STUFEN = {
    "high": ("hq_haeufig", "HQhäufig (hohe Wahrscheinlichkeit)"),
    "medium": ("hq_100", "HQ100 (mittlere Wahrscheinlichkeit)"),
    "low/extrem": ("hq_extrem", "HQextrem (niedrig/Extremereignis)"),
}


def bund_hochwasser_aufbereiten(xml_text: str) -> dict[str, Any]:
    """ESRI-``FeatureInfoResponse`` des BfG-Dienstes → gleiche Form wie die
    LfU-Auswertung, damit Anzeige und Bericht nichts unterscheiden müssen."""
    ergebnis: dict[str, Any] = {
        "betroffen": False, "gebiete": [],
        "hq_haeufig": False, "hq_100": False, "hq_extrem": False,
    }
    try:
        wurzel = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SourceError(
            "parse",
            f"BfG-Hochwasserantwort ist kein XML: {xml_text[:120]!r}",
        ) from exc
    gesehen: set[str] = set()
    for feld in wurzel.iter():
        if not feld.tag.endswith("FIELDS"):
            continue
        stufe = (feld.get("LikelihoodOfOccurrence") or "").strip().lower()
        art = feld.get("SpecificHazardType")
        if stufe in gesehen or stufe not in _BUND_STUFEN:
            continue
        gesehen.add(stufe)
        flag, text = _BUND_STUFEN[stufe]
        ergebnis[flag] = True
        ergebnis["gebiete"].append({
            "gewaesser": None,
            "jaehrlichkeit": text,
            "ermittelt": None,
            "amt": None,
            "rohwerte": {"LikelihoodOfOccurrence": stufe,
                         "SpecificHazardType": art},
        })
    ergebnis["betroffen"] = bool(ergebnis["gebiete"])
    # Ernstestes Szenario zuerst.
    reihenfolge = {"HQhäufig": 0, "HQ100": 1, "HQextrem": 2}
    ergebnis["gebiete"].sort(
        key=lambda g: reihenfolge.get(g["jaehrlichkeit"].split(" ")[0], 9))
    return ergebnis


def erhalt_aufbereiten(payload: Any) -> dict[str, Any]:
    """Erhaltungssatzungs-Treffer: Gebietsname, gültig ab, Satzungs-PDFs."""
    gebiete = [
        {
            "name": p.get("gebietname"),
            "gueltig_ab": p.get("gueltig_ab"),
            "plan_pdf": p.get("p_url"),
            "text_pdf": p.get("t_url"),
            "info_pdf": p.get("d_url"),
            "rohwerte": p,
        }
        for p in _eigenschaften(payload)
    ]
    return {"betroffen": bool(gebiete), "gebiete": gebiete}


def bplan_aufbereiten(payload: Any) -> dict[str, Any]:
    treffer = _eigenschaften(payload)
    plaene = [
        {
            "nummer": p.get("nr_plan"),
            "verfahren": p.get("nr_va") if p.get("nr_va") != "unbekannt" else None,
            "rohwerte": p,
        }
        for p in treffer
    ]
    return {"vorhanden": bool(plaene), "plaene": plaene}


HINWEISE = [
    "Ein Bebauungsplan sagt hier nur, **dass** es einen gibt — nicht, was er "
    "erlaubt. Was für die Fläche gilt, steht im Plan selbst; die Nummer ist der "
    "Einstieg dafür.",
    "Wo kein Plan ausgewiesen ist, heißt das nicht „alles erlaubt“: im "
    "unbeplanten Innenbereich gilt § 34 BauGB, also das Einfügen in die "
    "Umgebung. Auskunft gibt nur die Bauaufsicht.",
    "Die Hochwassergefahrenflächen sind Berechnungsergebnisse mit Stichtag, "
    "keine Zusage. Für Versicherung und Ausbau zählt die Auskunft des "
    "zuständigen Wasserwirtschaftsamts.",
    "In einem Erhaltungssatzungsgebiet (§ 172 BauGB) ist die **Umwandlung "
    "von Wohnraum in einen Gastraum praktisch ausgeschlossen** und jeder "
    "Umbau genehmigungspflichtig. Eine bestehende Gewerbefläche zu "
    "übernehmen bleibt möglich — was gilt, steht im verlinkten Satzungstext.",
]

PORTALE = [
    {
        "titel": "Geoportal München — Fachportal PLAN (Bebauungspläne im Original)",
        "url": "https://geoportal.muenchen.de/portal/plan",
    },
    {
        "titel": "Geoportal München — Flächennutzungsplan",
        "url": "https://geoportal.muenchen.de/portal/fnp",
    },
    {
        "titel": "LfU Bayern — Hochwassergefahrenflächen im Kartendienst",
        "url": "https://www.lfu.bayern.de/wasser/hw_ue_gebiete/index.htm",
    },
]


def _bund_gfi_params(lat: float, lon: float) -> dict[str, str]:
    """GetFeatureInfo für den BfG-INSPIRE-Dienst. Er antwortet mit
    ESRI-XML (``text/xml``) — live verifiziert; ``CRS:84`` wie überall."""
    d = BOX
    return {
        "service": "WMS",
        "version": "1.3.0",
        "request": "GetFeatureInfo",
        "layers": BUND_HOCHWASSER_LAYER,
        "query_layers": BUND_HOCHWASSER_LAYER,
        "styles": "",
        "crs": "CRS:84",
        "bbox": f"{lon - d},{lat - d},{lon + d},{lat + d}",
        "width": "101",
        "height": "101",
        "i": "50",
        "j": "50",
        "info_format": "text/xml",
        "feature_count": "10",
    }


async def load(
    out: Outbound, settings: Settings, lat: float, lon: float, radius: int
) -> SourceResult:
    started = time.perf_counter()
    if not in_bayern(lat, lon):
        # Bundesweite Hochwassergefahrenkarten (BfG/LAWA); Bebauungsplan
        # und Milieuschutz bleiben Stadtdienste und fehlen hier ehrlich.
        warnungen = [
            "Bebauungspläne und Erhaltungssatzungen sind kommunale Dienste "
            "und hier nur für München eingebunden — außerhalb sagt der "
            "Block dazu nichts. Die Hochwassergefahren kommen bundesweit "
            "von BfG/LAWA."
        ]
        data: dict[str, Any] = {
            "portale": [PORTALE[-1]], "hinweise": HINWEISE,
        }
        try:
            text = await out.get_text(
                "bfg_hochwasser",
                BUND_HOCHWASSER_URL,
                params=_bund_gfi_params(lat, lon),
                timeout=60.0,
                limiter="bfg",
                min_interval=1.0,
            )
            data["hochwasser"] = bund_hochwasser_aufbereiten(text)
            data["hochwasser"]["dienst"] = "bfg"
        except SourceError as err:
            return SourceResult.failed(
                "planung", err, int((time.perf_counter() - started) * 1000)
            )
        return _SR(
            name="planung",
            ok=True,
            data=data,
            duration_ms=int((time.perf_counter() - started) * 1000),
            warnings=warnungen,
            provenance=Provenance(
                source=(
                    "Hochwassergefahrenkarten der Länder (HWRM-Richtlinie) "
                    "über den BfG-INSPIRE-Dienst „Natural Risk Zones DE“"
                ),
                license=BUND_HOCHWASSER_LIZENZ,
                endpoint=BUND_HOCHWASSER_URL,
                retrieved_at=now_iso(),
                note=(
                    "Punktabfrage über GetFeatureInfo. Stufen: high = "
                    "HQhäufig, medium = HQ100, low/extrem = HQextrem. "
                    "Gewässername und Ermittlungsdatum führt der "
                    "Bundesdienst nicht — dafür die Landesportale."
                ),
            ),
        )

    warnungen = []
    data = {"portale": PORTALE, "hinweise": HINWEISE}

    try:
        payload = await out.get_json(
            "lfu_hochwasser",
            HOCHWASSER_URL,
            params=feature_info_params(HOCHWASSER_LAYER, lat, lon),
            timeout=60.0,
            limiter="lfu",
            min_interval=1.0,
        )
        data["hochwasser"] = hochwasser_aufbereiten(payload)
        data["hochwasser"]["dienst"] = "lfu"
    except SourceError as err:
        return SourceResult.failed(
            "planung", err, int((time.perf_counter() - started) * 1000)
        )

    if in_muenchen(lat, lon):
        try:
            payload = await out.get_json(
                "muenchen_bplan",
                BPLAN_URL,
                params=feature_info_params(BPLAN_LAYER, lat, lon),
                timeout=60.0,
                limiter="muenchen",
                min_interval=1.0,
            )
            data["bebauungsplan"] = bplan_aufbereiten(payload)
        except SourceError as err:
            warnungen.append(
                f"Bebauungsplan-Umgriffe der Stadt München nicht abrufbar: {err.message}"
            )
        try:
            payload = await out.get_json(
                "muenchen_erhaltungssatzung",
                ERHALT_URL,
                params=feature_info_params(ERHALT_LAYER, lat, lon),
                timeout=60.0,
                limiter="muenchen",
                min_interval=1.0,
            )
            data["erhaltungssatzung"] = erhalt_aufbereiten(payload)
        except SourceError as err:
            warnungen.append(
                f"Erhaltungssatzungs-Gebiete der Stadt München nicht abrufbar: {err.message}"
            )
    else:
        warnungen.append(
            "Bebauungspläne und Erhaltungssatzungen kommen aus dem Geoportal der "
            "Landeshauptstadt München und liegen deshalb nur für das Stadtgebiet vor."
        )

    return _SR(
        name="planung",
        ok=True,
        data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnungen,
        provenance=Provenance(
            source=(
                "Hochwassergefahrenflächen: Bayerisches Landesamt für Umwelt · "
                "Bebauungsplan-Umgriffe und Erhaltungssatzungen: "
                "Landeshauptstadt München"
            ),
            license=f"{HOCHWASSER_LIZENZ} · {BPLAN_LIZENZ}",
            endpoint=HOCHWASSER_URL,
            retrieved_at=now_iso(),
            note=(
                "Punktabfrage über GetFeatureInfo. Der Flächennutzungsplan ist "
                "nicht abfragbar und liegt nur als Kartenebene vor."
            ),
        ),
    )
