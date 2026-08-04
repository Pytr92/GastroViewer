"""Straßenlärm am Punkt — Umgebungslärmkartierung des LfU Bayern.

Für Außengastronomie ist Straßenlärm eine Standorteigenschaft wie Sonne
oder Passantenlage. Die EU-Umgebungslärmkartierung liefert berechnete
Pegel an Hauptverkehrsstraßen; das LfU Bayern stellt sie als WMS bereit,
und ``GetFeatureInfo`` gibt den Rasterwert (dB(A)) am Punkt zurück.

Phase-0 verifiziert am 2026-08-04 (Mittlerer Ring München: LDEN 65,6 /
LNight 56,9 dB(A), Kartierung 2017):

* ``https://www.lfu.bayern.de/gdi/wms/laerm/hauptverkehrsstrassen`` —
  ``GetFeatureInfo`` mit ``info_format=application/geojson`` liefert
  ``{"Classify.Pixel Value": "65.58…"}`` oder ``"NoData"``.
* Die **2022er-Schichten decken nur Gebiete außerhalb der Ballungsräume**
  ab; innerhalb (z. B. München) ist die jüngste LfU-Fläche die Kartierung
  2017. Deshalb wird 2022 zuerst gefragt und bei NoData auf 2017
  zurückgegriffen — das Kartierungsjahr steht immer dabei.
* ``GetMap`` verlangt einen ``styles``-Parameter; ``GetFeatureInfo``
  funktioniert auch ohne, er wird trotzdem mitgesendet.

Die zwei ehrlichen Grenzen, die in jede Anzeige gehören: Kartiert ist nur
der Straßenlärm an **Hauptverkehrsstraßen** (außerhalb der Ballungsräume:
> 3 Mio. Kfz/Jahr). „NoData" heißt also „keine kartierte Hauptverkehrs-
straße am Punkt", nicht „leise" — Nebenstraßen-, Schienen-, Flug- und
Gewerbelärm sind hier nicht enthalten. Und es sind berechnete Pegel aus
der Kartierung, keine Messwerte am Haus.
"""

from __future__ import annotations

import time
from typing import Any

from ..config import Settings
from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, now_iso

WMS_URL = "https://www.lfu.bayern.de/gdi/wms/laerm/hauptverkehrsstrassen"
LIZENZ = "© Bayerisches Landesamt für Umwelt (LfU) · www.lfu.bayern.de"

# Reihenfolge = Abfragereihenfolge: jüngste Kartierung zuerst, bei NoData
# die nächstältere. 2022 deckt nur Gebiete außerhalb der Ballungsräume ab.
SCHICHTEN = [
    {"kartierung": 2022, "lden": "mroadbylden2022", "lnight": "mroadbyln2022",
     "abdeckung": "außerhalb der Ballungsräume"},
    {"kartierung": 2017, "lden": "mroadbylden2017", "lnight": "mroadbyln2017",
     "abdeckung": "einschließlich der Ballungsräume"},
]

# Halbe Kantenlänge der Abfragebox in Grad (~55 m in der Breite) — nur das
# Abfragefenster um den Mittelpixel, kein fachlicher Radius.
BOX_GRAD = 0.0005

# Klassengrenzen der Kartierung selbst (Legende des Dienstes):
# über 55–60, 60–65, 65–70, 70–75, über 75 dB(A).
KLASSEN = [55, 60, 65, 70, 75]


def klasse(wert_db: float) -> str:
    """Das Band der Kartierungslegende, in dem der Wert liegt."""
    if wert_db <= KLASSEN[0]:
        return f"bis {KLASSEN[0]} dB(A)"
    if wert_db > KLASSEN[-1]:
        return f"über {KLASSEN[-1]} dB(A)"
    for unter, ober in zip(KLASSEN, KLASSEN[1:]):
        if wert_db <= ober:
            return f"über {unter} bis {ober} dB(A)"
    return f"über {KLASSEN[-1]} dB(A)"  # unerreichbar, hält den Typ ehrlich


def wert_aus(payload: Any) -> float | None:
    """Pixelwert aus der GetFeatureInfo-Antwort — ``None`` bei NoData.

    Der Schlüssel heißt wörtlich „Classify.Pixel Value" (mit Leerzeichen);
    verglichen wird deshalb unscharf über den normalisierten Namen."""
    for f in (payload or {}).get("features") or []:
        for k, v in (f.get("properties") or {}).items():
            kn = str(k).replace(" ", "").lower()
            if kn.endswith("pixelvalue"):
                s = str(v).strip()
                if not s or s.lower() == "nodata":
                    return None
                try:
                    return float(s)
                except ValueError:
                    return None
    return None


def params_fuer(layer: str, lat: float, lon: float) -> dict[str, str]:
    d = BOX_GRAD
    return {
        "service": "WMS",
        "version": "1.3.0",
        "request": "GetFeatureInfo",
        "layers": layer,
        "query_layers": layer,
        "styles": "",
        "crs": "CRS:84",
        "bbox": f"{lon - d},{lat - d},{lon + d},{lat + d}",
        "width": "101",
        "height": "101",
        "i": "50",
        "j": "50",
        "info_format": "application/geojson",
        "feature_count": "5",
    }


HINWEISE = [
    "Kartiert ist nur Straßenlärm an Hauptverkehrsstraßen (außerhalb der "
    "Ballungsräume: mehr als 3 Mio. Kfz/Jahr). „Nicht kartiert“ heißt deshalb "
    "„keine kartierte Hauptverkehrsstraße am Punkt“ — nicht „leise“. "
    "Nebenstraßen-, Schienen-, Flug- und Gewerbelärm fehlen hier.",
    "Berechnete Pegel aus der EU-Umgebungslärmkartierung, keine Messwerte am "
    "Haus. LDEN ist der Tag-Abend-Nacht-Pegel (Abend und Nacht mit Zuschlag), "
    "LNight der Nachtpegel 22–6 Uhr.",
    "Innerhalb der Ballungsräume (etwa München) ist die jüngste flächige "
    "LfU-Kartierung die von 2017 — die 2022er-Runde des LfU deckt nur Gebiete "
    "außerhalb ab. Das Kartierungsjahr steht an jedem Wert.",
]


async def load(
    out: Outbound, settings: Settings, lat: float, lon: float,
    bundesland_code: str | None,
) -> SourceResult:
    started = time.perf_counter()

    if bundesland_code != "09":
        return SourceResult(
            name="laerm", ok=True, data=None,
            warnings=[
                "Die Umgebungslärmkartierung ist hier als Dienst des LfU "
                "Bayern angebunden — für Punkte außerhalb Bayerns liegt "
                "keine Karte vor. Andere Länder führen eigene Dienste."
            ],
        )

    async def pegel(metrik: str) -> dict[str, Any]:
        """Jüngste Kartierung zuerst; NoData → nächstältere Schicht."""
        for schicht in SCHICHTEN:
            payload = await out.get_json(
                "laerm", WMS_URL,
                params=params_fuer(schicht[metrik], lat, lon),
                timeout=45.0,
            )
            wert = wert_aus(payload)
            if wert is not None:
                return {
                    "wert_db": round(wert, 1),
                    "klasse": klasse(wert),
                    "kartierung": schicht["kartierung"],
                    "abdeckung": schicht["abdeckung"],
                }
        return {"wert_db": None, "klasse": None, "kartierung": None,
                "abdeckung": None}

    try:
        lden = await pegel("lden")
        lnight = await pegel("lnight")
    except SourceError as err:
        return SourceResult.failed(
            "laerm", err, int((time.perf_counter() - started) * 1000)
        )

    kartiert = lden["wert_db"] is not None or lnight["wert_db"] is not None
    data = {
        "lden": lden,
        "lnight": lnight,
        "kartiert": kartiert,
        "hinweise": HINWEISE,
    }

    warnungen: list[str] = []
    if not kartiert:
        warnungen.append(
            "Am Punkt liegt keine kartierte Hauptverkehrsstraßen-Belastung — "
            "für Außengastronomie meist die gute Nachricht, aber keine "
            "Aussage über Nebenstraßen-, Schienen- oder Gewerbelärm."
        )

    return SourceResult(
        name="laerm",
        ok=True,
        data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnungen,
        provenance=Provenance(
            source="Umgebungslärmkartierung Bayern (LfU, WMS „Lärm an Hauptverkehrsstraßen“)",
            license=LIZENZ,
            endpoint=WMS_URL,
            stand="Kartierungsrunden 2017 (inkl. Ballungsräume) und 2022 (außerhalb)",
            retrieved_at=now_iso(),
            note=(
                "Berechnete Pegel der EU-Umgebungslärmkartierung am Punkt "
                "(Rasterabfrage), keine Messwerte. Nur Straßenlärm an "
                "Hauptverkehrsstraßen."
            ),
        ),
    )
