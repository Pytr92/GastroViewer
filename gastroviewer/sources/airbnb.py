"""Kurzzeitvermietung im Umkreis (Inside Airbnb) — Touristen-Nachfrage-Signal.

Übernachtungszahlen gibt es amtlich nur je Kreis (Kreisprofil). Wo die
Gäste tatsächlich schlafen, zeigt kleinräumig der offene Datensatz von
Inside Airbnb: alle Airbnb-Inserate einer Stadt mit Koordinaten, Zimmertyp,
Preis und Bewertungszahl. Viele Inserate ums Eck heißen Frühstücks- und
Abendpublikum, das in keiner Einwohnerzahl auftaucht.

Verifiziert am 2026-08-07:

* ``https://insideairbnb.com/get-the-data/`` führt für Deutschland genau
  zwei Städte: München (Datenstand 2026-06-29, 6 890 Inserate) und
  Berlin (2026-06-26). Lizenz laut Seite: CC BY 4.0.
* ``…/visualisations/listings.csv`` je Stadt: Koordinaten, ``room_type``,
  ``price`` (nackte Zahl in Landeswährung, nur bei ~65 % der Inserate
  gefüllt), ``number_of_reviews_ltm``, ``availability_365``.
* Marienplatz, 600 m: 127 Inserate (86 ganze Unterkünfte, 41 Privatzimmer).

Grenzen, offen benannt:

* Airbnb versetzt Inserats-Positionen plattformseitig um bis zu ~150 m.
  Zählwerte im Radius sind deshalb Näherungen, keine Punktgenauigkeit.
* Momentaufnahme des Sammellaufs — Inside Airbnb aktualisiert etwa
  quartalsweise; der Stichtag steht im Block.
* Bewertungen der letzten zwölf Monate sind ein Aktivitätsindiz, keine
  Buchungszahl: nicht jede Buchung hinterlässt eine Bewertung.
"""

from __future__ import annotations

import csv
import io
import re
import time
from statistics import median
from typing import Any, Awaitable, Callable

from ..config import Settings
from .base import Provenance, SourceError, SourceResult, bearing_label, haversine_m, now_iso

INDEX_URL = "https://insideairbnb.com/get-the-data/"

LIZENZ = "Creative Commons Attribution 4.0 (CC BY 4.0) · Inside Airbnb (insideairbnb.com)"

# Gemeinde (Nominatim) → Stadt-Kürzel auf insideairbnb.com. Nur Städte, die
# die Datenseite am 2026-08-07 tatsächlich führt — für alle anderen bleibt
# der Block mit Begründung leer, statt „keine Airbnbs" zu behaupten.
STAEDTE = {
    "münchen": ("munich", "München"),
    "berlin": ("berlin", "Berlin"),
}

# room_type der CSV → deutsche Beschriftung. Reihenfolge = Anzeige-Reihenfolge.
ZIMMERTYPEN = [
    ("Entire home/apt", "Ganze Unterkunft"),
    ("Private room", "Privatzimmer"),
    ("Shared room", "Geteiltes Zimmer"),
    ("Hotel room", "Hotelzimmer"),
]
_TYP_INDEX = {roh: i for i, (roh, _) in enumerate(ZIMMERTYPEN)}

MAX_LISTE = 15
MAX_MARKER = 500

# Positionen sind plattformseitig um bis zu ~150 m versetzt (Angabe von
# Airbnb/Inside Airbnb) — Grundlage für den Näherungs-Hinweis.
VERSATZ_M = 150


def finde_stadt_urls(html_text: str) -> dict[str, dict[str, str]]:
    """Aktuelle ``listings.csv``-URL je Stadt-Kürzel aus der Datenseite.

    Die Seite listet je Stadt den jüngsten Sammellauf; das Datum steht in der
    URL. Gibt es (unerwartet) mehrere Läufe, gewinnt der jüngste."""
    treffer: dict[str, dict[str, str]] = {}
    muster = re.compile(
        r"https://data\.insideairbnb\.com/germany/[a-z-]+/([a-z-]+)/"
        r"(\d{4}-\d{2}-\d{2})/visualisations/listings\.csv"
    )
    for m in muster.finditer(html_text):
        slug, datum = m.group(1), m.group(2)
        bisher = treffer.get(slug)
        if bisher is None or datum > bisher["datum"]:
            treffer[slug] = {"datum": datum, "url": m.group(0)}
    return treffer


def _zahl(v: Any) -> float | None:
    s = str(v or "").strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def reduzieren(csv_text: str) -> list[list[Any]]:
    """CSV → kompakte Liste ``[lat, lon, typ, preis, bewertungen_12m]`` je
    Inserat. Nur diese fünf Felder braucht die Punktauswertung — so bleibt
    der stadtweite Cache-Eintrag klein. Namen von Inseraten und Gastgebern
    werden bewusst nicht übernommen."""
    zeilen: list[list[Any]] = []
    for row in csv.DictReader(io.StringIO(csv_text)):
        lat = _zahl(row.get("latitude"))
        lon = _zahl(row.get("longitude"))
        if lat is None or lon is None:
            continue
        typ = _TYP_INDEX.get(str(row.get("room_type") or "").strip())
        preis = _zahl(row.get("price"))
        rev = _zahl(row.get("number_of_reviews_ltm"))
        zeilen.append([
            round(lat, 5), round(lon, 5),
            typ if typ is not None else -1,
            int(preis) if preis is not None and preis > 0 else None,
            int(rev) if rev is not None else 0,
        ])
    return zeilen


def auswerten(
    listings: list[list[Any]], lat: float, lon: float, radius: int
) -> dict[str, Any]:
    """Punktauswertung auf dem stadtweiten Datensatz — reine lokale Rechnung."""
    im_radius: list[dict[str, Any]] = []
    for l_lat, l_lon, typ, preis, rev in listings:
        d = haversine_m(lat, lon, l_lat, l_lon)
        if d > radius:
            continue
        im_radius.append({
            "lat": l_lat, "lon": l_lon,
            "typ": typ, "preis": preis, "bewertungen_12m": rev,
            "distanz_m": round(d),
            "richtung": bearing_label(lat, lon, l_lat, l_lon),
        })
    im_radius.sort(key=lambda e: e["distanz_m"])

    nach_typ: dict[str, int] = {}
    for _, label in ZIMMERTYPEN:
        n = sum(1 for e in im_radius if e["typ"] >= 0 and ZIMMERTYPEN[e["typ"]][1] == label)
        if n:
            nach_typ[label] = n
    unbekannt = sum(1 for e in im_radius if e["typ"] < 0)
    if unbekannt:
        nach_typ["(Typ unbekannt)"] = unbekannt

    preise = [e["preis"] for e in im_radius if e["preis"]]
    marker = [
        {
            "lat": e["lat"], "lon": e["lon"],
            "name": ZIMMERTYPEN[e["typ"]][1] if e["typ"] >= 0 else "Inserat",
            "typ_label": "Airbnb-Inserat",
            "distanz_m": e["distanz_m"], "richtung": e["richtung"],
            "tags": {
                **({"Preis je Nacht": f"{e['preis']} €"} if e["preis"] else {}),
                "Bewertungen 12 Monate": e["bewertungen_12m"],
            },
        }
        for e in im_radius[:MAX_MARKER]
    ]
    return {
        "im_radius": len(im_radius),
        "radius_m": radius,
        "nach_typ": nach_typ,
        "ganze_unterkuenfte": nach_typ.get("Ganze Unterkunft", 0),
        "bewertungen_12m": sum(e["bewertungen_12m"] for e in im_radius),
        "preis_median_eur": round(median(preise)) if len(preise) >= 5 else None,
        "preis_basis": len(preise),
        "naechstes_m": im_radius[0]["distanz_m"] if im_radius else None,
        "stadtweit": len(listings),
        "marker": marker,
        "marker_gekappt": len(im_radius) > MAX_MARKER,
        "liste": marker[:MAX_LISTE],
    }


HINWEISE = [
    "Airbnb versetzt Inserats-Positionen plattformseitig um bis zu ~150 m — "
    "die Zählwerte im Radius sind Näherungen, die Pins zeigen nicht das "
    "richtige Haus.",
    "Bewertungen der letzten zwölf Monate sind ein Aktivitätsindiz, keine "
    "Buchungszahl: nicht jede Buchung hinterlässt eine Bewertung. Als "
    "Vergleich zwischen zwei Lagen brauchbar, als Absolutzahl nicht.",
    "Viele Inserate ums Eck heißen Gäste-Publikum, das in keiner "
    "Einwohnerzahl steckt (Frühstück, Abendgeschäft) — zugleich ein Zeichen "
    "für touristisch geprägte Mieten.",
    "Momentaufnahme des Sammellaufs; Inside Airbnb aktualisiert etwa "
    "quartalsweise. Der Stichtag steht oben.",
]


def norm_gemeinde(gemeinde: str | None) -> str:
    return re.sub(r"[^a-zäöüß]", "", str(gemeinde or "").lower())


async def load(
    settings: Settings,
    gemeinde: str | None,
    lat: float,
    lon: float,
    radius: int,
    stadt_laden: Callable[[str], Awaitable[dict[str, Any]]],
) -> SourceResult:
    """Blockergebnis. ``stadt_laden`` liefert den stadtweit gecachten,
    reduzierten Datensatz — je Stadt ein Download alle 30 Tage, danach ist
    jeder Punkt reine lokale Rechnung."""
    started = time.perf_counter()
    eintrag = STAEDTE.get(norm_gemeinde(gemeinde))
    if eintrag is None:
        return SourceResult(
            name="airbnb",
            ok=True,
            data=None,
            warnings=[
                "Inside Airbnb führt in Deutschland nur München und Berlin "
                f"(Stand der Datenseite). Für „{gemeinde or 'diesen Punkt'}“ "
                "liegt dort kein Datensatz vor — das ist eine Datenlücke, "
                "keine Aussage über das Airbnb-Angebot."
            ],
        )
    slug, stadt_name = eintrag
    try:
        stadt = await stadt_laden(slug)
    except SourceError as err:
        return SourceResult.failed(
            "airbnb", err, int((time.perf_counter() - started) * 1000)
        )

    data = auswerten(stadt["listings"], lat, lon, radius)
    data.update({
        "stadt": stadt_name,
        "stichtag": stadt.get("stichtag"),
        "rohdaten": INDEX_URL,
        "hinweise": HINWEISE,
    })
    warnungen: list[str] = []
    if data["marker_gekappt"]:
        warnungen.append(
            f"{data['im_radius']} Inserate im Radius — Karte und Liste zeigen "
            f"die {MAX_MARKER} nächsten, die Zählwerte umfassen alle."
        )
    return SourceResult(
        name="airbnb",
        ok=True,
        data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnungen,
        provenance=Provenance(
            source=f"Inside Airbnb, Datensatz {stadt_name}",
            license=LIZENZ,
            endpoint=stadt.get("quelle_url") or INDEX_URL,
            stand=(
                f"Sammellauf vom {stadt['stichtag']}"
                if stadt.get("stichtag") else None
            ),
            retrieved_at=now_iso(),
            note=(
                "Airbnb-Inserate mit Koordinaten (um bis zu ~150 m versetzt), "
                "Zimmertyp, Preis und Bewertungszahl. Stadtweiter Datensatz, "
                "Punktauswertung lokal."
            ),
        ),
    )
