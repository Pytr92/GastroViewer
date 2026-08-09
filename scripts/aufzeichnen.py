#!/usr/bin/env python3
"""Zeichnet die Antworten der eigenen ``/api``-Schnittstelle auf.

Die Browserprüfung ``scripts/uitest.py`` brauchte bisher einen laufenden
Server **mit Netzzugriff** — und lief deshalb nur von Hand. Damit war die
Oberfläche (6 400 Zeilen ``app.js``) das einzige größere Stück des Projekts
ohne automatische Absicherung. Genau dort saßen zuletzt drei echte Fehler:
sichtbare Sternchen aus der Markdown-Betonung, ``null`` als Text, und Blöcke,
die bei einem Fehler ewig im Ladezustand hingen.

Dieses Skript schließt die Lücke von der Datenseite her: Es ruft einmal alle
Pfade ab, die ``app.js`` benutzt, und legt die **echten** Antworten als
Fixture ab. ``scripts/attrappe.py`` spielt sie später ohne Netz wieder ab.

Aufruf::

    gastroviewer serve --port 8031 &
    python scripts/aufzeichnen.py http://127.0.0.1:8031

Bewusst gilt auch hier §10: Aufgezeichnet wird, was der Server wirklich
liefert — auch Fehlerzustände. Ein Block, der ohne Kennung eine Fehlermeldung
zeigt, ist ein gültiger und prüfenswerter Zustand; erfunden wird nichts.

Exitcodes: 0 = aufgezeichnet · 1 = zu viele Fehlschläge · 2 = Server nicht
erreichbar.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ZIEL = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "ui"

# Standorte der Browserprüfung. Sie müssen mit den Konstanten in
# scripts/uitest.py übereinstimmen — sonst fehlt der Attrappe genau die
# Antwort, die eine Prüfung braucht.
PUNKTE = {
    "marienplatz": (48.1372, 11.5755),   # dichte Innenstadt
    "isarufer": (48.1297, 11.5822),      # Fluss als Barriere
    "isarauen": (48.1050, 11.5530),      # Hochwassergebiet HQ 100
    "freiham": (48.1450, 11.4200),       # Bebauungsplan
    "giesing": (48.1114, 11.5859),       # Wohnlage
    "haidhausen": (48.1289, 11.5967),    # Erhaltungssatzung § 172 BauGB
    "koeln": (50.9413, 6.9583),          # anderes Bundesland (NRW)
}
STANDARD_RADIUS = 600

# Pfade mit lat/lon/r — die Masse der Blöcke.
PUNKT_PFADE_MIT_RADIUS = [
    "/api/point/zensus", "/api/point/osm", "/api/point/overture",
    "/api/point/gtfs", "/api/point/radzaehlung", "/api/point/verkehrsmenge",
    "/api/point/planung", "/api/point/leerstandsmelder",
    "/api/point/dynamik", "/api/point/baustellen", "/api/point/maerkte",
    "/api/point/airbnb", "/api/point/ihk-berlin",
    "/api/schaetzung/vorgaben",
]

# Teure Antworten (1–3 MB je Standort) nur dort, wo eine Browserprüfung sie
# wirklich anfasst. Sechsmal das Fußwegenetz aufzunehmen würde die Fixture
# vervielfachen, ohne eine einzige Prüfung zusätzlich abzudecken.
NUR_FUER = {
    "/api/point/gehweg": ["isarufer"],          # Prüfungen 33 und 34
    "/api/point/liefergebiet": ["marienplatz"],
    "/api/point/oepnv-einzug": ["marienplatz"],
    "/api/point/marke": ["marienplatz"],         # Prüfung 18
}

# Pfade nur mit lat/lon.
PUNKT_PFADE_OHNE_RADIUS = [
    "/api/point/adresse", "/api/point/klima", "/api/point/luft",
    "/api/point/sonne", "/api/point/frequenz", "/api/point/baurecht",
    "/api/point/indikatoren", "/api/point/messe", "/api/point/tourismus",
]

# Pfade, die einen Gemeindeschlüssel brauchen; er stammt aus der zuvor
# aufgezeichneten Zensus-Antwort desselben Punktes.
AGS_PFADE = ["/api/einkommen", "/api/kreisprofil", "/api/pendler",
             "/api/genesis", "/api/pks", "/api/wahl", "/api/kalender"]

# Feste Abrufe ohne Standortbezug.
FESTE_ABRUFE: list[tuple[str, dict[str, Any]]] = [
    ("/api/health", {}),
    ("/api/stats", {}),
    ("/api/genesis/zugang", {}),
]
# Bewusst NICHT aufgezeichnet: alles unter /api/points. Diese Routen haben
# Zustand (merken, benoten, löschen, vergleichen) und laufen in der Attrappe
# gegen die echte Anwendung und eine frische Datenbank. Eine eingefrorene
# Antwort würde genau die Prüfungen entwerten, die Zustand testen.

# Adresssuche und Vorschläge — die Oberfläche schickt genau diese Texte in
# der Browserprüfung.
SUCHBEGRIFFE = ["Marienplatz München", "Domplatz", "Freiham"]


def schluessel(pfad: str, params: dict[str, Any] | None = None) -> str:
    """Normalisierter Fixture-Schlüssel: Pfad plus sortierte Parameter.

    ``refresh`` fliegt heraus — es ändert nur, ob der Server den Cache
    umgeht, nicht die Gestalt der Antwort.
    """
    rein = {k: str(v) for k, v in (params or {}).items()
            if v not in (None, "") and k != "refresh"}
    if not rein:
        return pfad
    return pfad + "?" + urllib.parse.urlencode(sorted(rein.items()))


def hole(basis: str, pfad: str, params: dict[str, Any] | None = None,
         zeit: float = 180.0) -> dict[str, Any]:
    """Ein Abruf. Fehler werden mitaufgezeichnet, nicht verschluckt."""
    url = basis.rstrip("/") + pfad
    if params:
        url += "?" + urllib.parse.urlencode(
            {k: v for k, v in params.items() if v not in (None, "")})
    anfrage = urllib.request.Request(url, headers={"Accept": "application/json"})
    # Der Server läuft lokal; ein Proxy aus der Umgebung würde stören.
    oeffner = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with oeffner.open(anfrage, timeout=zeit) as antwort:
            roh = antwort.read().decode("utf-8")
            return {"status": antwort.status, "json": json.loads(roh)}
    except urllib.error.HTTPError as err:
        roh = err.read().decode("utf-8", "replace")
        try:
            koerper = json.loads(roh)
        except ValueError:
            koerper = {"detail": roh[:500]}
        return {"status": err.code, "json": koerper}


def ags_aus(zensus: dict[str, Any]) -> tuple[str | None, str | None]:
    daten = (zensus or {}).get("json") or {}
    for ebene in (daten, daten.get("data") or {}, daten.get("gemeinde") or {}):
        if isinstance(ebene, dict) and ebene.get("ags"):
            return str(ebene["ags"]), ebene.get("bundesland_code")
    return None, None


def aufzeichnen(basis: str, vorhanden: dict[str, Any] | None = None,
                ) -> dict[str, Any]:
    # Eine vorhandene Aufnahme wird ergänzt, nicht verworfen: Ein zweiter
    # Lauf holt nur, was noch fehlt.
    aufnahme: dict[str, Any] = dict(vorhanden or {})
    fehler: list[str] = []
    # Alles, was dieser Lauf anfasst. Am Ende wird die Datei darauf
    # eingedampft — so bleibt die Aufzeichnung immer genau das, was das
    # Skript beschreibt, und sammelt keine Altlasten an.
    gewollt: set[str] = set()

    def merke(pfad: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        k = schluessel(pfad, params)
        gewollt.add(k)
        if k in aufnahme:
            sys.stdout.write("=")
            sys.stdout.flush()
            return aufnahme[k]
        antwort = hole(basis, pfad, params)
        aufnahme[k] = antwort
        zeichen = "." if antwort["status"] == 200 else "!"
        if antwort["status"] != 200:
            fehler.append(f"{antwort['status']} {k}")
        sys.stdout.write(zeichen)
        sys.stdout.flush()
        return antwort

    for pfad, params in FESTE_ABRUFE:
        merke(pfad, params)
    for q in SUCHBEGRIFFE:
        merke("/api/geocode", {"q": q})
        merke("/api/geocode/vorschlaege", {"q": q})

    for name, (lat, lon) in PUNKTE.items():
        print(f"\n{name} ({lat}, {lon})", end=" ", flush=True)
        zensus = merke("/api/point/zensus",
                       {"lat": lat, "lon": lon, "r": STANDARD_RADIUS})
        # Der Sammelendpunkt wird von der Oberfläche nicht aufgerufen, wohl
        # aber intern beim Merken eines Punktes — ohne ihn bliebe die halbe
        # Vergleichs- und Berichtsprüfung stumm.
        merke("/api/point", {"lat": lat, "lon": lon, "r": STANDARD_RADIUS})
        for pfad in PUNKT_PFADE_MIT_RADIUS:
            if pfad == "/api/point/zensus":
                continue
            merke(pfad, {"lat": lat, "lon": lon, "r": STANDARD_RADIUS})
        for pfad in PUNKT_PFADE_OHNE_RADIUS:
            merke(pfad, {"lat": lat, "lon": lon})

        ags, land = ags_aus(zensus)
        for pfad in AGS_PFADE:
            merke(pfad, {"ags": ags})
        merke("/api/point/laerm", {"lat": lat, "lon": lon,
                                   "bundesland_code": land})
        merke("/api/wms", {"bundesland_code": land})
        merke("/api/wms/ebenen", {"bundesland_code": land})
        merke("/api/wms/bodenrichtwert", {"lat": lat, "lon": lon,
                                          "bundesland_code": land})
        merke("/api/point/links", {"lat": lat, "lon": lon,
                                   "r": STANDARD_RADIUS, "ags": ags,
                                   "bundesland_code": land})
        if name in NUR_FUER["/api/point/gehweg"]:
            merke("/api/point/gehweg",
                  {"lat": lat, "lon": lon, "r": STANDARD_RADIUS})
        if name in NUR_FUER["/api/point/marke"]:
            merke("/api/point/marke", {"lat": lat, "lon": lon,
                                       "marke": "Vapiano", "r": 5000})
        if name in NUR_FUER["/api/point/liefergebiet"]:
            merke("/api/point/liefergebiet", {"lat": lat, "lon": lon,
                                              "minuten": 10})
        if name in NUR_FUER["/api/point/oepnv-einzug"]:
            merke("/api/point/oepnv-einzug", {"lat": lat, "lon": lon,
                                              "minuten": 30})
        merke("/api/register", {"plz": ""})

    # Kartenebenen. Die Ausschnitte müssen zu dem passen, was der Browser
    # bei 1440×1000 tatsächlich anfordert — die Prüfung verlangt über 800
    # 10-km-Zellen (Bayern, Zoom 8) und über 300 1-km-Zellen (München,
    # Zoom 12). Eine zu kleine Aufnahme ließe die Prüfung fehlschlagen,
    # obwohl die Oberfläche in Ordnung ist.
    print("\nKarte", end=" ", flush=True)
    merke("/api/gitter", {"ebene": "10km", "west": 8.6, "sued": 47.2,
                          "ost": 14.2, "nord": 50.7})
    merke("/api/gitter", {"ebene": "1km", "west": 11.34, "sued": 48.06,
                          "ost": 11.76, "nord": 48.23})
    # Der Flächen-Scan klemmt seinen Ausschnitt selbst auf SCAN_SPANNE
    # (0,055° × 0,04°) um die Kartenmitte — größer beantwortet der Server
    # ihn gar nicht. Das ist exakt die Box, die die Oberfläche an der
    # Prüfkoordinate 48.137/11.575 bildet.
    merke("/api/scan", {"west": 11.5475, "sued": 48.117,
                        "ost": 11.6025, "nord": 48.157})

    print()
    ueberzaehlig = sorted(set(aufnahme) - gewollt)
    if ueberzaehlig:
        print(f"{len(ueberzaehlig)} nicht mehr benötigte Einträge entfernt.")
    return {"aufnahme": {k: aufnahme[k] for k in sorted(gewollt)
                         if k in aufnahme},
            "fehler": fehler}


def main(argv: list[str]) -> int:
    basis = argv[1] if len(argv) > 1 else "http://127.0.0.1:8031"
    try:
        gesund = hole(basis, "/api/health", zeit=10.0)
    except OSError as err:
        print(f"Server unter {basis} nicht erreichbar: {err}")
        return 2
    if gesund["status"] != 200:
        print(f"Server unter {basis} antwortet mit {gesund['status']}.")
        return 2

    ZIEL.mkdir(parents=True, exist_ok=True)
    datei = ZIEL / "api-antworten.json"
    vorhanden = (json.loads(datei.read_text(encoding="utf-8"))
                 if datei.exists() else {})

    ergebnis = aufzeichnen(basis, vorhanden)
    aufnahme, fehler = ergebnis["aufnahme"], ergebnis["fehler"]

    # Kompakt: Die Datei ist eine Maschinenaufnahme, keine Lektüre —
    # Einrückung kostete hier gut ein Drittel der Größe.
    datei.write_text(
        json.dumps(aufnahme, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")),
        encoding="utf-8")

    mb = datei.stat().st_size / 1_000_000
    print(f"{len(aufnahme)} Antworten in {datei} ({mb:.1f} MB)")
    if fehler:
        print(f"\n{len(fehler)} Abrufe ohne HTTP 200 — mitaufgezeichnet, "
              "denn auch der Fehlerzustand gehört zur Oberfläche:")
        for f in sorted(set(fehler)):
            print(f"  {f}")
    # Wenn fast nichts geklappt hat, ist die Aufnahme wertlos.
    if len(fehler) > len(aufnahme) / 2:
        print("\nMehr als die Hälfte der Abrufe schlug fehl — "
              "die Aufnahme taugt so nicht als Grundlage.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
