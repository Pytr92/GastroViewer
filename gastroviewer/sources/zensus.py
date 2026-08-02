"""Zensus 2022, 100-m-Gitter (ArcGIS FeatureServer).

Geprüft in Phase 0, siehe ``docs/endpoints-verified.md``. Die drei Eigenheiten, die
den Code prägen:

1. ``exceededTransferLimit`` steht nur im JSON, **wenn es true ist**. Prüfung auf
   Existenz des Schlüssels wäre falsch. Bei true wird über ``resultOffset``
   weitergeblättert (in Phase 0 verifiziert: r=3000 → 2000 + 6 Features).
2. ``null`` ist ein regulärer Wert. „keine Angabe" darf nie als 0 in einen
   Mittelwert einfließen.
3. Über den Werten liegt zum Datenschutz eine stochastische Überlagerung
   (Cell-Key-Methode). Einzelwerte summieren sich nicht zwingend zur Summe. Das
   wird nicht geglättet, sondern ausgewiesen.

Es wird nichts geschätzt: jede ausgegebene Zahl ist entweder ein Rohwert oder eine
Summe/ein Mittel über Rohwerte, immer mit der Zahl der einbezogenen Zellen daneben.
"""

from __future__ import annotations

import time
from typing import Any

from ..config import Settings
from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, now_iso

LICENSE = (
    "© Statistische Ämter des Bundes und der Länder 2024 · "
    "Datenlizenz Deutschland – Namensnennung – Version 2.0 · GeoBasis-DE/BKG 2024"
)
STICHTAG = "15.05.2022"

# Alle 49 Felder des Layers wurden in Phase 0 abgefragt. Hier die fachlich
# genutzten — Shape__Area/Shape__Length und OBJECTID tragen nichts bei.
FIELDS = [
    "GITTER_ID_100m",
    "ags",
    "Einwohner",
    "AnteilAuslaender",
    "Durchschnittsalter",
    "Unter18",
    "a18bis29",
    "a30bis49",
    "a50bis64",
    "a65undaelter",
    "AnteilUnter18",
    "AnteilUeber65",
    "DurchschnHHGroesse",
    "durchschnMieteQM",
    "durchschnFlaechejeWohn",
    "durchschnFlaechejeBew",
    "Eigentuemerquote",
    "Leerstandsquote",
    "MALeerstQuote",
    "Insgesamt_Gebaeude",
    "Vor1919",
    "a1919bis1948",
    "a1949bis1978",
    "a1979bis1990",
    "a1991bis2000",
    "a2001bis2010",
    "a2011bis2019",
    "a2020undspaeter",
]

AGE_BUCKETS = [
    ("Unter18", "unter 18"),
    ("a18bis29", "18–29"),
    ("a30bis49", "30–49"),
    ("a50bis64", "50–64"),
    ("a65undaelter", "65 und älter"),
]

BUILDING_AGE = [
    ("Vor1919", "vor 1919"),
    ("a1919bis1948", "1919–1948"),
    ("a1949bis1978", "1949–1978"),
    ("a1979bis1990", "1979–1990"),
    ("a1991bis2000", "1991–2000"),
    ("a2001bis2010", "2001–2010"),
    ("a2011bis2019", "2011–2019"),
    ("a2020undspaeter", "2020 und später"),
]

# Amtlicher Regionalschlüssel, Stellen 1–2 = Land (Spec §4.5).
BUNDESLAENDER = {
    "01": "Schleswig-Holstein",
    "02": "Hamburg",
    "03": "Niedersachsen",
    "04": "Bremen",
    "05": "Nordrhein-Westfalen",
    "06": "Hessen",
    "07": "Rheinland-Pfalz",
    "08": "Baden-Württemberg",
    "09": "Bayern",
    "10": "Saarland",
    "11": "Berlin",
    "12": "Brandenburg",
    "13": "Mecklenburg-Vorpommern",
    "14": "Sachsen",
    "15": "Sachsen-Anhalt",
    "16": "Thüringen",
}


def bundesland_from_ags(ags: str | None) -> tuple[str | None, str | None]:
    if not ags or len(ags) < 2:
        return None, None
    code = str(ags)[:2]
    return code, BUNDESLAENDER.get(code)


def _point_in_ring(lat: float, lon: float, ring: list[list[float]]) -> bool:
    """Strahlenmethode. Ringe kommen als [lon, lat]."""
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > lat) != (y2 > lat):
            x_at = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lon < x_at:
                inside = not inside
    return inside


def _ring_center(ring: list[list[float]]) -> tuple[float, float]:
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    return sum(lats) / len(lats), sum(lons) / len(lons)


class Aggregate:
    """Sammelt Rohwerte und weist immer aus, wie viele Zellen beigetragen haben.

    Nullwerte werden ausgelassen, nicht als 0 gewertet.
    """

    def __init__(self, cells: list[dict[str, Any]]) -> None:
        self.cells = cells
        self.n = len(cells)

    def values(self, field: str) -> list[float]:
        out = []
        for c in self.cells:
            v = c.get(field)
            if v is not None:
                try:
                    out.append(float(v))
                except (TypeError, ValueError):
                    continue
        return out

    def sum(self, field: str) -> dict[str, Any] | None:
        vals = self.values(field)
        if not vals:
            return None
        return {"wert": round(sum(vals), 2), "zellen": len(vals), "zellen_gesamt": self.n}

    def mean_weighted(self, field: str, weight_field: str = "Einwohner") -> dict[str, Any] | None:
        """Nach Einwohnern gewichtetes Mittel. Fällt auf das ungewichtete Mittel
        zurück, wenn kein Gewicht vorliegt — beides wird ausgewiesen."""
        pairs = []
        for c in self.cells:
            v, w = c.get(field), c.get(weight_field)
            if v is None:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            try:
                fw = float(w) if w is not None else 0.0
            except (TypeError, ValueError):
                fw = 0.0
            pairs.append((fv, fw))
        if not pairs:
            return None
        vals = [p[0] for p in pairs]
        wsum = sum(p[1] for p in pairs)
        if wsum > 0:
            mean = sum(v * w for v, w in pairs) / wsum
            gewichtung = f"nach {weight_field} gewichtet"
        else:
            mean = sum(vals) / len(vals)
            gewichtung = "ungewichtet (keine Gewichte vorhanden)"
        srt = sorted(vals)
        mid = len(srt) // 2
        median = srt[mid] if len(srt) % 2 else (srt[mid - 1] + srt[mid]) / 2
        return {
            "wert": round(mean, 2),
            "median": round(median, 2),
            "min": round(min(vals), 2),
            "max": round(max(vals), 2),
            "zellen": len(vals),
            "zellen_gesamt": self.n,
            "gewichtung": gewichtung,
        }


# ------------------------------------------------- Übersichtsgitter (1/10 km)
#
# Der Umkreis beantwortet „wie ist es HIER?" — die Frage „WO ist es überhaupt
# interessant?" braucht die Fläche. Derselbe verifizierte Dienst führt das
# Gitter auch in 1 km (Layer 1) und 10 km (Layer 2); am 01.08.2026 gemessen:
# ganz München in 1 km sind 613 Zellen, ganz Bayern in 10 km sind 1.083 —
# jeweils eine einzige Antwortseite.
GITTER_EBENEN = {
    "1km": {"layer": 1, "id_feld": "GITTER_ID_1km",
            # Spannweite der Abfragebox in Grad (Länge, Breite). Rund 110×90 km
            # — mehr 1-km-Zellen wären weder ladbar noch lesbar.
            "max_spanne": (1.6, 1.0)},
    "10km": {"layer": 2, "id_feld": "GITTER_ID_10km",
             # reicht für ganz Bayern in einem Ausschnitt
             "max_spanne": (7.5, 5.0)},
}
GITTER_FELDER = ["Einwohner", "Durchschnittsalter", "DurchschnHHGroesse",
                 "durchschnMieteQM", "Leerstandsquote"]
# Die Abfragebox wird auf dieses Raster nach außen gerundet, damit leichtes
# Schwenken denselben Cache-Eintrag trifft statt jedes Mal neu zu laden.
GITTER_RASTER = {"1km": 0.2, "10km": 1.0}


def gitter_kachel(ebene: str, west: float, sued: float, ost: float, nord: float):
    """Rundet die Box nach außen auf das Cache-Raster.

    Das Zwischenergebnis wird auf 6 Stellen gerundet, bevor floor/ceil greifen:
    11,4 / 0,2 ist in Gleitkommadarstellung 56,999…, und ohne Rundung fiele der
    Westrand um eine ganze Kachel zu weit hinaus.
    """
    import math

    r = GITTER_RASTER[ebene]
    return (
        round(math.floor(round(west / r, 6)) * r, 6),
        round(math.floor(round(sued / r, 6)) * r, 6),
        round(math.ceil(round(ost / r, 6)) * r, 6),
        round(math.ceil(round(nord / r, 6)) * r, 6),
    )


async def fetch_gitter(
    out: Outbound,
    settings: Settings,
    ebene: str,
    west: float,
    sued: float,
    ost: float,
    nord: float,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Gitterzellen einer Übersichtsebene im Kartenausschnitt."""
    cfg = GITTER_EBENEN[ebene]
    url = f"{settings.zensus_base}/{cfg['layer']}/query"
    felder = [cfg["id_feld"], *GITTER_FELDER]
    features: list[dict[str, Any]] = []
    warnings: list[str] = []
    offset = 0
    for _page in range(3):
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
            "outFields": ",".join(felder),
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
            "Der Ausschnitt enthält mehr Zellen, als in drei Seiten passen — "
            "Anzeige unvollständig. Ein kleinerer Ausschnitt behebt das."
        )

    zellen = []
    for f in features:
        attrs = dict(f.get("attributes") or {})
        rings = (f.get("geometry") or {}).get("rings") or []
        if not rings:
            continue
        zellen.append({
            "id": attrs.get(cfg["id_feld"]),
            "einwohner": attrs.get("Einwohner"),
            "alter": attrs.get("Durchschnittsalter"),
            "haushalt": attrs.get("DurchschnHHGroesse"),
            "miete_qm": attrs.get("durchschnMieteQM"),
            "leerstand": attrs.get("Leerstandsquote"),
            "ring": rings[0],
        })
    return zellen, warnings


async def fetch_cells(
    out: Outbound, settings: Settings, lat: float, lon: float, radius: int
) -> tuple[list[dict[str, Any]], list[str]]:
    """Alle Gitterzellen im Umkreis. Blättert bei ``exceededTransferLimit``."""
    url = f"{settings.zensus_base}/{settings.zensus_layer}/query"
    features: list[dict[str, Any]] = []
    warnings: list[str] = []
    offset = 0

    for page in range(settings.zensus_max_pages):
        form = {
            "f": "json",
            "where": "1=1",
            "geometry": f'{{"x":{lon},"y":{lat},"spatialReference":{{"wkid":4326}}}}',
            "geometryType": "esriGeometryPoint",
            "distance": str(radius),
            "units": "esriSRUnit_Meter",
            "inSR": "4326",
            "outSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": ",".join(FIELDS),
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
                detail=str(err.get("details")),
            )
        batch = payload.get("features", []) if isinstance(payload, dict) else []
        features.extend(batch)

        # Nur gesetzt, wenn true — Phase-0-Befund A-2.
        if payload.get("exceededTransferLimit") is not True:
            break
        offset += len(batch) or settings.zensus_page_size
        if page == settings.zensus_max_pages - 1:
            warnings.append(
                f"Seitenlimit erreicht ({settings.zensus_max_pages} Seiten à "
                f"{settings.zensus_page_size}). Ergebnis ist unvollständig — Radius verkleinern."
            )

    return features, warnings


def build_cells(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cells = []
    for f in features:
        attrs = dict(f.get("attributes") or {})
        geom = f.get("geometry") or {}
        rings = geom.get("rings") or []
        if rings:
            clat, clon = _ring_center(rings[0])
            attrs["_center"] = [clat, clon]
            attrs["_ring"] = rings[0]
        cells.append(attrs)
    return cells


def pick_center_cell(cells: list[dict[str, Any]], lat: float, lon: float) -> dict[str, Any] | None:
    """Die Zelle, in der der Punkt liegt. Ohne Treffer: keine — lieber nichts
    ausweisen als die falsche Zelle als „Standortzelle" verkaufen."""
    for c in cells:
        ring = c.get("_ring")
        if ring and _point_in_ring(lat, lon, ring):
            return c
    return None


def summarize(cells: list[dict[str, Any]], lat: float, lon: float) -> dict[str, Any]:
    agg = Aggregate(cells)
    center = pick_center_cell(cells, lat, lon)

    einwohner = agg.sum("Einwohner")
    alters_summen = {}
    age_total = 0.0
    for field, label in AGE_BUCKETS:
        s = agg.sum(field)
        alters_summen[label] = s
        if s:
            age_total += s["wert"]

    hinweise: list[str] = []
    if einwohner and age_total:
        diff = age_total - einwohner["wert"]
        if abs(diff) >= 1:
            hinweise.append(
                f"Summe der Altersgruppen ({age_total:.0f}) weicht um {diff:+.0f} von der "
                f"ausgewiesenen Einwohnerzahl ({einwohner['wert']:.0f}) ab. Ursache ist die "
                "stochastische Überlagerung (Cell-Key-Methode) zum Schutz der Einzelangaben, "
                "kein Rechenfehler."
            )

    gebaeude = agg.sum("Insgesamt_Gebaeude")
    baualter = {label: agg.sum(field) for field, label in BUILDING_AGE}

    # "2020 und später" endet am Stichtag 15.05.2022 und umfasst damit nur gut
    # zwei Jahre. Der Anteil ist deshalb kein Maß für Neubau, sondern ein
    # Anzeiger dafür, dass am Ort zuletzt überhaupt gebaut wurde. Nachgemessen
    # am 01.08.2026: gewachsene Viertel liegen bei exakt 0,00 % (Marienplatz,
    # Giesing), wachsende bei 2,2 % (Moosach) bis 2,9 % (Freiham). Der Hinweis
    # braucht deshalb keine gewählte Schwelle — er hängt an "größer null".
    # agg.sum() liefert {"wert": …, "zellen": …}, nicht die nackte Zahl.
    neubau_wert = (baualter.get("2020 und später") or {}).get("wert")
    gebaeude_wert = (gebaeude or {}).get("wert")
    neubau_anteil = (
        round(neubau_wert / gebaeude_wert * 100, 1)
        if isinstance(neubau_wert, (int, float))
        and isinstance(gebaeude_wert, (int, float))
        and gebaeude_wert > 0
        else None
    )
    if neubau_anteil:
        hinweise.append(
            f"{neubau_anteil:.1f} % der Gebäude im Umkreis wurden zwischen 2020 und dem "
            "Stichtag 15.05.2022 errichtet — hier wurde zuletzt gebaut. Was nach dem "
            "Stichtag entstanden ist, fehlt im Zensus vollständig; die heutige "
            "Einwohnerzahl liegt an solchen Orten über der ausgewiesenen."
        )

    ags_counts: dict[str, int] = {}
    for c in cells:
        a = c.get("ags")
        if a:
            ags_counts[str(a)] = ags_counts.get(str(a), 0) + 1
    ags_main = max(ags_counts, key=lambda k: ags_counts[k]) if ags_counts else None
    ags_point = str(center.get("ags")) if center and center.get("ags") else None
    ags = ags_point or ags_main
    bl_code, bl_name = bundesland_from_ags(ags)

    return {
        "zellen_gefunden": len(cells),
        "zelle_am_punkt": (
            {k: v for k, v in center.items() if not k.startswith("_")} if center else None
        ),
        "ags": ags,
        "ags_quelle": "Zelle am Punkt" if ags_point else "häufigster Wert im Umkreis",
        "ags_im_umkreis": ags_counts,
        "bundesland_code": bl_code,
        "bundesland": bl_name,
        "bevoelkerung": {
            "einwohner": einwohner,
            "altersgruppen": alters_summen,
            "durchschnittsalter": agg.mean_weighted("Durchschnittsalter"),
            "haushaltsgroesse": agg.mean_weighted("DurchschnHHGroesse"),
            "anteil_auslaender": agg.mean_weighted("AnteilAuslaender"),
            "anteil_unter18": agg.mean_weighted("AnteilUnter18"),
            "anteil_ueber65": agg.mean_weighted("AnteilUeber65"),
        },
        "wohnen": {
            "miete_qm": agg.mean_weighted("durchschnMieteQM"),
            "eigentuemerquote": agg.mean_weighted("Eigentuemerquote"),
            "leerstandsquote": agg.mean_weighted("Leerstandsquote"),
            "ma_leerstandsquote": agg.mean_weighted("MALeerstQuote"),
            "flaeche_je_wohnung": agg.mean_weighted("durchschnFlaechejeWohn"),
            "flaeche_je_bewohner": agg.mean_weighted("durchschnFlaechejeBew"),
            "gebaeude": gebaeude,
            "baualter": baualter,
            "neubau_anteil": neubau_anteil,
        },
        "hinweise": hinweise,
    }


async def load(
    out: Outbound, settings: Settings, lat: float, lon: float, radius: int
) -> SourceResult:
    started = time.perf_counter()
    try:
        features, warnings = await fetch_cells(out, settings, lat, lon, radius)
    except SourceError as err:
        return SourceResult.failed(
            "zensus", err, int((time.perf_counter() - started) * 1000)
        )

    cells = build_cells(features)
    data = summarize(cells, lat, lon)
    data["zellen"] = cells  # Rohwerte je Zelle für Karte und Klick

    if not cells:
        warnings.append(
            "Keine Gitterzelle im Umkreis. Im Zensus 2022 fehlen unbewohnte Zellen "
            "vollständig — das ist eine echte Aussage über die Lage, kein Datenfehler."
        )

    return SourceResult(
        name="zensus",
        ok=True,
        data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnings,
        provenance=Provenance(
            source="Zensus 2022, 100-m-Gitter (Statistische Ämter des Bundes und der Länder)",
            license=LICENSE,
            endpoint=f"{settings.zensus_base}/{settings.zensus_layer}/query",
            stand=f"Stichtag {STICHTAG}",
            retrieved_at=now_iso(),
            note=(
                "Zum Schutz der Einzelangaben liegt über den Werten eine stochastische "
                "Überlagerung (Cell-Key-Methode). Einzelwerte summieren sich nicht zwingend "
                "zur ausgewiesenen Summe. Zellen ohne Einwohner fehlen im Datensatz."
            ),
        ),
    )
