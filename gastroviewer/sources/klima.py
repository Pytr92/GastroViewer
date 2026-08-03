"""Klimanormalwerte der nächsten DWD-Station — für die Außengastronomie.

Für Biergarten, Terrasse oder Eisdiele ist das Klima keine Nebensache,
sondern Teil der Standortfrage. Der Deutsche Wetterdienst veröffentlicht
auf seinem Open-Data-Server vieljährige Stationsmittel der Normalperiode
**1991–2020** als offene Textdateien (geprüft am 03.08.2026, Verzeichnis
``…/climate/multi_annual/mean_91-20/``):

* Sommertage (Höchsttemperatur ≥ 25 °C) und Heiße Tage (≥ 30 °C) je Jahr
* Sonnenscheindauer in Stunden je Jahr
* Niederschlag in mm je Jahr
* Lufttemperatur im Jahresmittel

Gegenprobe München-Stadt (Station 3379): 53,3 Sommertage, 12 Heiße Tage,
1.841,5 h Sonne, 939,7 mm, 10,1 °C — deckungsgleich mit den
Klimatafeln des DWD.

Ehrliche Grenzen, die der Block mit ausweist:

* Es ist der Wert der **nächsten Station**, nicht des Punktes. Name,
  Entfernung und Stationshöhe stehen dabei; ab spürbarem Höhenunterschied
  (Alpenrand!) ist der Wert nur bedingt übertragbar.
* Jeder Parameter hat sein eigenes Stationsnetz — Sonnenschein wird an
  weit weniger Stationen gemessen als Niederschlag. Deshalb kann jede
  Kennzahl von einer anderen Station stammen.
* 1991–2020 ist eine Normalperiode, kein aktuelles Jahr und keine Prognose.
"""

from __future__ import annotations

import math
import time
from typing import Any

from ..config import Settings
from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, now_iso

LICENSE = (
    "© Deutscher Wetterdienst (DWD), offene Geodaten nach GeoNutzV — "
    "Quellenvermerk erforderlich"
)

# Dateipaare auf dem Open-Data-Server: Werte + Stationsliste je Parameter.
PARAMETER: list[dict[str, Any]] = [
    {"schluessel": "sommertage", "datei": "Sommertage_1991-2020",
     "titel": "Sommertage (Höchstwert ≥ 25 °C)", "einheit": "Tage/Jahr",
     "stellen": 1},
    {"schluessel": "heisse_tage", "datei": "Heissetage_1991-2020",
     "titel": "Heiße Tage (Höchstwert ≥ 30 °C)", "einheit": "Tage/Jahr",
     "stellen": 1},
    {"schluessel": "sonnenschein", "datei": "Sonnenscheindauer_1991-2020",
     "titel": "Sonnenscheindauer", "einheit": "Stunden/Jahr", "stellen": 0},
    {"schluessel": "niederschlag", "datei": "Niederschlag_1991-2020",
     "titel": "Niederschlag", "einheit": "mm/Jahr", "stellen": 0},
    {"schluessel": "temperatur", "datei": "Temperatur_1991-2020",
     "titel": "Lufttemperatur im Jahresmittel", "einheit": "°C", "stellen": 1},
]

NORMALPERIODE = "1991–2020"
# Jenseits dieser Distanz wird der Wert als nur bedingt übertragbar markiert —
# eine gewählte Schwelle, kein Messwert, und so steht sie auch im Hinweistext.
# Einen Höhenvergleich gibt es bewusst nicht: die Höhe des angefragten Punktes
# ist unbekannt, also wird die Stationshöhe angezeigt statt verglichen.
WARN_DISTANZ_M = 30_000


def _zahl(s: str) -> float | None:
    s = s.strip()
    if not s or s in {".", "-"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_werte(text: str) -> dict[str, dict[str, Any]]:
    """Wertedatei: ``Stations_id;Bezugszeitraum;Datenquelle;Jan.;…;Dez.;Jahr;``.
    Dezimaltrennzeichen ist der Punkt, ``.6`` heißt 0,6."""
    zeilen = [z for z in text.splitlines() if z.strip()]
    ergebnis: dict[str, dict[str, Any]] = {}
    for zeile in zeilen[1:]:
        teile = [t.strip() for t in zeile.split(";")]
        if len(teile) < 16:
            continue
        sid = teile[0]
        if not sid.isdigit():
            continue
        monate = [_zahl(t) for t in teile[3:15]]
        jahr = _zahl(teile[15])
        if jahr is None:
            continue
        ergebnis[sid] = {"jahr": jahr, "monate": monate}
    return ergebnis


def parse_stationen(text: str) -> dict[str, dict[str, Any]]:
    """Stationsliste: ``Stations_id;Stationsname;Breite;Laenge;Hoehe;Bundesland``."""
    zeilen = [z for z in text.splitlines() if z.strip()]
    ergebnis: dict[str, dict[str, Any]] = {}
    for zeile in zeilen[1:]:
        teile = [t.strip() for t in zeile.split(";")]
        if len(teile) < 6 or not teile[0].isdigit():
            continue
        lat, lon = _zahl(teile[2]), _zahl(teile[3])
        if lat is None or lon is None:
            continue
        ergebnis[teile[0]] = {
            "name": teile[1],
            "lat": lat,
            "lon": lon,
            "hoehe_m": _zahl(teile[4]),
            "bundesland": teile[5],
        }
    return ergebnis


def _distanz_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Planare Näherung mit Breitengrad-Korrektur — für Stationsabstände
    (< 100 km) genau genug."""
    dy = (lat2 - lat1) * 111_320.0
    dx = (lon2 - lon1) * 111_320.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


def naechste_station(
    lat: float,
    lon: float,
    stationen: dict[str, dict[str, Any]],
    werte: dict[str, dict[str, Any]],
) -> tuple[str, float] | None:
    """Nächste Station, die für diesen Parameter auch einen Wert hat."""
    beste: tuple[str, float] | None = None
    for sid, s in stationen.items():
        if sid not in werte:
            continue
        d = _distanz_m(lat, lon, s["lat"], s["lon"])
        if beste is None or d < beste[1]:
            beste = (sid, d)
    return beste


async def lade_parameter(
    out: Outbound, settings: Settings, eintrag: dict[str, Any]
) -> dict[str, Any]:
    """Beide Dateien eines Parameters laden und parsen — Deutschland-weit,
    wird vom Service je Parameter (nicht je Punkt) zwischengespeichert."""
    basis = settings.dwd_base
    werte_text = await out.get_text(
        "klima", f"{basis}/{eintrag['datei']}.txt",
        encoding="latin-1", timeout=settings.zensus_timeout,
    )
    stationen_text = await out.get_text(
        "klima", f"{basis}/{eintrag['datei']}_Stationsliste.txt",
        encoding="latin-1", timeout=settings.zensus_timeout,
    )
    werte = parse_werte(werte_text)
    stationen = parse_stationen(stationen_text)
    if not werte or not stationen:
        raise SourceError(
            "parse",
            f"DWD-Datei {eintrag['datei']} ließ sich nicht auswerten — "
            "Format geändert?",
        )
    return {"werte": werte, "stationen": stationen}


def auswerten(
    lat: float, lon: float, dateien: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Je Parameter die nächste Station mit Wert; rein lokale Rechnung."""
    kennzahlen: list[dict[str, Any]] = []
    hinweise: set[str] = set()
    for eintrag in PARAMETER:
        datei = dateien.get(eintrag["schluessel"])
        if not datei:
            continue
        treffer = naechste_station(lat, lon, datei["stationen"], datei["werte"])
        if treffer is None:
            continue
        sid, dist = treffer
        s = datei["stationen"][sid]
        w = datei["werte"][sid]
        eintrag_daten = {
            "schluessel": eintrag["schluessel"],
            "titel": eintrag["titel"],
            "einheit": eintrag["einheit"],
            "stellen": eintrag["stellen"],
            "wert": w["jahr"],
            "monate": w["monate"],
            "station": {
                "id": sid,
                "name": s["name"],
                "distanz_m": round(dist),
                "hoehe_m": s["hoehe_m"],
            },
        }
        kennzahlen.append(eintrag_daten)
        if dist > WARN_DISTANZ_M:
            hinweise.add(
                f"Die nächste Station für „{eintrag['titel']}“ liegt "
                f"{dist / 1000:.0f} km entfernt — der Wert ist nur bedingt "
                "übertragbar (gewählte Warnschwelle: 30 km)."
            )
    return {"kennzahlen": kennzahlen, "hinweise": sorted(hinweise)}


def ergebnis(
    lat: float, lon: float, dateien: dict[str, dict[str, Any]],
    started: float, warnings: list[str],
) -> SourceResult:
    data = auswerten(lat, lon, dateien)
    if not data["kennzahlen"]:
        return SourceResult.failed(
            "klima",
            SourceError("api_error",
                        "Keine der DWD-Klimadateien lieferte auswertbare Werte."),
            int((time.perf_counter() - started) * 1000),
        )
    return SourceResult(
        name="klima",
        ok=True,
        data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnings + data.pop("hinweise"),
        provenance=Provenance(
            source="Deutscher Wetterdienst (DWD), vieljährige Stationsmittel",
            license=LICENSE,
            endpoint="https://opendata.dwd.de/climate_environment/CDC/",
            stand=f"Normalperiode {NORMALPERIODE}",
            retrieved_at=now_iso(),
            note=(
                "Wert der jeweils nächsten Station, nicht des Punktes — Name, "
                "Entfernung und Stationshöhe stehen dabei. Jeder Parameter hat "
                "sein eigenes Stationsnetz."
            ),
        ),
    )
