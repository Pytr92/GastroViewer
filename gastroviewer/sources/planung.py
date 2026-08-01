"""Planungsrecht und Hochwasserrisiko am Punkt.

Zwei Fragen, die eine Standortentscheidung kippen können und die keine der
bisherigen Quellen beantwortet:

* **Liegt die Fläche in einem Hochwassergefahrengebiet?** Für Keller, Lager,
  Kühltechnik und die Versicherungsprämie ist das entscheidend.
* **Gilt für die Fläche ein Bebauungsplan?** Gastronomie in einem reinen
  Wohngebiet ist ein Genehmigungsproblem, kein Standortproblem — aber es kippt
  die Entscheidung. Wo ein Plan gilt, muss man ihn lesen.

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
        "info_format": "application/json"
        if layers == BPLAN_LAYER
        else "application/geojson",
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


async def load(
    out: Outbound, settings: Settings, lat: float, lon: float, radius: int
) -> SourceResult:
    started = time.perf_counter()
    if not in_bayern(lat, lon):
        return _SR(
            name="planung",
            ok=True,
            data=None,
            warnings=[
                "Die Hochwasser- und Planungsdienste dieses Blocks decken Bayern "
                "bzw. München ab. Für andere Länder führen die Behörden eigene "
                "Dienste; im Werkzeug ist keiner davon eingebunden."
            ],
            provenance=Provenance(
                source="Planung & Hochwasser (außerhalb Bayerns)",
                license=HOCHWASSER_LIZENZ,
            ),
        )

    warnungen: list[str] = []
    data: dict[str, Any] = {"portale": PORTALE, "hinweise": HINWEISE}

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
    else:
        warnungen.append(
            "Bebauungspläne kommen aus dem Geoportal der Landeshauptstadt München "
            "und liegen deshalb nur für das Stadtgebiet vor."
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
                "Bebauungsplan-Umgriffe: Landeshauptstadt München"
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
