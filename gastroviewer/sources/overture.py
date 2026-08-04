"""Zweite Wettbewerbsquelle: Overture Maps Places (lokaler Import).

Warum es diese Quelle gibt: OSM ist die ehrliche Untergrenze — aber gerade
Einkaufszentren-Innenleben und Neueröffnungen fehlen dort oft komplett.
Phase-0 am 2026-08-04 am Einkaufszentrum MIRA (München-Nordheide) gemessen:
OSM kennt dort **3** Gastro-Betriebe, Overture **14+** (Hans im Glück, Thai
Curry, Altuntas Palast, Veneras Pizza, Van Hoa Sushi, Peking, Subway, …).
Overture speist sich u. a. aus den Facebook/Instagram-Unternehmensprofilen
(Meta), Foursquare und den offiziellen Filiallisten der Ketten — Quellen, die
Ladenpassagen kennen, in die OSM-Freiwillige selten hineinkartieren.

Lizenz CDLA-Permissive 2.0: darf — anders als Google-Daten — lokal
gespeichert, beliebig lange gecacht und auf unserer eigenen Karte angezeigt
werden.

Arbeitsweise wie beim GTFS-Fahrplan: einmal importieren
(``gastroviewer import-overture --region muenchen``), danach beantwortet eine
lokale SQLite jede Punktabfrage ohne Netz. Der Import braucht das Paket
``overturemaps`` (``pip install overturemaps``); der Server selbst nicht.

Die ehrlichen Grenzen, die in jede Anzeige gehören:

* Maschinell zusammengeführte Daten mit Ausreißern — am MIRA lagen in der
  Testbox u. a. eine japanische Brücke und ein versprengter „Karlsplatz"
  mit niedriger Verlässlichkeit. Deshalb trägt jeder Eintrag seinen
  ``confidence``-Wert, und angezeigt wird erst ab einer benannten Schwelle.
* Schließungen hinken auch hier hinterher. Overture ersetzt die Begehung
  nicht — es kontrolliert die OSM-Untergrenze nach oben.
* Der Abgleich mit OSM läuft über Name und Nähe. Er ist eine Heuristik:
  ein umbenannter Betrieb zählt fälschlich doppelt, zwei Filialen derselben
  Kette nebeneinander können fälschlich verschmelzen.
"""

from __future__ import annotations

import re
import sqlite3
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from ..config import Settings
from .base import Provenance, SourceResult, bearing_label, haversine_m, now_iso

LIZENZ = (
    "CDLA-Permissive 2.0 · © Overture Maps Foundation — enthält Daten von "
    "Meta, Microsoft, Foursquare, AllThePlaces und OpenStreetMap-Mitwirkenden"
)

# Anzeigeschwelle für die Verlässlichkeit. Ein gewählter Wert, kein Messwert —
# er steht in der Oberfläche, und die Zahl der Einträge darunter wird genannt.
SCHWELLE = 0.5

# Abgleich mit OSM: näher als das und ähnlicher Name = derselbe Betrieb.
# Gewählte Werte; die Heuristik-Grenzen stehen im Modul-Docstring.
MATCH_DISTANZ_M = 100
MATCH_AEHNLICHKEIT = 0.75

# ---------------------------------------------------------------- Kategorien
#
# Overture führt eine große Kategorien-Taxonomie. Erst die explizite Zuordnung,
# dann zwei Endungsregeln (…_restaurant, …_bar). Was nicht zuzuordnen ist,
# wird beim Import verworfen — lieber ein fehlender Freizeitpark als eine
# „Gastronomie", die keine ist.
GRUPPEN_LABELS = {
    "restaurant": "Restaurant",
    "schnellgastronomie": "Schnellrestaurant",
    "cafe": "Café",
    "bar": "Bar / Nachtleben",
    "eisdiele": "Eisdiele / Dessert",
    "baeckerei_snack": "Bäckerei / Snack-Verkauf",
}

_EXPLIZIT = {
    "restaurant": "restaurant",
    "fast_food_restaurant": "schnellgastronomie",
    "food_court": "schnellgastronomie",
    "food_truck": "schnellgastronomie",
    "sandwich_shop": "schnellgastronomie",
    "cafe": "cafe",
    "coffee_shop": "cafe",
    "tea_room": "cafe",
    "bubble_tea": "cafe",
    "juice_bar": "cafe",
    "internet_cafe": "cafe",
    "bar": "bar",
    "pub": "bar",
    "night_club": "bar",
    "beer_garden": "bar",
    "brewery": "bar",
    "hookah_bar": "bar",
    "ice_cream_shop": "eisdiele",
    "gelato": "eisdiele",
    "dessert_shop": "eisdiele",
    "frozen_yogurt": "eisdiele",
    "bakery": "baeckerei_snack",
    "patisserie": "baeckerei_snack",
    "donut_shop": "baeckerei_snack",
    "bagel_shop": "baeckerei_snack",
    "eat_and_drink": "restaurant",
}


def _gruppe_einer(k: str) -> str | None:
    if k in _EXPLIZIT:
        return _EXPLIZIT[k]
    if k.endswith("_restaurant"):
        return "restaurant"
    if k.endswith("_bar") and k != "juice_bar":
        return "bar"
    return None


def gruppe_fuer(kategorien: list[str | None]) -> str | None:
    """Nur die **Primärkategorie** entscheidet; die Alternativen zählen erst,
    wenn keine Primärkategorie gesetzt ist. Gemessen am 2026-08-04: über die
    Alternativen rutschten sonst Hotels, ein REWE und Vereine als
    „Gastronomie" hinein — die Primärkategorie ist die Selbstauskunft des
    Betriebs und deutlich präziser."""
    if kategorien and kategorien[0]:
        return _gruppe_einer(kategorien[0])
    for k in kategorien[1:]:
        if k:
            g = _gruppe_einer(k)
            if g:
                return g
    return None


def zeile_aus_properties(
    props: dict[str, Any], lat: float, lon: float
) -> dict[str, Any] | None:
    """Normalisiert einen Overture-Datensatz (GeoJSON-Properties oder
    pyarrow-Zeile — beide tragen dieselben Schlüssel) auf unsere Tabellenzeile.
    ``None``: kein Gastro-Eintrag."""
    cats = props.get("categories") or {}
    kategorien = [cats.get("primary"), *(cats.get("alternate") or [])]
    gruppe = gruppe_fuer(kategorien)
    if gruppe is None:
        return None
    name = (props.get("names") or {}).get("primary")
    if not name:
        return None
    adresse = plz = ort = None
    for a in props.get("addresses") or []:
        adresse = adresse or a.get("freeform")
        plz = plz or a.get("postcode")
        ort = ort or a.get("locality")
    marke = ((props.get("brand") or {}).get("names") or {}).get("primary")
    quellen = sorted({
        s.get("dataset") for s in (props.get("sources") or []) if s.get("dataset")
    })
    conf = props.get("confidence")
    return {
        "id": props.get("id") or f"{lat:.6f}|{lon:.6f}|{name}",
        "name": str(name),
        "kategorie": cats.get("primary") or "",
        "gruppe": gruppe,
        "confidence": round(float(conf), 3) if conf is not None else 0.0,
        "lat": round(float(lat), 7),
        "lon": round(float(lon), 7),
        "adresse": adresse,
        "plz": plz,
        "ort": ort,
        "marke": marke,
        "quellen": ",".join(quellen),
    }


def wkb_punkt(blob: bytes) -> tuple[float, float] | None:
    """Overture-Geometrien kommen als WKB; Places sind Punkte (21 Bytes)."""
    import struct

    if not blob or len(blob) < 21:
        return None
    little = blob[0] == 1
    fmt = "<" if little else ">"
    (typ,) = struct.unpack_from(f"{fmt}I", blob, 1)
    if typ & 0xFF != 1:  # kein Punkt
        return None
    x, y = struct.unpack_from(f"{fmt}dd", blob, 5)
    return y, x  # lat, lon


# ------------------------------------------------------------------ SQLite


def db_init(pfad: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(pfad)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS places (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            kategorie TEXT,
            gruppe TEXT NOT NULL,
            confidence REAL NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            adresse TEXT, plz TEXT, ort TEXT, marke TEXT, quellen TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_places_lat_lon ON places (lat, lon);
        """
    )
    return conn


def meta_lesen(conn: sqlite3.Connection) -> dict[str, str]:
    return dict(conn.execute("SELECT key, value FROM meta"))


# ------------------------------------------------------------- Abgleich


def _norm(s: str) -> str:
    s = s.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"), ("'", "")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]", "", s)


def namen_aehnlich(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    return SequenceMatcher(None, na, nb).ratio() >= MATCH_AEHNLICHKEIT


def abgleichen(
    overture_eintraege: list[dict[str, Any]],
    osm_gastro: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Teilt die Overture-Treffer in „auch in OSM" und „nur Overture".

    Rückgabe: (nur_overture, anzahl_beide). Jeder Overture-Eintrag matcht
    höchstens einen OSM-Betrieb und umgekehrt (nächster zuerst)."""
    vergeben: set[int] = set()
    nur: list[dict[str, Any]] = []
    beide = 0
    for e in overture_eintraege:
        partner = None
        partner_dist = MATCH_DISTANZ_M + 1
        for i, g in enumerate(osm_gastro):
            if i in vergeben:
                continue
            d = haversine_m(e["lat"], e["lon"], g["lat"], g["lon"])
            if d > MATCH_DISTANZ_M or d >= partner_dist:
                continue
            if namen_aehnlich(e["name"], g.get("name")) or (
                e.get("marke") and namen_aehnlich(e["marke"], g.get("marke"))
            ):
                partner, partner_dist = i, d
        if partner is None:
            nur.append(e)
        else:
            vergeben.add(partner)
            beide += 1
    return nur, beide


# ------------------------------------------------------------------ Laden


def load(
    settings: Settings,
    lat: float,
    lon: float,
    radius: int,
    osm_gastro: list[dict[str, Any]] | None,
) -> SourceResult:
    """Rein lokal (SQLite aus dem Import) — kein Outbound, wie GTFS."""
    started = time.perf_counter()
    pfad = settings.overture_db_path
    if not pfad.exists():
        return SourceResult(
            name="overture", ok=True,
            data={"importiert": False},
            warnings=[
                "Kein Overture-Import vorhanden. Einmal ausführen: "
                "pip install overturemaps && "
                "gastroviewer import-overture --region muenchen — danach "
                "kontrolliert dieser Block die OSM-Untergrenze nach oben."
            ],
        )

    conn = sqlite3.connect(pfad)
    conn.row_factory = sqlite3.Row
    try:
        meta = meta_lesen(conn)
        dlat = radius / 111_320.0
        import math

        dlon = radius / (111_320.0 * max(0.2, math.cos(math.radians(lat))))
        rows = conn.execute(
            "SELECT * FROM places WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
            (lat - dlat, lat + dlat, lon - dlon, lon + dlon),
        ).fetchall()
    finally:
        conn.close()

    alle = []
    for r in rows:
        d = dict(r)
        dist = haversine_m(lat, lon, d["lat"], d["lon"])
        if dist > radius:
            continue
        d["distanz_m"] = round(dist)
        d["richtung"] = bearing_label(lat, lon, d["lat"], d["lon"])
        d["gruppe_label"] = GRUPPEN_LABELS.get(d["gruppe"], d["gruppe"])
        alle.append(d)
    alle.sort(key=lambda x: x["distanz_m"])

    sicher = [e for e in alle if e["confidence"] >= SCHWELLE]
    unter_schwelle = len(alle) - len(sicher)

    # Liegt der Punkt außerhalb des importierten Ausschnitts, wäre „0 Treffer"
    # eine falsche Aussage über die Lage statt über den Import.
    bbox_warnung = None
    box = meta.get("bbox", "")
    try:
        b = [float(x) for x in box.split(",")]
        if len(b) == 4 and not (b[0] <= lat <= b[2] and b[1] <= lon <= b[3]):
            bbox_warnung = (
                "Der Punkt liegt außerhalb des importierten Overture-"
                f"Ausschnitts ({meta.get('region') or box}). Für diesen Punkt "
                "sagt der Block nichts — Import mit passender Region wiederholen."
            )
    except ValueError:
        pass

    osm_liste = osm_gastro or []
    nur_overture, beide = abgleichen(sicher, osm_liste)

    data = {
        "importiert": True,
        "region": meta.get("region"),
        "release": meta.get("release"),
        "importiert_am": meta.get("importiert_am"),
        "schwelle": SCHWELLE,
        "anzahl_overture": len(sicher),
        "unter_schwelle": unter_schwelle,
        "osm_gesamt": len(osm_liste),
        "beide": beide,
        "nur_osm": len(osm_liste) - beide,
        "nur_overture": nur_overture,
        "kombiniert_gesamt": len(osm_liste) + len(nur_overture),
        "hinweise": [
            f"Angezeigt ab Verlässlichkeit {SCHWELLE:g} (gewählte Schwelle); "
            f"{unter_schwelle} Eintrag/Einträge darunter sind ausgeblendet.",
            "Der Abgleich über Name und Nähe ist eine Heuristik — umbenannte "
            "Betriebe zählen doppelt, benachbarte Filialen können verschmelzen.",
            "Auch OSM+Overture ist kein Vollbestand: Schließungen hinken in "
            "beiden Quellen hinterher. Die kombinierte Zahl ist die bessere "
            "Näherung, die Begehung bleibt die Wahrheit.",
        ],
    }

    warnungen = [bbox_warnung] if bbox_warnung else []
    return SourceResult(
        name="overture",
        ok=True,
        data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnungen,
        provenance=Provenance(
            source="Overture Maps Places (lokaler Import)",
            license=LIZENZ,
            endpoint="https://overturemaps.org/ (Import über das Paket overturemaps)",
            stand=(
                f"Release {meta.get('release') or 'unbekannt'}, "
                f"importiert {meta.get('importiert_am') or '—'}"
            ),
            retrieved_at=now_iso(),
            note=(
                "Offene POI-Daten (u. a. Meta/Facebook-Unternehmensprofile, "
                "Foursquare, Ketten-Filiallisten). Kontrolliert die OSM-"
                "Untergrenze nach oben; jeder Eintrag trägt seine "
                "Verlässlichkeit."
            ),
        ),
    )
