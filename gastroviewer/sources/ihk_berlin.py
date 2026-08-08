"""Gastronomie-Bestand Berlins aus den IHK-Gewerbedaten.

Die IHK Berlin veröffentlicht ihren Mitgliederbestand monatlich unter
**CC0** — ohne jede Lizenzeinschränkung, mit Koordinate, Postleitzahl,
LOR-Planungsraum, Betriebsalter und Beschäftigtenklasse. Das ist für
Berlin deutlich mehr, als OSM und Overture zusammen hergeben: OSM kennt
nur, was jemand eingetragen hat, die IHK kennt jeden Mitgliedsbetrieb.

Zwei Dinge, die der Block ehrlich sagen muss:

* Es ist ein **Bestand**, keine Bewegung — An- und Abmeldungen stehen
  nicht drin. Die Dynamik liefert für Hamburg das Statistikamt Nord,
  für Berlin gibt es sie offen nicht.
* Erfasst sind nur **IHK-pflichtige** Betriebe. Für Gastronomie ist das
  nahezu vollständig (Handwerksbetriebe wie Bäckereien fehlen), für
  andere Branchen nicht.

Die Datei ist rund 125 MB groß und liegt in Git LFS. Sie wird deshalb
**auf Anforderung** geladen, nicht beim Öffnen eines Punktes — und danach
30 Tage zwischengespeichert.
"""

from __future__ import annotations

import csv
import io
from typing import Any, Callable

from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, haversine_m, now_iso

# Wichtig: media.githubusercontent.com, nicht raw.githubusercontent.com —
# letzteres liefert bei Git LFS nur den Zeiger, nicht die Datei
# (Phase-0-Befund 2026-08-08).
CSV_URL = ("https://media.githubusercontent.com/media/IHKBerlin"
           "/IHKBerlin_Gewerbedaten/master/data/IHKBerlin_Gewerbedaten.csv")
PORTAL = "https://datenregister.berlin.de/dataset/gewerbedaten-ihkberlin"
LIZENZ = ("Creative Commons Zero (CC0) — IHK Berlin: „Alle Daten werden "
          "maschinenlesbar, ohne lizenzrechtliche Einschränkungen zur "
          "freien Nutzung bereit gestellt.“")
DATEIGROESSE_MB = 125

# NACE-Abschnitt I: 55 Beherbergung, 56 Gastronomie. Für die
# Wettbewerbsfrage zählt 56; 55 wird getrennt ausgewiesen.
NACE_GASTRONOMIE = "56"
NACE_BEHERBERGUNG = "55"

BERLIN_BBOX = (52.33, 13.08, 52.68, 13.77)
STANDARD_RADIUS_M = 600

HINWEISE = [
    "Die IHK-Daten sind ein **Bestand zum Stichtag**, keine Bewegung: "
    "Wer neu aufmacht oder zumacht, steht nicht darin. Für Berlin gibt "
    "es offene An-/Abmeldezahlen unterhalb der Stadtebene nicht.",
    "Erfasst sind **IHK-pflichtige Betriebe**. Für Gastronomie ist das "
    "nahezu vollständig; Handwerksbetriebe (etwa Bäckereien mit "
    "Sitzplätzen) gehören zur Handwerkskammer und fehlen hier.",
    "Das **Betriebsalter** ist der aussagekräftigste Nebenwert: Viele "
    "sehr junge Betriebe in einer Lage sprechen für Fluktuation, viele "
    "alte für einen tragfähigen Markt.",
    "Gegenprobe zur OSM-Zählung im Gastronomieblock: Weicht die IHK-Zahl "
    "stark nach oben ab, ist das Umfeld in OpenStreetMap unvollständig "
    "erfasst — nicht unbedingt weniger dicht bebaut.",
]


def ist_berlin(lat: float, lon: float) -> bool:
    return (BERLIN_BBOX[0] <= lat <= BERLIN_BBOX[2]
            and BERLIN_BBOX[1] <= lon <= BERLIN_BBOX[3])


def _zahl(wert: str | None) -> int | None:
    try:
        return int(str(wert).strip())
    except (TypeError, ValueError):
        return None


def parse_gastro(text: str) -> list[dict[str, Any]]:
    """CSV → nur die Beherbergungs- und Gastronomiebetriebe.

    Die Vollzeile hat 20 Spalten; behalten wird, was der Block zeigt —
    aus 368 000 Zeilen werden so gut 23 000."""
    betriebe = []
    leser = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    for zeile in leser:
        abschnitt = (zeile.get("branch_top_level_id") or "").strip()
        if abschnitt not in (NACE_GASTRONOMIE, NACE_BEHERBERGUNG):
            continue
        lat, lon = zeile.get("latitude"), zeile.get("longitude")
        try:
            lat_f, lon_f = float(lat), float(lon)
        except (TypeError, ValueError):
            continue
        betriebe.append({
            "lat": lat_f, "lon": lon_f,
            "plz": (zeile.get("postcode") or "").strip() or None,
            "abschnitt": abschnitt,
            "branche": (zeile.get("ihk_branch_desc") or "").strip() or None,
            "nace": (zeile.get("nace_desc") or "").strip() or None,
            "alter_jahre": _zahl(zeile.get("business_age")),
            "beschaeftigte": (zeile.get("employees_range") or "").strip() or None,
            "planungsraum": (zeile.get("Planungsraum") or "").strip() or None,
            "bezirk": (zeile.get("Bezirk") or "").strip() or None,
        })
    return betriebe


def auswerten(betriebe: list[dict[str, Any]], lat: float, lon: float,
              radius: int) -> dict[str, Any]:
    """Umkreisauswertung: Wie viele, wie alt, welche Art."""
    nah = []
    for b in betriebe:
        d = haversine_m(lat, lon, b["lat"], b["lon"])
        if d <= radius:
            nah.append({**b, "distanz_m": round(d)})
    nah.sort(key=lambda b: b["distanz_m"])

    gastronomie = [b for b in nah if b["abschnitt"] == NACE_GASTRONOMIE]
    beherbergung = [b for b in nah if b["abschnitt"] == NACE_BEHERBERGUNG]
    alter = [b["alter_jahre"] for b in gastronomie
             if b["alter_jahre"] is not None]
    alter.sort()
    median = None
    if alter:
        mitte = len(alter) // 2
        median = (alter[mitte] if len(alter) % 2
                  else (alter[mitte - 1] + alter[mitte]) / 2)

    nach_branche: dict[str, int] = {}
    for b in gastronomie:
        if b["branche"]:
            nach_branche[b["branche"]] = nach_branche.get(b["branche"], 0) + 1

    return {
        "radius_m": radius,
        "gastronomie": len(gastronomie),
        "beherbergung": len(beherbergung),
        "median_alter_jahre": median,
        "junge_betriebe": sum(1 for a in alter if a <= 3),
        "alte_betriebe": sum(1 for a in alter if a >= 20),
        "planungsraum": (nah[0]["planungsraum"] if nah else None),
        "bezirk": (nah[0]["bezirk"] if nah else None),
        "nach_branche": [{"branche": k, "anzahl": v} for k, v in
                         sorted(nach_branche.items(), key=lambda x: -x[1])[:10]],
        "naechste": [{k: b[k] for k in
                      ("branche", "distanz_m", "alter_jahre", "beschaeftigte")}
                     for b in gastronomie[:10]],
        "hinweise": HINWEISE,
    }


async def load(out: Outbound, lat: float, lon: float, radius: int,
               betriebe_laden: Callable[[], Any]) -> SourceResult:
    """Gastronomie-Bestand im Umkreis. Nur für Berlin."""
    if not ist_berlin(lat, lon):
        return SourceResult(
            name="ihk_berlin", ok=True, data=None,
            warnings=["Die IHK-Gewerbedaten gibt es nur für Berlin. Andere "
                      "Industrie- und Handelskammern veröffentlichen ihren "
                      "Mitgliederbestand nicht als offene Daten."],
            provenance=Provenance(source="IHK Berlin (außerhalb Berlins)",
                                  license=LIZENZ),
        )
    betriebe = await betriebe_laden()
    if not betriebe:
        raise SourceError(
            "parse", "Die IHK-Datei enthielt keine Gastronomiebetriebe.")
    return SourceResult(
        name="ihk_berlin", ok=True,
        data=auswerten(betriebe, lat, lon, radius),
        provenance=Provenance(
            source="IHK Berlin — Gewerbedaten (Mitgliederbestand)",
            license=LIZENZ, endpoint=PORTAL,
            stand="monatlich fortgeschrieben",
            retrieved_at=now_iso(),
            note=("Bestand IHK-pflichtiger Betriebe, NACE-Abschnitt I "
                  "(55 Beherbergung, 56 Gastronomie)."),
        ),
    )
