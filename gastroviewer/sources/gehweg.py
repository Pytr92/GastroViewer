"""Gehstrecke statt Luftlinie.

Der Umkreis, mit dem dieses Werkzeug arbeitet, ist ein Kreis auf der Karte. Zu
Fuß ist er das nicht: Flüsse, Gleise und Autobahnen zerschneiden ihn, und man
kommt nur dort hinüber, wo eine Brücke steht. In München ist das kein Randfall —
Isar, Bahnanlagen und der Mittlere Ring durchziehen die halbe Stadt.

Gemessen am 01.08.2026, Radius 600 m, Anteil der Wegeknoten im Luftlinienkreis,
die zu Fuß **weiter** als 600 m entfernt liegen:

===================  =====
Marienplatz          28 %
Freiham (A 99)       53 %
Ostbahnhof (Gleise)  51 %
Isarufer (Fluss)     57 %
===================  =====

Selbst ohne Barriere sind am Marienplatz **84 von 379** Gastronomiebetrieben im
Kreis zu Fuß weiter als 600 m weg. Der Umwegfaktor liegt im Median bei 1,34.

Wie es rechnet: das Fußwegenetz kommt aus derselben Overpass-Quelle wie alles
andere, wird zu einem Graphen aus Wegsegmenten verknüpft, und ein Dijkstra vom
Startpunkt liefert die Gehstrecke je Knoten. Für 12.000 Knoten dauert das rund
20 ms — es braucht **keinen** Routing-Dienst und keine zusätzliche Abhängigkeit.

Was es nicht ist: eine Wegbeschreibung. Gerechnet wird die Länge des kürzesten
Weges im OSM-Netz, ohne Ampeln, Wartezeiten, Steigung oder Barrierefreiheit.
Treppen zählen wie ebener Weg.
"""

from __future__ import annotations

import heapq
import math
import time
from typing import Any, Iterable

from ..config import Settings
from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, haversine_m, now_iso
from .overpass import LICENSE, run_query

# Wege, auf denen man zu Fuß unterwegs sein darf. Autobahnen und Schnellstraßen
# fehlen bewusst — an genau denen soll die Rechnung scheitern, wo der
# Luftlinienkreis blind hindurchgeht.
FUSSWEGE = (
    "footway|path|pedestrian|steps|living_street|residential|service|"
    "unclassified|tertiary|tertiary_link|secondary|secondary_link|primary|"
    "primary_link|track|cycleway|road|corridor|platform"
)

# Das Netz muss über den Umkreis hinausreichen: der kürzeste Fußweg zu einem
# Ziel am Rand führt oft ein Stück nach außen. Faktor aus der Messung — mit 1,8
# lag der Umwegfaktor im 90. Perzentil (1,58) sicher innerhalb des geladenen
# Ausschnitts.
NETZ_PUFFER = 1.8

# Ein Punkt, der weiter als das vom nächsten Wegeknoten entfernt liegt, ist
# nicht sinnvoll ans Netz anzuschließen (mitten im Feld, im Gebäudeinneren).
MAX_ANBINDUNG_M = 150.0

# Übliche Gehgeschwindigkeit für die Umrechnung in Minuten. Gewählter Wert,
# kein Messwert — er steht deshalb in der Ausgabe mit dabei.
GEHTEMPO_M_PRO_MIN = 80.0


def _tempo_hinweis() -> str:
    kmh = f"{GEHTEMPO_M_PRO_MIN * 60 / 1000:.1f}".replace(".", ",")
    return (
        f"Gehzeit gerechnet mit {GEHTEMPO_M_PRO_MIN:.0f} m/min "
        f"({kmh} km/h) — ein gewählter Wert, kein gemessener."
    )


def build_query(lat: float, lon: float, radius: int, timeout: int = 90) -> str:
    """Nur die Geometrie der Wege, keine Tags außer den nötigen."""
    reichweite = int(radius * NETZ_PUFFER)
    return (
        f"[out:json][timeout:{timeout}];\n"
        f'way["highway"~"^({FUSSWEGE})$"](around:{reichweite},{lat},{lon});\n'
        f"out geom;"
    )


def _begehbar(tags: dict[str, str]) -> bool:
    """OSM-Angaben, die einen Weg für Fußgänger ausschließen."""
    if tags.get("foot") in ("no", "private"):
        return False
    if tags.get("access") in ("no", "private") and tags.get("foot") not in ("yes", "designated"):
        return False
    return True


class Wegenetz:
    """Ungerichteter Graph aus Wegsegmenten mit einfachem Gitterindex.

    Knoten sind gerundete Koordinaten. OSM-Wege teilen sich an Kreuzungen
    denselben Knoten und damit exakt dieselbe Koordinate — das Runden verbindet
    sie also korrekt und trennt Brücke und Unterführung weiterhin, weil deren
    Geometrien keinen gemeinsamen Punkt haben.
    """

    # Kantenlänge der Indexzellen in Grad, rund 110 m in der Breite.
    ZELLE = 0.001

    def __init__(self) -> None:
        self.kanten: dict[tuple[float, float], list[tuple[tuple[float, float], float]]] = {}
        self._index: dict[tuple[int, int], list[tuple[float, float]]] = {}
        self.wege = 0
        self.uebersprungen = 0

    def __len__(self) -> int:
        return len(self.kanten)

    @property
    def kantenzahl(self) -> int:
        return sum(len(v) for v in self.kanten.values()) // 2

    def _zelle(self, lat: float, lon: float) -> tuple[int, int]:
        return (int(lat / self.ZELLE), int(lon / self.ZELLE))

    def _merke(self, knoten: tuple[float, float]) -> None:
        if knoten not in self.kanten:
            self.kanten[knoten] = []
            self._index.setdefault(self._zelle(*knoten), []).append(knoten)

    def verbinde(self, a: tuple[float, float], b: tuple[float, float], laenge: float) -> None:
        self._merke(a)
        self._merke(b)
        self.kanten[a].append((b, laenge))
        self.kanten[b].append((a, laenge))

    def naechster_knoten(
        self, lat: float, lon: float, max_m: float = MAX_ANBINDUNG_M
    ) -> tuple[tuple[float, float] | None, float]:
        """Nächster Wegeknoten über den Gitterindex — ringweise nach außen."""
        zl, zo = self._zelle(lat, lon)
        bester: tuple[float, float] | None = None
        beste = float("inf")
        # Ein Ring entspricht rund 110 m; mehr als MAX_ANBINDUNG_M brauchen wir nicht.
        max_ringe = int(max_m / (self.ZELLE * 111_320)) + 2
        for ring in range(max_ringe):
            kandidaten: list[tuple[float, float]] = []
            for dl in range(-ring, ring + 1):
                for do in range(-ring, ring + 1):
                    if ring and max(abs(dl), abs(do)) != ring:
                        continue  # nur der neue Rand
                    kandidaten.extend(self._index.get((zl + dl, zo + do), ()))
            for k in kandidaten:
                d = haversine_m(lat, lon, k[0], k[1])
                if d < beste:
                    bester, beste = k, d
            # Erst abbrechen, wenn der gefundene Knoten näher ist als der
            # nächste ungeprüfte Ring sein könnte.
            if bester is not None and beste <= ring * self.ZELLE * 111_320:
                break
        if bester is None or beste > max_m:
            return None, beste
        return bester, beste


def baue_netz(elements: Iterable[dict[str, Any]]) -> Wegenetz:
    netz = Wegenetz()
    for el in elements:
        if el.get("type") != "way":
            continue
        tags = el.get("tags") or {}
        if not _begehbar(tags):
            netz.uebersprungen += 1
            continue
        geom = el.get("geometry") or []
        if len(geom) < 2:
            continue
        netz.wege += 1
        for a, b in zip(geom, geom[1:]):
            ka = (round(a["lat"], 6), round(a["lon"], 6))
            kb = (round(b["lat"], 6), round(b["lon"], 6))
            if ka == kb:
                continue
            netz.verbinde(ka, kb, haversine_m(ka[0], ka[1], kb[0], kb[1]))
    return netz


def gehstrecken(
    netz: Wegenetz, start: tuple[float, float], max_m: float
) -> dict[tuple[float, float], float]:
    """Dijkstra vom Startknoten, abgebrochen jenseits von ``max_m``."""
    dist = {start: 0.0}
    warteschlange = [(0.0, start)]
    while warteschlange:
        d, k = heapq.heappop(warteschlange)
        if d > dist.get(k, math.inf):
            continue
        if d > max_m:
            continue  # weiter außen brauchen wir nichts
        for nachbar, laenge in netz.kanten.get(k, ()):
            nd = d + laenge
            if nd <= max_m and nd < dist.get(nachbar, math.inf):
                dist[nachbar] = nd
                heapq.heappush(warteschlange, (nd, nachbar))
    return dist


def _minuten(meter: float) -> float:
    return round(meter / GEHTEMPO_M_PRO_MIN, 1)


def bewerte(
    netz: Wegenetz,
    dist: dict[tuple[float, float], float],
    anbindung: float,
    objekte: list[dict[str, Any]],
    radius: int,
) -> dict[str, Any]:
    """Hängt jedem Objekt die Gehstrecke an und zählt aus, was herausfällt.

    ``gehweg_m`` ist ``None``, wenn das Objekt zu Fuß nicht innerhalb des Radius
    erreichbar ist — das ist ausdrücklich **nicht** dasselbe wie „weit weg".
    """
    treffer = 0
    ausserhalb = 0
    ohne_anbindung = 0
    faktoren: list[float] = []

    for o in objekte:
        lat, lon = o.get("lat"), o.get("lon")
        if lat is None or lon is None:
            continue
        knoten, anschluss = netz.naechster_knoten(lat, lon)
        if knoten is None:
            o["gehweg_m"] = None
            o["gehweg_grund"] = "kein Weg in der Nähe erfasst"
            ohne_anbindung += 1
            continue
        d = dist.get(knoten)
        if d is None:
            o["gehweg_m"] = None
            o["gehweg_grund"] = "zu Fuß nicht im Umkreis erreichbar"
            if o.get("distanz_m", radius + 1) <= radius:
                ausserhalb += 1
            continue
        gesamt = d + anschluss + anbindung
        o["gehweg_m"] = round(gesamt)
        o["gehweg_minuten"] = _minuten(gesamt)
        o["gehweg_grund"] = None
        luft = o.get("distanz_m")
        if luft and luft <= radius:
            if gesamt > radius:
                ausserhalb += 1
            else:
                treffer += 1
            if luft > 20:
                faktoren.append(gesamt / luft)

    faktoren.sort()
    im_kreis = treffer + ausserhalb
    return {
        "im_gehradius": treffer,
        "nur_luftlinie": ausserhalb,
        "im_luftlinienkreis": im_kreis,
        # Anteil des Luftlinienkreises, der zu Fuß tatsächlich erreichbar ist.
        # Erst diese Verhältniszahl macht zwei Standorte vergleichbar — die
        # absolute Differenz sagt vor allem, dass ein Fußwegradius eine kleinere
        # Fläche umfasst als ein gleich großer Luftlinienradius.
        "erschliessungsgrad": (
            round(treffer / im_kreis * 100, 1) if im_kreis else None
        ),
        "ohne_anbindung": ohne_anbindung,
        "umwegfaktor_median": (
            round(faktoren[len(faktoren) // 2], 2) if faktoren else None
        ),
        "umwegfaktor_p90": (
            round(faktoren[int(len(faktoren) * 0.9)], 2) if faktoren else None
        ),
    }


def erreichbare_zellen(
    netz: Wegenetz,
    dist: dict[tuple[float, float], float],
    anbindung: float,
    zellen: list[dict[str, Any]],
    radius: int,
) -> dict[str, Any]:
    """Zensuszellen nach Gehstrecke filtern.

    Angesetzt wird der Zellmittelpunkt. Eine 100-m-Zelle ist eine Fläche, die
    teils erreichbar sein kann und teils nicht — die Zuordnung ist deshalb eine
    Näherung und wird als solche ausgewiesen.
    """
    einwohner_gesamt = 0.0
    einwohner_gehweg = 0.0
    drin = 0
    draussen = 0
    for z in zellen:
        # zensus.build_cells legt den Mittelpunkt als "_center" ab.
        mitte = z.get("_center") or []
        lat, lon = (mitte + [None, None])[:2] if mitte else (z.get("lat"), z.get("lon"))
        ew = z.get("Einwohner")
        if lat is None or lon is None or not isinstance(ew, (int, float)):
            continue
        einwohner_gesamt += ew
        knoten, anschluss = netz.naechster_knoten(lat, lon)
        d = dist.get(knoten) if knoten is not None else None
        if d is not None and d + anschluss + anbindung <= radius:
            einwohner_gehweg += ew
            drin += 1
        else:
            draussen += 1
    return {
        "zellen_im_gehradius": drin,
        "zellen_nur_luftlinie": draussen,
        "einwohner_luftlinie": round(einwohner_gesamt) if einwohner_gesamt else None,
        "einwohner_gehweg": round(einwohner_gehweg) if einwohner_gesamt else None,
        "erschliessungsgrad": (
            round(einwohner_gehweg / einwohner_gesamt * 100, 1)
            if einwohner_gesamt
            else None
        ),
        "hinweis": (
            "Angesetzt ist der Mittelpunkt der 100-m-Zelle. Eine Zelle kann "
            "teilweise erreichbar sein; die Zuordnung ist eine Näherung."
        ),
    }


HINWEISE = [
    "600 m Fußweg und 600 m Luftlinie sind nicht dasselbe Gebiet. Bei einem "
    "Umwegfaktor von 1,4 entspricht ein 600-m-Fußweg etwa einem Luftlinienkreis "
    "von 430 m — also gut der halben Fläche. Der Rückgang ist deshalb keine "
    "Korrektur eines Fehlers, sondern eine andere, engere Definition des "
    "Einzugsgebiets. Vergleichbar zwischen Standorten wird sie über den "
    "Erschließungsgrad.",
    "Gerechnet wird die Länge des kürzesten Weges im OSM-Fußwegenetz — ohne "
    "Ampeln, Wartezeiten, Steigung und Barrierefreiheit. Treppen zählen wie "
    "ebener Weg.",
    "Das Netz stammt aus OpenStreetMap und ist wie alle OSM-Daten unvollständig. "
    "Ein nicht erfasster Durchgang lässt einen Weg länger erscheinen, als er ist.",
    "Wege mit `foot=no` oder `access=private` bleiben unberücksichtigt. Ein "
    "faktisch begehbarer, aber so getaggter Durchgang fällt damit heraus.",
]


async def load(
    out: Outbound,
    settings: Settings,
    lat: float,
    lon: float,
    radius: int,
    *,
    objekte: dict[str, list[dict[str, Any]]] | None = None,
    zellen: list[dict[str, Any]] | None = None,
) -> SourceResult:
    started = time.perf_counter()
    query = build_query(lat, lon, radius, timeout=int(settings.overpass_timeout))
    try:
        payload, endpoint, problems = await run_query(out, settings, query)
    except SourceError as err:
        return SourceResult.failed(
            "gehweg", err, int((time.perf_counter() - started) * 1000)
        )

    elements = payload.get("elements", []) if isinstance(payload, dict) else []
    netz = baue_netz(elements)
    warnungen = list(problems)

    if not len(netz):
        return SourceResult(
            name="gehweg",
            ok=True,
            data=None,
            duration_ms=int((time.perf_counter() - started) * 1000),
            warnings=warnungen
            + [
                "Im Umkreis ist kein begehbares Wegenetz erfasst. Ohne Netz "
                "bleibt es bei der Luftlinie."
            ],
            provenance=Provenance(
                source="OpenStreetMap Fußwegenetz über Overpass",
                license=LICENSE,
                endpoint=endpoint,
            ),
        )

    start, anbindung = netz.naechster_knoten(lat, lon)
    if start is None:
        return SourceResult(
            name="gehweg",
            ok=True,
            data=None,
            duration_ms=int((time.perf_counter() - started) * 1000),
            warnings=warnungen
            + [
                f"Der gewählte Punkt liegt mehr als {MAX_ANBINDUNG_M:.0f} m vom "
                "nächsten erfassten Weg entfernt. Eine Gehstrecke lässt sich "
                "daraus nicht sinnvoll ableiten."
            ],
            provenance=Provenance(
                source="OpenStreetMap Fußwegenetz über Overpass",
                license=LICENSE,
                endpoint=endpoint,
            ),
        )

    t0 = time.perf_counter()
    dist = gehstrecken(netz, start, float(radius))
    rechenzeit = int((time.perf_counter() - t0) * 1000)

    data: dict[str, Any] = {
        "knoten": len(netz),
        "kanten": netz.kantenzahl,
        "wege": netz.wege,
        "wege_gesperrt": netz.uebersprungen,
        "anbindung_m": round(anbindung),
        "erreichbare_knoten": len(dist),
        "rechenzeit_ms": rechenzeit,
        "radius_m": radius,
        "gehtempo_m_pro_min": GEHTEMPO_M_PRO_MIN,
        "gehzeit_minuten": _minuten(radius),
        "hinweise": [*HINWEISE, _tempo_hinweis()],
    }

    for name, liste in (objekte or {}).items():
        data[name] = bewerte(netz, dist, anbindung, liste, radius)
        if name == "gastronomie":
            # Die Einzelstrecken sind ohnehin gerechnet; als schlanke Zuordnung
            # OSM-Kennung → Meter kann die Betriebsliste sie mit anzeigen,
            # ohne dass die Objekte doppelt gespeichert werden.
            data["gehstrecke_je_id"] = {
                str(o["id"]): o["gehweg_m"]
                for o in liste
                if o.get("id") is not None and o.get("gehweg_m") is not None
            }
    if zellen is not None:
        data["zensus"] = erreichbare_zellen(netz, dist, anbindung, zellen, radius)

    return SourceResult(
        name="gehweg",
        ok=True,
        data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnungen,
        provenance=Provenance(
            source="OpenStreetMap Fußwegenetz über Overpass",
            license=LICENSE,
            endpoint=endpoint,
            stand=(payload.get("osm3s") or {}).get("timestamp_osm_base"),
            retrieved_at=now_iso(),
            note=(
                "Kürzester Weg im OSM-Fußwegenetz, berechnet mit Dijkstra. "
                "Keine Wegbeschreibung, keine Wartezeiten."
            ),
        ),
    )
