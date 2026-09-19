"""Starkregen-Hinweiskarte (BKG) — Wassertiefe am Punkt bei Starkregen.

Ergänzt den Hochwasserblock (``planung.py``), der nur Flusshochwasser
kennt: Keller, Lager und Kühltechnik sind häufiger vom Starkregen
betroffen als vom Fluss. Der BKG-Dienst ``wms_starkregen`` (Hinweiskarte
Starkregengefahren, HWK_SRG) rechnet zwei Szenarien — **außergewöhnlich**
(``_agw``) und **extrem** — und führt je Bundesland Layer für Wassertiefe
(``<land>_tiefe_agw``), Fließgeschwindigkeit (``<land>_geschw_agw``) und
Fließrichtung; die Sammellayer ``tiefe_agw``, ``tiefe_extrem``,
``geschwindigkeit_agw``, ``geschwindigkeit_extrem`` fragen alle Länder
zugleich.

Live belegt am 18.09.2026 (fixtures/de, Probe Runde 5 und 6):

* GetFeatureInfo mit ``crs=CRS:84`` und ``info_format=application/json``
  antwortet mit einer FeatureCollection ohne Geometrie; je getroffenem
  Landeslayer ein Feature mit ``properties.Tiefe`` (Zentimeter) bzw.
  ``properties.Geschwindigkeit`` (m/s). Am Alexanderplatz 39 cm
  (außergewöhnlich), in Dresden 3 cm, in Köln 0 cm; ``-9999`` ist „kein
  Wert“ (Gewässer, Gebäude, Rand).
* Abgedeckt sind **13 Länder**: BB, BE, HB, HH, MV, NI, NW, RP, SH, SL,
  SN, ST, TH. Bayern, Baden-Württemberg und Hessen fehlen im Dienst —
  dort antwortet er leer, und der Block sagt das, statt „trocken“ zu
  behaupten. Bayern hat eine eigene Hinweiskarte (nur Kartenebene),
  BW/HE Länderkarten ohne belegten Punktdienst.
"""

from __future__ import annotations

import time
from typing import Any

from ..http import Outbound
from .base import SourceError

WMS_URL = "https://sgx.geodatenzentrum.de/wms_starkregen"
LIZENZ = "Datenlizenz Deutschland – Namensnennung – Version 2.0 (dl-de/by-2-0) · © GeoBasis-DE / BKG"
ABGEDECKT = {"BB", "BE", "HB", "HH", "MV", "NI", "NW", "RP", "SH", "SL", "SN", "ST", "TH"}
NICHT_ABGEDECKT = {"BY": "Bayern", "BW": "Baden-Württemberg", "HE": "Hessen"}
BOX = 0.0004
NODATA = -9999

SZENARIEN = {"agw": "außergewöhnlich (ca. 100-jährlich)", "extrem": "extrem"}

HINWEISE = [
    "Die Hinweiskarte ist eine **bundesweit einheitliche Modellrechnung** "
    "(BKG mit den Ländern) — kein Ersatz für die kommunale Starkregen-"
    "gefahrenkarte, aber ein früher Hinweis auf Senken und Fließwege.",
    "Wassertiefe in Zentimetern am Punkt; 0 cm heißt „kein Wasserstand im "
    "Modell“, nicht „kein Risiko“ — Kellerlichtschächte und Tiefgaragen-"
    "zufahrten liegen unter dem Geländeniveau, das die Karte kennt.",
]


def gfi_params(layer: str, lat: float, lon: float, box: float = BOX) -> dict[str, str]:
    return {
        "service": "WMS", "version": "1.3.0", "request": "GetFeatureInfo",
        "layers": layer, "query_layers": layer, "styles": "", "crs": "CRS:84",
        "bbox": f"{lon - box},{lat - box},{lon + box},{lat + box}",
        "width": "101", "height": "101", "i": "50", "j": "50",
        "info_format": "application/json", "feature_count": "10",
    }


def wert(payload: Any, feld: str) -> float | None:
    """Größter gültiger Wert über die getroffenen Landeslayer (an Landes-
    grenzen liegen zwei übereinander); ``None`` ohne gültigen Treffer."""
    werte = []
    for f in (payload or {}).get("features") or [] if isinstance(payload, dict) else []:
        v = (f.get("properties") or {}).get(feld)
        if isinstance(v, (int, float)) and v != NODATA:
            werte.append(float(v))
    return max(werte) if werte else None


def einordnung(tiefe_cm: float | None) -> str | None:
    if tiefe_cm is None:
        return None
    if tiefe_cm < 10:
        return "unter 10 cm — Pfützen, kein Eindringen zu erwarten"
    if tiefe_cm < 30:
        return "10–30 cm — Bordsteinhöhe, Schwellen und Lichtschächte gefährdet"
    if tiefe_cm < 50:
        return "30–50 cm — Wasser dringt in Erdgeschosse ohne Schutz ein"
    return "über 50 cm — ernste Gefährdung, Tiefgaragen und Keller"


async def load(out: Outbound, lat: float, lon: float, bundesland_iso: str | None) -> dict[str, Any]:
    """Teilblock für ``planung.data["starkregen"]``. Wirft ``SourceError``,
    wenn der Dienst nicht antwortet; die Landesabdeckung wird vorher
    geprüft, damit außerhalb kein Aufruf hinausgeht."""
    started = time.perf_counter()
    land = (bundesland_iso or "").split("-")[-1].upper() or None
    if land in NICHT_ABGEDECKT:
        return {
            "abgefragt": False, "dienst": "bkg", "land": land,
            "hinweis": (f"Die BKG-Hinweiskarte deckt {NICHT_ABGEDECKT[land]} nicht ab — dort gibt es nur "
                        "die Landeskarte ohne Punktabfrage."),
            "hinweise": HINWEISE,
        }
    ergebnis: dict[str, Any] = {"abgefragt": True, "dienst": "bkg", "land": land, "szenarien": {},
                                "hinweise": HINWEISE, "dauer_ms": None}
    for kurz, titel in SZENARIEN.items():
        tiefe = await out.get_json(
            "bkg_starkregen", WMS_URL, params=gfi_params(f"tiefe_{kurz}", lat, lon),
            timeout=45.0, limiter="bkg", min_interval=0.5)
        geschw = await out.get_json(
            "bkg_starkregen", WMS_URL, params=gfi_params(f"geschwindigkeit_{kurz}", lat, lon),
            timeout=45.0, limiter="bkg", min_interval=0.5)
        t, g = wert(tiefe, "Tiefe"), wert(geschw, "Geschwindigkeit")
        ergebnis["szenarien"][kurz] = {
            "titel": titel, "tiefe_cm": t, "geschwindigkeit_ms": g, "einordnung": einordnung(t),
            "kartiert": t is not None,
        }
    ergebnis["kartiert"] = any(s["kartiert"] for s in ergebnis["szenarien"].values())
    ergebnis["tiefe_max_cm"] = max((s["tiefe_cm"] for s in ergebnis["szenarien"].values()
                                    if s["tiefe_cm"] is not None), default=None)
    if not ergebnis["kartiert"]:
        ergebnis["hinweis"] = ("Am Punkt liefert die Hinweiskarte keinen Wert — außerhalb der 13 "
                               "abgedeckten Länder, auf einem Gewässer oder einem Gebäude.")
    ergebnis["dauer_ms"] = int((time.perf_counter() - started) * 1000)
    return ergebnis


__all__ = ["WMS_URL", "LIZENZ", "ABGEDECKT", "gfi_params", "wert", "einordnung", "load", "SourceError"]
