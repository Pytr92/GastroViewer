"""Tourismus-Saisonalität Österreich — Statistik Austria, Nächtigungsstatistik.

Gegenstück zu ``tourismus.py`` (Monatszahlen München): dieselbe Blockform
(``letzte_12_monate``, ``uebernachtungen_12m``, ``veraenderung_vorjahr_prozent``,
``gaeste_12m``, ``aufenthaltsdauer_naechte``, ``ausland_anteil_prozent``,
``saison``, ``jahresreihe``) — gerechnet wird mit ``tourismus.auswerten``,
nur die Reihen kommen aus einer anderen Datei.

Datensatz ``OGD_touextsai_Tour_HKL_1`` („Nächtigungsstatistik ab November
1973 – Nächtigungen nach Herkunftsländern und Bundesländern“, CC BY 4.0,
monatlich aktualisiert), live belegt am 18.09.2026 (fixtures/at):

* ``https://data.statistik.gv.at/data/OGD_touextsai_Tour_HKL_1.csv`` —
  Semikolon, UTF-8, Spalten ``C-SDB_TIT-0`` (Monat als ``JJJJMM``),
  ``C-W96-0`` (Bundesland ``W96-1`` … ``W96-9``, dieselbe Ziffer wie
  ``laender.AT.laender``), ``C-C93-2`` (Herkunftsland als Code),
  ``F-ANK`` (Ankünfte), ``F-UEB`` (Übernachtungen).
* ``…_C-C93-2.csv`` — die Herkunftsland-Klassifikation (``code;name;…``),
  166 Codes ohne Summenzeilen: das Inland ist nach Bundesland aufgeteilt
  (``01`` Wien, ``70``–``77`` die übrigen Länder ab 05/2003, ``02``
  „Österreich ohne Wien“ bis 04/2003), Restposten wie „übriges Ausland“
  oder ``0`` „Nicht klassifizierbar“ sind echte Buckets und zählen mit.
  Ausland = alles, was nicht Wien, Österreich oder ein Bundesland ist.

Die Werte gelten **landesweit** (Bundesland); für Wien ist das die Stadt.
Die ganze Datei ist Megabytes groß — sie wird einmal je 30 Tage geladen,
auf drei Reihen je Bundesland eingedampft und gecacht.
"""

from __future__ import annotations

import csv
import io
import re
import time
from typing import Any, Awaitable, Callable

from .base import Provenance, SourceError, SourceResult, now_iso
from . import tourismus as tourismus_mod

DATENSATZ = "OGD_touextsai_Tour_HKL_1"
BASIS = "https://data.statistik.gv.at/data"
CSV_URL = f"{BASIS}/{DATENSATZ}.csv"
HERKUNFT_URL = f"{BASIS}/{DATENSATZ}_C-C93-2.csv"
ROHDATEN = f"https://data.statistik.gv.at/web/meta.jsp?dataset={DATENSATZ}"
LIZENZ = "Creative Commons Namensnennung 4.0 International (CC BY 4.0) · Statistik Austria"
_INLAND = re.compile(r"^(Wien|Österreich|Oesterreich|Burgenland|Kärnten|Niederösterreich|"
                     r"Oberösterreich|Salzburg|Steiermark|Tirol|Vorarlberg)\b")


def herkunft_lesen(text: str) -> tuple[set[str], set[str]]:
    """(Inland-Codes, alle Codes) aus der Klassifikationsdatei."""
    inland: set[str] = set()
    alle: set[str] = set()
    for r in csv.reader(io.StringIO(text.lstrip("\ufeff")), delimiter=";"):
        if len(r) < 2 or r[0].strip().lower() == "code":
            continue
        code, name = r[0].strip(), r[1].strip()
        if not code:
            continue
        alle.add(code)
        if _INLAND.match(name):
            inland.add(code)
    return inland, alle


def reduzieren(csv_text: str, inland: set[str], einzel: set[str] | None = None) -> dict[str, dict[str, dict[str, int]]]:
    """Daten-CSV → je Bundesland-Schlüssel (``1`` … ``9``) die drei Reihen
    in der Form von ``tourismus.parse_monatszahlen``."""
    reihen: dict[str, dict[str, dict[str, int]]] = {}
    reader = csv.reader(io.StringIO(csv_text.lstrip("\ufeff")), delimiter=";")
    kopf = next(reader, None)
    if not kopf:
        return {}
    spalten = {h.strip(): i for i, h in enumerate(kopf)}
    try:
        i_monat, i_land, i_herk = spalten["C-SDB_TIT-0"], spalten["C-W96-0"], spalten["C-C93-2"]
        i_ank, i_ueb = spalten["F-ANK"], spalten["F-UEB"]
    except KeyError as err:
        raise SourceError("parse", f"Spalte {err} fehlt in {DATENSATZ}.csv") from err
    for z in reader:
        if len(z) <= max(i_monat, i_land, i_herk, i_ank, i_ueb):
            continue
        herk = z[i_herk].strip()
        if einzel and herk not in einzel:
            continue
        monat = z[i_monat].strip()
        if not re.match(r"^\d{6}$", monat):
            continue
        land = z[i_land].strip().split("-")[-1]
        r = reihen.setdefault(land, {"Übernachtungen|insgesamt": {}, "Gäste|insgesamt": {},
                                     "Übernachtungen|Ausland": {}})
        try:
            ank, ueb = int(float(z[i_ank] or 0)), int(float(z[i_ueb] or 0))
        except ValueError:
            continue
        r["Übernachtungen|insgesamt"][monat] = r["Übernachtungen|insgesamt"].get(monat, 0) + ueb
        r["Gäste|insgesamt"][monat] = r["Gäste|insgesamt"].get(monat, 0) + ank
        if herk not in inland:
            r["Übernachtungen|Ausland"][monat] = r["Übernachtungen|Ausland"].get(monat, 0) + ueb
    # Jahressummen nur für volle Jahre — wie die Münchner Datei sie führt.
    for r in reihen.values():
        for reihe in r.values():
            jahre: dict[str, list[str]] = {}
            for m in list(reihe):
                if len(m) == 6:
                    jahre.setdefault(m[:4], []).append(m)
            for jahr, monate in jahre.items():
                if len(monate) == 12:
                    reihe[f"{jahr}|Summe"] = sum(reihe[m] for m in monate)
    return reihen


HINWEISE = [
    "Die Zahlen erfassen **gewerbliche und private Beherbergung** laut "
    "Nächtigungsstatistik (Betriebe ab drei Betten, Privatquartiere) — "
    "Airbnb-Inserate kommen obendrauf.",
    "Die Werte gelten **landesweit** (Bundesland; für Wien die Stadt) und "
    "ändern sich nicht mit dem gewählten Punkt; sie beantworten die Frage "
    "nach dem Jahresverlauf, nicht die nach der Lage.",
    "Die Aufenthaltsdauer ist eine abgeleitete Zahl: Übernachtungen der "
    "letzten 12 Monate geteilt durch Ankünfte derselben Monate.",
    "Liegen Corona-Jahre (2020–2022) in der Saisonkurve, drücken Lockdown-"
    "Monate Winter und Frühjahr zusätzlich — die einbezogenen Jahre stehen "
    "deshalb direkt an der Kurve.",
]


async def load(schluessel: str | None, bundesland: str | None,
               daten_laden: Callable[[], Awaitable[dict[str, dict[str, dict[str, int]]]]]) -> SourceResult:
    started = time.perf_counter()
    if not schluessel:
        return SourceResult(
            name="tourismus", ok=True, data=None,
            warnings=["Ohne Bundesland (aus der Adresse) lässt sich keine Nächtigungsreihe zuordnen."])
    try:
        alle = await daten_laden()
    except SourceError as err:
        return SourceResult.failed("tourismus", err, int((time.perf_counter() - started) * 1000))
    reihen = alle.get(str(schluessel))
    if not reihen:
        return SourceResult(
            name="tourismus", ok=True, data=None,
            warnings=[f"Statistik Austria führt für Bundesland {schluessel} keine Reihe."])
    try:
        data = tourismus_mod.auswerten(reihen)
    except SourceError as err:
        return SourceResult.failed("tourismus", err, int((time.perf_counter() - started) * 1000))
    data["rohdaten"] = ROHDATEN
    data["gebiet"] = bundesland or f"Bundesland {schluessel}"
    data["hinweise"] = HINWEISE
    letzter = data["letzte_12_monate"][-1]["monat"]
    return SourceResult(
        name="tourismus", ok=True, data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        provenance=Provenance(
            source=f"Statistik Austria — Nächtigungsstatistik, Bundesland {data['gebiet']}",
            license=LIZENZ, endpoint=CSV_URL,
            stand=f"Monatsreihe ab November 1973, jüngster gefüllter Monat {letzter}",
            retrieved_at=now_iso(),
            note=("Ankünfte und Übernachtungen je Bundesland, Summe über die Einzel-"
                  "Herkunftsländer; Ausland = alle außer Österreich."),
        ),
    )
