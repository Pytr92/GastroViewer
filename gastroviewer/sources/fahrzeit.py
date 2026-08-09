"""Fahrzeit-Einzugsgebiet mit dem Auto — und die Einwohner darin.

Für Schnellgastronomie, erst recht mit Drive-through, ist „Einwohner im
10-Minuten-Fahrzeitgebiet" die Kennzahl, nach der jede Systemzentrale
fragt. Das Werkzeug kennt bisher Gehstrecke, Rad-Liefergebiet und
ÖPNV-Einzugsgebiet — das Auto fehlte.

Der Kreis auf der Karte überschätzt Einzugsgebiete systematisch: Flüsse,
Bahnlinien und Autobahnen ohne Anschluss schneiden ganze Sektoren ab. Beim
Auto stärker als zu Fuß, weil die Umwege größer sind.

Phase 0 (09.08.2026, Overpass) hat drei Dinge gezeigt, die den Entwurf
bestimmen:

1. **Das Netz ist groß.** Mit Wohnstraßen sind es bei 3 km Umkreis schon
   5,0 MB. Ohne sie (nur Autobahn bis Tertiärstraße) reichen 6,6 MB für
   6,5 km. Gerechnet wird deshalb auf dem **Hauptnetz** — es trägt eine
   Fahrt von fünf bis zehn Minuten fast vollständig. Was fehlt, sind die
   letzten Hundert Meter durchs Wohngebiet.
2. **Die öffentlichen Spiegel sind unzuverlässig.** Von sieben Abrufen
   endeten zwei mit HTTP 504, teils nach 90 Sekunden; dieselbe Abfrage lief
   beim zweiten Versuch durch. Deshalb ist der Block **auf Anforderung**,
   nicht automatisch, und ein Fehlschlag wird als solcher angezeigt.
3. **Tempolimits sind gut, aber nicht vollständig erfasst.** München 97–99 %
   der Wege mit ``maxspeed``, Köln nur 85 %. Für den Rest gilt eine Annahme
   je Straßenklasse — sie steht in der Ausgabe, nicht nur im Quelltext.

Und die wichtigste Einschränkung: Gerechnet wird die **Freifluss-Fahrzeit**.
Kein Stau, keine Ampel, keine Tageszeit. Im Berufsverkehr ist das Gebiet
kleiner, nachts größer. Das steht im Block.
"""

from __future__ import annotations

import heapq
import math
import re
from typing import Any

from ..config import Settings
from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, now_iso
from .gehweg import Wegenetz, erreichbare_flaeche
from .overpass import LICENSE, run_query

#: Straßenklassen, die eine Autofahrt tragen. Wohn- und Anliegerstraßen
#: fehlen bewusst — sie vervielfachen die Datenmenge (Phase 0: Faktor 4)
#: und ändern an einer Fünf-bis-Zehn-Minuten-Fahrt wenig.
AUTOKLASSEN = (
    "motorway|trunk|primary|secondary|tertiary"
    "|motorway_link|trunk_link|primary_link|secondary_link|tertiary_link"
)

#: Angenommene Geschwindigkeit, wo OSM kein Tempolimit kennt (km/h).
#: Gewählte Werte, keine Messwerte — sie stehen in der Ausgabe mit dabei.
TEMPO_JE_KLASSE = {
    "motorway": 120, "motorway_link": 60,
    "trunk": 90, "trunk_link": 50,
    "primary": 60, "primary_link": 40,
    "secondary": 50, "secondary_link": 40,
    "tertiary": 50, "tertiary_link": 40,
}

#: Anteil des Tempolimits, der im Mittel tatsächlich gefahren wird —
#: Kreuzungen, Ampeln, Abbiegen. Gewählter Wert; er steht in der Ausgabe
#: und ist der größte einzelne Unsicherheitsfaktor dieser Rechnung.
ZUEGIGKEIT = 0.7

#: Wie weit die nächste Hauptstraße entfernt sein darf. Die 150 m des
#: Gehwegnetzes sind hier zu eng: Der Marienplatz ist eine Fußgängerzone,
#: und auch eine Adresse in einem Wohngebiet liegt schnell 400 m von der
#: nächsten Tertiärstraße entfernt. Die Strecke bis dorthin wird mit einem
#: eigenen, langsamen Tempo gerechnet und ausgewiesen.
ANBINDUNG_MAX_M = 900
ANBINDUNG_KMH = 20

#: Phase 0: 6,5 km lieferten die Spiegel noch, 9 km reproduzierbar nicht
#: mehr (HTTP 504). Der Umkreis wird deshalb gedeckelt — und wenn er greift,
#: wird das ausgewiesen, statt ein zu kleines Gebiet als vollständig
#: auszugeben.
MAX_UMKREIS_M = 6500
NETZ_PUFFER = 1.15
MIN_MINUTEN, MAX_MINUTEN = 5, 10
VORGABE_MINUTEN = 10

GRENZEN = [
    "**Freifluss-Fahrzeit**: ohne Stau, ohne Ampelphasen, ohne Tageszeit. "
    "Im Berufsverkehr ist das Gebiet kleiner, nachts größer.",
    "Gerechnet wird auf dem **Hauptstraßennetz** (Autobahn bis "
    "Tertiärstraße). Die letzten Meter durchs Wohngebiet fehlen — die "
    "erreichbare Fläche ist am Rand also eher zu klein als zu groß.",
    "Einbahnstraßen werden **nicht** berücksichtigt: Die Rechnung fährt "
    "jede Kante in beide Richtungen. In Innenstädten mit vielen "
    "Einbahnstraßen fällt das Gebiet dadurch etwas zu groß aus.",
    "Wo OpenStreetMap kein Tempolimit kennt, gilt eine Annahme je "
    "Straßenklasse. Phase 0: München 97–99 % der Wege mit Tempolimit, "
    "Köln 85 %.",
]


def _tempo_kmh(tags: dict[str, str]) -> tuple[float, bool]:
    """(km/h, aus_osm). ``maxspeed`` schlägt die Klassenannahme."""
    roh = (tags.get("maxspeed") or "").strip().lower()
    if roh:
        if roh in ("none", "signals", "variable"):
            pass                       # kein verwertbarer Zahlenwert
        elif roh == "walk":
            return 7.0, True
        else:
            treffer = re.match(r"^(\d+(?:\.\d+)?)\s*(mph)?$", roh)
            if treffer:
                wert = float(treffer.group(1))
                return (wert * 1.609 if treffer.group(2) else wert), True
    return float(TEMPO_JE_KLASSE.get(tags.get("highway", ""), 50)), False


def _befahrbar(tags: dict[str, str]) -> bool:
    if tags.get("motor_vehicle") in ("no", "private"):
        return False
    if tags.get("access") in ("no", "private") and tags.get("motor_vehicle") not in (
        "yes", "designated", "permissive",
    ):
        return False
    return True


def umkreis_m(minuten: int) -> tuple[int, bool]:
    """Wie weit das Netz geholt wird — und ob der Deckel greift."""
    # Obergrenze der plausiblen Reisegeschwindigkeit: Tertiär-/Hauptstraße
    # mit 60 km/h, gezügelt. Autobahnen reichen weiter; genau dafür ist der
    # ausgewiesene Deckel da.
    meter = minuten * (60_000 / 60) * ZUEGIGKEIT * NETZ_PUFFER
    return (min(int(meter), MAX_UMKREIS_M), meter > MAX_UMKREIS_M)


def build_query(lat: float, lon: float, minuten: int, timeout: int = 120) -> str:
    reichweite, _ = umkreis_m(minuten)
    return (
        f"[out:json][timeout:{timeout}];\n"
        f'way["highway"~"^({AUTOKLASSEN})$"](around:{reichweite},{lat},{lon});\n'
        f"out geom;"
    )


def _meter(a: tuple[float, float], b: tuple[float, float]) -> float:
    dlat = (b[0] - a[0]) * 111_320.0
    dlon = (b[1] - a[1]) * 111_320.0 * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot(dlat, dlon)


def baue_autonetz(elements: list[dict[str, Any]]) -> tuple[Wegenetz, dict[str, int]]:
    """Graph mit **Sekunden** als Kantengewicht.

    Dieselbe Struktur wie beim Gehwegnetz, nur ist das Gewicht keine Länge,
    sondern eine Zeit — sonst wäre die Fahrzeit auf einer Autobahn dieselbe
    wie auf einer Tempo-30-Straße.
    """
    netz = Wegenetz()
    zaehler = {"wege": 0, "gesperrt": 0, "mit_tempolimit": 0, "ohne_tempolimit": 0}
    for el in elements:
        if el.get("type") != "way":
            continue
        tags = el.get("tags") or {}
        geom = el.get("geometry") or []
        if len(geom) < 2:
            continue
        if not _befahrbar(tags):
            zaehler["gesperrt"] += 1
            continue
        kmh, aus_osm = _tempo_kmh(tags)
        zaehler["mit_tempolimit" if aus_osm else "ohne_tempolimit"] += 1
        m_pro_s = max(kmh, 5.0) * ZUEGIGKEIT * 1000 / 3600
        zaehler["wege"] += 1
        netz.wege += 1
        for a, b in zip(geom, geom[1:]):
            pa = (round(a["lat"], 6), round(a["lon"], 6))
            pb = (round(b["lat"], 6), round(b["lon"], 6))
            if pa == pb:
                continue
            netz.verbinde(pa, pb, _meter(pa, pb) / m_pro_s)
    return netz, zaehler


def fahrzeiten(netz: Wegenetz, start: tuple[float, float], max_s: float,
               ) -> dict[tuple[float, float], float]:
    """Dijkstra über die Sekunden bis ``max_s``."""
    if start not in netz.kanten:
        return {}
    dist = {start: 0.0}
    halde = [(0.0, start)]
    while halde:
        d, knoten = heapq.heappop(halde)
        if d > dist.get(knoten, math.inf):
            continue
        for nachbar, gewicht in netz.kanten[knoten]:
            neu = d + gewicht
            if neu <= max_s and neu < dist.get(nachbar, math.inf):
                dist[nachbar] = neu
                heapq.heappush(halde, (neu, nachbar))
    return dist


def auswerten(netz: Wegenetz, zaehler: dict[str, int], lat: float, lon: float,
              minuten: int, gedeckelt: bool) -> dict[str, Any]:
    knoten, anbindung_m = netz.naechster_knoten(lat, lon, ANBINDUNG_MAX_M)
    if knoten is None:
        raise SourceError(
            "kein_netz",
            f"Im Umkreis von {ANBINDUNG_MAX_M:.0f} m liegt keine Straße des "
            "Hauptnetzes. Das ist eine Aussage, keine Panne: Der Punkt liegt "
            "abseits des befahrbaren Netzes — etwa in einer Fußgängerzone. "
            "Für Autokundschaft ist das der entscheidende Befund.")
    max_s = minuten * 60.0
    # Der Weg bis zur ersten Hauptstraße führt über Nebenstraßen, die hier
    # nicht im Netz sind — deshalb ein eigenes, langsames Tempo.
    anbindung_s = anbindung_m / (ANBINDUNG_KMH * 1000 / 3600)
    dist = fahrzeiten(netz, knoten, max(0.0, max_s - anbindung_s))

    flaeche = erreichbare_flaeche(dist, anbindung_s, int(max_s))
    gesamt = zaehler["mit_tempolimit"] + zaehler["ohne_tempolimit"]
    return {
        "minuten": minuten,
        "anbindung_m": round(anbindung_m),
        "anbindung_s": round(anbindung_s),
        "erreichte_knoten": len(dist),
        "flaeche": flaeche,
        "netz": {
            "wege": zaehler["wege"],
            "gesperrt": zaehler["gesperrt"],
            "mit_tempolimit": zaehler["mit_tempolimit"],
            "tempolimit_anteil": (round(100 * zaehler["mit_tempolimit"] / gesamt, 1)
                                  if gesamt else None),
            "umkreis_m": umkreis_m(minuten)[0],
            "gedeckelt": gedeckelt,
        },
        "annahmen": {
            "zuegigkeit": ZUEGIGKEIT,
            "tempo_je_klasse": TEMPO_JE_KLASSE,
        },
        "hinweise": GRENZEN + ([
            f"Das Straßennetz wurde nur bis {MAX_UMKREIS_M / 1000:.1f} km "
            "geholt (Phase 0: darüber antworten die öffentlichen "
            "Overpass-Spiegel nicht mehr zuverlässig). Über eine Autobahn "
            "wären in dieser Zeit weitere Orte erreichbar — sie fehlen."
        ] if gedeckelt else []),
    }


async def load(out: Outbound, settings: Settings, lat: float, lon: float,
               minuten: int = VORGABE_MINUTEN) -> SourceResult:
    minuten = max(MIN_MINUTEN, min(MAX_MINUTEN, int(minuten)))
    _, gedeckelt = umkreis_m(minuten)
    query = build_query(lat, lon, minuten, timeout=int(settings.overpass_timeout))
    antwort = await run_query(out, settings, query, "fahrzeit")
    netz, zaehler = baue_autonetz(antwort.get("elements") or [])
    if not len(netz):
        raise SourceError(
            "leeres_netz",
            "Overpass lieferte kein befahrbares Straßennetz für diesen Punkt.")
    return SourceResult(
        name="fahrzeit", ok=True,
        data=auswerten(netz, zaehler, lat, lon, minuten, gedeckelt),
        provenance=Provenance(
            source="OpenStreetMap über Overpass (Hauptstraßennetz)",
            license=LICENSE, retrieved_at=now_iso(),
            note=("Freifluss-Fahrzeit auf dem Hauptnetz, gerechnet mit "
                  f"{ZUEGIGKEIT:.0%} des Tempolimits.")),
    )
