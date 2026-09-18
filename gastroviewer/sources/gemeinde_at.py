"""Gemeindeprofil Österreich — Statistik Austria, Gemeindetabelle der
Abgestimmten Erwerbsstatistik und Arbeitsstättenzählung.

Gegenstück zum deutschen Kreisprofil (``kreisprofil.py``, Regionalatlas):
dieselbe Blockform (``gebiete`` mit ``kreis``/``land``/``bund``,
``indikatoren`` mit ``schluessel``, ``titel``, ``thema``, ``einheit``,
``stellen``, ``jahr``, ``kreis``, ``land``, ``bund``, ``reihe``), nur dass
die erste Spalte die **Gemeinde** ist — in Wien der Gemeindebezirk.

Datensatz ``OGDEXT_AEST_GEMTAB_1`` (CC BY 4.0), live belegt am 18.09.2026
(fixtures/at, AT-Probe Runde 5): eine CSV (2,8 MB, Semikolon, UTF-8,
Dezimalkomma) mit den Spalten ``JAHR;GCD;GEM_NAME;BEV_ABSOLUT;BEV_UNTER15;
BEV_UEBER65;AUSL_STAATSB;EWTQ_15BIS64;ALQ_15PLUS;EDU_15_SEK;EDU_15_TER;
AUSPENDLER;PHH;HH_SIZE;FAMILIEN;UNT;AST;BESCH_AST`` — Jahre 2011 bis 2021,
alle 2.093 Gemeinden, Wien nach 23 Gemeindebezirken (``90101`` Innere
Stadt … ``92301`` Liesing). Das jüngste Jahr ist je Gemeinde verschieden
(2021 liegt nur für einen Teil vor), deshalb nimmt der Block das jüngste
verfügbare und nennt es.

Bundesland und Österreich werden hier aus den Gemeindezeilen gerechnet:
Summen für absolute Größen, einwohnergewichtete Mittel für Anteile — die
Datei führt keine Aggregatzeilen. Die Zuordnung Punkt → Gemeinde läuft
über den Namen aus dem Geocoder innerhalb des Bundeslands (wie beim
Wahlblock); ohne Treffer bleibt der Bundeslandwert.
"""

from __future__ import annotations

import csv
import io
import re
import time
from typing import Any, Awaitable, Callable

from ..laender import AT
from .base import Provenance, SourceError, SourceResult, now_iso
from .wahl_at import _norm

DATENSATZ = "OGDEXT_AEST_GEMTAB_1"
CSV_URL = f"https://data.statistik.gv.at/data/{DATENSATZ}.csv"
ROHDATEN = f"https://data.statistik.gv.at/web/meta.jsp?dataset={DATENSATZ}"
LIZENZ = "Creative Commons Namensnennung 4.0 International (CC BY 4.0) · Statistik Austria"

ABSOLUT = ("BEV_ABSOLUT", "PHH", "FAMILIEN", "UNT", "AST", "BESCH_AST")
# Anteile: gewichtet mit der Bevölkerung (Haushaltsgröße mit den Haushalten).
GEWICHTET = {"BEV_UNTER15": "BEV_ABSOLUT", "BEV_UEBER65": "BEV_ABSOLUT", "AUSL_STAATSB": "BEV_ABSOLUT",
             "EWTQ_15BIS64": "BEV_ABSOLUT", "ALQ_15PLUS": "BEV_ABSOLUT", "EDU_15_SEK": "BEV_ABSOLUT",
             "EDU_15_TER": "BEV_ABSOLUT", "AUSPENDLER": "BEV_ABSOLUT", "HH_SIZE": "PHH"}

INDIKATOREN: list[dict[str, Any]] = [
    {"schluessel": "einwohner", "feld": "BEV_ABSOLUT", "thema": "Bevölkerung", "titel": "Einwohner", "einheit": "", "stellen": 0},
    {"schluessel": "unter15", "feld": "BEV_UNTER15", "thema": "Bevölkerung", "titel": "unter 15 Jahre", "einheit": "%", "stellen": 1},
    {"schluessel": "ueber65", "feld": "BEV_UEBER65", "thema": "Bevölkerung", "titel": "65 Jahre und älter", "einheit": "%", "stellen": 1},
    {"schluessel": "auslaender", "feld": "AUSL_STAATSB", "thema": "Bevölkerung", "titel": "ausländische Staatsangehörige", "einheit": "%", "stellen": 1},
    {"schluessel": "haushalte", "feld": "PHH", "thema": "Bevölkerung", "titel": "Privathaushalte", "einheit": "", "stellen": 0},
    {"schluessel": "haushaltsgroesse", "feld": "HH_SIZE", "thema": "Bevölkerung", "titel": "Personen je Haushalt", "einheit": "", "stellen": 2},
    {"schluessel": "erwerbstaetigenquote", "feld": "EWTQ_15BIS64", "thema": "Arbeit", "titel": "Erwerbstätigenquote (15–64)", "einheit": "%", "stellen": 1},
    {"schluessel": "arbeitslosenquote", "feld": "ALQ_15PLUS", "thema": "Arbeit", "titel": "Arbeitslosenquote (ab 15, Registerzählung)", "einheit": "%", "stellen": 1},
    {"schluessel": "auspendler", "feld": "AUSPENDLER", "thema": "Arbeit", "titel": "Auspendler (Anteil der Erwerbstätigen)", "einheit": "%", "stellen": 1},
    {"schluessel": "sekundar", "feld": "EDU_15_SEK", "thema": "Bildung", "titel": "Sekundarabschluss (ab 15)", "einheit": "%", "stellen": 1},
    {"schluessel": "tertiaer", "feld": "EDU_15_TER", "thema": "Bildung", "titel": "Hochschulabschluss (ab 15)", "einheit": "%", "stellen": 1},
    {"schluessel": "unternehmen", "feld": "UNT", "thema": "Wirtschaft", "titel": "Unternehmen", "einheit": "", "stellen": 0},
    {"schluessel": "arbeitsstaetten", "feld": "AST", "thema": "Wirtschaft", "titel": "Arbeitsstätten", "einheit": "", "stellen": 0},
    {"schluessel": "beschaeftigte", "feld": "BESCH_AST", "thema": "Wirtschaft", "titel": "Beschäftigte in Arbeitsstätten", "einheit": "", "stellen": 0},
    {"schluessel": "et_je_1000_ew", "feld": "_BESCH_JE_1000", "thema": "Wirtschaft", "titel": "Beschäftigte am Arbeitsort je 1.000 Einwohner", "einheit": "", "stellen": 0},
]

HINWEISE = [
    "Gemeindeebene (in Wien der Gemeindebezirk), nicht Adresse: Die Feinauflösung "
    "liefert das Bevölkerungsraster, hier steht der amtliche Rahmen der Gemeinde "
    "gegen Bundesland und Österreich.",
    "Stichtag ist der 31. Oktober des Jahres (Registerzählung bzw. Abgestimmte "
    "Erwerbsstatistik); das jüngste Jahr ist je Gemeinde verschieden und steht in "
    "der Spalte.",
    "Bundesland und Österreich sind aus den Gemeindezeilen gerechnet (Summen bzw. "
    "einwohnergewichtete Mittel) — die Datei führt keine Aggregate.",
    "Beschäftigte je 1.000 Einwohner über 1.000 heißt: mehr Arbeitsplätze als "
    "Einwohner — Einpendlerlage mit Tagesbevölkerung.",
]


def _zahl(s: str | None) -> float | None:
    t = str(s or "").strip().replace(" ", "").replace(",", ".")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def reduzieren(csv_text: str) -> dict[str, Any]:
    """CSV → ``{"gemeinden": {gcd: {"name", "land", "jahre": {jahr: {feld: wert}}}},
    "aggregate": {"1"…"9", "AT": {jahr: {feld: wert}}}}``."""
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("﻿")), delimiter=";")
    if not reader.fieldnames or "GCD" not in reader.fieldnames:
        raise SourceError("parse", f"Spalte GCD fehlt in {DATENSATZ}.csv")
    felder = [f for f in reader.fieldnames if f not in ("JAHR", "GCD", "GEM_NAME")]
    gemeinden: dict[str, dict[str, Any]] = {}
    summen: dict[tuple[str, str], dict[str, float]] = {}
    for r in reader:
        gcd, jahr = (r.get("GCD") or "").strip(), (r.get("JAHR") or "").strip()
        if not re.match(r"^\d{5}$", gcd) or not jahr.isdigit():
            continue
        werte = {f: _zahl(r.get(f)) for f in felder}
        g = gemeinden.setdefault(gcd, {"name": (r.get("GEM_NAME") or "").strip(), "land": gcd[0], "jahre": {}})
        g["jahre"][jahr] = werte
        for gebiet in (gcd[0], "AT"):
            s = summen.setdefault((gebiet, jahr), {})
            for f, w in werte.items():
                if w is None:
                    continue
                if f in ABSOLUT:
                    s[f] = s.get(f, 0.0) + w
                elif f in GEWICHTET:
                    gew = werte.get(GEWICHTET[f]) or 0.0
                    s[f + "|zaehler"] = s.get(f + "|zaehler", 0.0) + w * gew
                    s[f + "|nenner"] = s.get(f + "|nenner", 0.0) + gew
    aggregate: dict[str, dict[str, dict[str, float]]] = {}
    for (gebiet, jahr), s in summen.items():
        out: dict[str, float] = {f: s[f] for f in ABSOLUT if f in s}
        for f in GEWICHTET:
            if s.get(f + "|nenner"):
                out[f] = s[f + "|zaehler"] / s[f + "|nenner"]
        aggregate.setdefault(gebiet, {})[jahr] = out
    return {"gemeinden": gemeinden, "aggregate": aggregate}


def _abgeleitet(werte: dict[str, Any]) -> dict[str, Any]:
    w = dict(werte)
    bev, besch = w.get("BEV_ABSOLUT"), w.get("BESCH_AST")
    w["_BESCH_JE_1000"] = round(besch / bev * 1000) if bev and besch is not None else None
    return w


def finde_gemeinde(daten: dict[str, Any], schluessel: str, gemeinde: str | None,
                   ortsteil: str | None = None) -> str | None:
    """GCD der Gemeinde im Bundesland ``schluessel`` — über den Namen aus dem
    Geocoder; in Wien über den Gemeindebezirk (``Wien-Innere Stadt``)."""
    kandidaten = {gcd: g for gcd, g in daten["gemeinden"].items() if g["land"] == str(schluessel)}
    if str(schluessel) == "9":
        ziel = _norm(ortsteil)
        if ziel:
            for gcd, g in kandidaten.items():
                if _norm(g["name"].split("-", 1)[-1]) == ziel:
                    return gcd
        return None
    ziel = _norm(gemeinde)
    if not ziel:
        return None
    treffer = [gcd for gcd, g in kandidaten.items() if _norm(g["name"]) == ziel]
    if not treffer:
        treffer = [gcd for gcd, g in kandidaten.items()
                   if _norm(g["name"]).startswith(ziel + " ") or _norm(g["name"]) == ziel + " stadt"]
    return treffer[0] if len(treffer) == 1 else None


def auswerten(daten: dict[str, Any], schluessel: str, gcd: str | None, land_name: str) -> dict[str, Any] | None:
    agg_land = daten["aggregate"].get(str(schluessel)) or {}
    agg_at = daten["aggregate"].get("AT") or {}
    g = daten["gemeinden"].get(gcd) if gcd else None
    jahre = sorted((g["jahre"] if g else agg_land).keys())
    if not jahre:
        return None
    jahr = jahre[-1]
    quelle = g["jahre"] if g else agg_land
    indikatoren = []
    for ind in INDIKATOREN:
        f = ind["feld"]
        aktuell = _abgeleitet(quelle.get(jahr) or {})
        if aktuell.get(f) is None:
            continue
        indikatoren.append({
            "schluessel": ind["schluessel"], "titel": ind["titel"], "thema": ind["thema"],
            "einheit": ind["einheit"], "stellen": ind["stellen"], "jahr": int(jahr),
            "kreis": round(aktuell[f], ind["stellen"]),
            "land": (round(_abgeleitet(agg_land.get(jahr) or {}).get(f), ind["stellen"])
                     if _abgeleitet(agg_land.get(jahr) or {}).get(f) is not None else None),
            "bund": (round(_abgeleitet(agg_at.get(jahr) or {}).get(f), ind["stellen"])
                     if _abgeleitet(agg_at.get(jahr) or {}).get(f) is not None else None),
            "reihe": [{"jahr": int(j), "wert": round(_abgeleitet(quelle[j])[f], ind["stellen"])}
                      for j in jahre if _abgeleitet(quelle[j]).get(f) is not None],
        })
    return {
        "gebiete": {"kreis": {"name": g["name"] if g else f"{land_name} (Landeswert)", "gkz": gcd,
                              "ebene": "Gemeindebezirk" if (g and str(schluessel) == "9") else "Gemeinde"},
                    "land": {"name": land_name}, "bund": {"name": "Österreich"}},
        "indikatoren": indikatoren,
        "jahr": int(jahr),
        "hinweise": HINWEISE,
        "rohdaten": ROHDATEN,
    }


async def load(adresse: dict[str, Any] | None,
               daten_laden: Callable[[], Awaitable[dict[str, Any]]]) -> SourceResult:
    from ..laender import land_aus_iso

    started = time.perf_counter()
    a = adresse or {}
    treffer = land_aus_iso(a.get("bundesland_iso"))
    if not treffer:
        return SourceResult(name="kreisprofil", ok=True, data=None,
                            warnings=["Ohne Bundesland (aus der Adresse) lässt sich keine Gemeinde zuordnen."])
    _, schluessel, land_name = treffer
    try:
        daten = await daten_laden()
    except SourceError as err:
        return SourceResult.failed("kreisprofil", err, int((time.perf_counter() - started) * 1000))
    gcd = finde_gemeinde(daten, schluessel, a.get("gemeinde"), a.get("ortsteil"))
    data = auswerten(daten, schluessel, gcd, land_name)
    warnungen: list[str] = []
    if gcd is None:
        wer = a.get("ortsteil") if schluessel == "9" else a.get("gemeinde")
        warnungen.append(f"„{wer or 'Der Ort'}“ ließ sich nicht eindeutig in der Gemeindetabelle "
                         f"finden — angezeigt ist der Landeswert {land_name}.")
    if data and data["jahr"] < 2021:
        warnungen.append(f"Jüngstes Jahr für diese Gemeinde in der Tabelle: {data['jahr']}.")
    return SourceResult(
        name="kreisprofil", ok=True, data=data,
        duration_ms=int((time.perf_counter() - started) * 1000), warnings=warnungen,
        provenance=Provenance(
            source="Statistik Austria — Gemeindetabelle Abgestimmte Erwerbsstatistik / Arbeitsstättenzählung",
            license=LIZENZ, endpoint=CSV_URL, stand=f"Stichtag 31.10.{data['jahr']}" if data else None,
            retrieved_at=now_iso(),
            note="Gemeindezeile (Wien: Gemeindebezirk) gegen einwohnergewichtete Landes- und Bundeswerte."),
    )


__all__ = ["AT", "CSV_URL", "reduzieren", "finde_gemeinde", "auswerten", "load"]
