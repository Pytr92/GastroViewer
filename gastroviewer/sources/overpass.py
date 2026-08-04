"""OpenStreetMap über Overpass.

Eine einzige kombinierte Abfrage je Punkt statt einer pro Kategorie — Overpass ist
ein Spendenprojekt (Spec §4.2). Gemessen für r=600 in der Münchner Innenstadt:
843 Elemente inklusive der Linienrelationen (801 vor der Erweiterung der
Frequenzbringer um Märkte, Behörden und Alltagsversorger).

Phase-0-Befunde, die den Code prägen:

* ``out center tags`` liefert für Ways und POI-Relationen ein ``center``-Objekt
  statt ``lat``/``lon``. Beides muss behandelt werden.
* Die als Risiko markierte Rekursion ``rel(bn.sp)["type"="route"]`` funktioniert.
  Routenrelationen kommen ohne ``center`` und sind daran erkennbar.
* ``timestamp_osm_base`` aus der Antwort ist der Datenstand für die UI-Fußzeile —
  keine Konstante im Code.
"""

from __future__ import annotations

import time
from typing import Any

from ..config import Settings
from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, bearing_label, haversine_m, now_iso

LICENSE = "© OpenStreetMap-Mitwirkende · ODbL 1.0"

GASTRO_AMENITIES = [
    "fast_food",
    "restaurant",
    "cafe",
    "bar",
    "pub",
    "ice_cream",
    "biergarten",
    "food_court",
]

GASTRO_LABELS = {
    "fast_food": "Schnellrestaurant",
    "restaurant": "Restaurant",
    "cafe": "Café",
    "bar": "Bar",
    "pub": "Kneipe",
    "ice_cream": "Eisdiele",
    "biergarten": "Biergarten",
    "food_court": "Food-Court",
}

# Frequenzbringer nach Kategorie.
#
# Die mit ★ markierten Einträge stehen nicht in der Liste aus §4.2, sind für
# einen Schnellgastronomie-Standort aber ebenso relevant: Märkte, Busbahnhöfe
# und Tankstellen erzeugen Laufkundschaft, Behörden und Alltagsversorger
# bringen wiederkehrende Wege. Gemessen am Sendlinger Tor waren das 46 Objekte
# im 600-m-Umkreis, die das Werkzeug vorher nicht gesehen hat.
FREQ_AMENITIES = {
    "school": ("Bildung", "Schule"),
    "university": ("Bildung", "Universität"),
    "college": ("Bildung", "Hochschule"),
    "kindergarten": ("Bildung", "Kindergarten"),
    "hospital": ("Gesundheit", "Krankenhaus"),
    "clinic": ("Gesundheit", "Klinik"),
    "doctors": ("Gesundheit", "Arztpraxis"),
    "pharmacy": ("Gesundheit", "Apotheke"),                      # ★
    "cinema": ("Kultur & Freizeit", "Kino"),
    "theatre": ("Kultur & Freizeit", "Theater"),
    "library": ("Kultur & Freizeit", "Bibliothek"),
    "community_centre": ("Kultur & Freizeit", "Bürgerhaus"),     # ★
    "parking": ("Verkehr & Parken", "Parkplatz"),
    "bus_station": ("Verkehr & Parken", "Busbahnhof"),           # ★
    "fuel": ("Verkehr & Parken", "Tankstelle"),                  # ★
    "marketplace": ("Markt & Alltagsversorgung", "Marktplatz"),  # ★
    "bank": ("Markt & Alltagsversorgung", "Bank"),               # ★
    "post_office": ("Markt & Alltagsversorgung", "Post"),        # ★
    "townhall": ("Behörden", "Rathaus"),                         # ★
    "courthouse": ("Behörden", "Gericht"),                       # ★
}
FREQ_SHOPS = {
    "supermarket": ("Einkauf", "Supermarkt"),
    "mall": ("Einkauf", "Einkaufszentrum"),
    "department_store": ("Einkauf", "Kaufhaus"),
    "convenience": ("Einkauf", "Nahversorger"),
    "bakery": ("Einkauf", "Bäckerei"),
    "butcher": ("Einkauf", "Metzgerei"),
    "kiosk": ("Markt & Alltagsversorgung", "Kiosk"),             # ★
    "greengrocer": ("Markt & Alltagsversorgung", "Obst & Gemüse"),  # ★
    "deli": ("Markt & Alltagsversorgung", "Feinkost"),           # ★
    "beverages": ("Markt & Alltagsversorgung", "Getränkemarkt"), # ★
}
FREQ_LEISURE = {
    "fitness_centre": ("Sport", "Fitnessstudio"),
    "sports_centre": ("Sport", "Sportzentrum"),
    "stadium": ("Sport", "Stadion"),
    "swimming_pool": ("Sport", "Schwimmbad"),
}
FREQ_TOURISM = {
    "hotel": ("Übernachtung & Tourismus", "Hotel"),
    "hostel": ("Übernachtung & Tourismus", "Hostel"),
    "museum": ("Übernachtung & Tourismus", "Museum"),
    "attraction": ("Übernachtung & Tourismus", "Sehenswürdigkeit"),
}

TRANSPORT_LABELS = {
    "bus_stop": "Bushaltestelle",
    "station": "Bahnhof / Station",
    "tram_stop": "Tramhaltestelle",
    "halt": "Haltepunkt",
}

GASTRO_TAGS = [
    "name",
    "cuisine",
    "brand",
    "operator",
    "opening_hours",
    "takeaway",
    "delivery",
    "outdoor_seating",
    "drive_through",
    "wheelchair",
]


def build_query(lat: float, lon: float, radius: int, timeout: int = 90) -> str:
    a = f"(around:{radius},{lat},{lon})"
    gastro = "|".join(GASTRO_AMENITIES)
    freq_am = "|".join(FREQ_AMENITIES)
    shops = "|".join(list(FREQ_SHOPS) + ["vacant"])
    leisure = "|".join(FREQ_LEISURE)
    tourism = "|".join(FREQ_TOURISM)
    return f"""[out:json][timeout:{timeout}];
(
  nwr["amenity"~"^({gastro})$"]{a};
  nwr["amenity"~"^({freq_am})$"]{a};
  nwr["shop"~"^({shops})$"]{a};
  nwr["leisure"~"^({leisure})$"]{a};
  nwr["office"]{a};
  nwr["building"="office"]{a};
  nwr["tourism"~"^({tourism})$"]{a};
  nwr["highway"="bus_stop"]{a};
  nwr["railway"~"^(station|tram_stop|halt)$"]{a};
  nwr["public_transport"="station"]{a};
  nwr["disused:shop"]{a};
  nwr["disused:amenity"]{a};
)->.poi;
.poi out center tags;
node["public_transport"~"^(platform|stop_position)$"]{a}->.sp;
rel(bn.sp)["type"="route"]->.rt;
.rt out tags;
"""


def element_coords(el: dict[str, Any]) -> tuple[float, float] | None:
    if "lat" in el and "lon" in el:
        return float(el["lat"]), float(el["lon"])
    center = el.get("center")
    if isinstance(center, dict) and "lat" in center:
        return float(center["lat"]), float(center["lon"])
    return None


def osm_url(el: dict[str, Any]) -> str:
    return f"https://www.openstreetmap.org/{el.get('type')}/{el.get('id')}"


async def run_query(
    out: Outbound, settings: Settings, query: str
) -> tuple[dict[str, Any], str, list[str]]:
    """Reihum über die konfigurierten Endpunkte. Gibt Antwort, benutzten Endpunkt
    und die Fehler der übersprungenen Spiegel zurück — die gehören in die UI,
    damit „langsam" nicht mit „kaputt" verwechselt wird."""
    problems: list[str] = []
    last: SourceError | None = None
    for endpoint in settings.overpass_endpoints:
        try:
            payload = await out.post_json(
                "overpass",
                endpoint,
                data={"data": query},
                timeout=settings.overpass_timeout,
                limiter="overpass",
                min_interval=settings.overpass_min_interval,
            )
            if isinstance(payload, dict) and "remark" in payload and not payload.get("elements"):
                raise SourceError(
                    "api_error",
                    f"Overpass meldet: {payload['remark']}",
                    detail=endpoint,
                )
            return payload, endpoint, problems
        except SourceError as err:
            problems.append(f"{endpoint}: {err.message}")
            last = err
    raise last or SourceError("connect", "Kein Overpass-Endpunkt erreichbar.")


def _service_tags(tags: dict[str, str]) -> dict[str, str]:
    return {k: tags[k] for k in GASTRO_TAGS if k in tags}


def classify(
    elements: list[dict[str, Any]], lat: float, lon: float, radius: int
) -> dict[str, Any]:
    gastro: list[dict[str, Any]] = []
    frequenz: list[dict[str, Any]] = []
    oepnv: list[dict[str, Any]] = []
    leerstand: list[dict[str, Any]] = []
    routen: list[dict[str, Any]] = []

    for el in elements:
        tags = el.get("tags") or {}
        if el.get("type") == "relation" and tags.get("type") == "route":
            routen.append(
                {
                    "id": el.get("id"),
                    "route": tags.get("route"),
                    "ref": tags.get("ref"),
                    "name": tags.get("name"),
                    "from": tags.get("from"),
                    "to": tags.get("to"),
                    "network": tags.get("network:short") or tags.get("network"),
                    "colour": tags.get("colour"),
                    "gtfs_route_id": tags.get("gtfs:route_id"),
                    "osm_url": osm_url(el),
                }
            )
            continue

        coords = element_coords(el)
        if coords is None:
            continue
        elat, elon = coords
        dist = haversine_m(lat, lon, elat, elon)
        # Overpass prüft `around:` gegen die **Geometrie**, wir messen zum
        # Mittelpunkt. Ein Campus oder Klinikgelände kann in den Umkreis
        # hineinreichen, während sein Flächenmittelpunkt Kilometer entfernt liegt
        # (gemessen: LMU München, 5.798 m bei r=600). Solche Objekte werden nicht
        # verworfen — sie sind echte Frequenzbringer —, aber gekennzeichnet, damit
        # die Distanzangabe nicht wie ein Datenfehler aussieht.
        ausserhalb = dist > radius
        base = {
            "id": el.get("id"),
            "osm_type": el.get("type"),
            "name": tags.get("name"),
            "lat": round(elat, 7),
            "lon": round(elon, 7),
            "distanz_m": round(dist),
            "richtung": bearing_label(lat, lon, elat, elon),
            "mittelpunkt_ausserhalb": ausserhalb,
            "distanz_hinweis": (
                "Fläche reicht in den Umkreis hinein; angegeben ist die Entfernung "
                "zum Mittelpunkt der Gesamtfläche."
                if ausserhalb
                else None
            ),
            "osm_url": osm_url(el),
        }

        amenity = tags.get("amenity")
        shop = tags.get("shop")
        leisure = tags.get("leisure")
        tourism = tags.get("tourism")
        office = tags.get("office")
        highway = tags.get("highway")
        railway = tags.get("railway")
        ptrans = tags.get("public_transport")

        # Leerstand zuerst — sonst landet shop=vacant im Einkaufsblock.
        if "disused:shop" in tags or "disused:amenity" in tags or shop == "vacant":
            leerstand.append(
                {
                    **base,
                    "art": (
                        "shop=vacant"
                        if shop == "vacant"
                        else ("disused:shop" if "disused:shop" in tags else "disused:amenity")
                    ),
                    "frueher": tags.get("disused:shop") or tags.get("disused:amenity"),
                }
            )
            continue

        if amenity in GASTRO_AMENITIES:
            brand = tags.get("brand") or tags.get("operator")
            gastro.append(
                {
                    **base,
                    "typ": amenity,
                    "typ_label": GASTRO_LABELS.get(amenity, amenity),
                    "kette": bool(tags.get("brand")),
                    "marke": brand,
                    "cuisine": tags.get("cuisine"),
                    "tags": _service_tags(tags),
                }
            )
            continue

        kat: tuple[str, str] | None = None
        if amenity in FREQ_AMENITIES:
            kat = FREQ_AMENITIES[amenity]
        elif shop in FREQ_SHOPS:
            kat = FREQ_SHOPS[shop]
        elif leisure in FREQ_LEISURE:
            kat = FREQ_LEISURE[leisure]
        elif tourism in FREQ_TOURISM:
            kat = FREQ_TOURISM[tourism]
        elif office or tags.get("building") == "office":
            kat = ("Büro & Arbeitsplätze", f"Büro{f' ({office})' if office else ''}")

        if kat:
            frequenz.append({**base, "kategorie": kat[0], "art": kat[1]})
            continue

        if highway == "bus_stop" or railway in TRANSPORT_LABELS or ptrans == "station":
            art = TRANSPORT_LABELS.get(railway or "") or (
                "Bushaltestelle" if highway == "bus_stop" else "Station"
            )
            oepnv.append({**base, "art": art, "netz": tags.get("network")})

    for lst in (gastro, frequenz, oepnv, leerstand):
        lst.sort(key=lambda x: x["distanz_m"])

    return {
        "gastronomie": gastro,
        "frequenzbringer": frequenz,
        "oepnv": oepnv,
        "leerstand": leerstand,
        "linien": routen,
    }


# ------------------------------------------------- Öffnungszeiten-Lücken
#
# Grundsatz: konservativ. Die opening_hours-Syntax kennt Feiertage, Saisons,
# Wochennummern und Sonnenstände — ein Parser, der davon etwas falsch deutet,
# erzeugt falsche Zahlen im Messwert-Kostüm. Deshalb wird eine Angabe nur
# bewertet, wenn sie vollständig aus einfachen Wochentag-Uhrzeit-Regeln
# besteht („Mo-Fr 11:00-22:00; Sa 12:00-23:00", „24/7", „Su off"). Alles
# andere zählt als „nicht auswertbar", und jede Auswertungszahl ist damit
# eine Mindestzahl. Einzige geduldete Sonderregel: „PH off/closed" — sie
# betrifft weder die Sonntags- noch die Abendfrage und wird übersprungen.
#
# Mitternachtsüberhang („Fr-Sa 20:00-04:00") bleibt dem genannten Tag
# zugeordnet: eine Bar, die Samstagnacht bis 4 Uhr offen hat, gilt nicht als
# „sonntags geöffnet" — das entspricht dem alltäglichen Sprachgebrauch und
# steht im Hinweistext.

_OH_TAGE = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
# Ab hier gilt „abends geöffnet": nach 22 Uhr. 22 Uhr ist die Grenze des
# GTFS-Nachtfensters dieses Werkzeugs — dieselbe Grenze, damit sich beide
# Blöcke aufeinander beziehen lassen. Eine gewählte Grenze, kein Messwert.
NACHT_AB_MINUTE = 22 * 60


def _oh_zeitspanne(t: str) -> tuple[int, int] | None:
    import re as _re

    m = _re.fullmatch(r"(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})", t)
    if not m:
        return None
    a = int(m.group(1)) * 60 + int(m.group(2))
    b = int(m.group(3)) * 60 + int(m.group(4))
    if a > 24 * 60 or b > 24 * 60:
        return None
    if b <= a:  # über Mitternacht
        b += 24 * 60
    return (a, b)


def _oh_tage(spec: str) -> set[int] | None:
    tage: set[int] = set()
    for teil in spec.split(","):
        teil = teil.strip()
        if "-" in teil:
            a, _, b = teil.partition("-")
            if a not in _OH_TAGE or b not in _OH_TAGE:
                return None
            i, j = _OH_TAGE.index(a), _OH_TAGE.index(b)
            if i <= j:
                tage.update(range(i, j + 1))
            else:  # Wochenwechsel, z. B. Sa-Mo
                tage.update(range(i, 7))
                tage.update(range(0, j + 1))
        elif teil in _OH_TAGE:
            tage.add(_OH_TAGE.index(teil))
        else:
            return None
    return tage


def bewerte_oeffnungszeiten(oh: Any) -> dict[str, bool] | None:
    """Bewertet eine opening_hours-Angabe — oder lehnt sie ab.

    ``None`` heißt „nicht auswertbar", nie „geschlossen". Rückgabe sonst:
    ``sonntag`` (am Sonntag geöffnet), ``nach22`` (an mindestens einem Tag
    nach 22 Uhr geöffnet), ``immer`` (24/7).
    """
    import re as _re

    if not oh:
        return None
    s = " ".join(str(oh).split())
    if s == "24/7":
        return {"sonntag": True, "nach22": True, "immer": True}

    belegung: dict[int, list[tuple[int, int]]] = {i: [] for i in range(7)}
    for teil in s.split(";"):
        teil = teil.strip()
        if not teil:
            continue
        if _re.fullmatch(r"PH (off|closed)", teil):
            continue
        m = _re.fullmatch(r"(?:([A-Za-z,\- ]+) )?([\d:,\- ]+|off|closed)", teil)
        if not m:
            return None
        tage = (
            _oh_tage(m.group(1).replace(" ", "")) if m.group(1) else set(range(7))
        )
        if tage is None:
            return None
        zeit_spec = m.group(2).strip()
        if zeit_spec in ("off", "closed"):
            for t in tage:
                belegung[t] = []
            continue
        spannen = []
        for z in zeit_spec.replace(" ", "").split(","):
            sp = _oh_zeitspanne(z)
            if sp is None:
                return None
            spannen.append(sp)
        # Spätere Regeln überschreiben frühere für die genannten Tage —
        # das ist die Grundsemantik von opening_hours.
        for t in tage:
            belegung[t] = list(spannen)

    return {
        "sonntag": bool(belegung[6]),
        "nach22": any(b > NACHT_AB_MINUTE for spannen in belegung.values()
                      for _, b in spannen),
        "immer": False,
    }


def oeffnungszeiten_luecken(gastro: list[dict[str, Any]]) -> dict[str, Any]:
    """Sonntags- und Abendlücke im Umfeld — ausschließlich Mindestzahlen."""
    gesamt = len(gastro)
    mit_angabe = auswertbar = sonntag = sonntag_zu = nach22 = rund_um_die_uhr = 0
    for g in gastro:
        oh = (g.get("tags") or {}).get("opening_hours")
        if not oh:
            continue
        mit_angabe += 1
        b = bewerte_oeffnungszeiten(oh)
        if b is None:
            continue
        auswertbar += 1
        if b["sonntag"]:
            sonntag += 1
        else:
            sonntag_zu += 1
        if b["nach22"]:
            nach22 += 1
        if b["immer"]:
            rund_um_die_uhr += 1
    return {
        "gesamt": gesamt,
        "mit_angabe": mit_angabe,
        "auswertbar": auswertbar,
        "sonntag_offen": sonntag,
        "sonntag_geschlossen": sonntag_zu,
        "nach22_offen": nach22,
        "rund_um_die_uhr": rund_um_die_uhr,
        "nacht_ab": "22:00",
        "hinweis": (
            "Nur einfache Wochentag-Uhrzeit-Regeln werden bewertet; Feiertags-, "
            "Saison- und Sonderregeln zählen als nicht auswertbar. Alle Zahlen "
            "sind deshalb Mindestzahlen. Mitternachtsüberhang bleibt dem "
            "genannten Tag zugeordnet — Samstagnacht bis 4 Uhr ist nicht "
            "„sonntags geöffnet“."
        ),
    }


# Entfernungsstufen für die Wettbewerbsdichte. Ein Imbiss in 50 m konkurriert
# anders als einer am Rand des Umkreises; die reine Umkreiszahl verwischt das.
# Es sind Zählgrenzen, keine Gewichte — gewichtet wird nirgends.
ENTFERNUNGSSTUFEN = (150, 300, 600, 900, 1400)


def nach_entfernung(objekte: list[dict[str, Any]], radius: int) -> list[dict[str, Any]]:
    """Kumulierte Anzahl je Entfernungsstufe, begrenzt auf den Abfrageradius."""
    stufen = [s for s in ENTFERNUNGSSTUFEN if s < radius] + [radius]
    return [
        {"bis_m": s, "anzahl": sum(1 for o in objekte if o["distanz_m"] <= s)}
        for s in stufen
    ]


def summarize(cls: dict[str, Any], radius: int | None = None) -> dict[str, Any]:
    gastro = cls["gastronomie"]
    nach_typ: dict[str, int] = {}
    nach_kueche: dict[str, int] = {}
    marken: dict[str, int] = {}
    ketten = 0
    for g in gastro:
        label = g["typ_label"]
        nach_typ[label] = nach_typ.get(label, 0) + 1
        for c in (g.get("cuisine") or "").split(";"):
            c = c.strip()
            if c:
                nach_kueche[c] = nach_kueche.get(c, 0) + 1
        if g["kette"]:
            ketten += 1
            if g.get("marke"):
                marken[g["marke"]] = marken.get(g["marke"], 0) + 1

    freq_nach_kat: dict[str, int] = {}
    for f in cls["frequenzbringer"]:
        freq_nach_kat[f["kategorie"]] = freq_nach_kat.get(f["kategorie"], 0) + 1

    linien_nach_art: dict[str, int] = {}
    refs: dict[str, set[str]] = {}
    for r in cls["linien"]:
        art = r.get("route") or "unbekannt"
        linien_nach_art[art] = linien_nach_art.get(art, 0) + 1
        if r.get("ref"):
            refs.setdefault(art, set()).add(r["ref"])

    return {
        "gastronomie": {
            "gesamt": len(gastro),
            "nach_typ": dict(sorted(nach_typ.items(), key=lambda kv: -kv[1])),
            "nach_kueche": dict(sorted(nach_kueche.items(), key=lambda kv: -kv[1])),
            "ketten": ketten,
            "einzelbetriebe": len(gastro) - ketten,
            "marken": dict(sorted(marken.items(), key=lambda kv: -kv[1])),
            "ohne_kuechenangabe": sum(1 for g in gastro if not g.get("cuisine")),
            "nach_entfernung": nach_entfernung(gastro, radius) if radius else [],
            "naechster_m": gastro[0]["distanz_m"] if gastro else None,
            "oeffnungszeiten": oeffnungszeiten_luecken(gastro),
            "schnellrestaurants_nach_entfernung": (
                nach_entfernung(
                    [g for g in gastro if g["typ_label"] == "Schnellrestaurant"], radius
                )
                if radius
                else []
            ),
        },
        "frequenzbringer": {
            "gesamt": len(cls["frequenzbringer"]),
            "nach_kategorie": dict(sorted(freq_nach_kat.items(), key=lambda kv: -kv[1])),
        },
        "oepnv": {
            "haltestellen": len(cls["oepnv"]),
            "linien_gesamt": len(cls["linien"]),
            "linien_nach_art": dict(sorted(linien_nach_art.items(), key=lambda kv: -kv[1])),
            # Richtungen zählen doppelt (Hin- und Rückrelation) -> eindeutige Refs
            "linien_refs": {k: sorted(v) for k, v in sorted(refs.items())},
            "linien_eindeutig": sum(len(v) for v in refs.values()),
        },
        "leerstand": {"gesamt": len(cls["leerstand"])},
    }


async def load(
    out: Outbound, settings: Settings, lat: float, lon: float, radius: int
) -> SourceResult:
    started = time.perf_counter()
    query = build_query(lat, lon, radius, timeout=int(settings.overpass_timeout))
    try:
        payload, endpoint, problems = await run_query(out, settings, query)
    except SourceError as err:
        return SourceResult.failed("osm", err, int((time.perf_counter() - started) * 1000))

    elements = payload.get("elements", []) if isinstance(payload, dict) else []
    cls = classify(elements, lat, lon, radius)
    data = {
        **cls,
        "zusammenfassung": summarize(cls, radius),
        "elemente_gesamt": len(elements),
    }

    warnings = list(problems)
    flaechen = [
        e
        for key in ("gastronomie", "frequenzbringer", "oepnv", "leerstand")
        for e in cls[key]
        if e.get("mittelpunkt_ausserhalb")
    ]
    if flaechen:
        warnings.append(
            f"{len(flaechen)} Objekt(e) sind Flächen, die in den Umkreis hineinreichen, "
            "deren Mittelpunkt aber außerhalb liegt (z. B. ein Universitäts- oder "
            "Klinikgelände). Die Entfernung bezieht sich auf den Flächenmittelpunkt."
        )
    if not elements:
        warnings.append(
            "Keine OSM-Objekte im Umkreis gefunden. Im ländlichen Raum ist das ein "
            "realistisches Ergebnis, kein Fehler."
        )

    stand = None
    osm3s = payload.get("osm3s") if isinstance(payload, dict) else None
    if isinstance(osm3s, dict):
        stand = osm3s.get("timestamp_osm_base")

    return SourceResult(
        name="osm",
        ok=True,
        data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnings,
        provenance=Provenance(
            source="OpenStreetMap über Overpass API",
            license=LICENSE,
            endpoint=endpoint,
            stand=f"OSM-Datenstand {stand}" if stand else None,
            retrieved_at=now_iso(),
            note=(
                "OSM ist unvollständig, besonders bei kleinen Imbissen und Neueröffnungen. "
                "Die angezeigte Wettbewerbsdichte ist eine Untergrenze, kein Vollbestand."
            ),
        ),
    )
