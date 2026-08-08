"""Gemessene Passantenfrequenz — der Tagesgang vor der Tür.

Die größte Lücke jeder Standortanalyse ist, wie viele Menschen tatsächlich
vorbeikommen und **wann**. Für Gastronomie entscheidet genau das: Eine
Straße mit Mittagsspitze und leerem Abend trägt ein Mittagslokal, aber kein
Abendrestaurant.

Gemessen wird das in Deutschland fast ausschließlich von hystreet.com per
Laserscanner — deren API ist für dieses Werkzeug unbrauchbar, weil die
Nutzungsbedingungen im kostenfreien Zugang gewerbliche Nutzung untersagen
(Phase-0-Befund 2026-08-08). Einzelne Städte haben die Daten aber lizenziert
und veröffentlichen sie unter offener Lizenz weiter — damit ist die
AGB-Kette gebrochen und die Nutzung erlaubt.

Das Ergebnis ist ein sehr kleines, sehr wertvolles Netz: **sieben
Zählstellen in drei Städten**, alle in 1a-Einzelhandelslagen. Für die
allermeisten Adressen gibt es schlicht nichts — der Block sagt das dann
und behauptet nicht, Frequenz sei unbekannt gleich niedrig.

Der Radius ist bewusst eng (250 m): Passantenfrequenz ist eine Eigenschaft
*dieses* Straßenabschnitts. Ein Zähler zwei Straßen weiter sagt über den
eigenen Standort nichts.
"""

from __future__ import annotations

import csv
import io
from typing import Any, Callable

from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, haversine_m, now_iso

MAX_DISTANZ_M = 250

# Alle Angaben in Phase 0 am 2026-08-08 mit echten Abrufen geprüft:
# Koordinaten aus den Geometrie-Datensätzen der jeweiligen Portale
# (Augsburg: Straßenmitte aus OpenStreetMap, weil die Stadt keine
# Geometrie mitliefert).
ZAEHLSTELLEN = (
    {
        "stadt": "Dortmund", "name": "Westenhellweg West",
        "lat": 51.51398205011683, "lon": 7.457912087920916,
        "quelle": "dortmund", "filter": "Westenhellweg (West)",
    },
    {
        "stadt": "Dortmund", "name": "Westenhellweg Mitte",
        "lat": 51.51431456440767, "lon": 7.462598392084305,
        "quelle": "dortmund", "filter": "Westenhellweg (Mitte)",
    },
    {
        "stadt": "Dortmund", "name": "Westenhellweg Ost",
        "lat": 51.514269195863264, "lon": 7.465442072003704,
        "quelle": "dortmund", "filter": "Westenhellweg (Ost)",
    },
    {
        "stadt": "Würzburg", "name": "Kaiserstraße",
        "lat": 49.798498976405355, "lon": 9.933887635731686,
        "quelle": "wuerzburg", "filter": "Kaiserstraße",
    },
    {
        "stadt": "Würzburg", "name": "Spiegelstraße",
        "lat": 49.79512717222457, "lon": 9.934114106308467,
        "quelle": "wuerzburg", "filter": "Spiegelstraße",
    },
    {
        "stadt": "Würzburg", "name": "Schönbornstraße",
        "lat": 49.795490162266525, "lon": 9.931060093195851,
        "quelle": "wuerzburg", "filter": "Schönbornstraße",
    },
    {
        "stadt": "Augsburg", "name": "Annastraße",
        "lat": 48.3700136, "lon": 10.8958202,
        "quelle": "augsburg", "filter": "Annastraße",
    },
)

QUELLEN = {
    "dortmund": {
        "url": ("https://open-data.dortmund.de/api/explore/v2.1/catalog"
                "/datasets/passantenaufkommen-fussgangerzone-hellweg-2026"
                "/records"),
        "traeger": "Stadt Dortmund (Open Data) · Messung hystreet.com GmbH",
        "lizenz": ("Datenlizenz Deutschland – Zero – Version 2.0 "
                   "(dl-de/zero-2-0) · Stadt Dortmund"),
        "stand": "laufendes Jahr, stündlich fortgeschrieben",
    },
    "wuerzburg": {
        "url": ("https://opendata.wuerzburg.de/api/explore/v2.1/catalog"
                "/datasets/passantenzaehlung_stundendaten/records"),
        "traeger": "Stadt Würzburg (Open Data) · Messung hystreet.com GmbH",
        "lizenz": ("Datenlizenz Deutschland – Namensnennung – Version 2.0 "
                   "(dl-de/by-2-0) · Stadt Würzburg / hystreet.com GmbH"),
        "stand": "Zeitreihe bis Mai 2026 — danach kein Nachlauf mehr",
    },
    "augsburg": {
        "url": ("https://www.augsburg.de/fileadmin/user_upload"
                "/buergerservice_rathaus/Smart_City/opendata/240429"
                "/Annastra%C3%9Fe_Frequenzdaten.csv"),
        "traeger": "Stadt Augsburg (Smart City, Open Data)",
        "lizenz": "Creative Commons Namensnennung 4.0 (CC BY 4.0) · Stadt Augsburg",
        "stand": "16.12.2020 bis 09.10.2025",
    },
}

HINWEISE = [
    "Gezählt wird **an dieser Zählstelle**, nicht im ganzen Viertel. "
    f"Der Block meldet sich nur, wenn ein Zähler höchstens {MAX_DISTANZ_M} m "
    "entfernt steht — Frequenz ist eine Eigenschaft des Straßenabschnitts.",
    "Der **Tagesgang** ist die eigentliche Aussage: Wann sind die Leute da? "
    "Eine Straße mit Nachmittagsspitze und leerem Abend trägt ein "
    "Mittagslokal, aber kein Abendrestaurant.",
    "Die Werte sind Stundenmittel über den gesamten verfügbaren Zeitraum, "
    "also über Wochentage, Wochenenden und Jahreszeiten hinweg gemittelt. "
    "Ein einzelner Tag kann deutlich abweichen.",
    "Gemessen mit Laserscannern von hystreet.com; die Städte haben die "
    "Daten lizenziert und geben sie unter offener Lizenz weiter. Der "
    "direkte Zugang bei hystreet.com wäre für gewerbliche Nutzung "
    "kostenpflichtig.",
]

# Nur Städte mit stündlicher Auflösung sind aufgenommen. Oldenburg
# veröffentlicht dieselben Messungen (dl-de/by-2-0, vier Zählstellen),
# aber ausschließlich als **Tagessummen** — ohne Tagesgang fehlt genau
# die Information, für die dieser Block da ist. Deshalb bewusst außen vor.
NICHT_AUFGENOMMEN = (
    "Oldenburg veröffentlicht vier Zählstellen unter derselben Lizenz, "
    "aber nur als Tagessummen ohne Stundenwerte — der Tagesgang, um den "
    "es hier geht, lässt sich daraus nicht ableiten."
)


def naechste_zaehlstelle(lat: float, lon: float) -> dict[str, Any] | None:
    """Nächste Zählstelle innerhalb des Radius — oder ``None``."""
    beste = None
    for z in ZAEHLSTELLEN:
        d = haversine_m(lat, lon, z["lat"], z["lon"])
        if d <= MAX_DISTANZ_M and (beste is None or d < beste[0]):
            beste = (d, z)
    if beste is None:
        return None
    return {**beste[1], "distanz_m": round(beste[0])}


def _stunde(eintrag: dict[str, Any]) -> int | None:
    """Die Stunde steht je nach Dienst unter „stunde" oder unter dem
    rohen Gruppenschlüssel — Würzburgs Alias bleibt leer."""
    for schluessel in ("stunde", "hour(timestamp)"):
        wert = eintrag.get(schluessel)
        if wert is not None:
            try:
                return int(wert)
            except (TypeError, ValueError):
                continue
    return None


def parse_tagesgang(antwort: dict[str, Any]) -> list[dict[str, Any]]:
    """Stundenmittel aus einer Opendatasoft-Aggregation."""
    kurve: dict[int, float] = {}
    for e in antwort.get("results") or []:
        stunde = _stunde(e)
        wert = e.get("mittel")
        if stunde is None or wert is None:
            continue
        kurve[stunde] = float(wert)
    return [{"stunde": s, "passanten": round(kurve[s])}
            for s in sorted(kurve)]


def parse_augsburg_csv(text: str) -> list[dict[str, Any]]:
    """Augsburg liefert Rohzeilen statt einer Aggregation — Stundenmittel
    hier selbst rechnen. Spalten: Standort;Jahr;Datum;Stunde;Passanten,
    die Stunde als „13 Uhr"."""
    summe: dict[int, list[float]] = {}
    leser = csv.DictReader(io.StringIO(text.lstrip("﻿")), delimiter=";")
    for zeile in leser:
        roh = (zeile.get("Stunde") or "").split()
        wert = (zeile.get("Passanten") or "").strip()
        if not roh or not wert.isdigit():
            continue
        try:
            stunde = int(roh[0])
        except ValueError:
            continue
        summe.setdefault(stunde, []).append(float(wert))
    return [{"stunde": s, "passanten": round(sum(v) / len(v))}
            for s, v in sorted(summe.items()) if v]


def auswerten(
    zaehlstelle: dict[str, Any], kurve: list[dict[str, Any]]
) -> dict[str, Any]:
    """Kennzahlen, die eine Entscheidung tragen: Spitze, Mittags- und
    Abendniveau — und wie viel vom Tag nach 18 Uhr übrig bleibt."""
    if not kurve:
        raise SourceError(
            "parse", "Die Zählstelle lieferte keine Stundenwerte.")

    def fenster(von: int, bis: int) -> int | None:
        werte = [k["passanten"] for k in kurve if von <= k["stunde"] <= bis]
        return round(sum(werte) / len(werte)) if werte else None

    spitze = max(kurve, key=lambda k: k["passanten"])
    tagessumme = sum(k["passanten"] for k in kurve)
    abend = sum(k["passanten"] for k in kurve if k["stunde"] >= 18)
    quelle = QUELLEN[zaehlstelle["quelle"]]
    return {
        "zaehlstelle": zaehlstelle["name"],
        "stadt": zaehlstelle["stadt"],
        "distanz_m": zaehlstelle["distanz_m"],
        "traeger": quelle["traeger"],
        "stand": quelle["stand"],
        "spitzenstunde": spitze["stunde"],
        "spitze_passanten": spitze["passanten"],
        "mittags": fenster(12, 14),
        "nachmittags": fenster(15, 17),
        "abends": fenster(18, 20),
        "tagessumme": tagessumme,
        "abendanteil_prozent": (round(100 * abend / tagessumme, 1)
                                if tagessumme else None),
        "kurve": kurve,
        "hinweise": HINWEISE,
    }


async def load(out: Outbound, lat: float, lon: float,
               augsburg_laden: Callable[[], Any] | None = None) -> SourceResult:
    """Frequenzblock für den Punkt. Ohne Zählstelle in der Nähe: leer mit
    Begründung — kein Ersatzwert, keine Schätzung."""
    z = naechste_zaehlstelle(lat, lon)
    if z is None:
        return SourceResult(
            name="frequenz", ok=True, data=None,
            warnings=[
                "Keine offene Passantenzählung in der Nähe. Gemessene "
                "Frequenzdaten gibt es in Deutschland nur an wenigen "
                f"Stellen — dieses Werkzeug kennt {len(ZAEHLSTELLEN)} "
                "Zählstellen in Dortmund, Würzburg und Augsburg. Das "
                "heißt nicht, dass hier wenig los ist; es ist schlicht "
                "nicht gemessen.",
                NICHT_AUFGENOMMEN,
            ],
            provenance=Provenance(
                source="Offene Passantenzählungen (keine in Reichweite)",
                license="je Stadt verschieden — siehe Block bei Treffer"),
        )

    quelle = QUELLEN[z["quelle"]]
    if z["quelle"] == "augsburg":
        if augsburg_laden is None:
            raise SourceError("konfiguration",
                              "Augsburger Frequenzdatei nicht verfügbar.")
        kurve = await augsburg_laden()
    else:
        if z["quelle"] == "dortmund":
            params = {
                "select": "stunde, avg(zeitpunkt_total_count) as mittel",
                "where": f'name like "{z["filter"]}"',
                "group_by": "stunde",
            }
        else:
            params = {
                "select": "hour(timestamp) as stunde, "
                          "avg(pedestrians_count) as mittel",
                "where": f'location_name="{z["filter"]}"',
                "group_by": "hour(timestamp)",
            }
        params.update({"order_by": "stunde", "limit": "24"})
        antwort = await out.get_json(
            f"frequenz_{z['quelle']}", quelle["url"], params=params,
            timeout=60.0, limiter=f"frequenz_{z['quelle']}", min_interval=1.0)
        kurve = parse_tagesgang(antwort)

    daten = auswerten(z, kurve)
    return SourceResult(
        name="frequenz", ok=True, data=daten,
        provenance=Provenance(
            source=f"Passantenzählung {z['stadt']} — {z['name']}",
            license=quelle["lizenz"],
            endpoint=quelle["url"],
            stand=quelle["stand"],
            retrieved_at=now_iso(),
            note=("Stundenmittel über den gesamten verfügbaren Zeitraum; "
                  f"Zählstelle {z['distanz_m']} m vom Punkt entfernt."),
        ),
    )
