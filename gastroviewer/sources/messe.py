"""Messe-Kalender: Veranstaltungen der Messe München mit Besucherzahlen.

Messetage sind planbare Frequenzspitzen: eine bauma bringt eine halbe Million
Besucher in die Stadt, die in Hotels schlafen und abends essen gehen. Wer in
Riem, an der U2 oder in Hotelnähe plant, will wissen, **wann** diese Spitzen
kommen und **wie groß** sie sind — und genau das steht in keiner der bisherigen
Quellen.

Verifiziert am 2026-08-07: CKAN-Datensatz ``veranstaltungen-der-messe-muenchen``
auf ``opendata.muenchen.de`` (Herausgeber Messe München GmbH, Datenlizenz
Deutschland Namensnennung 2.0, Ressource am Prüftag zuletzt aktualisiert).
307 Veranstaltungen weltweit ab 2018 — die Messe München veranstaltet auch in
Delhi und Shanghai, gefiltert wird deshalb auf ``stadt = München`` (95 Zeilen).
Semikolon-getrennt; Termine als ``TT.MM.JJJJ``; Besucher- und
Ausstellerzahlen nur für vergangene Veranstaltungen gefüllt (52 von 95).

Drei Gelände kommen im Datensatz vor: Messe München (Riem), das ICM auf dem
Messegelände und das MOC in Freimann. Ihre Koordinaten sind fest hinterlegt
(gewählte Werte, keine Messwerte) — sie dienen nur der Entfernungsangabe.
"""

from __future__ import annotations

import csv
import io
import time
from typing import Any

from ..config import Settings
from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, bearing_label, haversine_m, now_iso

CSV_URL = (
    "https://opendata.muenchen.de/dataset/ef068a1c-315c-4262-8cf1-903767831225/"
    "resource/b698829c-b051-4092-a276-9ba1afdc12f3/download/veranstaltungsdaten.csv"
)
LIZENZ = (
    "Datenlizenz Deutschland Namensnennung 2.0 (dl-de/by-2-0) · "
    "© Messe München GmbH, über das Open-Data-Portal der Landeshauptstadt München"
)
ROHDATEN = "https://opendata.muenchen.de/dataset/veranstaltungen-der-messe-muenchen"

# Feste Gelände-Koordinaten (gewählte Werte, nur für die Entfernungsangabe).
# Der Datensatz nennt die Gelände beim Namen, aber ohne Koordinaten.
GELAENDE: dict[str, tuple[float, float]] = {
    "Messe München": (48.1352, 11.6959),
    "ICM Internationales Congress Center": (48.1353, 11.6862),
    "M,O,C,": (48.1972, 11.6021),
}

# Jenseits davon prägt der Messebetrieb den Standort kaum noch — die Wirkung
# läuft über Hotels und die U2, nicht über Laufkundschaft (gewählter Wert).
MAX_DISTANZ_M = 20_000

# Anzeige-Obergrenzen (gewählte Werte, damit der Block lesbar bleibt).
MAX_KOMMENDE = 8
MAX_GROESSTE = 5


def _zahl(text: Any) -> int | None:
    t = str(text or "").strip()
    if not t or t.upper() == "NA":
        return None
    try:
        return int(float(t.replace(".", "").replace(",", ".")))
    except ValueError:
        return None


def _datum_iso(text: Any) -> str | None:
    """``11.12.2024`` → ``2024-12-11`` — sortierbar, ohne Zeitzonen-Deutung."""
    t = str(text or "").strip()
    teile = t.split(".")
    if len(teile) != 3:
        return None
    tag, monat, jahr = (p.strip() for p in teile)
    if not (tag.isdigit() and monat.isdigit() and len(jahr) == 4 and jahr.isdigit()):
        return None
    return f"{jahr}-{int(monat):02d}-{int(tag):02d}"


def parse_veranstaltungen(csv_text: str) -> tuple[list[dict[str, Any]], int]:
    """Nur die Münchner Veranstaltungen, auf das Nötige reduziert.

    Liefert zusätzlich die Zahl der Münchner Zeilen mit unlesbarem Termin —
    im Prüf-Download vom 2026-08-07 stand dort z. B. „Mai 2.2026“. Solche
    Zeilen werden übersprungen und die Zahl im Block genannt, statt sie
    stillschweigend verschwinden zu lassen."""
    reader = csv.DictReader(io.StringIO(csv_text), delimiter=";")
    pflicht = {"stadt", "kurztitel", "startdatum", "enddatum", "messegelaende"}
    if not pflicht.issubset(set(reader.fieldnames or [])):
        raise SourceError(
            "parse",
            "Die Veranstaltungs-CSV hat nicht mehr die erwarteten Spalten — "
            f"gefunden: {reader.fieldnames}",
        )
    events: list[dict[str, Any]] = []
    verworfen = 0
    for row in reader:
        if (row.get("stadt") or "").strip() != "München":
            continue
        start = _datum_iso(row.get("startdatum"))
        ende = _datum_iso(row.get("enddatum"))
        if not start or not ende:
            verworfen += 1
            continue
        events.append(
            {
                "titel": (row.get("kurztitel") or "").strip() or "(ohne Titel)",
                "start": start,
                "ende": ende,
                "gelaende": (row.get("messegelaende") or "").strip(),
                "turnus": (row.get("turnus") or "").strip() or None,
                "messetyp": (row.get("messetyp") or "").strip() or None,
                "besucher": _zahl(row.get("besucher_gesamt")),
                "aussteller": _zahl(row.get("aussteller_gesamt")),
            }
        )
    events.sort(key=lambda e: e["start"])
    return events, verworfen


def auswerten(
    events: list[dict[str, Any]], lat: float, lon: float, heute: str
) -> dict[str, Any]:
    """Kommende Termine, Jahresbilanz und die Entfernung zu den Geländen."""
    gelaende = []
    for name, (glat, glon) in GELAENDE.items():
        dist = haversine_m(lat, lon, glat, glon)
        gelaende.append(
            {
                "name": name,
                "lat": glat,
                "lon": glon,
                "distanz_m": round(dist),
                "richtung": bearing_label(lat, lon, glat, glon),
            }
        )
    gelaende.sort(key=lambda g: g["distanz_m"])

    laufend = [e for e in events if e["start"] <= heute <= e["ende"]]
    kommend = [e for e in events if e["start"] > heute][:MAX_KOMMENDE]

    jahre: dict[str, dict[str, Any]] = {}
    for e in events:
        jahr = e["start"][:4]
        j = jahre.setdefault(
            jahr,
            {"jahr": int(jahr), "veranstaltungen": 0,
             "besucher": 0, "mit_besucherzahl": 0},
        )
        j["veranstaltungen"] += 1
        if e["besucher"] is not None:
            j["besucher"] += e["besucher"]
            j["mit_besucherzahl"] += 1
    jahresreihe = [jahre[k] for k in sorted(jahre)]
    for j in jahresreihe:
        if j["mit_besucherzahl"] == 0:
            j["besucher"] = None

    groesste = sorted(
        (e for e in events if e["besucher"] is not None),
        key=lambda e: e["besucher"],
        reverse=True,
    )[:MAX_GROESSTE]

    return {
        "naechstes_gelaende": gelaende[0],
        "gelaende": gelaende,
        "laufend": laufend,
        "kommend": kommend,
        "jahresreihe": jahresreihe[-8:],
        "groesste": groesste,
        "stand_heute": heute,
        "rohdaten": ROHDATEN,
    }


HINWEISE = [
    "Messebesucher wirken vor allem über **Hotels und die U2**, nicht über "
    "Laufkundschaft am Gelände — die Spitzen kommen dort an, wo die Gäste "
    "übernachten und abends ausgehen.",
    "Besucher- und Ausstellerzahlen stehen erst **nach** einer Veranstaltung "
    "im Datensatz; für kommende Termine gibt der Turnus-Vergleich mit der "
    "Vorveranstaltung die Größenordnung.",
    "Die Gelände-Koordinaten sind fest hinterlegte gewählte Werte für die "
    "Entfernungsangabe, keine Messwerte aus dem Datensatz.",
]


async def load(
    out: Outbound,
    settings: Settings,
    lat: float,
    lon: float,
    heute: str | None = None,
) -> SourceResult:
    started = time.perf_counter()
    naechste = min(
        haversine_m(lat, lon, glat, glon) for glat, glon in GELAENDE.values()
    )
    if naechste > MAX_DISTANZ_M:
        return SourceResult(
            name="messe",
            ok=True,
            data=None,
            warnings=[
                "Der Messe-Kalender gilt für die Gelände der Messe München — "
                f"der Punkt liegt mehr als {MAX_DISTANZ_M // 1000} km davon "
                "entfernt. Für andere Messestädte gibt es keinen vergleichbar "
                "offenen Veranstaltungsdatensatz mit Besucherzahlen."
            ],
        )
    try:
        csv_text = await out.get_text(
            "muenchen_messe",
            CSV_URL,
            timeout=60.0,
            limiter="muenchen",
            min_interval=1.0,
        )
    except SourceError as err:
        return SourceResult.failed(
            "messe", err, int((time.perf_counter() - started) * 1000)
        )

    try:
        events, verworfen = parse_veranstaltungen(csv_text)
    except SourceError as err:
        return SourceResult.failed(
            "messe", err, int((time.perf_counter() - started) * 1000)
        )
    if not events:
        return SourceResult.failed(
            "messe",
            SourceError("parse", "Keine Münchner Veranstaltungen in der CSV gefunden."),
            int((time.perf_counter() - started) * 1000),
        )
    heute = heute or time.strftime("%Y-%m-%d", time.gmtime())
    data = auswerten(events, lat, lon, heute)
    data["hinweise"] = HINWEISE

    warnungen: list[str] = []
    if verworfen:
        warnungen.append(
            f"{verworfen} Münchner Zeile(n) mit unlesbarem Termin im "
            "Datensatz übersprungen."
        )
    if not data["kommend"] and not data["laufend"]:
        warnungen.append(
            "Der Datensatz führt derzeit keine kommenden Münchner Termine — "
            "er wird als „bisherige Veranstaltungen“ gepflegt und läuft dem "
            "Kalender hinterher. Die Jahresbilanz unten zeigt, was der "
            "Messebetrieb üblicherweise bringt."
        )
    return SourceResult(
        name="messe",
        ok=True,
        data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnungen,
        provenance=Provenance(
            source="Veranstaltungen der Messe München (Messe München GmbH, Open-Data-Portal München)",
            license=LIZENZ,
            endpoint=CSV_URL,
            stand="fortlaufend gepflegt, Veranstaltungen ab 2018",
            retrieved_at=now_iso(),
            note=(
                "Nur Veranstaltungen in München (die Messe München veranstaltet "
                "auch im Ausland — diese Zeilen sind herausgefiltert). "
                "Besucherzahlen nur für vergangene Veranstaltungen."
            ),
        ),
    )
