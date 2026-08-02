"""Flächen-Scan: WO im Viertel teilen sich viele Anwohner wenige Betriebe?

Die Erkundungsebene (1/10 km) zeigt, wo Menschen wohnen; der Umkreis zeigt,
wie es an einem Punkt ist. Dazwischen fehlte die Frage „WO im Viertel ist das
Verhältnis aus Nachfrage und Angebot am günstigsten?". Der Scan legt über
einen gewählten Ausschnitt das 100-m-Zensusgitter und stellt jeder Zelle die
Gastronomie aus OSM gegenüber — als **Einwohner je Betrieb im 300-m-Umfeld**.

Bewusste Entscheidungen:

* **Eine** Overpass-Abfrage für den ganzen Ausschnitt (nur Gastronomie, als
  Rechteck) statt dutzender Umkreisabfragen — Overpass ist ein Spendenprojekt.
  Gemessen am 02.08.2026 für 4×4 km Münchner Innenstadt: eine Antwort in der
  Größenordnung weniger hundert KB.
* Das Umfeld von 300 m ist eine **gewählte** Größe (fußläufige Nachbarschaft
  von wenigen Minuten), keine Messgröße. Sie steht in Antwort und Legende.
* Die Kennzahl teilt zwei gemessene Größen; es kommt kein Gewicht hinzu.
  Zellen ohne Betrieb im Umfeld bekommen bewusst **keinen** Zahlenwert
  (nicht „unendlich"), sondern die eigene Klasse „kein Betrieb im Umfeld".
* OSM ist unvollständig — die Betriebszahl ist eine Untergrenze und der Wert
  „Einwohner je Betrieb" damit eine Obergrenze. Und die Kennzahl sieht nur die
  Wohnbevölkerung: Zulauf von Büros, Passanten und Touristen fehlt. Beides
  steht als Hinweis in der Antwort, nicht im Kleingedruckten.
"""

from __future__ import annotations

import math
import time
from typing import Any

from ..config import Settings
from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, now_iso
from .overpass import (GASTRO_AMENITIES, GASTRO_LABELS, LICENSE as OSM_LICENSE,
                       element_coords, run_query)
from .zensus import LICENSE as ZENSUS_LICENSE, STICHTAG, _ring_center

# Gewählte Umfeldgröße: die fußläufige Nachbarschaft von 3–4 Minuten.
UMFELD_M = 300

# Die Abfragebox wird auf dieses Raster nach außen gerundet, damit leichtes
# Schwenken denselben Cache-Eintrag trifft (gleiches Prinzip wie beim
# Übersichtsgitter). 0,01° sind ~1,1 km in Nord-Süd-Richtung.
SCAN_RASTER = 0.01

# Maximale Spannweite der Box in Grad (Länge, Breite) — rund 4,5 × 5 km.
# Mehr wären Tausende 100-m-Zellen und eine unnötig große Overpass-Antwort;
# für „ganz München" ist die Erkundungsebene da, der Scan ist das feine Werkzeug.
MAX_SPANNE = (0.06, 0.045)

# Seitenlimit der Zensus-Paginierung. 4,5×5 km sind höchstens ~2.250 Zellen,
# also zwei Seiten à 2.000 — vier Seiten sind Reserve, keine Erwartung.
MAX_SEITEN = 4


def scan_kachel(west: float, sued: float, ost: float, nord: float):
    """Rundet die Box nach außen auf das Cache-Raster.

    Wie beim Übersichtsgitter wird vor floor/ceil auf 6 Stellen gerundet:
    11,4 / 0,01 ist in Gleitkommadarstellung nicht exakt, und ohne Rundung
    fiele ein Rand um eine ganze Kachel zu weit hinaus.
    """
    r = SCAN_RASTER
    return (
        round(math.floor(round(west / r, 6)) * r, 6),
        round(math.floor(round(sued / r, 6)) * r, 6),
        round(math.ceil(round(ost / r, 6)) * r, 6),
        round(math.ceil(round(nord / r, 6)) * r, 6),
    )


def gastro_query(west: float, sued: float, ost: float, nord: float, timeout: int = 60) -> str:
    """Nur Gastronomie, nur diese Box — bewusst viel schmaler als die
    kombinierte Punktabfrage."""
    g = "|".join(GASTRO_AMENITIES)
    bbox = f"({sued},{west},{nord},{ost})"
    return f"""[out:json][timeout:{timeout}];
nwr["amenity"~"^({g})$"]{bbox};
out center tags;
"""


async def fetch_zellen(
    out: Outbound, settings: Settings,
    west: float, sued: float, ost: float, nord: float,
) -> tuple[list[dict[str, Any]], list[str]]:
    """100-m-Zellen im Rechteck, mit Paginierung wie beim Umkreis."""
    url = f"{settings.zensus_base}/{settings.zensus_layer}/query"
    features: list[dict[str, Any]] = []
    warnings: list[str] = []
    offset = 0
    for _seite in range(MAX_SEITEN):
        form = {
            "f": "json",
            "where": "1=1",
            "geometry": (
                f'{{"xmin":{west},"ymin":{sued},"xmax":{ost},"ymax":{nord},'
                f'"spatialReference":{{"wkid":4326}}}}'
            ),
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "outSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "GITTER_ID_100m,Einwohner",
            "returnGeometry": "true",
            "resultRecordCount": str(settings.zensus_page_size),
        }
        if offset:
            form["resultOffset"] = str(offset)
        payload = await out.post_json(
            "zensus", url, data=form, timeout=settings.zensus_timeout
        )
        if isinstance(payload, dict) and "error" in payload:
            err = payload["error"]
            raise SourceError(
                "api_error",
                f"Zensus-Dienst meldet Fehler {err.get('code')}: {err.get('message')}",
            )
        batch = payload.get("features", []) if isinstance(payload, dict) else []
        features.extend(batch)
        if payload.get("exceededTransferLimit") is not True:
            break
        offset += len(batch) or settings.zensus_page_size
    else:
        warnings.append(
            "Der Ausschnitt enthält mehr Zellen, als in vier Seiten passen — "
            "Anzeige unvollständig. Ein kleinerer Ausschnitt behebt das."
        )
    return features, warnings


def bewerte(
    features: list[dict[str, Any]], betriebe: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    """Je Zelle: Einwohner und Betriebe im 300-m-Umfeld um die Zellmitte.

    Nachbarschaftssuche über ein Gitterregister (gleiches Prinzip wie im
    Wegenetz), damit auch 2.000 Zellen in Millisekunden fertig sind. Die
    Entfernung wird planar mit Breitenkorrektur gerechnet — auf 300 m ist der
    Unterschied zur Kugelrechnung weit unter einem Meter.
    """
    zellen_roh: list[dict[str, Any]] = []
    uebersprungen = 0
    for f in features:
        attrs = f.get("attributes") or {}
        rings = (f.get("geometry") or {}).get("rings") or []
        if not rings:
            continue
        if attrs.get("Einwohner") is None:
            uebersprungen += 1
            continue
        clat, clon = _ring_center(rings[0])
        zellen_roh.append({
            "id": attrs.get("GITTER_ID_100m"),
            "einwohner": attrs.get("Einwohner"),
            "lat": clat,
            "lon": clon,
            "ring": rings[0],
        })

    if not zellen_roh:
        return [], uebersprungen

    lat0 = sum(z["lat"] for z in zellen_roh) / len(zellen_roh)
    m_lat = 111_320.0
    m_lon = 111_320.0 * math.cos(math.radians(lat0))

    def meter(obj: dict[str, Any]) -> tuple[float, float]:
        return obj["lon"] * m_lon, obj["lat"] * m_lat

    def register(objekte: list[dict[str, Any]]) -> dict[tuple[int, int], list[int]]:
        reg: dict[tuple[int, int], list[int]] = {}
        for i, o in enumerate(objekte):
            x, y = meter(o)
            reg.setdefault((int(x // UMFELD_M), int(y // UMFELD_M)), []).append(i)
        return reg

    reg_zellen = register(zellen_roh)
    reg_betriebe = register(betriebe)

    def nachbarn(reg: dict[tuple[int, int], list[int]], x: float, y: float):
        kx, ky = int(x // UMFELD_M), int(y // UMFELD_M)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                yield from reg.get((kx + dx, ky + dy), [])

    ergebnis: list[dict[str, Any]] = []
    for z in zellen_roh:
        x, y = meter(z)
        ew_umfeld = 0.0
        for i in nachbarn(reg_zellen, x, y):
            nx, ny = meter(zellen_roh[i])
            if (nx - x) ** 2 + (ny - y) ** 2 <= UMFELD_M ** 2:
                ew_umfeld += float(zellen_roh[i]["einwohner"])
        n_betriebe = 0
        for i in nachbarn(reg_betriebe, x, y):
            bx, by = meter(betriebe[i])
            if (bx - x) ** 2 + (by - y) ** 2 <= UMFELD_M ** 2:
                n_betriebe += 1
        ergebnis.append({
            "id": z["id"],
            "ring": z["ring"],
            "einwohner": z["einwohner"],
            "einwohner_umfeld": round(ew_umfeld),
            "betriebe_umfeld": n_betriebe,
            # Kein Betrieb im Umfeld ist eine eigene Aussage, kein hoher Wert.
            "je_betrieb": round(ew_umfeld / n_betriebe) if n_betriebe else None,
        })
    return ergebnis, uebersprungen


async def load(
    out: Outbound, settings: Settings,
    west: float, sued: float, ost: float, nord: float,
) -> SourceResult:
    started = time.perf_counter()
    try:
        features, warnings = await fetch_zellen(out, settings, west, sued, ost, nord)
    except SourceError as err:
        return SourceResult.failed("scan", err, int((time.perf_counter() - started) * 1000))

    query = gastro_query(west, sued, ost, nord, timeout=int(settings.overpass_timeout))
    try:
        payload, endpoint, probleme = await run_query(out, settings, query)
    except SourceError as err:
        return SourceResult.failed("scan", err, int((time.perf_counter() - started) * 1000))
    warnings.extend(probleme)

    betriebe: list[dict[str, Any]] = []
    for el in payload.get("elements", []) if isinstance(payload, dict) else []:
        tags = el.get("tags") or {}
        if tags.get("amenity") not in GASTRO_AMENITIES:
            continue
        coords = element_coords(el)
        if coords is None:
            continue
        betriebe.append({
            "lat": coords[0],
            "lon": coords[1],
            "name": tags.get("name"),
            "typ": GASTRO_LABELS.get(tags["amenity"], tags["amenity"]),
        })

    zellen, uebersprungen = bewerte(features, betriebe)
    if uebersprungen:
        warnings.append(
            f"{uebersprungen} Zelle(n) ohne Einwohnerangabe wurden ausgelassen — "
            "keine Angabe ist nicht null."
        )
    if not zellen:
        warnings.append(
            "Keine bewohnte Zensuszelle im Ausschnitt. Im Zensus 2022 fehlen "
            "unbewohnte Zellen vollständig — das ist eine Aussage über die "
            "Fläche, kein Datenfehler."
        )

    stand = None
    osm3s = payload.get("osm3s") if isinstance(payload, dict) else None
    if isinstance(osm3s, dict):
        stand = osm3s.get("timestamp_osm_base")

    return SourceResult(
        name="scan",
        ok=True,
        data={
            "kachel": [west, sued, ost, nord],
            "umfeld_m": UMFELD_M,
            "zellen": zellen,
            "betriebe_gesamt": len(betriebe),
            "hinweise": [
                "Die Betriebszahl stammt aus OSM und ist eine Untergrenze — "
                "„Einwohner je Betrieb“ ist damit eine Obergrenze.",
                "Die Kennzahl sieht nur die Wohnbevölkerung. Zulauf von Büros, "
                "Passanten und Touristen fehlt — eine dunkle Wohnlage ist ein "
                "Suchhinweis, keine Standortentscheidung.",
                f"Das Umfeld von {UMFELD_M} m ist eine gewählte Größe "
                "(fußläufige Nachbarschaft), keine Messgröße.",
            ],
        },
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnings,
        provenance=Provenance(
            source="Zensus 2022, 100-m-Gitter + OpenStreetMap über Overpass",
            license=f"{ZENSUS_LICENSE} · {OSM_LICENSE}",
            endpoint=endpoint,
            stand=(
                f"Zensus-Stichtag {STICHTAG}"
                + (f" · OSM-Datenstand {stand}" if stand else "")
            ),
            retrieved_at=now_iso(),
            note=(
                "Einwohner je Gastronomiebetrieb im 300-m-Umfeld der Zellmitte. "
                "Zwei gemessene Größen, geteilt — keine Gewichte, keine Indizes."
            ),
        ),
    )
