"""Wahlergebnis der Bundestagswahl 2025 — Wahlkreisebene, als Struktur-Marker.

Auf ausdrücklichen Nutzerwunsch eingebaut. Was das für die Standortwahl
sein kann — und was nicht — steht als Warnung am Block: Wahlverhalten
ist eine grobe Näherung an die soziale Zusammensetzung des Umfelds,
**kein** Kundenprofil.

Phase-0 am 2026-08-08 mit echten Downloads verifiziert (beide Dateien
Datenlizenz Deutschland — Namensnennung — 2.0):

* ``…/opendata/btw25/csv/kerg2.csv`` — 1,8 MB, UTF-8 mit BOM, Semikolon;
  je Gebiet (Bund/Land/**Wahlkreis**) und Gruppe die Erst-/Zweitstimmen
  („Stimme" 1/2) mit Prozent und Differenz zur Vorwahl in
  Prozentpunkten. Endgültiges Ergebnis, Stand 14.03.2025.
* ``…/btw25_wkr_gemeinden_20241130_utf8.csv`` — Zuordnung aller
  Gemeinden zu Wahlkreisen (Gebietsstand 30.11.2024). Der AGS entsteht
  aus RGS_Land + RGS_RegBez + RGS_Kreis + RGS_Gemeinde. Großstädte
  verteilen sich auf **mehrere** Wahlkreise (München: 4) — dann werden
  die absoluten Zweitstimmen dieser Wahlkreise aufsummiert und genau so
  beschriftet; Wahlkreiszuschnitte folgen nicht den Gemeindegrenzen.

Beide Dateien werden **einmal** geladen und gecacht (endgültiges
Ergebnis — es ändert sich bis zur nächsten Wahl nicht).
"""

from __future__ import annotations

import csv
import io
import time
from typing import Any

from .base import Provenance, SourceError, SourceResult, now_iso

WAHL = "Bundestagswahl 23.02.2025"
KERG2_URL = ("https://www.bundeswahlleiterin.de/bundestagswahlen/2025/"
             "ergebnisse/opendata/btw25/csv/kerg2.csv")
MAPPING_URL = ("https://www.bundeswahlleiterin.de/dam/jcr/"
               "aa868597-0e60-476c-bd2b-279c1e9a142a/"
               "btw25_wkr_gemeinden_20241130_utf8.csv")
PORTAL = ("https://www.bundeswahlleiterin.de/bundestagswahlen/2025/"
          "ergebnisse/opendata.html")
LIZENZ = ("Datenlizenz Deutschland — Namensnennung — 2.0 (dl-de/by-2-0), "
          "© Die Bundeswahlleiterin, Wiesbaden 2025")


def _zahl(s: str | None) -> float | None:
    t = str(s or "").strip()
    if not t or t in ("–", "-"):
        return None
    try:
        return float(t.replace(",", "."))
    except ValueError:
        return None


def _csv_zeilen(text: str) -> list[dict[str, str]]:
    """Kopfkommentare (mit oder ohne ``#``) überspringen, ab der
    Spaltenzeile als CSV lesen."""
    zeilen = text.lstrip("﻿").splitlines()
    start = next((i for i, z in enumerate(zeilen)
                  if z.startswith(("Wahlart;", "Wahlkreis-Nr;"))), None)
    if start is None:
        raise SourceError(
            "parse", "Wahl-CSV ohne erwartete Spaltenzeile — Format geändert?")
    return list(csv.DictReader(io.StringIO("\n".join(zeilen[start:])),
                               delimiter=";"))


def parse_mapping(text: str) -> dict[str, list[dict[str, Any]]]:
    """Zuordnungsdatei → AGS8 → Wahlkreise (dedupliziert, Reihenfolge
    der Datei)."""
    zuordnung: dict[str, list[dict[str, Any]]] = {}
    for r in _csv_zeilen(text):
        land = (r.get("RGS_Land") or "").strip()
        regbez = (r.get("RGS_RegBez") or "").strip()
        kreis = (r.get("RGS_Kreis") or "").strip()
        gemeinde = (r.get("RGS_Gemeinde") or "").strip()
        nr = (r.get("Wahlkreis-Nr") or "").strip()
        if not (land and kreis and gemeinde and nr):
            continue
        ags8 = f"{land:0>2}{regbez:0>1}{kreis:0>2}{gemeinde:0>3}"
        eintrag = {"nr": nr, "name": (r.get("Wahlkreis-Bez") or "").strip()}
        liste = zuordnung.setdefault(ags8, [])
        if eintrag not in liste:
            liste.append(eintrag)
    if not zuordnung:
        raise SourceError("parse", "Wahlkreis-Zuordnung ohne Zeilen.")
    return zuordnung


def parse_kerg2(text: str) -> dict[str, dict[str, Any]]:
    """kerg2.csv → je Wahlkreis Beteiligung und Zweitstimmen je Partei."""
    kreise: dict[str, dict[str, Any]] = {}
    for r in _csv_zeilen(text):
        if (r.get("Gebietsart") or "").strip() != "Wahlkreis":
            continue
        nr = (r.get("Gebietsnummer") or "").strip()
        wk = kreise.setdefault(nr, {
            "nr": nr, "name": (r.get("Gebietsname") or "").strip(),
            "wahlberechtigte": None, "beteiligung_prozent": None,
            "parteien": [],
        })
        gruppe = (r.get("Gruppenname") or "").strip()
        art = (r.get("Gruppenart") or "").strip()
        stimme = (r.get("Stimme") or "").strip()
        if art == "System-Gruppe" and gruppe == "Wahlberechtigte":
            wk["wahlberechtigte"] = _zahl(r.get("Anzahl"))
        elif art == "System-Gruppe" and gruppe == "Wählende":
            wk["beteiligung_prozent"] = _zahl(r.get("Prozent"))
        elif art == "Partei" and stimme == "2":
            anzahl = _zahl(r.get("Anzahl"))
            if anzahl is None:
                continue
            wk["parteien"].append({
                "partei": gruppe,
                "zweitstimmen": int(anzahl),
                "prozent": _zahl(r.get("Prozent")),
                "diff_prozentpunkte": _zahl(r.get("DiffProzentPkt")
                                            or r.get("DiffProzentpunkte")),
            })
    if not kreise:
        raise SourceError("parse", "kerg2.csv ohne Wahlkreiszeilen.")
    return kreise


def auswerten(
    zuordnung: dict[str, list[dict[str, Any]]],
    kreise: dict[str, dict[str, Any]],
    ags8: str,
) -> dict[str, Any] | None:
    wahlkreise = zuordnung.get(ags8)
    if not wahlkreise:
        return None
    treffer = [kreise[w["nr"]] for w in wahlkreise if w["nr"] in kreise]
    if not treffer:
        return None

    if len(treffer) == 1:
        basis = treffer[0]
        parteien = sorted(basis["parteien"],
                          key=lambda p: p["zweitstimmen"], reverse=True)
        beteiligung = basis["beteiligung_prozent"]
    else:
        # Mehrere Wahlkreise: absolute Zweitstimmen aufsummieren, Anteile
        # daraus neu rechnen. Punktdifferenzen zur Vorwahl lassen sich
        # über Summen nicht sauber bilden — sie entfallen dann.
        summen: dict[str, int] = {}
        for wk in treffer:
            for p in wk["parteien"]:
                summen[p["partei"]] = summen.get(p["partei"], 0) + p["zweitstimmen"]
        gesamt = sum(summen.values())
        parteien = [{"partei": name, "zweitstimmen": st,
                     "prozent": round(st / gesamt * 100, 1) if gesamt else None,
                     "diff_prozentpunkte": None}
                    for name, st in sorted(summen.items(),
                                           key=lambda kv: kv[1], reverse=True)]
        berechtigte = [w["wahlberechtigte"] for w in treffer]
        beteiligungen = [w["beteiligung_prozent"] for w in treffer]
        beteiligung = (
            round(sum(b * w for b, w in zip(beteiligungen, berechtigte))
                  / sum(berechtigte), 1)
            if all(b is not None for b in beteiligungen)
            and all(w for w in berechtigte) else None
        )

    return {
        "wahl": WAHL,
        "wahlkreise": [{"nr": w["nr"], "name": w["name"]} for w in wahlkreise],
        "mehrere_wahlkreise": len(treffer) > 1,
        "beteiligung_prozent": beteiligung,
        "parteien": parteien[:8],
        "portal": PORTAL,
    }


HINWEISE = [
    "Struktur-Marker, kein Kundenprofil: Wahlverhalten beschreibt das "
    "Umfeld nur grob, sagt nichts über einzelne Gäste und ersetzt keine "
    "Zielgruppenanalyse. Für Konzeptfragen (Szene-Bar oder bürgerliches "
    "Wirtshaus) allenfalls ein Puzzlestein neben Alter, Haushalten und "
    "Miete aus dem Zensusblock.",
    "Wahlkreisebene: Der Zuschnitt folgt nicht den Gemeinde- oder "
    "Viertelgrenzen — ein Wahlkreis kann Innenstadt und Umland mischen.",
]


async def load(out, ags: str, daten_laden) -> SourceResult:
    """Blockergebnis. ``daten_laden`` liefert das (gecachte) Paar aus
    Zuordnung und Wahlkreisergebnissen."""
    started = time.perf_counter()
    try:
        zuordnung, kreise = await daten_laden()
    except SourceError as err:
        return SourceResult.failed(
            "wahl", err, int((time.perf_counter() - started) * 1000))

    data = auswerten(zuordnung, kreise, (ags or "")[:8])
    warnungen: list[str] = []
    if data is None:
        warnungen.append(
            "Die Gemeinde steht nicht in der Wahlkreis-Zuordnung "
            "(Gebietsstand 30.11.2024) — bei Gebietsreformen kann der "
            "Schlüssel abweichen.")
    else:
        if data["mehrere_wahlkreise"]:
            warnungen.append(
                f"Die Gemeinde verteilt sich auf {len(data['wahlkreise'])} "
                "Wahlkreise — angezeigt ist deren Summe; die Zuschnitte "
                "greifen teils über die Gemeindegrenze hinaus.")
        data["hinweise"] = HINWEISE

    return SourceResult(
        name="wahl",
        ok=True,
        data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnungen,
        provenance=Provenance(
            source=f"Die Bundeswahlleiterin — {WAHL}, endgültiges Ergebnis",
            license=LIZENZ,
            endpoint=KERG2_URL,
            stand="endgültiges Ergebnis vom 14.03.2025",
            retrieved_at=now_iso(),
            note=(
                "Zweitstimmen auf Wahlkreisebene; Zuordnung der Gemeinde "
                "über die amtliche Wahlkreis-Gemeinde-Datei "
                "(Gebietsstand 30.11.2024)."
            ),
        ),
    )
