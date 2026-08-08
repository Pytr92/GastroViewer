"""Sonne und Schatten am Standort — was eine Terrasse wert ist.

Für Außengastronomie ist die Besonnung ein harter Wirtschaftsfaktor: Eine
Fläche, die ab 14 Uhr im Vollschatten liegt, trägt sich anders als eine mit
Abendsonne. Ermittelt wird das in der Branche bislang von Hand — die
Fachliteratur empfiehlt, zwei Wochen lang stündlich zu notieren.

Diese Auswertung rechnet es statt dessen aus, und zwar aus drei Zutaten,
von denen zwei schon im Werkzeug liegen:

* **Sonnenstand** — reine Astronomie, keine Datenquelle nötig. Der Algorithmus
  steht unten; gegengeprüft an den theoretischen Extremwerten (München 48,13° N:
  65,3° zur Sommer-, 18,4° zur Wintersonnenwende).
* **Gebäude ringsum** — Grundrisse und Höhen aus OpenStreetMap. Die Höhe kommt
  aus ``height`` (selten) oder ``building:levels`` (häufig, × 3,2 m je Geschoss).
* **Sonnenscheindauer** — die DWD-Monatswerte des Klimablocks sagen, wie oft die
  geometrisch mögliche Sonne tatsächlich scheint.

**Die entscheidende Ehrlichkeit:** In OSM hat nur ein Teil der Gebäude eine
Höhenangabe (im geprüften Innenstadtbereich 77 %, in Randlagen um 50 %).
Gebäude ohne Angabe werden **nicht** geschätzt, sondern übergangen — das
Ergebnis ist damit eine *Obergrenze* der Besonnung, und der Block sagt
ausdrücklich, wie viele Häuser er nicht beurteilen konnte. Erfundene Höhen
wären hier besonders verführerisch und besonders falsch.

Weitere benannte Vereinfachungen: Gerechnet wird für den Punkt selbst in
1,5 m Höhe (Kopfhöhe einer sitzenden Person), nicht für eine Fläche; Bäume,
Markisen, Balkone und Geländeneigung bleiben außen vor; die Erdatmosphäre
(Refraktion) wird nicht korrigiert, was nur nahe dem Horizont zählt.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any

from ..config import Settings
from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, now_iso

LICENSE = (
    "Gebäudedaten: © OpenStreetMap-Mitwirkende, ODbL 1.0 · "
    "Sonnenstand: eigene Berechnung (Astronomie, keine Datenquelle)"
)

# Radius der berücksichtigten Nachbarbebauung. Ein 15-m-Haus wirft bei 20°
# Sonnenhöhe rund 42 m Schatten; 150 m decken damit auch Hochhäuser ab und
# halten die Overpass-Antwort bei ~64 KB (real gemessen).
UMKREIS_M = 150
METER_JE_GESCHOSS = 3.2
AUGENHOEHE_M = 1.5
# Zeitraster der Tagesrechnung. 10 Minuten sind fein genug, dass eine
# Häuserlücke nicht übersprungen wird, und grob genug für ~90 Schritte/Tag.
SCHRITT_MINUTEN = 10

# Stichtage: die beiden Sonnenwenden und eine Tagundnachtgleiche. Damit ist
# die Spanne über das Jahr benannt, statt einen Mittelwert zu behaupten.
STICHTAGE = (
    ("sommer", 6, 21, "Sommersonnenwende (21.06.)"),
    ("uebergang", 9, 22, "Tagundnachtgleiche (22.09.)"),
    ("winter", 12, 21, "Wintersonnenwende (21.12.)"),
)

HINWEISE = [
    "Gerechnet wird für den **Punkt selbst in 1,5 m Höhe** (sitzende "
    "Augenhöhe), nicht für eine bestimmte Terrassenfläche. Liegt die "
    "geplante Fläche einige Meter daneben, verschiebt sich das Ergebnis.",
    "Nur **Gebäude mit Höhenangabe in OpenStreetMap** werfen hier Schatten. "
    "Häuser ohne `height` oder `building:levels` werden übergangen — die "
    "ausgewiesene Sonnenzeit ist deshalb eine **Obergrenze**. Wie viele "
    "Gebäude das betrifft, steht in der Kennzahl „Höhe unbekannt“.",
    "Bäume, Markisen, Balkone, Vordächer und Geländeneigung bleiben "
    "unberücksichtigt; sie können die Sonne zusätzlich nehmen, nie hinzufügen.",
    "Die Zeiten sind **geometrisch mögliche** Sonne bei wolkenlosem Himmel. "
    "Wie oft die Sonne tatsächlich scheint, steht im Klimablock (DWD-"
    "Sonnenscheindauer je Monat) — beides zusammen ergibt die Erwartung.",
]


# ------------------------------------------------------------ Astronomie

def sonnenstand(lat: float, lon: float, zeit_utc: dt.datetime) -> tuple[float, float]:
    """Sonnenhöhe und Azimut in Grad (Azimut: 0 = Nord, 90 = Ost, 180 = Süd).

    Verfahren nach der „Low precision formulae for the Sun" des Astronomical
    Almanac — für unsere Zwecke (Schattenwurf auf 10 Minuten genau) mehr als
    ausreichend; der Fehler liegt im Bogenminutenbereich.
    """
    a = (14 - zeit_utc.month) // 12
    y = zeit_utc.year + 4800 - a
    m = zeit_utc.month + 12 * a - 3
    jdn = (zeit_utc.day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100
           + y // 400 - 32045)
    tagesbruch = ((zeit_utc.hour - 12) / 24 + zeit_utc.minute / 1440
                  + zeit_utc.second / 86400)
    n = jdn + tagesbruch - 2451545.0

    mittlere_laenge = (280.460 + 0.9856474 * n) % 360
    anomalie = math.radians((357.528 + 0.9856003 * n) % 360)
    ekliptik_laenge = math.radians(
        mittlere_laenge + 1.915 * math.sin(anomalie)
        + 0.020 * math.sin(2 * anomalie))
    schiefe = math.radians(23.439 - 0.0000004 * n)

    rektaszension = math.atan2(math.cos(schiefe) * math.sin(ekliptik_laenge),
                               math.cos(ekliptik_laenge))
    deklination = math.asin(math.sin(schiefe) * math.sin(ekliptik_laenge))

    gmst = (18.697374558 + 24.06570982441908 * n) % 24
    lmst = math.radians((gmst * 15 + lon) % 360)
    stundenwinkel = lmst - rektaszension

    p = math.radians(lat)
    hoehe = math.asin(math.sin(p) * math.sin(deklination)
                      + math.cos(p) * math.cos(deklination)
                      * math.cos(stundenwinkel))
    azimut = math.atan2(
        math.sin(stundenwinkel),
        math.cos(stundenwinkel) * math.sin(p)
        - math.tan(deklination) * math.cos(p))
    return math.degrees(hoehe), (math.degrees(azimut) + 180) % 360


def _utc_versatz(tag: dt.date) -> int:
    """Stunden zwischen MEZ/MESZ und UTC. Sommerzeit gilt vom letzten
    Sonntag im März bis zum letzten Sonntag im Oktober."""
    def letzter_sonntag(jahr: int, monat: int) -> dt.date:
        d = dt.date(jahr, monat, 31) if monat == 3 else dt.date(jahr, monat, 31)
        while d.weekday() != 6:
            d -= dt.timedelta(days=1)
        return d

    start = letzter_sonntag(tag.year, 3)
    ende = letzter_sonntag(tag.year, 10)
    return 2 if start <= tag < ende else 1


# -------------------------------------------------------------- Gebäude

def gebaeude_hoehe(tags: dict[str, str]) -> float | None:
    """Gebäudehöhe in Metern aus OSM-Tags — oder ``None``, wenn die Angabe
    fehlt. Bewusst kein Schätzwert: eine erfundene Höhe wäre ein erfundener
    Schatten."""
    roh = (tags.get("height") or "").strip().replace(",", ".")
    if roh:
        # „12", „12 m", „12.5 m" — Fuß-Angaben („40'") sind in DE unüblich
        # und werden verworfen statt falsch umgerechnet.
        zahl = roh.replace("m", "").strip()
        try:
            wert = float(zahl)
            if 0 < wert < 400:
                return wert
        except ValueError:
            pass
    geschosse = (tags.get("building:levels") or "").strip().replace(",", ".")
    if geschosse:
        try:
            wert = float(geschosse)
            if 0 < wert < 130:
                return wert * METER_JE_GESCHOSS
        except ValueError:
            pass
    return None


def _overpass_abfrage(lat: float, lon: float, radius: int) -> str:
    return (
        "[out:json][timeout:60];"
        f'way["building"](around:{radius},{lat:.6f},{lon:.6f});'
        "out geom;"
    )


def _horizont(
    lat: float, lon: float, elemente: list[dict[str, Any]]
) -> tuple[list[tuple[float, float]], int, int]:
    """Höhenwinkel der Bebauung je Azimut-Grad.

    Für jede Gebäudekante wird geprüft, unter welchem Winkel sie vom
    Standort aus erscheint; je Blickrichtung bleibt der höchste Wert
    stehen. Ergebnis: 360 Werte, gegen die sich jeder Sonnenstand
    unmittelbar prüfen lässt.
    """
    horizont = [0.0] * 360
    mit_hoehe = ohne_hoehe = 0
    cos_lat = math.cos(math.radians(lat))

    for el in elemente:
        geom = el.get("geometry") or []
        if len(geom) < 2:
            continue
        hoehe = gebaeude_hoehe(el.get("tags") or {})
        if hoehe is None:
            ohne_hoehe += 1
            continue
        mit_hoehe += 1
        ueber_auge = hoehe - AUGENHOEHE_M
        if ueber_auge <= 0:
            continue

        # Meter-Koordinaten relativ zum Standort (x = Ost, y = Nord).
        punkte = []
        for p in geom:
            plat, plon = p.get("lat"), p.get("lon")
            if plat is None or plon is None:
                continue
            punkte.append(((plon - lon) * 111_320.0 * cos_lat,
                           (plat - lat) * 111_320.0))
        if len(punkte) < 2:
            continue

        # Jede Wandkante verdeckt den **gesamten** Azimutbereich zwischen
        # ihren Endpunkten, nicht nur deren zwei Blickrichtungen. Für jedes
        # Grad im Bereich wird der Schnittpunkt des Sehstrahls mit der
        # Kante bestimmt — das ergibt die tatsächliche Entfernung dorthin.
        for (x1, y1), (x2, y2) in zip(punkte, punkte[1:]):
            a1 = math.degrees(math.atan2(x1, y1)) % 360
            a2 = math.degrees(math.atan2(x2, y2)) % 360
            spanne = (a2 - a1) % 360
            if spanne > 180:
                a1, a2 = a2, a1
                spanne = 360 - spanne
            ex, ey = x2 - x1, y2 - y1
            start = int(math.ceil(a1))
            for schritt in range(int(spanne) + 2):
                grad = (start + schritt) % 360
                if (grad - a1) % 360 > spanne:
                    break
                r = math.radians(grad)
                dx, dy = math.sin(r), math.cos(r)
                nenner = ex * dy - ey * dx
                if abs(nenner) < 1e-9:
                    continue  # Kante liegt in Blickrichtung
                t = (ex * y1 - ey * x1) / nenner
                u = (dx * y1 - dy * x1) / nenner
                if t <= 1.0 or not (-0.001 <= u <= 1.001):
                    continue
                winkel = math.degrees(math.atan2(ueber_auge, t))
                if winkel > horizont[grad]:
                    horizont[grad] = winkel

    return [(float(i), horizont[i]) for i in range(360)], mit_hoehe, ohne_hoehe


def _tageslauf(
    lat: float, lon: float, horizont: list[tuple[float, float]],
    tag: dt.date,
) -> dict[str, Any]:
    """Ein Stichtag: wann steht die Sonne über dem Horizont, und wann davon
    über der Bebauung?"""
    versatz = _utc_versatz(tag)
    sonnig: list[bool] = []
    zeiten: list[dt.time] = []
    ueber_horizont = 0

    schritte = 24 * 60 // SCHRITT_MINUTEN
    for i in range(schritte):
        minute = i * SCHRITT_MINUTEN
        lokal = dt.datetime.combine(tag, dt.time(minute // 60, minute % 60))
        zeiten.append(lokal.time())
        hoehe, azimut = sonnenstand(lat, lon, lokal - dt.timedelta(hours=versatz))
        if hoehe <= 0:
            sonnig.append(False)
            continue
        ueber_horizont += 1
        sonnig.append(hoehe > horizont[int(azimut) % 360][1])

    # Zusammenhängende Sonnenfenster. Das Ende eines Fensters ist das Ende
    # des letzten besonnten Rasterschritts, nicht dessen Anfang — sonst
    # erschiene ein einzelner Schritt als „12:30–12:30".
    def _ende(index: int) -> str:
        minute = (index + 1) * SCHRITT_MINUTEN
        return f"{(minute // 60) % 24:02d}:{minute % 60:02d}"

    fenster: list[dict[str, Any]] = []
    start = None
    for i, s in enumerate(sonnig):
        if s and start is None:
            start = i
        elif not s and start is not None:
            fenster.append({"von": zeiten[start].strftime("%H:%M"),
                            "bis": _ende(i - 1),
                            "minuten": (i - start) * SCHRITT_MINUTEN})
            start = None
    if start is not None:
        fenster.append({"von": zeiten[start].strftime("%H:%M"),
                        "bis": _ende(len(sonnig) - 1),
                        "minuten": (len(sonnig) - start) * SCHRITT_MINUTEN})

    # Für die Anzeige zählen nur Fenster ab einer halben Stunde — kürzere
    # Sonnenblitze zwischen zwei Häusern nützen keinem Gast. Sie bleiben in
    # der Stundensumme, werden aber getrennt ausgewiesen.
    lang = [f for f in fenster if f["minuten"] >= 30]
    kurz_minuten = sum(f["minuten"] for f in fenster if f["minuten"] < 30)

    stunden = sum(sonnig) * SCHRITT_MINUTEN / 60
    moeglich = ueber_horizont * SCHRITT_MINUTEN / 60
    # Abendsonne ab 17 Uhr — das wirtschaftlich wertvollste Fenster für
    # Außengastronomie (Feierabendgeschäft).
    abend = sum(1 for z, s in zip(zeiten, sonnig) if s and z.hour >= 17)
    return {
        "stunden": round(stunden, 1),
        "moeglich_stunden": round(moeglich, 1),
        "anteil_prozent": round(100 * stunden / moeglich, 1) if moeglich else None,
        "erste_sonne": lang[0]["von"] if lang else None,
        "letzte_sonne": lang[-1]["bis"] if lang else None,
        "abendsonne_stunden": round(abend * SCHRITT_MINUTEN / 60, 1),
        "fenster": lang,
        "kurze_fenster_minuten": kurz_minuten,
    }


def auswerten(
    lat: float, lon: float, elemente: list[dict[str, Any]], jahr: int
) -> dict[str, Any]:
    horizont, mit_hoehe, ohne_hoehe = _horizont(lat, lon, elemente)
    tage = {}
    for schluessel, monat, tag, beschriftung in STICHTAGE:
        d = dt.date(jahr, monat, tag)
        tage[schluessel] = {"beschriftung": beschriftung,
                          "datum": d.strftime("%d.%m.%Y"),
                          **_tageslauf(lat, lon, horizont, d)}

    gesamt = mit_hoehe + ohne_hoehe
    abdeckung = round(100 * mit_hoehe / gesamt, 0) if gesamt else None
    # Höchstes Hindernis und seine Richtung — erklärt das Ergebnis.
    hoechstes = max(horizont, key=lambda x: x[1]) if horizont else (0.0, 0.0)
    return {
        "umkreis_m": UMKREIS_M,
        "jahr": jahr,
        "tage": tage,
        "gebaeude_gesamt": gesamt,
        "gebaeude_mit_hoehe": mit_hoehe,
        "gebaeude_ohne_hoehe": ohne_hoehe,
        "hoehen_abdeckung_prozent": abdeckung,
        "hoechstes_hindernis_grad": round(hoechstes[1], 1),
        "hoechstes_hindernis_richtung": _richtung(hoechstes[0]),
        "hinweise": HINWEISE,
    }


def _richtung(azimut: float) -> str:
    namen = ["N", "NO", "O", "SO", "S", "SW", "W", "NW"]
    return namen[int((azimut + 22.5) // 45) % 8]


async def load(
    out: Outbound, settings: Settings, lat: float, lon: float, jahr: int,
) -> SourceResult:
    """Besonnung am Punkt. Rein rechnerisch — nur die Gebäude kommen aus OSM."""
    antwort = None
    letzter_fehler = None
    for endpunkt in settings.overpass_endpoints:
        try:
            antwort = await out.post_json(
                "overpass_gebaeude", endpunkt,
                data={"data": _overpass_abfrage(lat, lon, UMKREIS_M)},
                timeout=settings.overpass_timeout,
                limiter="overpass",
                min_interval=settings.overpass_min_interval,
            )
            break
        except SourceError as err:
            letzter_fehler = err
    if antwort is None:
        raise letzter_fehler or SourceError(
            "network", "Kein Overpass-Endpunkt erreichbar.")

    elemente = antwort.get("elements") or []
    daten = auswerten(lat, lon, elemente, jahr)
    warnungen: list[str] = []
    if not daten["gebaeude_gesamt"]:
        warnungen.append(
            "Im Umkreis sind in OpenStreetMap keine Gebäude erfasst — die "
            "Rechnung zeigt dann die freie Horizontlage ohne Bebauung.")
    elif (daten["hoehen_abdeckung_prozent"] or 0) < 50:
        warnungen.append(
            f"Nur {daten['hoehen_abdeckung_prozent']:.0f} % der "
            f"{daten['gebaeude_gesamt']} Gebäude im Umkreis haben eine "
            "Höhenangabe in OpenStreetMap. Die Sonnenzeiten sind dadurch "
            "deutlich zu optimistisch — vor Ort gegenprüfen.")
    return SourceResult(
        name="sonne", ok=True, data=daten, warnings=warnungen,
        provenance=Provenance(
            source="Sonnenstandsberechnung über OSM-Gebäudehöhen",
            license=LICENSE,
            stand=f"Gebäudestand OSM heute · Stichtage {jahr}",
            retrieved_at=now_iso(),
            note=("Sonnenstand nach dem Astronomical Almanac; Schattenwurf "
                  "aus Grundriss und Höhe der Nachbargebäude im "
                  f"{UMKREIS_M}-m-Umkreis."),
        ),
    )
