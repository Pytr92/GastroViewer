"""Kfz-Verkehrsstärke außerhalb Bayerns — BASt-Dauerzählstellen.

In Bayern liefert BAYSIS 9 441 Zählstellen im ganzen klassifizierten
Netz. Für die übrigen Länder gibt es bundesweit offen nur die
automatischen Dauerzählstellen der Bundesanstalt für Straßenwesen:
**2 127 Querschnitte (Jahr 2024), ausschließlich Autobahnen und
Bundesstraßen** — dünner, aber gemessen statt geschätzt.

Phase-0 am 2026-08-07 mit echtem Download verifiziert:

* ``https://www.bast.de/DE/Themen/Digitales/HF_1/Massnahmen/
  verkehrszaehlung/Daten/2024_1/Jawe2024.csv?view=renderTcDataExportCSV``
  — HTTP 200, 1,84 MB, Semikolon-CSV in **Latin-1**, 255 Spalten,
  2 127 Datenzeilen.
* Genutzte Spalten: ``DZ_Name`` (Zählstellenname), ``Land_Code``,
  ``Str_Kl``/``Str_Nr`` (Straßenklasse und -nummer, z. B. A 1),
  ``DTV_Kfz_MobisSo_Q`` (DTV Mo–So, Querschnitt),
  ``DTV_SV_MobisSo_Q`` (Schwerverkehr), ``Koor_WGS84_N``/``…_E``.
* Zahlen im deutschen Format (Tausenderpunkt, Dezimalkomma); Zählstellen
  ohne Jahreswert (z. B. „Netzmodernisierung in 2024") haben leere
  DTV-Felder und werden mit ``None`` geführt, nicht mit 0.
* Nutzungsbedingungen der Seite: Creative Commons Namensnennung 4.0
  (CC BY 4.0), Bundesanstalt für Straßenwesen.

Der Datensatz wird **einmal** geladen und stadtweit gecacht (Jahresdatei);
jeder Punkt rechnet danach lokal. Die Blockform entspricht der
BAYSIS-Auswertung, damit Anzeige und Bericht nichts unterscheiden müssen.
"""

from __future__ import annotations

import csv
import io
import time
from typing import Any, Awaitable, Callable

from .base import (Provenance, SourceError, SourceResult, bearing_label,
                   haversine_m, now_iso)

JAHR = 2024
CSV_URL = (
    "https://www.bast.de/DE/Themen/Digitales/HF_1/Massnahmen/"
    f"verkehrszaehlung/Daten/{JAHR}_1/Jawe{JAHR}.csv"
    "?view=renderTcDataExportCSV"
)
LIZENZ = (
    "Creative Commons Namensnennung 4.0 (CC BY 4.0) · "
    "Bundesanstalt für Straßenwesen (BASt), automatische "
    "Straßenverkehrszählung"
)
PORTAL = (
    "https://www.bast.de/DE/Themen/Digitales/HF_1/Massnahmen/"
    "verkehrszaehlung/zaehl_node.html"
)

# Das BASt-Netz ist dünn (nur Autobahnen und Bundesstraßen) — ohne einen
# größeren Suchradius bliebe der Block fast überall leer. Die Entfernung
# steht an jedem Wert.
MAX_DISTANZ_M = 5000


def _zahl(s: str | None) -> int | float | None:
    """Deutsches Zahlenformat („111.624", „53,50754848") → Zahl."""
    t = str(s or "").strip()
    if not t:
        return None
    t = t.replace(".", "").replace(",", ".")
    try:
        wert = float(t)
    except ValueError:
        return None
    return int(wert) if wert == int(wert) else wert


def _koordinate(s: str | None) -> float | None:
    """Koordinaten tragen nur das Dezimalkomma, keinen Tausenderpunkt."""
    t = str(s or "").strip()
    if not t:
        return None
    try:
        return float(t.replace(",", "."))
    except ValueError:
        return None


def parse_zaehlstellen(csv_text: str) -> list[dict[str, Any]]:
    """Jahresdatei → reduzierte Zählstellenliste (nur belegte Felder)."""
    reader = csv.DictReader(io.StringIO(csv_text), delimiter=";")
    felder = set(reader.fieldnames or [])
    pflicht = {"DZ_Name", "Str_Kl", "Str_Nr", "Koor_WGS84_N", "Koor_WGS84_E",
               "DTV_Kfz_MobisSo_Q", "DTV_SV_MobisSo_Q"}
    if not pflicht <= felder:
        raise SourceError(
            "parse",
            "BASt-Jahresdatei hat unerwartete Spalten — Format geändert? "
            f"Fehlend: {', '.join(sorted(pflicht - felder))[:200]}",
        )
    stellen = []
    for r in reader:
        lat = _koordinate(r.get("Koor_WGS84_N"))
        lon = _koordinate(r.get("Koor_WGS84_E"))
        if lat is None or lon is None:
            continue
        klasse = (r.get("Str_Kl") or "").strip()
        nummer = (r.get("Str_Nr") or "").strip()
        stellen.append({
            "name": (r.get("DZ_Name") or "").strip() or None,
            "land": (r.get("Land_Code") or "").strip() or None,
            "strasse": f"{klasse} {nummer}".strip() or None,
            "lat": lat,
            "lon": lon,
            "dtv_kfz": _zahl(r.get("DTV_Kfz_MobisSo_Q")),
            "dtv_schwerverkehr": _zahl(r.get("DTV_SV_MobisSo_Q")),
        })
    return stellen


def aufbereiten(
    stellen: list[dict[str, Any]], lat: float, lon: float, radius: int
) -> dict[str, Any]:
    """Gleiches Ergebnisformat wie die BAYSIS-Auswertung."""
    treffer = []
    for s in stellen:
        dist = haversine_m(lat, lon, s["lat"], s["lon"])
        if dist > MAX_DISTANZ_M:
            continue
        kfz, sv = s["dtv_kfz"], s["dtv_schwerverkehr"]
        treffer.append({
            "strasse": s["strasse"],
            "zaehlstelle": s["name"],
            "zaehlart": "Dauerzählstelle (BASt)",
            "lat": s["lat"],
            "lon": s["lon"],
            "distanz_m": round(dist),
            "richtung": bearing_label(lat, lon, s["lat"], s["lon"]),
            "im_radius": dist <= radius,
            "dtv_kfz": kfz,
            "dtv_leichtverkehr": (
                kfz - sv if kfz is not None and sv is not None else None
            ),
            "dtv_schwerverkehr": sv,
            "schwerverkehr_anteil": (
                round(sv / kfz * 100, 1)
                if kfz and sv is not None and kfz > 0 else None
            ),
        })
    treffer.sort(key=lambda s: s["distanz_m"])
    treffer = treffer[:12]
    mit_wert = [s for s in treffer if s["dtv_kfz"] is not None]
    return {
        "zaehlstellen": treffer,
        "naechste": treffer[0] if treffer else None,
        "staerkste": max(mit_wert, key=lambda s: s["dtv_kfz"]) if mit_wert else None,
        "im_radius": [s for s in treffer if s["im_radius"]],
        "max_distanz_m": MAX_DISTANZ_M,
        "jahr": JAHR,
        "dienst": "bast",
        "portal": PORTAL,
    }


HINWEISE = [
    "Die BASt-Dauerzählstellen messen nur **Autobahnen und Bundesstraßen** "
    f"— deshalb der große Suchradius ({MAX_DISTANZ_M // 1000} km). Für "
    "innerstädtische Lagen ist die nächste Zählstelle oft nicht die Straße "
    "vor der Tür; die Entfernung steht an jedem Wert.",
    "DTV ist der durchschnittliche tägliche Verkehr Montag–Sonntag am "
    f"Querschnitt, Jahresauswertung {JAHR}. Zählstellen ohne Jahreswert "
    "(Umbau, Ausfall) erscheinen ohne Zahl statt mit 0.",
]


async def verkehrsmengen(
    lat: float, lon: float, radius: int,
    zaehlstellen_laden: Callable[[], Awaitable[list[dict[str, Any]]]],
) -> SourceResult:
    """Blockergebnis außerhalb Bayerns. ``zaehlstellen_laden`` liefert die
    (gecachte) bundesweite Liste — hier wird nur noch lokal gerechnet."""
    started = time.perf_counter()
    try:
        stellen = await zaehlstellen_laden()
    except SourceError as err:
        return SourceResult.failed(
            "verkehrsmenge", err, int((time.perf_counter() - started) * 1000)
        )

    data = aufbereiten(stellen, lat, lon, radius)
    data["hinweise"] = HINWEISE

    warnungen: list[str] = []
    if not data["zaehlstellen"]:
        warnungen.append(
            f"Keine BASt-Dauerzählstelle innerhalb von {MAX_DISTANZ_M} m. "
            "Gemessen werden bundesweit nur Autobahnen und Bundesstraßen — "
            "in Innenstädten ohne solche Achse bleibt der Block leer."
        )

    return SourceResult(
        name="verkehrsmenge",
        ok=True,
        data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnungen,
        provenance=Provenance(
            source=(
                "BASt — automatische Straßenverkehrszählung, "
                f"Jahresauswertung {JAHR} (bundesweit)"
            ),
            license=LIZENZ,
            endpoint=CSV_URL,
            stand=f"Jahresauswertung {JAHR}",
            retrieved_at=now_iso(),
            note=(
                "Jahresdatei einmal geladen und lokal ausgewertet. Nur "
                "Autobahnen und Bundesstraßen; in Bayern liefert BAYSIS "
                "das dichtere Netz."
            ),
        ),
    )
