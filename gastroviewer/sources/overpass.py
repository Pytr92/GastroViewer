"""OpenStreetMap über Overpass.

Eine einzige kombinierte Abfrage je Punkt statt einer pro Kategorie — Overpass ist
ein Spendenprojekt (Spec §4.2). In Phase 0 gemessen: 801 Elemente in 5,5 s für
r=600 in der Münchner Innenstadt, inklusive der Linienrelationen.

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

# Frequenzbringer nach Kategorie (Spec §4.2 / Panel-Block 5)
FREQ_AMENITIES = {
    "school": ("Bildung", "Schule"),
    "university": ("Bildung", "Universität"),
    "college": ("Bildung", "Hochschule"),
    "kindergarten": ("Bildung", "Kindergarten"),
    "hospital": ("Gesundheit", "Krankenhaus"),
    "clinic": ("Gesundheit", "Klinik"),
    "doctors": ("Gesundheit", "Arztpraxis"),
    "cinema": ("Kultur & Freizeit", "Kino"),
    "theatre": ("Kultur & Freizeit", "Theater"),
    "library": ("Kultur & Freizeit", "Bibliothek"),
    "parking": ("Verkehr & Parken", "Parkplatz"),
}
FREQ_SHOPS = {
    "supermarket": ("Einkauf", "Supermarkt"),
    "mall": ("Einkauf", "Einkaufszentrum"),
    "department_store": ("Einkauf", "Kaufhaus"),
    "convenience": ("Einkauf", "Nahversorger"),
    "bakery": ("Einkauf", "Bäckerei"),
    "butcher": ("Einkauf", "Metzgerei"),
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


def summarize(cls: dict[str, Any]) -> dict[str, Any]:
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
    data = {**cls, "zusammenfassung": summarize(cls), "elemente_gesamt": len(elements)}

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
