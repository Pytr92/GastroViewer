"""Immobilien-Durchschnittspreise je Bezirk (Statistik Austria).

Österreich kennt keine Bodenrichtwerte; das offene Gegenstück sind die
jährlichen **Durchschnittspreise aus Kaufverträgen** (Grundbuch-
Transaktionen, geometrische Mittel, Datenbasis fünf Jahre, auf das
Preisniveau des Berichtsjahres angepasst), die Statistik Austria als
drei ODS-Dateien veröffentlicht — live belegt am 18.09.2026
(fixtures/at, Runden 5 und 6, ``Haeuserpreise2024.ods`` u. a.):

* **Häuser**: je Bundesland ein Blatt; drei Blöcke „Durchschnittspreise
  für Häuser der Kategorie A/B/C“ (Grundstücksgröße klein/mittel/groß,
  Grenzen je Bezirk im Blatt „Grundstücksgrößen“), je Block eine Zeile
  pro Bezirk mit **9 Werten** (Bauperiode bis 1960 / 1961–1990 / ab 1991
  × drei Wohnflächenklassen), Euro je m² Wohnfläche.
* **Eigentumswohnungen**: gleiche Form, zwei Blöcke (ohne / mit
  Außenflächen), Wien je Gemeindebezirk.
* **Baugrundstücke**: je Bundesland Zeilen ``B.Nr. | Bezirk | G.Nr. |
  Gemeinde | Euro/m²`` — Bezirksdurchschnitt und jede Gemeinde mit der
  fünfstelligen Gemeindekennziffer.

Der Bezirk am Punkt kommt aus der **Gemeindekennziffer** (die ersten
drei Stellen sind die politische Bezirksnummer; Wien 901–923 je
Gemeindebezirk), die ``gemeinde_at.gkz_am_punkt`` liefert.
"""

from __future__ import annotations

import io
import re
import time
import xml.etree.ElementTree as ET
import zipfile
from typing import Any, Awaitable, Callable

from .base import Provenance, SourceError, SourceResult, now_iso

BASIS_URL = "https://www.statistik.at/fileadmin/pages/222/"
DATEIEN = {"haeuser": "Haeuserpreise{jahr}.ods", "wohnungen": "Wohnungspreise{jahr}.ods",
           "baugrund": "Baugrundstueckspreise{jahr}.ods"}
JAHRE = (2025, 2024)   # jüngstes zuerst; 2024 live belegt
PORTAL = "https://www.statistik.at/statistiken/volkswirtschaft-und-oeffentliche-finanzen/preise-und-preisindizes/immobilien-durchschnittspreise"
LIZENZ = "Creative Commons Namensnennung 4.0 (CC BY 4.0) · Statistik Austria"
LAENDER = {"1": "Burgenland", "2": "Kärnten", "3": "Niederösterreich", "4": "Oberösterreich", "5": "Salzburg",
           "6": "Steiermark", "7": "Tirol", "8": "Vorarlberg", "9": "Wien"}
_NS_TABLE = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
_NS_TEXT = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
_NS_OFFICE = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
PERIODEN = ("Bis 1960", "1961-1990", "Ab 1991")


def ods_tabellen(daten: bytes) -> dict[str, list[list[str]]]:
    """Alle Blätter einer ODS-Datei als Zeilenlisten (Zellwert: Zahl als
    ``office:value``, sonst Text). Wiederholte Zellen werden aufgelöst."""
    try:
        root = ET.fromstring(zipfile.ZipFile(io.BytesIO(daten)).read("content.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as err:
        raise SourceError("parse_error", f"ODS-Datei nicht lesbar: {err}") from err
    out: dict[str, list[list[str]]] = {}
    for t in root.iter(f"{{{_NS_TABLE}}}table"):
        rows: list[list[str]] = []
        for r in t.iter(f"{{{_NS_TABLE}}}table-row"):
            cells: list[str] = []
            for c in r:
                if c.tag not in (f"{{{_NS_TABLE}}}table-cell", f"{{{_NS_TABLE}}}covered-table-cell"):
                    continue
                rep = int(c.get(f"{{{_NS_TABLE}}}number-columns-repeated", "1"))
                val = c.get(f"{{{_NS_OFFICE}}}value")
                txt = " ".join("".join(p.itertext()) for p in c.iter(f"{{{_NS_TEXT}}}p")).strip()
                cells.extend([val if val is not None else txt] * min(rep, 40))
            while cells and cells[-1] == "":
                cells.pop()
            rows.append(cells)
        out[t.get(f"{{{_NS_TABLE}}}name") or f"Blatt{len(out) + 1}"] = rows
    return out


def _zahl(v: Any) -> float | None:
    try:
        return round(float(str(v).replace(",", ".")), 1)
    except (TypeError, ValueError):
        return None


def _name_norm(s: str) -> str:
    s = re.sub(r"\s*\d\)\s*", " ", s or "")          # Fußnoten „2)“, „3) 4)“
    s = re.sub(r"\s+", " ", s).strip().lower()
    s = s.replace("sankt ", "st. ").replace("(stadt)", "").strip()
    s = re.sub(r"^stadt ", "", s)
    return s


def _finde_bnr(namen: dict[str, str], name: str) -> str | None:
    """Bezirksname der Preisblätter → B.Nr. aus der Baugrund-Datei desselben
    Landes; die Schreibweisen weichen ab („Braunau“ / „Braunau am Inn“,
    „Stadt Linz“ / „Linz(Stadt)“, „Kirchdorf“ / „Kirchdorf an der Krems“)."""
    ziel = _name_norm(name)
    if ziel in namen:
        return namen[ziel]
    kandidaten = [bnr for n, bnr in namen.items()
                  if ziel.startswith(n + " ") or n.startswith(ziel + " ") or n.split(" ")[0] == ziel.split(" ")[0]]
    return kandidaten[0] if len(set(kandidaten)) == 1 else None


def _wien_bnr(name: str) -> str | None:
    m = re.match(r"\s*wien\s+(\d{1,2})\.", name or "", re.I)
    return f"9{int(m[1]):02d}" if m else None


def _preisbloecke(rows: list[list[str]], titel_muster: str) -> list[dict[str, Any]]:
    """Blöcke „<Titel>“ → Kopf (Perioden × Klassen) + Bezirkszeilen mit 9 Werten."""
    bloecke: list[dict[str, Any]] = []
    i = 0
    while i < len(rows):
        r = rows[i]
        if r and re.search(titel_muster, r[0] or "", re.I):
            titel = r[0]
            # Kopf: Zeile „Bezirke | Bis 1960 | | | 1961-1990 …“ und darunter die Klassen.
            j = i + 1
            klassen: list[str] = []
            while j < len(rows) and j < i + 5:
                if rows[j] and rows[j][0] == "" and len(rows[j]) >= 10 and "m²" in " ".join(rows[j]):
                    klassen = [k for k in rows[j][1:10]]
                    j += 1
                    break
                j += 1
            zeilen: dict[str, list[float | None]] = {}
            while j < len(rows):
                z = rows[j]
                if not z or not z[0] or re.match(r"^(Durchschnittspreise|Q:)", z[0]):
                    break
                werte = [_zahl(v) for v in z[1:10]]
                if any(w is not None for w in werte):
                    zeilen[z[0]] = werte + [None] * (9 - len(werte))
                j += 1
            bloecke.append({"titel": titel, "klassen": klassen[:9], "zeilen": zeilen})
            i = j
        else:
            i += 1
    return bloecke


def reduzieren(haeuser: bytes | None, wohnungen: bytes | None, baugrund: bytes | None) -> dict[str, Any]:
    """Alle drei Dateien zu ``{"bezirke": {bnr: {...}}, "gemeinden": {gkz: {...}},
    "stand": ..., "groessen": {bnr: {"A": ..}}}`` eindampfen."""
    bezirke: dict[str, dict[str, Any]] = {}
    gemeinden: dict[str, dict[str, Any]] = {}
    stand = None
    namen: dict[str, dict[str, str]] = {}   # Land → normierter Bezirksname → bnr (Baugrund-Datei)

    def bezirk(bnr: str, name: str, land: str) -> dict[str, Any]:
        return bezirke.setdefault(bnr, {"nummer": bnr, "name": re.sub(r"(\s*\d\))+\s*$", "", name).strip(),
                                        "land": land, "haeuser": [], "wohnungen": [], "baugrund": None,
                                        "groessen": None})

    if baugrund:
        for blatt, rows in ods_tabellen(baugrund).items():
            land = next((k for k, v in LAENDER.items() if v == blatt), None)
            if land is None:
                continue
            aktuell = None
            for r in rows:
                if len(r) >= 5 and r[0] and r[0].isdigit() and len(r[0]) == 3:
                    aktuell = bezirk(r[0], r[1], land)
                    aktuell["baugrund"] = _zahl(r[4])
                    namen.setdefault(land, {})[_name_norm(r[1])] = r[0]
                elif len(r) >= 5 and r[2] and r[2].isdigit() and len(r[2]) == 5 and aktuell is not None:
                    gemeinden[r[2]] = {"gkz": r[2], "name": r[3], "bezirk": aktuell["nummer"], "baugrund": _zahl(r[4])}
                elif r and str(r[0]).startswith("Q:") and stand is None:
                    m = re.search(r"Erstellt am (\d{2}\.\d{2}\.\d{4})", r[0])
                    stand = m[1] if m else None

    def einsortieren(daten: bytes | None, feld: str, muster: str) -> None:
        if not daten:
            return
        for blatt, rows in ods_tabellen(daten).items():
            land = next((k for k, v in LAENDER.items() if v == blatt), None)
            if land is None:
                if blatt.startswith("Grundstücksgrößen"):
                    _groessen(rows)
                continue
            for b in _preisbloecke(rows, muster):
                for name, werte in b["zeilen"].items():
                    bnr = _wien_bnr(name) if land == "9" else _finde_bnr(namen.get(land, {}), name)
                    if bnr is None:
                        # Bezirk ohne Baugrund-Zeile: eigenen Schlüssel aus Land + Name
                        bnr = f"{land}xx:{_name_norm(name)}"
                    bz = bezirk(bnr, name, land)
                    bz[feld].append({"titel": b["titel"], "klassen": b["klassen"], "werte": werte})

    def _groessen(rows: list[list[str]]) -> None:
        land = None
        for r in rows:
            if len(r) == 1 and r[0] in LAENDER.values():
                land = next(k for k, v in LAENDER.items() if v == r[0])
            elif land and len(r) >= 4 and r[0] not in ("Bezirke", "") and "m²" in r[1]:
                bnr = _wien_bnr(r[0]) if land == "9" else _finde_bnr(namen.get(land, {}), r[0])
                if bnr:
                    bezirk(bnr, r[0], land)["groessen"] = {"A": r[1], "B": r[2], "C": r[3]}

    einsortieren(haeuser, "haeuser", r"^Durchschnittspreise für Häuser")
    einsortieren(wohnungen, "wohnungen", r"^Durchschnittspreise Eigentumswohnungen")
    return {"bezirke": bezirke, "gemeinden": gemeinden, "stand": stand}


def _tabelle(block: dict[str, Any]) -> dict[str, Any]:
    """9 Werte → drei Perioden × drei Wohnflächenklassen."""
    kl = block["klassen"] or [""] * 9
    perioden = []
    for p, periode in enumerate(PERIODEN):
        perioden.append({"periode": periode,
                         "klassen": [{"klasse": kl[p * 3 + k] if p * 3 + k < len(kl) else "",
                                      "eur_m2": block["werte"][p * 3 + k]} for k in range(3)]})
    m = re.search(r"Kategorie ([ABC])", block["titel"])
    return {"titel": re.sub(r"[¹²³⁾]+", "", block["titel"]).strip(), "kategorie": m[1] if m else None,
            "perioden": perioden}


HINWEISE = [
    "**Durchschnittspreise aus Kaufverträgen** (Grundbuch), geometrische Mittel über fünf Jahre, "
    "auf das Preisniveau des Berichtsjahres angepasst — Euro je m² Wohnfläche bzw. je m² Baugrund. "
    "Für Gastronomie ein Maß für die **Lagequalität und Kaufkraft im Bezirk**, nicht für Gewerbemieten.",
    "Häuser nach Grundstücksgröße (Kategorie A klein, B mittel, C groß; Grenzen je Bezirk), Bauperiode "
    "und Wohnfläche; Wohnungen ohne/mit Außenflächen. Bezirke mit wenigen Transaktionen tragen "
    "Gruppenwerte — dann stehen in allen Spalten dieselben Zahlen.",
]


def auswerten(daten: dict[str, Any], gkz: str, jahr: int | None) -> dict[str, Any] | None:
    bnr = gkz[:3]
    bz = daten["bezirke"].get(bnr)
    gem = daten["gemeinden"].get(gkz)
    if bz is None and gem is None:
        return None
    if bz is None and gem is not None:
        bz = daten["bezirke"].get(gem["bezirk"])
    if bz is None:
        return None
    return {
        "jahr": jahr, "stand": daten.get("stand"),
        "land": LAENDER.get(bz["land"]), "bezirk": {"nummer": bz["nummer"], "name": bz["name"]},
        "gemeinde": ({"gkz": gem["gkz"], "name": gem["name"], "baugrund_eur_m2": gem["baugrund"]} if gem else None),
        "baugrund_bezirk_eur_m2": bz["baugrund"],
        "grundstuecksgroessen": bz["groessen"],
        "haeuser": [_tabelle(b) for b in bz["haeuser"]],
        "wohnungen": [_tabelle(b) for b in bz["wohnungen"]],
        "hinweise": HINWEISE, "portal": PORTAL,
    }


async def load(gkz: str | None, daten_laden: Callable[[], Awaitable[tuple[dict[str, Any], int | None]]]) -> SourceResult:
    started = time.perf_counter()
    if not gkz:
        return SourceResult(name="immobilien", ok=True, data=None,
                            warnings=["Ohne Gemeindekennziffer (Gemeindegrenzen-WFS nicht erreichbar) lässt sich "
                                      "kein Bezirk zuordnen."])
    try:
        daten, jahr = await daten_laden()
    except SourceError as err:
        return SourceResult.failed("immobilien", err, int((time.perf_counter() - started) * 1000))
    data = auswerten(daten, gkz, jahr)
    warnungen: list[str] = []
    if data is None:
        warnungen.append(f"Der Bezirk {gkz[:3]} steht in keiner der drei Preistabellen.")
    else:
        if not data["haeuser"]:
            warnungen.append("Für diesen Bezirk führt Statistik Austria keine Häuserpreise (zu wenige Verkäufe).")
        if not data["wohnungen"]:
            warnungen.append("Für diesen Bezirk führt Statistik Austria keine Wohnungspreise (zu wenige Verkäufe).")
    return SourceResult(
        name="immobilien", ok=True, data=data,
        duration_ms=int((time.perf_counter() - started) * 1000), warnings=warnungen,
        provenance=Provenance(
            source=f"Statistik Austria — Immobilien-Durchschnittspreise {jahr or ''} (Häuser, Eigentumswohnungen, Baugrundstücke)",
            license=LIZENZ, endpoint=BASIS_URL + DATEIEN["haeuser"].format(jahr=jahr or ""),
            stand=(f"Berichtsjahr {jahr}, erstellt {daten.get('stand')}" if daten.get("stand") else f"Berichtsjahr {jahr}"),
            retrieved_at=now_iso(),
            note="Drei ODS-Dateien einmal geladen und je Bezirk eingedampft; Zuordnung über die "
                 "Gemeindekennziffer (Bezirk = erste drei Stellen)."),
    )


__all__ = ["BASIS_URL", "DATEIEN", "JAHRE", "ods_tabellen", "reduzieren", "auswerten", "load"]
