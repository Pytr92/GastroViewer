"""Pendlerverflechtungen der Gemeinde — die beste Tagesbevölkerungs-Näherung.

Der Zensus zählt, wer hier **wohnt**. Für eine Mittagsgastronomie zählt,
wer tagsüber **da ist** — und das entscheiden die Pendler. Die amtliche
Quelle dafür ist die **Pendlerrechnung des Bundes und der Länder**
(Erwerbstätige nach Wohn- und Arbeitsort, Gemeindeebene), veröffentlicht
im Pendleratlas der Statistischen Ämter.

Phase-0-Prüfung am 03.08.2026:

* Die Anwendung ``pendleratlas.statistikportal.de`` lädt ihre Werte als
  **offene CSV-Dateien** unter ``/data/csv/{jahr}/…`` — je Jahr eine
  Deutschland-Datei für Einpendler, Auspendler, Saldo, Quoten und
  Binnenpendler (Schlüssel: 12-stelliger Regionalschlüssel ARS) sowie je
  Bundesland eine Verflechtungsdatei mit den wichtigsten Herkunfts- und
  Zielgemeinden samt Entfernung. Jahrgänge 2021–2024 vorhanden.
* Lizenz laut Anwendung: Datenlizenz Deutschland – Namensnennung – 2.0.
* Live-Gegenprobe München (ARS 091620000000, Jahr 2024): 529.834
  Einpendler, 248.679 Auspendler, Saldo +281.155, Einpendlerquote 45,3 %,
  640.422 Binnenpendler — plausibel gegen die Veröffentlichungen der
  Pendlerrechnung (Erwerbstätigen-, nicht nur SvB-Konzept).

Der Gemeindeschlüssel (AGS, 8-stellig) aus dem Zensusblock wird über die
Gemeindeliste des Pendleratlas auf den ARS abgebildet: die Stellen 1–5
(Land, RB, Kreis) und 10–12 (Gemeinde) des ARS ergeben zusammen den AGS.

Ehrliche Grenze: **Gemeindewert.** Für München heißt das die ganze Stadt,
nicht das Viertel. Und die Pendlerrechnung modelliert Arbeitswege aus den
Melde- und Erwerbsdaten — Fernpendler mit Zweitwohnung oder Homeoffice
stecken mit ihren gemeldeten Orten darin (Berlin taucht deshalb als
München-„Herkunft" auf, mit 501 km Entfernung dabei — die Distanz steht
mit im Datensatz und wird mit angezeigt).
"""

from __future__ import annotations

import time
from typing import Any

from .base import Provenance, SourceError, SourceResult, now_iso

LICENSE = (
    "© Statistische Ämter des Bundes und der Länder, Pendlerrechnung · "
    "Datenlizenz Deutschland – Namensnennung – Version 2.0"
)

BASIS = "https://pendleratlas.statistikportal.de/data"

# Deutschland-weite Kennzahldateien: Dateikürzel -> (Spaltenname, Schlüssel).
KARTEN = [
    ("EIP_Karte", "EIP", "einpendler"),
    ("AUSP_Karte", "AUSP", "auspendler"),
    ("Saldo_Karte", "Saldo", "saldo"),
    ("EIP_Quote_Karte", "EIP_Quote", "einpendler_quote"),
    ("AUSP_Quote_Karte", "AUSP_Quote", "auspendler_quote"),
    ("IOP_Karte", "IOP", "binnenpendler"),
]

TOP_N = 5


def _zahl(s: str) -> float | None:
    s = (s or "").strip()
    if not s or not s[0].isdigit() and not s.startswith("-"):
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f.is_integer() else f


def ars_aus_ags(ags: str, gemeinden: list[dict[str, Any]]) -> dict[str, Any] | None:
    """AGS (8-stellig) -> Gemeindeeintrag des Pendleratlas (ARS, Name).

    ARS-Aufbau: Land(2) RB(1) Kreis(2) Verband(4) Gemeinde(3). Der AGS ist
    dieselbe Kennung ohne den Verbandsteil: Stellen 1–5 + 10–12."""
    a = "".join(c for c in str(ags) if c.isdigit())
    if len(a) < 8:
        return None
    a = a[:8]
    for g in gemeinden:
        ars = str(g.get("ars") or "")
        if len(ars) == 12 and ars[:5] + ars[9:] == a:
            return g
    return None


def parse_karte(text: str, spalte: str) -> dict[str, float | None]:
    """``ARS;WERT;WERT_m;WERT_w`` — nur Gesamtwert, je ARS."""
    zeilen = text.splitlines()
    if not zeilen:
        return {}
    kopf = [t.strip() for t in zeilen[0].split(";")]
    try:
        idx = kopf.index(spalte)
    except ValueError:
        return {}
    ergebnis: dict[str, float | None] = {}
    for zeile in zeilen[1:]:
        teile = zeile.split(";")
        if len(teile) <= idx:
            continue
        ergebnis[teile[0].strip()] = _zahl(teile[idx])
    return ergebnis


def parse_verflechtung(
    text: str, ars: str, namen: dict[str, str]
) -> dict[str, list[dict[str, Any]]]:
    """``Rang;ARS;ARS_AO;AUSP_AO;AUSP_km;ARS_WO;EIP_WO;EIP_km`` je Gemeinde:
    die wichtigsten Auspendler-Ziele (AO) und Einpendler-Herkünfte (WO)."""
    ziele: list[dict[str, Any]] = []
    herkunft: list[dict[str, Any]] = []
    zeilen = text.splitlines()
    for zeile in zeilen[1:]:
        t = zeile.split(";")
        if len(t) < 8 or t[1].strip() != ars:
            continue
        if len(ziele) < TOP_N:
            ziel_ars = t[2].strip()
            anzahl = _zahl(t[3])
            if anzahl is not None:
                ziele.append({
                    "ars": ziel_ars,
                    "name": namen.get(ziel_ars) or ziel_ars,
                    "anzahl": anzahl,
                    "km": _zahl(t[4]),
                })
        if len(herkunft) < TOP_N:
            her_ars = t[5].strip()
            anzahl = _zahl(t[6])
            if anzahl is not None:
                herkunft.append({
                    "ars": her_ars,
                    "name": namen.get(her_ars) or her_ars,
                    "anzahl": anzahl,
                    "km": _zahl(t[7]),
                })
        if len(ziele) >= TOP_N and len(herkunft) >= TOP_N:
            break
    return {"ziele": ziele, "herkunft": herkunft}


def auswerten(
    ags: str,
    jahr: int,
    gemeinden: list[dict[str, Any]],
    karten_texte: dict[str, str],
    verflechtung_text: str | None,
) -> dict[str, Any] | None:
    eintrag = ars_aus_ags(ags, gemeinden)
    if eintrag is None:
        return None
    ars = str(eintrag["ars"])
    namen = {str(g.get("ars")): g.get("gen") for g in gemeinden}

    data: dict[str, Any] = {
        "jahr": jahr,
        "gemeinde": {"ars": ars, "name": eintrag.get("gen")},
    }
    belegt = False
    for datei, spalte, schluessel in KARTEN:
        text = karten_texte.get(datei)
        wert = parse_karte(text, spalte).get(ars) if text else None
        data[schluessel] = wert
        belegt = belegt or wert is not None
    if not belegt:
        return None
    if verflechtung_text:
        data["verflechtung"] = parse_verflechtung(verflechtung_text, ars, namen)
    return data


def ergebnis(
    data: dict[str, Any] | None, started: float, warnings: list[str], jahr: int | None
) -> SourceResult:
    if data is None:
        return SourceResult(
            name="pendler", ok=True, data=None,
            duration_ms=int((time.perf_counter() - started) * 1000),
            warnings=warnings + [
                "Für diese Gemeinde führt der Pendleratlas keine Werte."
            ],
        )
    return SourceResult(
        name="pendler",
        ok=True,
        data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnings,
        provenance=Provenance(
            source=(
                "Pendleratlas Deutschland — Pendlerrechnung des Bundes und "
                "der Länder (Erwerbstätige nach Wohn- und Arbeitsort)"
            ),
            license=LICENSE,
            endpoint=f"{BASIS}/csv/",
            stand=f"Berichtsjahr {jahr}" if jahr else None,
            retrieved_at=now_iso(),
            note=(
                "Gemeindewert — für eine Großstadt die ganze Stadt, kein "
                "Viertel. Erwerbstätigen-Konzept; gemeldete Orte, deshalb "
                "können Fernbeziehungen (Homeoffice, Zweitwohnung) mit "
                "großen Entfernungen auftauchen — die km stehen dabei."
            ),
        ),
    )


def datei_urls(jahr: int, land: str) -> dict[str, str]:
    urls = {
        datei: f"{BASIS}/csv/{jahr}/{jahr}_{datei}_L00.csv"
        for datei, _, _ in KARTEN
    }
    urls["Verfl"] = f"{BASIS}/csv/{jahr}/{jahr}_Verfl_L{land}.csv"
    urls["gemeinden"] = f"{BASIS}/geojson/gemeinden_{jahr}.json"
    return urls
