"""Stadt-Adapter Wien — Open Government Data der Stadt Wien (WFS).

Wien stellt seine Geodaten über einen GeoServer bereit
(``https://data.wien.gv.at/daten/geo``, Typen ``ogdwien:*``), Lizenz
Creative Commons Namensnennung 4.0 („Datenquelle: Stadt Wien –
data.wien.gv.at“). Vier Themen, die das Werkzeug für München, Hamburg
und Berlin schon kennt, am 18.09.2026 live abgefragt (fixtures/at,
AT-Probe Runde 1 und 2):

=========================  =================================================
Märkte                     ``MAERKTEOGD`` — 23 Punkte stadtweit mit ``NAME``,
                           ``MARKTKATEGORIE`` (Lebensmittel und Waren aller
                           Art, Flohmarkt, Kunst- und Antiquitätenmarkt) und
                           ``URL_MARKTAMT``. **Keine Öffnungszeiten** im
                           Datensatz — ehrlich benannt, wie in Hamburg.
Baustellen                 ``BAUSTELLENPKTOGD`` (Punkte) und
                           ``BAUSTELLENLINOGD`` (Linien) — ``BEZEICHNUNG``,
                           ``BEHINDERUNGSART`` (Straßenbau, Kanalbau,
                           U-Bahnbau …), ``PRESSETEXT``, ``OBJEKT_BEGINN``/
                           ``OBJEKT_ENDE`` (``2026-07-27Z``), ``ANTRAGSTELLER``.
                           Um den Stephansplatz: 12 Punkte, 31 Linien.
Schutzzonen                ``SCHUTZZONEOGD`` — 292 Polygone stadtweit, nur
                           ``SLANG`` (Bezirk, etwa „20. Brigittenau“).
                           Gegenstück zur Erhaltungssatzung (§ 7 BO für Wien).
Flächenwidmung             ``GENFLWIDMUNGOGD`` (generalisierte Widmung) —
                           ``WIDMUNGSKLASSE`` (``GB``), ``WIDMUNGSKLASSE_TXT``
                           („Gemischtes Baugebiet“), ``WIDMUNG`` (``GB3``),
                           ``WIDMUNG_TXT`` („… Bauklasse 3“), ``BEZIRK``,
                           ``BEFRISTUNG_DATUM``, ``SO_BAULICH_NUTZ``.
                           Punktgenau — was Deutschland nur in Hamburg und
                           Freiburg kann.
=========================  =================================================

Abfrageform (live belegt): ``service=WFS&request=GetFeature&version=1.1.0
&typeName=ogdwien:<TYP>&srsName=EPSG:4326&outputFormat=json
&bbox=<west>,<süd>,<ost>,<nord>,EPSG:4326``; die Antwort ist GeoJSON mit
lon,lat-Reihenfolge. Die Blockformen entsprechen den Münchner Adaptern.
"""

from __future__ import annotations

import math
import re
import time
from datetime import date
from typing import Any

from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, bearing_label, haversine_m, now_iso

WFS_URL = "https://data.wien.gv.at/daten/geo"
LIZENZ = "Creative Commons Namensnennung 4.0 (CC BY 4.0) · Datenquelle: Stadt Wien – data.wien.gv.at"
ROHDATEN = "https://www.data.gv.at/katalog/dataset/?q=stadt-wien"

# Großzügiger Kasten um das Stadtgebiet (Süd, West, Nord, Ost). Nur
# innerhalb wird angefragt — außerhalb gäbe „0 Treffer" falsche Entwarnung.
STADT_BBOX = (48.11, 16.18, 48.33, 16.58)

MAX_MARKT_DISTANZ_M = 2000
MAX_LISTE = 40
# Kasten für Punkt-in-Fläche-Abfragen (Schutzzone, Widmung): rund 50 m.
PUNKT_BOX = 0.0005


def in_wien(lat: float, lon: float) -> bool:
    s, w, n, o = STADT_BBOX
    return s <= lat <= n and w <= lon <= o


def _bbox_um(lat: float, lon: float, radius_m: float) -> str:
    rand = radius_m + 250
    dlat = rand / 111_320.0
    dlon = rand / (111_320.0 * max(0.2, math.cos(math.radians(lat))))
    return f"{lon - dlon:.6f},{lat - dlat:.6f},{lon + dlon:.6f},{lat + dlat:.6f},EPSG:4326"


def _punkt_box(lat: float, lon: float) -> str:
    return (f"{lon - PUNKT_BOX:.6f},{lat - PUNKT_BOX:.6f},"
            f"{lon + PUNKT_BOX:.6f},{lat + PUNKT_BOX:.6f},EPSG:4326")


async def _features(out: Outbound, quelle: str, typ: str, bbox: str | None = None,
                    max_features: int | None = None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "service": "WFS", "request": "GetFeature", "version": "1.1.0",
        "typeName": f"ogdwien:{typ}", "srsName": "EPSG:4326", "outputFormat": "json",
    }
    if bbox:
        params["bbox"] = bbox
    if max_features:
        params["maxFeatures"] = max_features
    payload = await out.get_json(quelle, WFS_URL, params=params, timeout=45.0,
                                 limiter="wien", min_interval=0.5)
    return payload.get("features") or [] if isinstance(payload, dict) else []


def _punkt(f: dict[str, Any]) -> tuple[float, float] | None:
    g = f.get("geometry") or {}
    c = g.get("coordinates") or []
    if g.get("type") == "Point" and len(c) >= 2:
        return float(c[1]), float(c[0])
    return None


def _linie(f: dict[str, Any]) -> list[tuple[float, float]]:
    g = f.get("geometry") or {}
    if g.get("type") == "LineString":
        return [(float(p[1]), float(p[0])) for p in g.get("coordinates") or [] if len(p) >= 2]
    if g.get("type") == "MultiLineString":
        return [(float(p[1]), float(p[0])) for teil in g.get("coordinates") or []
                for p in teil if len(p) >= 2]
    return []


def _datum(v: Any) -> date | None:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(v or ""))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


# ------------------------------------------------------------------ Märkte

MARKT_HINWEISE = [
    "Ein Markt bringt Frequenz **an seinen Markttagen**. Der Wiener "
    "Datensatz führt — wie der Hamburger — keine Öffnungszeiten; die "
    "Markttage stehen auf der verlinkten Seite des Marktamts (MA 59).",
    "„Lebensmittel und Waren aller Art“ sind die ständigen Detailmärkte "
    "(Naschmarkt, Brunnenmarkt, Karmelitermarkt …), Flohmärkte laufen "
    "meist samstags.",
]


def maerkte_aufbereiten(features: list[dict[str, Any]], lat: float, lon: float,
                        radius: int) -> dict[str, Any]:
    maerkte: list[dict[str, Any]] = []
    for f in features:
        pkt = _punkt(f)
        if pkt is None:
            continue
        p = f.get("properties") or {}
        dist = haversine_m(lat, lon, *pkt)
        maerkte.append({
            "name": p.get("NAME") or "(ohne Namen)",
            "rubrik": p.get("MARKTKATEGORIE") or "Markt",
            "oeffnungszeiten": None,
            "adresse": None,
            "link": p.get("URL_MARKTAMT") or None,
            "lat": pkt[0], "lon": pkt[1],
            "distanz_m": round(dist),
            "richtung": bearing_label(lat, lon, *pkt),
            "im_radius": dist <= radius,
        })
    maerkte.sort(key=lambda m: m["distanz_m"])
    nah = [m for m in maerkte if m["distanz_m"] <= MAX_MARKT_DISTANZ_M]
    nach_rubrik: dict[str, int] = {}
    for m in nah:
        nach_rubrik[m["rubrik"]] = nach_rubrik.get(m["rubrik"], 0) + 1
    return {
        "stadtweit": len(maerkte), "in_reichweite": nah,
        "im_radius": sum(1 for m in maerkte if m["im_radius"]),
        "naechster": nah[0] if nah else None,
        "nach_rubrik": nach_rubrik, "max_distanz_m": MAX_MARKT_DISTANZ_M,
        "rohdaten": f"{WFS_URL}?service=WFS&request=GetCapabilities",
        "stadt": "Wien",
    }


async def maerkte_load(out: Outbound, lat: float, lon: float, radius: int) -> SourceResult:
    started = time.perf_counter()
    try:
        features = await _features(out, "wien_maerkte", "MAERKTEOGD")
    except SourceError as err:
        return SourceResult.failed("maerkte", err, int((time.perf_counter() - started) * 1000))
    data = maerkte_aufbereiten(features, lat, lon, radius)
    data["hinweise"] = MARKT_HINWEISE
    warnungen = [] if data["in_reichweite"] else [
        f"Kein Wiener Markt innerhalb von {MAX_MARKT_DISTANZ_M} m."]
    return SourceResult(
        name="maerkte", ok=True, data=data,
        duration_ms=int((time.perf_counter() - started) * 1000), warnings=warnungen,
        provenance=Provenance(
            source="Märkte der Stadt Wien (Marktamt MA 59, WFS data.wien.gv.at)",
            license=LIZENZ, endpoint=WFS_URL, stand="laufend gepflegte Stadtliste",
            retrieved_at=now_iso(),
            note=f"{data['stadtweit']} Märkte stadtweit mit Kategorie und Link; "
                 "ohne Öffnungszeiten. Nur Stadtgebiet Wien."),
    )


# -------------------------------------------------------------- Baustellen

BAUSTELLEN_HINWEISE = [
    "Der Wiener Datensatz führt die **angemeldeten Baustellen** mit "
    "Behinderungsart, Zeitraum und Pressetext — laufende und bereits "
    "terminierte. Was später beginnt, steht noch nicht drin.",
    "Linienbaustellen (Straßen-, Kanal- und U-Bahnbau) sind über ihren "
    "nächsten Stützpunkt eingeordnet; 0 m heißt: der Punkt liegt am "
    "Baustellenabschnitt.",
    "Ob der Gehsteig betroffen ist, steht nur im Pressetext — hier grob "
    "aus dem Text gelesen, im Zweifel den Text selbst lesen.",
]

_GEHWEG = re.compile(r"(gehsteig|gehweg|fußgänger)[^.]{0,80}(gesperrt|sperre|umgeleitet|verlegt)", re.I)


def baustellen_aufbereiten(features: list[dict[str, Any]], lat: float, lon: float,
                           radius: int, heute: date) -> dict[str, Any]:
    eintraege: list[dict[str, Any]] = []
    for f in features:
        p = f.get("properties") or {}
        pkt = _punkt(f)
        linie = _linie(f) if pkt is None else []
        if pkt is None and not linie:
            continue
        ende = _datum(p.get("OBJEKT_ENDE"))
        if ende is not None and ende < heute:
            continue
        if pkt is not None:
            dist, naechst = haversine_m(lat, lon, *pkt), pkt
        else:
            dist, naechst = min((haversine_m(lat, lon, *q), q) for q in linie)
        if dist > radius:
            continue
        beginn = _datum(p.get("OBJEKT_BEGINN"))
        text = re.sub(r"\s+", " ", str(p.get("PRESSETEXT") or "")).strip() or None
        beschreibung = text[:237] + "…" if text and len(text) > 240 else text
        eintraege.append({
            "ort": p.get("BEZEICHNUNG") or "(ohne Ortsangabe)",
            "art": p.get("BEHINDERUNGSART") or "Baustelle",
            "status": "geplant" if beginn is not None and beginn > heute else "laufend",
            "beginn": str(p.get("OBJEKT_BEGINN") or "")[:10] or None,
            "ende": str(p.get("OBJEKT_ENDE") or "")[:10] or None,
            "distanz_m": round(dist),
            "richtung": bearing_label(lat, lon, *naechst) if dist > 0 else None,
            "gehweg_betroffen": bool(text and _GEHWEG.search(text)),
            "mit_sperrung": "sperr" in (text or "").lower(),
            "beeintraechtigung": p.get("BEHINDERUNGSART") or None,
            "betroffene_bereiche": (f"Bezirk {p.get('BEZIRK')}" if p.get("BEZIRK") else None),
            "beschreibung": beschreibung,
            "link": None,
            "antragsteller": p.get("ANTRAGSTELLER"),
            "lat": naechst[0], "lon": naechst[1],
            "umriss": None,
            "linie": [[q[0], q[1]] for q in linie] or None,
        })
    eintraege.sort(key=lambda e: (0 if e["status"] == "laufend" else 1, e["distanz_m"]))
    gesamt = len(eintraege)
    return {
        "gesamt": gesamt,
        # Alle Wiener Einträge sind Baumaßnahmen — Haltverbote führt die
        # Stadt nicht in diesem Datensatz.
        "baumassnahmen": gesamt, "haltverbote": 0,
        "laufend": sum(1 for e in eintraege if e["status"] == "laufend"),
        "geplant": sum(1 for e in eintraege if e["status"] == "geplant"),
        "gehweg_betroffen": sum(1 for e in eintraege if e["gehweg_betroffen"]),
        "liste": eintraege[:MAX_LISTE], "gekappt": gesamt > MAX_LISTE,
        "radius_m": radius, "stichtag": heute.isoformat(),
        "rohdaten": f"{WFS_URL}?service=WFS&request=GetCapabilities",
        "stadt": "Wien",
    }


async def baustellen_load(out: Outbound, lat: float, lon: float, radius: int,
                          heute: date | None = None) -> SourceResult:
    started = time.perf_counter()
    bbox = _bbox_um(lat, lon, radius)
    features: list[dict[str, Any]] = []
    fehler: list[str] = []
    for typ in ("BAUSTELLENPKTOGD", "BAUSTELLENLINOGD"):
        try:
            features += await _features(out, "wien_baustellen", typ, bbox)
        except SourceError as err:
            fehler.append(f"{typ}: {err.message}")
    if len(fehler) == 2:
        return SourceResult.failed(
            "baustellen", SourceError("api_error", "Baustellen-WFS der Stadt Wien: " + fehler[0]),
            int((time.perf_counter() - started) * 1000))
    data = baustellen_aufbereiten(features, lat, lon, radius, heute or date.today())
    data["hinweise"] = BAUSTELLEN_HINWEISE
    warnungen = list(fehler)
    if data["gekappt"]:
        warnungen.append(f"{data['gesamt']} Baustellen im Radius — die Liste zeigt die "
                         f"{MAX_LISTE} nächsten, die Zählwerte umfassen alle.")
    return SourceResult(
        name="baustellen", ok=True, data=data,
        duration_ms=int((time.perf_counter() - started) * 1000), warnings=warnungen,
        provenance=Provenance(
            source="Baustellen der Stadt Wien (MA 28/MA 46, WFS data.wien.gv.at)",
            license=LIZENZ, endpoint=WFS_URL, stand="laufend gepflegt",
            retrieved_at=now_iso(),
            note="Punkt- und Linienbaustellen mit Behinderungsart, Zeitraum und Pressetext. "
                 "Nur Stadtgebiet Wien."),
    )


# -------------------------------------------------------------- Schutzzonen

def _enthaelt(f: dict[str, Any], lat: float, lon: float) -> bool:
    from .baurecht import enthaelt_punkt

    return enthaelt_punkt(f.get("geometry"), lat, lon)


def schutzzonen_aufbereiten(features: list[dict[str, Any]], lat: float, lon: float) -> dict[str, Any]:
    gebiete = []
    for f in features:
        if not _enthaelt(f, lat, lon):
            continue
        p = f.get("properties") or {}
        gebiete.append({
            "name": (f"Schutzzone {p.get('SLANG')}" if p.get("SLANG") else "Schutzzone"),
            "gueltig_ab": None, "plan_pdf": None, "text_pdf": None,
            "info_pdf": "https://www.wien.gv.at/flaechenwidmung/public/",
            "rohwerte": {k: v for k, v in p.items() if v not in (None, "")},
        })
    return {"betroffen": bool(gebiete), "gebiete": gebiete,
            "titel": "Schutzzone (§ 7 Bauordnung für Wien)"}


async def schutzzonen(out: Outbound, lat: float, lon: float) -> dict[str, Any]:
    """Punktabfrage der Schutzzonen — für den Planungsrecht-Block."""
    features = await _features(out, "wien_schutzzonen", "SCHUTZZONEOGD", _punkt_box(lat, lon), 20)
    return schutzzonen_aufbereiten(features, lat, lon)


# ------------------------------------------------------- Flächenwidmung

# Widmungsklasse (Bauordnung für Wien §§ 4–6) → Gastronomie-Einordnung.
WIDMUNG_DEUTUNG: dict[str, str] = {
    "W": ("Wohngebiet (§ 6 Abs. 6 BO für Wien): Gastgewerbe ist zulässig, soweit "
          "es keine das ortsübliche Ausmaß übersteigende Belästigung (Lärm, Geruch) "
          "verursacht — Schanigarten und Nachtbetrieb sind der Prüfpunkt."),
    "GB": ("Gemischtes Baugebiet (§ 6 Abs. 8): Wohn- und Betriebsgebäude nebeneinander — "
           "Gastronomie ist hier regelmäßig zulässig."),
    "GBGV": ("Geschäftsviertel im gemischten Baugebiet (§ 6 Abs. 9): der klassische "
             "Gastronomie- und Handelsstandort."),
    "GBBG": ("Betriebsbaugebiet (§ 6 Abs. 10): Betriebe, Wohnungen nur betriebsbezogen — "
             "Gastronomie zulässig, Laufkundschaft aus dem Wohnumfeld fehlt."),
    "IG": ("Industriegebiet (§ 6 Abs. 12): Gastronomie nur als betriebsbezogene "
           "Einrichtung (Kantine, Betriebsrestaurant)."),
    "GBSO": "Sondergebiet: Nutzung steht im Plandokument — Einordnung nur darüber.",
    "Epk": "Erholungsgebiet – Parkanlage (§ 6 Abs. 2): keine Gastronomie ohne ausdrückliche Widmung.",
    "Esp": "Erholungsgebiet – Sport- und Spielplätze: Gastronomie nur als Nebenanlage (Vereinsheim).",
    "Ekl": "Erholungsgebiet – Kleingartengebiet: keine Gastronomie.",
    "Eklw": "Kleingartengebiet für ganzjähriges Wohnen: keine Gastronomie.",
    "Sww": "Schutzgebiet Wald- und Wiesengürtel: keine Gastronomie außer bestehender Betriebe.",
    "L": "Ländliches Gebiet (§ 6 Abs. 4): Gast- und Beherbergungsbetriebe zulässig.",
    "Str": "Verkehrsfläche (Straße): keine Bebauung möglich.",
    "Vb": "Verkehrsband: keine Bebauung möglich.",
}


def widmung_deuten(klasse: str | None, klasse_text: str | None) -> dict[str, Any] | None:
    if not klasse and not klasse_text:
        return None
    text = WIDMUNG_DEUTUNG.get(str(klasse or ""))
    return {"art": klasse_text or klasse, "kuerzel": klasse,
            "gastronomie": text or "Einordnung nur über das Plandokument (BO für Wien §§ 4–6)."}


def widmung_aufbereiten(features: list[dict[str, Any]], lat: float, lon: float) -> list[dict[str, Any]]:
    """Widmungsflächen, die den Punkt enthalten, in der Baugebiets-Form des
    Baurecht-Blocks."""
    flaechen = []
    gesehen = set()
    for f in features:
        if not _enthaelt(f, lat, lon):
            continue
        p = f.get("properties") or {}
        schluessel = (p.get("WIDMUNG"), p.get("BEZIRK"))
        if schluessel in gesehen:
            continue
        gesehen.add(schluessel)
        zusatz = [t for t in (
            p.get("WIDMUNG_DETAIL"), p.get("SO_BAULICH_NUTZ"),
            f"befristet bis {str(p['BEFRISTUNG_DATUM'])[:10]}" if p.get("BEFRISTUNG_DATUM") else None,
        ) if t]
        flaechen.append({
            "plan": (f"Flächenwidmungs- und Bebauungsplan Wien, {p.get('BEZIRK')}. Bezirk"
                     if p.get("BEZIRK") else "Flächenwidmungs- und Bebauungsplan Wien"),
            "art": p.get("WIDMUNG_TXT") or p.get("WIDMUNGSKLASSE_TXT"),
            "deutung": widmung_deuten(p.get("WIDMUNGSKLASSE"), p.get("WIDMUNGSKLASSE_TXT")),
            "allgemeine_art": p.get("WIDMUNGSKLASSE_TXT"),
            "rechtsstand": "rechtskräftig (generalisierte Widmung)",
            "aufschrift": p.get("WIDMUNG"),
            "grz": None, "gfz": None,
            "text": "; ".join(zusatz) or None,
        })
    return flaechen


async def baurecht_load(out: Outbound, lat: float, lon: float) -> SourceResult:
    """Baurecht-Block für Wien: Widmung am Punkt (Blockform von ``baurecht.py``)."""
    from .baurecht import HINWEISE as BAURECHT_HINWEISE

    started = time.perf_counter()
    daten: dict[str, Any] = {
        "stufe": None, "gebiet": "Wien", "baugebiete": [], "plaene": [],
        "sanierungsgebiete": [], "denkmale": [], "paragraf_34": False,
        "hinweise": BAURECHT_HINWEISE[:1] + [
            "Die **Widmungsklasse** kommt aus der generalisierten Flächenwidmung der "
            "Stadt Wien; Bauklasse und Detailwidmung stehen im Plandokument. Was im "
            "Einzelfall zulässig ist, entscheidet die Baubehörde (MA 37).",
            "**Sperrstunde** und Schanigarten-Genehmigung sind Landes- bzw. Bezirksrecht "
            "(Wiener Sperrzeitenverordnung, Gebrauchsabgabe) — nicht in offenen Daten."],
    }
    try:
        features = await _features(out, "wien_widmung", "GENFLWIDMUNGOGD", _punkt_box(lat, lon), 20)
    except SourceError as err:
        return SourceResult.failed("baurecht", err, int((time.perf_counter() - started) * 1000))
    daten["baugebiete"] = widmung_aufbereiten(features, lat, lon)
    warnungen: list[str] = []
    if daten["baugebiete"]:
        daten["stufe"] = "gebietsart"
    else:
        daten["stufe"] = "kein_plan"
        warnungen.append("Am Punkt weist die generalisierte Flächenwidmung keine Baulandwidmung "
                         "aus (Verkehrsfläche, Grünland oder Lücke im Datensatz) — das "
                         "Plandokument im Stadtplan gibt Auskunft.")
    return SourceResult(
        name="baurecht", ok=True, data=daten,
        duration_ms=int((time.perf_counter() - started) * 1000), warnings=warnungen,
        provenance=Provenance(
            source="Flächenwidmung Wien (generalisiert, MA 21, WFS data.wien.gv.at)",
            license=LIZENZ, endpoint=WFS_URL, stand="laufend fortgeschrieben",
            retrieved_at=now_iso(),
            note="Punktabfrage über WFS mit Punkt-in-Fläche-Prüfung; ersetzt keine Bauanfrage."),
    )
