"""Indikatorenatlas der Landeshauptstadt München — der Viertel-Steckbrief.

Der Zensus 2022 zeichnet das Umfeld räumlich fein (100-m-Raster), aber als
Momentaufnahme. Der Indikatorenatlas des Statistischen Amts ergänzt die
**Entwicklung**: jährliche Zeitreihen je Stadtbezirk. Für die Standortfrage
übersetzt: Wächst das Viertel? Altert es? Wohnen hier Singles (die häufiger
essen gehen) oder Familien? Wie stark wechselt die Wohnbevölkerung?

Verifiziert am 2026-08-07 über die CKAN-API
(``opendata.muenchen.de/api/3/action/package_search?q=indikatorenatlas``,
68 Datensätze): CSV-Spalten ``Indikator, Ausprägung, Jahr, Raumbezug,
Indikatorwert, Basiswert 1, Basiswert 2, Name Basiswert 1, Name Basiswert 2``;
Raumbezug „Stadt München" plus 25 Bezirke wie „01 Altstadt - Lehel";
Dezimalpunkt; Jahre bis 2025 (Arbeitslosen-Anteil bis 2024). Die Bedeutung
jeder Kennzahl ist aus den Basiswert-Spalten der Daten selbst belegt — z. B.
Einpersonenhaushalte = „Privathaushalte (Einpersonen)" geteilt durch
„Privathaushalte (insgesamt)".

Die Dateinamen im Portal sind unregelmäßig und werden über die CKAN-Suche
aufgelöst, nie geraten. Der Stadtbezirk des Punkts kommt aus der ohnehin
geladenen Nominatim-Adresse (``suburb``/``city_district``) — dafür geht
keine zusätzliche Anfrage hinaus.
"""

from __future__ import annotations

import csv
import io
import re
import time
from typing import Any

from .base import Provenance, SourceError, SourceResult, now_iso

CKAN_SEARCH_URL = "https://opendata.muenchen.de/api/3/action/package_search"
CKAN_SEARCH_PARAMS = {"q": "indikatorenatlas", "rows": "100"}

LIZENZ = (
    "Datenlizenz Deutschland Namensnennung 2.0 (dl-de/by-2-0) · "
    "© Landeshauptstadt München, Statistisches Amt"
)
PORTAL = "https://opendata.muenchen.de/dataset?q=indikatorenatlas"

# Sechs CSV-Dateien tragen sieben Kennzahlen (zwei Dateien liefern je zwei
# Ausprägungen) — heruntergeladen wird jede Datei genau einmal.
DATEIEN: dict[str, str] = {
    "einpersonenhaushalte": "Indikatorenatlas: Bevölkerung - Einpersonenhaushalte",
    "durchschnittsalter": "Indikatorenatlas: Bevölkerung - Durchschnittsalter",
    "altersgruppen": "Indikatorenatlas: Bevölkerung - Altersgruppen",
    "bev_dichte": "Indikatorenatlas: Bevölkerung - Bevölkerungsdichte",
    "wohndauer": "Indikatorenatlas: Bevölkerung - Wohndauer Adresse",
    "arbeitslosen_anteil": "Indikatorenatlas: Arbeitsmarkt - Arbeitslosen - Anteil",
}

# Jede Kennzahl nennt ihre Datei, die Ausprägung und die Bedeutung —
# Letztere aus den Basiswert-Spalten der CSV belegt (siehe Modulkopf).
INDIKATOREN: list[dict[str, str]] = [
    {
        "schluessel": "einpersonenhaushalte",
        "datei": "einpersonenhaushalte",
        "auspraegung": "insgesamt",
        "label": "Einpersonenhaushalte",
        "einheit": "% der Haushalte",
        "deutung": "Singles essen häufiger auswärts — je höher, desto mehr Ausgeh-Publikum wohnt im Viertel.",
    },
    {
        "schluessel": "einpersonen_jung",
        "datei": "einpersonenhaushalte",
        "auspraegung": "bis 29 Jahre",
        "label": "davon unter 30 Jahre",
        "einheit": "% der Einpersonenhaushalte",
        "deutung": "Junge Single-Haushalte: Kernzielgruppe für Schnellgastronomie und Bars.",
    },
    {
        "schluessel": "durchschnittsalter",
        "datei": "durchschnittsalter",
        "auspraegung": "insgesamt",
        "label": "Durchschnittsalter",
        "einheit": "Jahre",
        "deutung": "Wird das Viertel jünger oder älter? Verschiebt die Zielgruppe über Jahre.",
    },
    {
        "schluessel": "senioren",
        "datei": "altersgruppen",
        "auspraegung": "65 Jahre und älter",
        "label": "65 Jahre und älter",
        "einheit": "% der Bevölkerung",
        "deutung": "Hoher Senioren-Anteil: eher Café-/Konditorei-Publikum am Nachmittag als Barbetrieb.",
    },
    {
        "schluessel": "bev_dichte",
        "datei": "bev_dichte",
        "auspraegung": "insgesamt",
        "label": "Bevölkerungsdichte",
        "einheit": "Ew. je km²",
        "deutung": "Die Trendrichtung zeigt, ob der Bezirk wächst — mehr Anwohner, mehr Grundnachfrage.",
    },
    {
        "schluessel": "wohndauer",
        "datei": "wohndauer",
        "auspraegung": "insgesamt",
        "label": "Wohndauer an der Adresse",
        "einheit": "Jahre",
        "deutung": "Kurze Wohndauer = hohe Fluktuation: ständig neue Kundschaft, aber weniger Stammgäste.",
    },
    {
        "schluessel": "arbeitslosen_anteil",
        "datei": "arbeitslosen_anteil",
        "auspraegung": "insgesamt",
        "label": "Arbeitslose",
        "einheit": "% der 15- bis 64-Jährigen",
        "deutung": "Grober Kaufkraft-Frühindikator auf Bezirksebene.",
    },
]

STADT_RAUM = "Stadt München"


def finde_csv_urls(payload: Any) -> tuple[dict[str, str], list[str]]:
    """CKAN-Suche → je Kennzahl die CSV-URL. Titel werden exakt verglichen
    („Durchschnittsalter" darf nicht „Durchschnittsalter Mütter" treffen)."""
    je_titel: dict[str, str] = {}
    for p in ((payload or {}).get("result") or {}).get("results") or []:
        titel = str(p.get("title") or "")
        for r in p.get("resources") or []:
            if r.get("format") == "CSV" and r.get("url"):
                je_titel.setdefault(titel, r["url"])
                break
    urls: dict[str, str] = {}
    fehlend: list[str] = []
    for datei, titel in DATEIEN.items():
        url = je_titel.get(titel)
        if url:
            urls[datei] = url
        else:
            fehlend.append(titel)
    return urls, fehlend


def norm_bezirk(name: Any) -> str:
    """„01 Altstadt - Lehel" und „Altstadt-Lehel" → „altstadtlehel"."""
    return re.sub(r"[^a-zäöüß]", "", str(name or "").lower())


def reduzieren(texte: dict[str, str]) -> dict[str, Any]:
    """CSV-Texte → kompakte Reihen ``{schluessel: {raum: [[jahr, wert], …]}}``.

    Nur die benötigte Ausprägung je Kennzahl; so bleibt der stadtweite
    Cache-Eintrag klein und jede Punktauswertung reine lokale Rechnung.
    """
    kompakt: dict[str, Any] = {}
    for ind in INDIKATOREN:
        text = texte.get(ind["datei"])
        if not text:
            continue
        raeume: dict[str, list[list[float]]] = {}
        for row in csv.DictReader(io.StringIO(text.replace("﻿", ""))):
            if (row.get("Ausprägung") or "").strip() != ind["auspraegung"]:
                continue
            raum = (row.get("Raumbezug") or "").strip()
            jahr_s = (row.get("Jahr") or "").strip()
            wert_s = (row.get("Indikatorwert") or "").strip()
            if not raum or not re.fullmatch(r"\d{4}", jahr_s):
                continue
            try:
                wert = float(wert_s)
            except ValueError:
                continue
            raeume.setdefault(raum, []).append([int(jahr_s), wert])
        for reihe in raeume.values():
            reihe.sort()
        if raeume:
            kompakt[ind["schluessel"]] = raeume
    return kompakt


def _trend(reihe: list[list[float]]) -> dict[str, Any] | None:
    """Jüngster Wert gegen den Stand ~5 Jahre davor (nächstes vorhandenes
    Jahr; notfalls das früheste). Delta in der Einheit der Kennzahl."""
    if not reihe:
        return None
    jahr_neu, wert_neu = reihe[-1]
    ziel = jahr_neu - 5
    frueher = [p for p in reihe if p[0] <= ziel]
    basis = frueher[-1] if frueher else reihe[0]
    if basis[0] == jahr_neu:
        return {"jahr": int(jahr_neu), "wert": wert_neu, "von_jahr": None,
                "von_wert": None, "delta": None}
    return {
        "jahr": int(jahr_neu),
        "wert": wert_neu,
        "von_jahr": int(basis[0]),
        "von_wert": basis[1],
        "delta": round(wert_neu - basis[1], 2),
    }


def auswerten(kompakt: dict[str, Any], bezirksname: str | None) -> dict[str, Any]:
    """Kompakte Reihen + Bezirksname → Blockdaten. Ohne zuordenbaren Bezirk
    bleiben die Stadtwerte stehen — mit klarer Ansage statt stillem Loch."""
    ziel_norm = norm_bezirk(bezirksname)
    bezirk_raum: str | None = None
    if ziel_norm:
        for schluessel in kompakt:
            for raum in kompakt[schluessel]:
                if raum != STADT_RAUM and norm_bezirk(raum) == ziel_norm:
                    bezirk_raum = raum
                    break
            if bezirk_raum:
                break

    zeilen: list[dict[str, Any]] = []
    for ind in INDIKATOREN:
        raeume = kompakt.get(ind["schluessel"]) or {}
        stadt = _trend(raeume.get(STADT_RAUM) or [])
        bezirk = _trend(raeume.get(bezirk_raum) or []) if bezirk_raum else None
        reihe = (raeume.get(bezirk_raum) or []) if bezirk_raum else []
        if stadt is None and bezirk is None:
            continue
        zeilen.append(
            {
                "schluessel": ind["schluessel"],
                "label": ind["label"],
                "einheit": ind["einheit"],
                "deutung": ind["deutung"],
                "bezirk": bezirk,
                "stadt": stadt,
                "reihe": [[int(j), w] for j, w in reihe[-12:]],
            }
        )
    return {
        "bezirk": bezirk_raum,
        "bezirk_gesucht": bezirksname,
        "stadt_raum": STADT_RAUM,
        "indikatoren": zeilen,
        "hinweise": HINWEISE,
    }


HINWEISE = [
    "Bezirksebene, nicht Adresse: Ein Stadtbezirk mischt sehr verschiedene "
    "Lagen — die Feinauflösung liefert weiterhin der Zensus-Block, hier "
    "steht die **Entwicklung über die Jahre**.",
    "Der Trendvergleich reicht ~5 Jahre zurück (gewählter Wert): kurz genug "
    "für aktuelle Entwicklung, lang genug, um Einmaleffekte zu glätten.",
    "Die Bedeutung jeder Kennzahl ist aus den Basiswert-Spalten der "
    "Original-CSV übernommen, nicht interpretiert.",
]


async def load(
    out: Any,
    settings: Any,
    gemeinde: str | None,
    bezirksname: str | None,
    stadt_laden: Any,
) -> SourceResult:
    """``stadt_laden``: async-Funktion, die die **stadtweit gecachten**
    kompakten Reihen liefert (eine CKAN-Suche + sechs CSVs, einmal je
    Laufzeit des Caches). Außerhalb Münchens wird sie gar nicht gerufen."""
    started = time.perf_counter()
    if (gemeinde or "").strip() != "München":
        return SourceResult(
            name="indikatoren",
            ok=True,
            data=None,
            warnings=[
                "Den Indikatorenatlas gibt es nur für die Stadt München "
                "(Stadtbezirks-Ebene). Für andere Kommunen liegt hier keine "
                "vergleichbare offene Zeitreihe vor."
            ],
        )
    try:
        stadt = await stadt_laden()
    except SourceError as err:
        return SourceResult.failed(
            "indikatoren", err, int((time.perf_counter() - started) * 1000)
        )

    kompakt = (stadt or {}).get("kompakt") or {}
    data = auswerten(kompakt, bezirksname)
    warnungen = list((stadt or {}).get("fehlend_warnungen") or [])
    if data["bezirk"] is None:
        warnungen.append(
            "Der Stadtbezirk ließ sich aus der Adresse nicht eindeutig "
            f"zuordnen (gemeldet: {bezirksname or '—'}). Gezeigt werden die "
            "stadtweiten Reihen."
        )
    return SourceResult(
        name="indikatoren",
        ok=True,
        data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnungen,
        provenance=Provenance(
            source="Indikatorenatlas München (Statistisches Amt, Open-Data-Portal)",
            license=LIZENZ,
            endpoint=CKAN_SEARCH_URL,
            stand=(stadt or {}).get("stand") or "jährliche Fortschreibung",
            retrieved_at=now_iso(),
            note=(
                "Jahresreihen je Stadtbezirk; Kennzahl-Bedeutungen aus den "
                "Basiswert-Spalten der Original-CSVs. Dateinamen über die "
                "CKAN-API aufgelöst."
            ),
        ),
    )
