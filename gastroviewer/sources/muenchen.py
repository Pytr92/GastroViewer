"""Raddauerzählstellen der Landeshauptstadt München.

Die Spec sagt in §8: „Passantenströme fehlen komplett. Fußgängerzone und
Seitenstraße sind in diesen Daten nicht unterscheidbar." Das ist die größte
Lücke des Werkzeugs. Vollständig schließen lässt sie sich mit offenen Daten
nicht — hystreet untersagt die gewerbliche Nutzung im kostenfreien Modell —,
aber München betreibt sechs **dauerhafte Zählstellen mit echten Messwerten**.

Das sind Radfahrende, keine Fußgänger, und sechs Punkte für eine Stadt mit
1,6 Mio. Einwohnern. Beides steht in der Ausgabe. Was die Zahlen leisten: eine
gemessene Größenordnung für die Verkehrsstärke einer Achse, gegen die sich ein
Standort einordnen lässt — statt gar nichts.

Verifiziert am 2026-08-01:
``https://geoportal.muenchen.de/geoserver/mor_wfs/ows`` ·
``typeName=mor_wfs:raddauerzaehlstellen`` · WFS 2.0.0 · GeoJSON · 6 Features ·
Datenlizenz Deutschland Namensnennung 2.0.
"""

from __future__ import annotations

import re
import time
from typing import Any

from ..config import Settings
from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, bearing_label, haversine_m, now_iso

WFS_URL = "https://geoportal.muenchen.de/geoserver/mor_wfs/ows"
TYPENAME = "mor_wfs:raddauerzaehlstellen"

LIZENZ = (
    "Datenlizenz Deutschland Namensnennung 2.0 (dl-de/by-2-0) · "
    "© Landeshauptstadt München, Mobilitätsreferat"
)
ROHDATEN = (
    "https://opendata.muenchen.de/dataset/"
    "daten-der-raddauerzaehlstellen-muenchen-jahreszahlen"
)

# Jenseits dieser Entfernung sagt eine Zählstelle über den Standort nichts mehr
# aus. Sechs Stellen decken die Stadt nicht flächig ab — der Block bleibt dann
# bewusst leer, statt eine Zahl von der anderen Stadtseite zu zeigen.
MAX_DISTANZ_M = 3000


def _zahl(v: Any) -> int | None:
    """Die Felder kommen als Zeichenketten, teils mit Text wie „Derzeit keine Daten"."""
    if v is None:
        return None
    s = str(v).strip().replace(".", "").replace(" ", "")
    if not s or not re.fullmatch(r"-?\d+", s):
        return None
    return int(s)


def _ohne_html(v: Any) -> str | None:
    if not v:
        return None
    text = re.sub(r"<[^>]+>", " ", str(v))
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def aufbereiten(
    features: list[dict[str, Any]], lat: float, lon: float, radius: int
) -> dict[str, Any]:
    stellen = []
    for f in features:
        p = f.get("properties") or {}
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if geom.get("type") != "Point" or len(coords) < 2:
            continue
        slon, slat = float(coords[0]), float(coords[1])
        dist = haversine_m(lat, lon, slat, slon)
        jahr = _zahl(p.get("gesamt_sum_2025"))
        stellen.append(
            {
                "name": p.get("zaehlstelle_lang") or p.get("zaehlstelle"),
                "kurzname": p.get("zaehlstelle"),
                "lat": slat,
                "lon": slon,
                "distanz_m": round(dist),
                "richtung": bearing_label(lat, lon, slat, slon),
                "im_radius": dist <= radius,
                "richtungen": [
                    r for r in (p.get("richtung_1"), p.get("richtung_2")) if r
                ],
                "summe_vorjahr": jahr,
                "summe_vorjahr_jahr": 2025 if jahr is not None else None,
                "summe_laufender_monat": _zahl(p.get("gesamt_sum_monat_2026")),
                "je_tag_vorjahr": round(jahr / 365) if jahr is not None else None,
                "besonderheiten": _ohne_html(p.get("besonderheiten")),
                "stoerung": _ohne_html(p.get("zaehler_kaputt_sum_2025")),
            }
        )
    stellen.sort(key=lambda s: s["distanz_m"])
    nah = [s for s in stellen if s["distanz_m"] <= MAX_DISTANZ_M]
    return {
        "zaehlstellen_gesamt": len(stellen),
        "in_reichweite": nah,
        "naechste": nah[0] if nah else None,
        "im_radius": [s for s in stellen if s["im_radius"]],
        "max_distanz_m": MAX_DISTANZ_M,
        "rohdaten": ROHDATEN,
    }


# ------------------------------------------- Jahresgang aus den Tages-Rohdaten
#
# Die WFS-Stammdaten tragen nur Jahressumme und laufenden Monat. Der
# **Jahresgang** — wie stark Sommer und Winter auseinanderliegen — steht in
# den Tageswerte-CSVs des Open-Data-Portals. Verifiziert am 2026-08-04:
# CKAN ``package_show?id=daten-der-raddauerzaehlstellen-muenchen-jahreszahlen``
# listet je Jahr eine Datei „Tageswerte Wetter {Jahr}" mit den Spalten
# ``datum,uhrzeit_start,uhrzeit_ende,zaehlstelle,richtung_1,richtung_2,gesamt,…``
# (Datum als ``2025.01.01``; in den Monatsdateien sind die Felder mit
# Leerzeichen aufgefüllt — deshalb wird überall gestrippt). Die Dateinamen
# sind unregelmäßig („rad_2025_tage_export_19_01_25.csv") und werden deshalb
# über die CKAN-API aufgelöst, nie geraten.
CKAN_JAHRESZAHLEN = (
    "https://opendata.muenchen.de/api/3/action/package_show"
    "?id=daten-der-raddauerzaehlstellen-muenchen-jahreszahlen"
)
MONATE_KURZ = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
               "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]


def finde_tageswerte(payload: Any) -> tuple[int, str] | None:
    """Jüngste „Tageswerte Wetter {Jahr}"-Ressource aus der CKAN-Antwort."""
    beste: tuple[int, str] | None = None
    for r in ((payload or {}).get("result") or {}).get("resources") or []:
        name = str(r.get("name") or "")
        m = re.search(r"Tageswerte.*?(\d{4})", name)
        if not m or not r.get("url"):
            continue
        jahr = int(m.group(1))
        if beste is None or jahr > beste[0]:
            beste = (jahr, r["url"])
    return beste


def parse_tageswerte(text: str) -> dict[str, dict[str, Any]]:
    """Tages-CSV → je Zählstelle: Messtage, Tagesmittel, Monatsmittel, Spitzentag.

    Nur Zeilen mit lesbarem Datum und Gesamtwert zählen; die Zahl der
    Messtage steht im Ergebnis, denn nicht jede Stelle misst das ganze Jahr
    (Kreuther hatte 2025 nur 92 Tage).
    """
    zeilen = [z for z in text.replace("﻿", "").splitlines() if z.strip()]
    if not zeilen:
        return {}
    kopf = [c.strip() for c in zeilen[0].split(",")]
    try:
        i_datum = kopf.index("datum")
        i_stelle = kopf.index("zaehlstelle")
        i_gesamt = kopf.index("gesamt")
    except ValueError:
        return {}

    je_stelle: dict[str, dict[int, list[int]]] = {}
    for zeile in zeilen[1:]:
        teile = [c.strip() for c in zeile.split(",")]
        if len(teile) <= max(i_datum, i_stelle, i_gesamt):
            continue
        m = re.fullmatch(r"(\d{4})\.(\d{2})\.(\d{2})", teile[i_datum])
        if not m:
            continue
        monat = int(m.group(2))
        stelle = teile[i_stelle]
        if not stelle or not re.fullmatch(r"-?\d+", teile[i_gesamt] or ""):
            continue
        wert = int(teile[i_gesamt])
        if wert < 0:
            continue
        je_stelle.setdefault(stelle, {}).setdefault(monat, []).append(wert)

    out: dict[str, dict[str, Any]] = {}
    for stelle, monate in je_stelle.items():
        alle = [w for ws in monate.values() for w in ws]
        if not alle:
            continue
        out[stelle] = {
            "messtage": len(alle),
            "je_tag_mittel": round(sum(alle) / len(alle)),
            "monatsmittel": [
                round(sum(monate[m]) / len(monate[m])) if monate.get(m) else None
                for m in range(1, 13)
            ],
            "spitzentag": max(alle),
        }
    return out


HINWEISE = [
    "Gezählt werden **Radfahrende**, keine Fußgänger. Für eine Fußgängerzone sagt "
    "die Zahl wenig, für eine Radachse viel.",
    "Es sind sechs Zählstellen für die ganze Stadt. Sie messen ihren Querschnitt, "
    "nicht das Umfeld — schon eine Parallelstraße kann völlig anders liegen.",
    "Die Stellen zählen ganzjährig; Wetter und Jahreszeit schlagen stark durch. "
    "Der Jahreswert ist die belastbarere Größe als der laufende Monat.",
]


async def zaehlstellen(
    out: Outbound,
    settings: Settings,
    lat: float,
    lon: float,
    radius: int,
    jahresgang_laden: Any = None,
) -> SourceResult:
    """``jahresgang_laden``: optionale async-Funktion, die die geparsten
    Tageswerte liefert — sie wird nur gerufen, wenn überhaupt eine Zählstelle
    in Reichweite liegt, damit Punkte außerhalb Münchens die 100-KB-Datei
    nie anfassen. Ihr Ausfall kostet nur den Jahresgang, nicht den Block."""
    started = time.perf_counter()
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeName": TYPENAME,
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
    }
    try:
        payload = await out.get_json(
            "muenchen_rad",
            WFS_URL,
            params=params,
            timeout=45.0,
            limiter="muenchen",
            min_interval=1.0,
        )
    except SourceError as err:
        return SourceResult.failed(
            "radzaehlung", err, int((time.perf_counter() - started) * 1000)
        )

    features = payload.get("features", []) if isinstance(payload, dict) else []
    data = aufbereiten(features, lat, lon, radius)

    warnungen: list[str] = []
    if data["in_reichweite"] and jahresgang_laden is not None:
        try:
            jg = await jahresgang_laden()
        except SourceError as err:
            warnungen.append(f"Jahresgang nicht ladbar: {err.message}")
            jg = None
        if jg:
            data["jahresgang_jahr"] = jg.get("jahr")
            stationen = jg.get("stationen") or {}
            for s in data["in_reichweite"]:
                s["jahresgang"] = stationen.get(s["kurzname"])
            if data["naechste"]:
                data["naechste"]["jahresgang"] = stationen.get(
                    data["naechste"]["kurzname"]
                )

    if not data["in_reichweite"]:
        warnungen.append(
            f"Keine Zählstelle innerhalb von {MAX_DISTANZ_M} m. Die sechs Stellen "
            "decken München nicht flächig ab — für diesen Punkt liegt keine gemessene "
            "Frequenz vor."
        )
    for s in data["in_reichweite"]:
        if s["stoerung"]:
            warnungen.append(f"{s['kurzname']}: {s['stoerung']}")

    return SourceResult(
        name="radzaehlung",
        ok=True,
        data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnungen,
        provenance=Provenance(
            source="Raddauerzählstellen München (Mobilitätsreferat, WFS)",
            license=LIZENZ,
            endpoint=WFS_URL,
            stand="Jahressumme 2025, laufender Monat 2026",
            retrieved_at=now_iso(),
            note=(
                "Gemessene Radverkehrszahlen an sechs festen Querschnitten. Keine "
                "Fußgängerzählung und keine flächendeckende Erhebung."
            ),
        ),
    )
