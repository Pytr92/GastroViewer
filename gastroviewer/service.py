"""Zusammenführung der Quellen: Cache davor, Fehler je Quelle isoliert.

Zwei Regeln aus der Spec bestimmen den Aufbau:

* §7 „Cache greift: zweiter Aufruf desselben Punkts erzeugt keinen Outbound-Traffic."
  Deshalb liegt der Cache **vor** dem Laden, nicht darin. Bei einem Treffer wird
  die Loader-Funktion nie aufgerufen, also kann kein Aufruf hinausgehen.
* §5 „Fällt eine Quelle aus, laufen die übrigen weiter." Deshalb ``gather`` mit
  ``return_exceptions=True`` und je Quelle ein eigenes Ergebnisobjekt.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

from .cache import AsyncCache, cache_key
from .config import Settings
from .http import Outbound
from .sources import (bayern, boris, gehweg, links, marke as marke_mod, muenchen,
                      nominatim, overpass, planung, scan as scan_mod, zensus)
from .sources.base import Provenance, SourceError, SourceResult

Loader = Callable[[], Awaitable[SourceResult]]


class PointService:
    def __init__(self, settings: Settings, cache: AsyncCache, outbound: Outbound) -> None:
        self.settings = settings
        self.cache = cache
        self.outbound = outbound

    async def _cached(
        self, source: str, key: str, loader: Loader, *, refresh: bool = False
    ) -> SourceResult:
        ttl = self.settings.ttl_for(source)
        if not refresh:
            hit = await self.cache.get(key)
            if hit is not None:
                result = SourceResult(**{**hit["payload"], "provenance": None})
                prov = hit["payload"].get("provenance")
                if prov:
                    result.provenance = Provenance(**prov)
                    result.provenance.cached = True
                    age = int(time.time() - hit["fetched_at"])
                    result.provenance.note = (
                        (result.provenance.note or "")
                        + f" [aus dem lokalen Cache, {age} s alt]"
                    ).strip()
                return result

        try:
            result = await loader()
        except SourceError as err:
            return SourceResult.failed(source, err)
        except Exception as exc:  # noqa: BLE001 — darf die anderen Quellen nicht reißen
            return SourceResult.failed(
                source, SourceError("unknown", f"{type(exc).__name__}: {exc}")
            )

        if result.ok:
            await self.cache.set(key, source, result.to_dict(), ttl)
        return result

    # ------------------------------------------------------------ Quellen

    async def zensus(self, lat: float, lon: float, radius: int, refresh: bool = False):
        key = cache_key("zensus", lat, lon, radius)
        return await self._cached(
            "zensus",
            key,
            lambda: zensus.load(self.outbound, self.settings, lat, lon, radius),
            refresh=refresh,
        )

    async def osm(self, lat: float, lon: float, radius: int, refresh: bool = False):
        key = cache_key("overpass", lat, lon, radius)
        return await self._cached(
            "overpass",
            key,
            lambda: overpass.load(self.outbound, self.settings, lat, lon, radius),
            refresh=refresh,
        )

    async def adresse(self, lat: float, lon: float, refresh: bool = False):
        key = cache_key("nominatim_reverse", lat, lon, 0)
        return await self._cached(
            "nominatim_reverse",
            key,
            lambda: nominatim.reverse(self.outbound, self.settings, lat, lon),
            refresh=refresh,
        )

    async def suche(self, query: str, refresh: bool = False):
        key = f"nominatim_search|{query.strip().lower()}"
        return await self._cached(
            "nominatim_search",
            key,
            lambda: nominatim.search(self.outbound, self.settings, query),
            refresh=refresh,
        )

    async def radzaehlung(self, lat: float, lon: float, radius: int, refresh: bool = False):
        # Die sechs Zählstellen ändern sich nicht stündlich; der Cache-Schlüssel
        # rundet ohnehin auf 4 Nachkommastellen. TTL wie OSM: 24 h.
        key = cache_key("muenchen_rad", lat, lon, radius)
        return await self._cached(
            "muenchen_rad",
            key,
            lambda: muenchen.zaehlstellen(self.outbound, self.settings, lat, lon, radius),
            refresh=refresh,
        )

    async def verkehrsmenge(self, lat: float, lon: float, radius: int, refresh: bool = False):
        key = cache_key("baysis", lat, lon, radius)
        return await self._cached(
            "baysis",
            key,
            lambda: bayern.verkehrsmengen(self.outbound, self.settings, lat, lon, radius),
            refresh=refresh,
        )

    async def gehweg(self, lat: float, lon: float, radius: int, refresh: bool = False):
        """Gehstrecken statt Luftlinie.

        Bewusst **nicht** Teil von :meth:`point`: das Wegenetz ist mit 1–3 MB je
        Punkt die mit Abstand größte Overpass-Antwort des Werkzeugs. Es wird nur
        geladen, wenn es angefordert wird, und liegt dann lange im Cache — ein
        Fußwegenetz ändert sich in Wochen, nicht in Stunden.

        Die Bewertung braucht die Objekte aus OSM und die Zensuszellen. Beide
        kommen aus dem Cache, wenn der Punkt schon geladen war; sonst werden sie
        hier nachgeholt.
        """
        key = cache_key("gehweg", lat, lon, radius)

        async def laden() -> SourceResult:
            osm_res, zensus_res = await asyncio.gather(
                self.osm(lat, lon, radius),
                self.zensus(lat, lon, radius),
                return_exceptions=True,
            )
            objekte: dict[str, list[dict[str, Any]]] = {}
            if isinstance(osm_res, SourceResult) and osm_res.ok and osm_res.data:
                for feld in ("gastronomie", "frequenzbringer", "oepnv", "leerstand"):
                    liste = osm_res.data.get(feld)
                    if liste:
                        # Kopien: die Gehstrecke gehört in den Gehweg-Block und
                        # darf den zwischengespeicherten OSM-Block nicht ändern.
                        objekte[feld] = [dict(o) for o in liste]
            zellen = None
            if isinstance(zensus_res, SourceResult) and zensus_res.ok and zensus_res.data:
                zellen = zensus_res.data.get("zellen")
            return await gehweg.load(
                self.outbound,
                self.settings,
                lat,
                lon,
                radius,
                objekte=objekte,
                zellen=zellen,
            )

        return await self._cached("gehweg", key, laden, refresh=refresh)

    async def gehweg_aus_cache(
        self, lat: float, lon: float, radius: int
    ) -> SourceResult | None:
        """Nur nachsehen, nie laden.

        Beim Merken eines Punktes darf keine 1–3-MB-Abfrage ausgelöst werden.
        Wer den Gehwegblock vorher geöffnet hat, bekommt die Werte in die
        Vergleichstabelle; wer nicht, bekommt dort leere Felder.
        """
        hit = await self.cache.get(cache_key("gehweg", lat, lon, radius))
        if hit is None:
            return None
        payload = dict(hit["payload"])
        prov = payload.pop("provenance", None)
        result = SourceResult(**payload)
        if prov:
            result.provenance = Provenance(**prov)
            result.provenance.cached = True
        return result

    async def gitter(self, ebene: str, west: float, sued: float, ost: float, nord: float):
        """Übersichtsgitter für den Kartenausschnitt, mit Kachel-Cache.

        Die Box wird auf ein Raster nach außen gerundet — leichtes Schwenken
        trifft so denselben Cache-Eintrag, statt den Dienst erneut zu fragen.
        """
        w, s, o, n = zensus.gitter_kachel(ebene, west, sued, ost, nord)
        key = f"zensus_gitter|{ebene}|{w:.2f}|{s:.2f}|{o:.2f}|{n:.2f}"

        async def laden() -> SourceResult:
            started = time.perf_counter()
            try:
                zellen, warnungen = await zensus.fetch_gitter(
                    self.outbound, self.settings, ebene, w, s, o, n
                )
            except SourceError as err:
                return SourceResult.failed("zensus_gitter", err)
            return SourceResult(
                name="zensus_gitter",
                ok=True,
                data={"ebene": ebene, "kachel": [w, s, o, n], "zellen": zellen},
                duration_ms=int((time.perf_counter() - started) * 1000),
                warnings=warnungen,
                provenance=Provenance(
                    source=f"Zensus 2022, {ebene}-Gitter (Statistische Ämter des Bundes und der Länder)",
                    license=zensus.LICENSE,
                    stand=f"Stichtag {zensus.STICHTAG}",
                ),
            )

        return await self._cached("zensus_gitter", key, laden)

    async def marke(self, lat: float, lon: float, radius: int, marke: str):
        """Gebietsschutz-Check: Betriebe der eigenen Marke im großen Umkreis.

        Gecacht wird die **markenunabhängige** Basis (alle Gastronomie im
        Radius) — eine Regex-Suche auf dem Server lief in den Timeout, und so
        bedient ein Abruf jede weitere Markensuche am selben Punkt. Der
        Markenfilter selbst ist reine Python-Rechnung.
        """
        basis = await self._cached(
            "marke_basis",
            cache_key("marke_basis", lat, lon, radius),
            lambda: marke_mod.load_basis(self.outbound, self.settings, lat, lon, radius),
        )
        if not basis.ok:
            return basis
        return marke_mod.suche(basis, marke, lat, lon, radius)

    async def scan(self, west: float, sued: float, ost: float, nord: float):
        """Flächen-Scan: Einwohner je Gastronomiebetrieb im 300-m-Umfeld,
        je 100-m-Zelle. Die Box wird wie beim Übersichtsgitter auf ein Raster
        nach außen gerundet, damit leichtes Schwenken den Cache trifft statt
        Zensus und Overpass erneut zu fragen."""
        w, s, o, n = scan_mod.scan_kachel(west, sued, ost, nord)
        key = f"scan|{w:.2f}|{s:.2f}|{o:.2f}|{n:.2f}"
        return await self._cached(
            "scan",
            key,
            lambda: scan_mod.load(self.outbound, self.settings, w, s, o, n),
        )

    async def planung(self, lat: float, lon: float, radius: int, refresh: bool = False):
        """Planungsrecht und Hochwasserrisiko. Beides aendert sich in Jahren,
        nicht in Stunden — deshalb dieselbe lange Haltbarkeit wie das Wegenetz."""
        key = cache_key("planung", lat, lon, radius)
        return await self._cached(
            "planung",
            key,
            lambda: planung.load(self.outbound, self.settings, lat, lon, radius),
            refresh=refresh,
        )

    async def gtfs(self, lat: float, lon: float, radius: int):
        """Rein lokal (SQLite aus dem Import) — kein Cache, kein Outbound."""
        from .sources import gtfs as gtfs_mod

        return await asyncio.to_thread(
            gtfs_mod.load, self.settings, lat, lon, radius
        )

    # -------------------------------------------------------- Gesamtpunkt

    async def point(
        self, lat: float, lon: float, radius: int, refresh: bool = False
    ) -> dict[str, Any]:
        started = time.perf_counter()
        outbound_before = await asyncio.to_thread(self.cache.sync.outbound_count)

        results = await asyncio.gather(
            self.adresse(lat, lon, refresh),
            self.zensus(lat, lon, radius, refresh),
            self.osm(lat, lon, radius, refresh),
            self.gtfs(lat, lon, radius),
            self.radzaehlung(lat, lon, radius, refresh),
            self.verkehrsmenge(lat, lon, radius, refresh),
            self.planung(lat, lon, radius, refresh),
            return_exceptions=True,
        )
        names = ["adresse", "zensus", "osm", "gtfs", "radzaehlung", "verkehrsmenge",
                 "planung"]
        blocks: dict[str, Any] = {}
        for name, res in zip(names, results):
            if isinstance(res, BaseException):
                blocks[name] = SourceResult.failed(
                    name, SourceError("unknown", f"{type(res).__name__}: {res}")
                ).to_dict()
            else:
                blocks[name] = res.to_dict()

        adresse = blocks["adresse"].get("data") or {}
        zensus_data = blocks["zensus"].get("data") or {}
        ags = zensus_data.get("ags")
        bl_code = zensus_data.get("bundesland_code")
        gemeinde = adresse.get("gemeinde")
        plz = adresse.get("plz")

        # Gegenprobe: Bundesland aus AGS gegen ISO-Code von Nominatim.
        hinweise: list[str] = []
        iso = adresse.get("bundesland_iso")
        if iso and bl_code:
            from .sources.zensus import BUNDESLAENDER

            iso_land = {
                "DE-BW": "08", "DE-BY": "09", "DE-BE": "11", "DE-BB": "12",
                "DE-HB": "04", "DE-HH": "02", "DE-HE": "06", "DE-MV": "13",
                "DE-NI": "03", "DE-NW": "05", "DE-RP": "07", "DE-SL": "10",
                "DE-SN": "14", "DE-ST": "15", "DE-SH": "01", "DE-TH": "16",
            }.get(iso)
            if iso_land and iso_land != bl_code:
                hinweise.append(
                    f"Bundesland uneindeutig: aus dem Gemeindeschlüssel folgt "
                    f"{BUNDESLAENDER.get(bl_code)}, Nominatim meldet {iso}. "
                    "Der Punkt liegt vermutlich nah an einer Landesgrenze."
                )

        outbound_after = await asyncio.to_thread(self.cache.sync.outbound_count)

        return {
            "punkt": {
                "lat": lat,
                "lon": lon,
                "radius_m": radius,
                "adresse": adresse.get("display_name"),
                "gemeinde": gemeinde,
                "ortsteil": adresse.get("ortsteil"),
                "plz": plz,
                "ags": ags,
                "ags_quelle": zensus_data.get("ags_quelle"),
                "bundesland": zensus_data.get("bundesland") or adresse.get("bundesland"),
                "bundesland_code": bl_code,
            },
            "bloecke": blocks,
            "bodenrichtwerte": boris.links_for(bl_code, gemeinde),
            "weiterfuehrend": links.build(
                lat, lon, radius, gemeinde=gemeinde, plz=plz, ags=ags
            ),
            "hinweise": hinweise,
            "grenzen": GRENZEN,
            "meta": {
                "erzeugt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "dauer_ms": int((time.perf_counter() - started) * 1000),
                "outbound_requests": outbound_after - outbound_before,
                "aus_cache": outbound_after == outbound_before,
            },
        }


# Spec §8: gehört in die UI, nicht ins Kleingedruckte.
GRENZEN = [
    "OSM ist unvollständig, besonders bei kleinen Imbissen und Neueröffnungen. "
    "Die angezeigte Wettbewerbsdichte ist eine Untergrenze.",
    "Zensus-Stichtag ist der 15.05.2022 mit stochastischer Überlagerung. "
    "Neubaugebiete nach 2022 fehlen.",
    "Öffnungszeiten werden unverändert aus OSM übernommen und nicht interpretiert. "
    "Die opening_hours-Syntax kennt Feiertage, Saisons und Ausnahmen — ein einfacher "
    "Parser deckt das nicht ab.",
    "Passantenströme fehlen komplett. Fußgängerzone und Seitenstraße sind in diesen "
    "Daten nicht unterscheidbar. Dafür hystreet, GTFS-Abfahrten und eigene Zählung.",
    "Die Umsatzstärke der Wettbewerber ist unbekannt.",
]
