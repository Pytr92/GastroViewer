"""Straßenlärm am Punkt — EU-Umgebungslärmkartierung, bundesweit.

Für Außengastronomie ist Straßenlärm eine Standorteigenschaft wie Sonne
oder Passantenlage. Zwei Dienste, nach Präzision gestaffelt:

**Bayern — LfU-WMS** (Phase-0 am 2026-08-04, Mittlerer Ring München:
LDEN 65,6 / LNight 56,9 dB(A), Kartierung 2017):

* ``https://www.lfu.bayern.de/gdi/wms/laerm/hauptverkehrsstrassen`` —
  ``GetFeatureInfo`` mit ``info_format=application/geojson`` liefert
  ``{"Classify.Pixel Value": "65.58…"}`` oder ``"NoData"``. Rasterwerte
  mit Nachkommastelle — präziser als die 5-dB-Klassen des Bundesdienstes,
  deshalb bleibt der LfU-Dienst für Bayern erste Wahl.
* Die 2022er-Schichten decken nur Gebiete außerhalb der Ballungsräume ab;
  innerhalb (z. B. München) ist die jüngste LfU-Fläche die Kartierung
  2017 — 2022 zuerst, bei NoData 2017, Jahr steht immer dabei.

**Restliches Bundesgebiet — UBA-WMS „VeLa/LK"** (Phase-0 am 2026-08-07,
Berlin Hermannplatz: road Lden7074/Lnight6569; Hamburg Reeperbahn:
Lden7074; Köln Nord-Süd-Fahrt: Lden5559; München Sendlinger Tor über
denselben Dienst: Lden6569 — der Bundesdienst enthält auch Bayern und
diente als Gegenprobe):

* ``https://datahub.uba.de/server/services/VeLa/LK/MapServer/WMSServer``
  (ArcGIS-WMS, „Lärmkartierung nach der EU-Umgebungslärmrichtlinie",
  Stand der Daten 12/2023, Kartierungsrunde 2022).
* Layer ``35`` (``LK_BLR_Abfrage``) beantwortet **in Ballungsräumen** eine
  einzige Klickabfrage mit allen Quellen: ``road_den``, ``road_night``,
  ``rail_den``, ``rail_night``, ``air_den``, ``air_night`` als
  Pegelklassen (``Lden6569``, ``LnightGreaterThan70`` …) plus
  Gemeindename. Außerhalb der Ballungsräume ist der Abfrage-Layer leer —
  dann liefern die Einzel-Layer ``30`` (``LK_HLQ_road_Den``) und ``29``
  (``LK_HLQ_road_Night``) den Straßenlärm an Hauptverkehrsstraßen.
* Antworten sind **5-dB-Klassen**, keine Rasterwerte — die Anzeige nennt
  deshalb die Spanne statt einer Scheinpräzision.

Die zwei ehrlichen Grenzen, die in jede Anzeige gehören: Kartiert ist nur
Lärm an **Hauptlärmquellen** (außerhalb der Ballungsräume nur Straßen mit
mehr als 3 Mio. Kfz/Jahr). „Nicht kartiert" heißt also „keine kartierte
Hauptlärmquelle am Punkt", nicht „leise". Und es sind berechnete Pegel
aus der Kartierung, keine Messwerte am Haus.
"""

from __future__ import annotations

import re
import time
from typing import Any

from ..config import Settings
from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, now_iso

WMS_URL = "https://www.lfu.bayern.de/gdi/wms/laerm/hauptverkehrsstrassen"
LIZENZ = "© Bayerisches Landesamt für Umwelt (LfU) · www.lfu.bayern.de"

UBA_WMS_URL = (
    "https://datahub.uba.de/server/services/VeLa/LK/MapServer/WMSServer"
)
UBA_LIZENZ = (
    "© Umweltbundesamt — Lärmkartierung nach der "
    "EU-Umgebungslärmrichtlinie (Daten der Länder und des Bundes)"
)
UBA_KARTIERUNG = 2022  # Kartierungsrunde; Dienststand der Daten: 12/2023
UBA_LAYER_ABFRAGE = "35"    # LK_BLR_Abfrage — Ballungsräume, alle Quellen
UBA_LAYER_HLQ_DEN = "30"    # LK_HLQ_road_Den — außerhalb, Straße LDEN
UBA_LAYER_HLQ_NIGHT = "29"  # LK_HLQ_road_Night — außerhalb, Straße LNight

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

UBA_HINWEISE = [
    "Kartiert sind nur Hauptlärmquellen: in Ballungsräumen Straße, Schiene, "
    "Flug und Industrie; außerhalb nur Hauptverkehrsstraßen mit mehr als "
    "3 Mio. Kfz/Jahr. „Nicht kartiert“ heißt „keine kartierte "
    "Hauptlärmquelle am Punkt“ — nicht „leise“.",
    "Berechnete Pegel aus der EU-Umgebungslärmkartierung (Runde 2022, "
    "Datenstand 12/2023), keine Messwerte am Haus. Der Bundesdienst liefert "
    "5-dB-Klassen — angezeigt wird deshalb die Spanne. LDEN ist der "
    "Tag-Abend-Nacht-Pegel, LNight der Nachtpegel 22–6 Uhr.",
]


# --------------------------------------------------- UBA-Pegelklassen

def uba_klasse(code: str | None) -> dict[str, Any] | None:
    """Pegelklasse des UBA-Dienstes → Spanne.

    Live gesehene Formen: ``Lden6569``, ``Lnight5054``,
    ``LdenGreaterThan75``. Unbekannte Formen ergeben ``None`` statt einer
    geratenen Zahl."""
    s = str(code or "").strip()
    m = re.fullmatch(r"(Lden|Lnight)(\d{2})(\d{2})", s)
    if m:
        von, bis = int(m.group(2)), int(m.group(3))
        return {"von_db": von, "bis_db": bis,
                "klasse": f"{von}–{bis} dB(A)"}
    m = re.fullmatch(r"(Lden|Lnight)GreaterThan(\d{2})", s)
    if m:
        von = int(m.group(2))
        return {"von_db": von, "bis_db": None,
                "klasse": f"über {von} dB(A)"}
    return None


def _lauteste(klassen: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Bei mehreren getroffenen Bändern (Abfragefenster schneidet
    Nachbarpolygone) zählt das lauteste."""
    if not klassen:
        return None
    return max(klassen, key=lambda k: (k["von_db"],
                                       k["bis_db"] is None,
                                       k["bis_db"] or 0))


def uba_abfrage_auswerten(payload: Any) -> dict[str, Any] | None:
    """Layer 35 (Ballungsraum): je Quelle die lauteste Klasse am Punkt.
    Leere FeatureCollection → ``None`` (Punkt liegt in keinem
    Ballungsraum)."""
    features = (payload or {}).get("features") or []
    if not features:
        return None
    quellen: dict[str, list[dict[str, Any]]] = {}
    gemeinde = None
    for f in features:
        p = f.get("properties") or {}
        gemeinde = gemeinde or p.get("GEN")
        for feld in ("road_den", "road_night", "rail_den", "rail_night",
                     "air_den", "air_night"):
            k = uba_klasse(p.get(feld))
            if k:
                quellen.setdefault(feld, []).append(k)
    return {
        "gemeinde": gemeinde,
        **{feld: _lauteste(kl) for feld, kl in quellen.items()},
    }


def uba_einzel_auswerten(payload: Any) -> dict[str, Any] | None:
    """HLQ-Einzel-Layer: Feld ``Lärmpegelklasse`` der Treffer."""
    klassen = []
    for f in (payload or {}).get("features") or []:
        p = f.get("properties") or {}
        for k, v in p.items():
            if "pegelklasse" in str(k).lower():
                kl = uba_klasse(v)
                if kl:
                    klassen.append(kl)
    return _lauteste(klassen)


def uba_params_fuer(layer: str, lat: float, lon: float) -> dict[str, str]:
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
        # ArcGIS-Schreibweise; das LfU nimmt "application/geojson".
        "info_format": "application/geo+json",
        "feature_count": "8",
    }


async def load(
    out: Outbound, settings: Settings, lat: float, lon: float,
    bundesland_code: str | None,
) -> SourceResult:
    """Bayern über den präziseren LfU-Rasterdienst, alles andere über den
    bundesweiten UBA-Klassendienst."""
    if bundesland_code == "09":
        return await _load_lfu(out, lat, lon)
    return await _load_uba(out, lat, lon)


async def _load_lfu(out: Outbound, lat: float, lon: float) -> SourceResult:
    started = time.perf_counter()

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
        "dienst": "lfu",
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


def _uba_pegel(kl: dict[str, Any] | None,
               abdeckung: str) -> dict[str, Any]:
    """UBA-Klasse → Anzeigeform des Blocks. ``wert_db`` bleibt ``None``
    (der Bundesdienst liefert Klassen, keine Rasterwerte)."""
    if kl is None:
        return {"wert_db": None, "klasse": None, "kartierung": None,
                "abdeckung": None, "von_db": None, "bis_db": None}
    return {"wert_db": None, "klasse": kl["klasse"],
            "kartierung": UBA_KARTIERUNG, "abdeckung": abdeckung,
            "von_db": kl["von_db"], "bis_db": kl["bis_db"]}


async def _load_uba(out: Outbound, lat: float, lon: float) -> SourceResult:
    started = time.perf_counter()

    async def gfi(layer: str) -> Any:
        return await out.get_json(
            "laerm", UBA_WMS_URL,
            params=uba_params_fuer(layer, lat, lon),
            timeout=60.0,
        )

    weitere: dict[str, Any] = {}
    try:
        # Ballungsraum-Abfrage zuerst: eine Anfrage, alle Quellen.
        ballungsraum = uba_abfrage_auswerten(await gfi(UBA_LAYER_ABFRAGE))
        if ballungsraum is not None:
            abdeckung = "Ballungsraum"
            if ballungsraum.get("gemeinde"):
                abdeckung = f"Ballungsraum ({ballungsraum['gemeinde']})"
            lden = _uba_pegel(ballungsraum.get("road_den"), abdeckung)
            lnight = _uba_pegel(ballungsraum.get("road_night"), abdeckung)
            for quelle, feld in (("schiene", "rail_den"),
                                 ("flug", "air_den")):
                kl = ballungsraum.get(feld)
                if kl:
                    weitere[quelle] = kl["klasse"]
        else:
            abdeckung = "außerhalb der Ballungsräume (Hauptverkehrsstraßen)"
            lden = _uba_pegel(
                uba_einzel_auswerten(await gfi(UBA_LAYER_HLQ_DEN)), abdeckung)
            lnight = _uba_pegel(
                uba_einzel_auswerten(await gfi(UBA_LAYER_HLQ_NIGHT)),
                abdeckung)
    except SourceError as err:
        return SourceResult.failed(
            "laerm", err, int((time.perf_counter() - started) * 1000)
        )

    kartiert = lden["klasse"] is not None or lnight["klasse"] is not None
    data = {
        "dienst": "uba",
        "lden": lden,
        "lnight": lnight,
        "weitere_quellen": weitere,
        "kartiert": kartiert,
        "hinweise": UBA_HINWEISE,
    }

    warnungen: list[str] = []
    if not kartiert:
        warnungen.append(
            "Am Punkt liegt keine kartierte Hauptlärmquelle — für "
            "Außengastronomie meist die gute Nachricht, aber keine Aussage "
            "über Nebenstraßen- oder Gewerbelärm."
        )

    return SourceResult(
        name="laerm",
        ok=True,
        data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnungen,
        provenance=Provenance(
            source=("Lärmkartierung nach der EU-Umgebungslärmrichtlinie, "
                    "bundesweit (Umweltbundesamt, WMS „VeLa/LK“)"),
            license=UBA_LIZENZ,
            endpoint=UBA_WMS_URL,
            stand="Kartierungsrunde 2022, Stand der Daten 12/2023",
            retrieved_at=now_iso(),
            note=(
                "Berechnete Pegel als 5-dB-Klassen am Punkt "
                "(Klickabfrage), keine Messwerte. In Ballungsräumen "
                "Straße/Schiene/Flug, außerhalb nur Hauptverkehrsstraßen."
            ),
        ),
    )
