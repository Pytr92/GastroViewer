"""Wahlergebnis Österreich — Nationalratswahl 29.09.2024 (BMI über data.gv.at).

Gegenstück zu ``wahl.py`` (Bundestagswahl, Wahlkreisebene): dieselbe
Blockform (``wahl``, ``wahlkreise``, ``mehrere_wahlkreise``,
``beteiligung_prozent``, ``parteien`` mit ``partei``, ``zweitstimmen``,
``prozent``, ``diff_prozentpunkte``, ``portal``). In Österreich gibt es
keine Zweitstimme — ``zweitstimmen`` trägt die Parteistimmen, das Etikett
dafür steht in ``stimmen_label``.

Datensatz ``Ergebnisse der Nationalratswahl 2024 (BMI)`` auf data.gv.at
(Paket ``e40e3b00-1a98-4338-acb7-42547e6fee55``, CC BY 4.0), am
18.09.2026 live abgefragt (fixtures/at, AT-Probe Runde 3 und 4):

* ``wahl_20241003_214746.csv`` — Semikolon, **cp1252**, Kopfzeile
  ``;Gebietsname;Wahlberechtigte;Abgegebene;Ungültige;Gültige;ÖVP;SPÖ;FPÖ;
  GRÜNE;NEOS;BIER;MFG;BGE;LMP;GAZA;KPÖ;KEINE;``; erste Spalte der
  Gebietscode (``G00000`` Österreich, ``G10000`` Burgenland, ``G1A000``
  Regionalwahlkreis, ``G10100`` Bezirk, ``G10101`` Gemeinde, ``…99``
  Wahlkarten).
* ``gkz-liste-.csv`` — UTF-8 mit BOM, ``LAND;RWK;BEZ;GKZ;NAME``; LAND ist
  die Bundeslandziffer (1 Burgenland … 9 Wien), also derselbe Schlüssel wie
  ``laender.AT.laender``.

Die Gemeinde kommt vom Geocoder (Name), nicht aus einem Schlüssel — der
Block sucht sie namentlich im Bundesland und fällt sonst ehrlich auf das
Landesergebnis zurück. Wien ist Gemeinde und Land zugleich (``G90000``).
Ein Vergleich zu 2019 entfällt: die Vergleichsdatei führt keine
Spaltenköpfe, und geratene Parteispalten wären keine Zahl wert.
"""

from __future__ import annotations

import csv
import io
import re
import time
from typing import Any, Awaitable, Callable

from .base import Provenance, SourceError, SourceResult, now_iso

WAHL = "Nationalratswahl 29.09.2024"
PAKET = "https://www.data.gv.at/katalog/dataset/e40e3b00-1a98-4338-acb7-42547e6fee55"
_RES = PAKET + "/resource"
ERGEBNIS_URL = f"{_RES}/ce85ad5c-e471-42c0-83e5-580dbb627717/download/wahl_20241003_214746.csv"
GKZ_URL = f"{_RES}/da545c2c-b421-439d-8a8a-144c81b66c2e/download/gkz-liste-.csv"
PORTAL = PAKET
LIZENZ = "Creative Commons Namensnennung 4.0 (CC BY 4.0) · Bundesministerium für Inneres, data.gv.at"
STIMMEN_LABEL = "Stimmen"
NICHT_PARTEI = {"gebietsname", "wahlberechtigte", "abgegebene", "ungültige", "gültige"}


def dekodieren(daten: bytes) -> str:
    """UTF-8 (mit oder ohne BOM), sonst cp1252 — die Ergebnisdatei kommt
    in Windows-Kodierung, die GKZ-Liste in UTF-8 mit BOM."""
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return daten.decode(enc)
        except UnicodeDecodeError:
            continue
    return daten.decode("latin-1")


def _zahl(s: str | None) -> int | None:
    t = re.sub(r"[^\d]", "", str(s or ""))
    return int(t) if t else None


def parse_ergebnisse(text: str) -> dict[str, dict[str, Any]]:
    """Gebietscode → {name, wahlberechtigte, abgegebene, gueltige,
    parteien: [{partei, stimmen}]}."""
    zeilen = list(csv.reader(io.StringIO(text), delimiter=";"))
    if not zeilen:
        return {}
    kopf = [h.strip() for h in zeilen[0]]
    parteien = [(i, h) for i, h in enumerate(kopf)
                if i >= 2 and h and h.lower() not in NICHT_PARTEI]
    out: dict[str, dict[str, Any]] = {}
    for z in zeilen[1:]:
        if not z or not re.match(r"^G[0-9][0-9A-Z]\d{3}$", z[0].strip()):
            continue
        code = z[0].strip()
        felder = dict(zip(kopf, z))
        out[code] = {
            "name": felder.get("Gebietsname", "").strip(),
            "wahlberechtigte": _zahl(felder.get("Wahlberechtigte")),
            "abgegebene": _zahl(felder.get("Abgegebene")),
            "gueltige": _zahl(felder.get("Gültige")),
            "parteien": [{"partei": name, "stimmen": _zahl(z[i]) if i < len(z) else None}
                         for i, name in parteien],
        }
    return out


def parse_gkz(text: str) -> list[dict[str, str]]:
    """GKZ-Liste → [{land, rwk, bez, gkz, name}]."""
    out = []
    for r in csv.DictReader(io.StringIO(text.lstrip("﻿")), delimiter=";"):
        gkz = (r.get("GKZ") or "").strip()
        if gkz:
            out.append({"land": (r.get("LAND") or "").strip(), "rwk": (r.get("RWK") or "").strip(),
                        "bez": (r.get("BEZ") or "").strip(), "gkz": gkz,
                        "name": (r.get("NAME") or "").strip()})
    return out


def _norm(name: str | None) -> str:
    s = str(name or "").lower().strip()
    s = s.replace("st. ", "sankt ").replace("st.", "sankt ")
    s = re.sub(r"\s*\(.*?\)\s*", " ", s)
    s = re.sub(r"[^a-zäöüß0-9]+", " ", s).strip()
    return re.sub(r"\s+", " ", s)


def ist_gemeinde(gkz: str) -> bool:
    """``G10101`` Gemeinde; ``G10100`` Bezirk, ``G1A000`` Wahlkreis,
    ``G10000`` Land, ``…99`` Wahlkarten — keine Gemeinden."""
    return bool(re.match(r"^G[1-9]\d{4}$", gkz)) and gkz[-2:] not in ("00", "99")


def finde_gebiet(gkz_liste: list[dict[str, str]], schluessel: str,
                 gemeinde: str | None, gkz: str | None = None) -> tuple[dict[str, str] | None, str]:
    """(Eintrag, Ebene): die Gemeinde im Bundesland, sonst das Land. Eine
    fünfstellige ``gkz`` (Gemeindegrenzen-WFS) hat Vorrang vor dem Namen."""
    land = [g for g in gkz_liste if g["land"] == str(schluessel)]
    if gkz and schluessel != "9":
        eintrag = next((g for g in land if g["gkz"] == f"G{gkz}"), None)
        if eintrag is not None:
            return eintrag, "Gemeinde"
    if schluessel == "9":
        # Wien: Gemeinde = Land (die Bezirke sind Wahlbezirke, keine Gemeinden).
        eintrag = next((g for g in land if g["gkz"] == "G90000"), None)
        return eintrag, "Gemeinde"
    ziel = _norm(gemeinde)
    if ziel:
        gemeinden = [g for g in land if ist_gemeinde(g["gkz"])]
        treffer = [g for g in gemeinden if _norm(g["name"]) == ziel]
        if not treffer:
            treffer = [g for g in gemeinden
                       if _norm(g["name"]).startswith(ziel + " ") or _norm(g["name"]) == ziel + " stadt"]
        if len(treffer) == 1:
            return treffer[0], "Gemeinde"
    eintrag = next((g for g in land if g["gkz"] == f"G{schluessel}0000"), None)
    return eintrag, "Bundesland"


def auswerten(ergebnisse: dict[str, dict[str, Any]], gebiet: dict[str, str],
              ebene: str) -> dict[str, Any] | None:
    e = ergebnisse.get(gebiet["gkz"])
    if e is None or not e.get("gueltige"):
        return None
    gueltige = e["gueltige"]
    parteien = sorted(
        ({"partei": p["partei"], "zweitstimmen": p["stimmen"],
          "prozent": round(p["stimmen"] / gueltige * 100, 1), "diff_prozentpunkte": None}
         for p in e["parteien"] if p["stimmen"] is not None),
        key=lambda p: p["zweitstimmen"], reverse=True)
    beteiligung = (round(e["abgegebene"] / e["wahlberechtigte"] * 100, 1)
                   if e.get("abgegebene") and e.get("wahlberechtigte") else None)
    return {
        "wahl": WAHL,
        "wahlkreise": [{"nr": gebiet["gkz"], "name": e["name"] or gebiet["name"]}],
        "mehrere_wahlkreise": False,
        "ebene": ebene,
        "stimmen_label": STIMMEN_LABEL,
        "beteiligung_prozent": beteiligung,
        "wahlberechtigte": e.get("wahlberechtigte"),
        "parteien": parteien[:8],
        "portal": PORTAL,
    }


HINWEISE = [
    "Struktur-Marker, kein Kundenprofil: Wahlverhalten beschreibt das Umfeld "
    "nur grob, sagt nichts über einzelne Gäste und ersetzt keine "
    "Zielgruppenanalyse.",
    "Gemeindeergebnis der Nationalratswahl 2024 ohne Wahlkarten — die "
    "Briefwahl zählt das BMI je Bezirk und Bundesland gesondert. Ein "
    "Vergleich zu 2019 ist in der offenen Datei nicht sauber möglich und "
    "entfällt.",
]


async def load(adresse: dict[str, Any] | None,
               daten_laden: Callable[[], Awaitable[tuple[dict[str, dict[str, Any]], list[dict[str, str]]]]],
               schluessel: str | None = None, gkz: str | None = None) -> SourceResult:
    """``adresse`` liefert Gemeinde und Bundesland (ISO ``AT-9``);
    ``daten_laden`` das einmal gecachte Paar aus Ergebnissen und GKZ-Liste."""
    from ..laender import land_aus_iso

    started = time.perf_counter()
    a = adresse or {}
    if schluessel is None:
        treffer = land_aus_iso(a.get("bundesland_iso"))
        schluessel = treffer[1] if treffer else None
    if not schluessel and gkz and gkz[:1].isdigit():
        schluessel = gkz[0]
    if not schluessel:
        return SourceResult(
            name="wahl", ok=True, data=None,
            warnings=["Ohne Bundesland (aus der Adresse) lässt sich kein Wahlergebnis zuordnen."])
    try:
        ergebnisse, gkz_liste = await daten_laden()
    except SourceError as err:
        return SourceResult.failed("wahl", err, int((time.perf_counter() - started) * 1000))
    gebiet, ebene = finde_gebiet(gkz_liste, schluessel, a.get("gemeinde"), gkz)
    data = auswerten(ergebnisse, gebiet, ebene) if gebiet else None
    warnungen: list[str] = []
    if data is None:
        warnungen.append("Das Gebiet steht nicht in der Ergebnisdatei des BMI.")
    else:
        if ebene == "Bundesland" and a.get("gemeinde"):
            warnungen.append(
                f"Die Gemeinde „{a['gemeinde']}“ ließ sich namentlich nicht eindeutig "
                "in der GKZ-Liste finden — angezeigt ist das Landesergebnis.")
        data["hinweise"] = HINWEISE
    return SourceResult(
        name="wahl", ok=True, data=data,
        duration_ms=int((time.perf_counter() - started) * 1000), warnings=warnungen,
        provenance=Provenance(
            source=f"Bundesministerium für Inneres — {WAHL}, endgültiges Ergebnis (data.gv.at)",
            license=LIZENZ, endpoint=ERGEBNIS_URL, stand="endgültiges Ergebnis (Datei vom 03.10.2024)",
            retrieved_at=now_iso(),
            note=("Parteistimmen je Gemeinde (ohne Wahlkarten); Zuordnung der Gemeinde "
                  "über Name und Bundesland aus dem Geocoder."),
        ),
    )
