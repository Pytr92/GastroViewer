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
from .sources import (baustellen as baustellen_mod, bayern, boris,
                      dynamik as dynamik_mod,
                      einkommen as einkommen_mod, gehweg,
                      indikatoren as indikatoren_mod,
                      klima as klima_mod, kreisprofil as kreisprofil_mod,
                      laerm as laerm_mod, links,
                      maerkte as maerkte_mod,
                      marke as marke_mod, muenchen, nominatim, overpass,
                      overture as overture_mod,
                      pendler as pendler_mod, planung, scan as scan_mod, zensus)
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

    async def _rad_jahresgang(self):
        """Tageswerte des jüngsten Jahres, geparst — **einmal** stadtweit
        gecacht, nicht je Punkt: dieselbe Datei beantwortet jeden Münchner
        Punkt. Dateiname über die CKAN-API aufgelöst, nie geraten."""

        async def laden() -> SourceResult:
            listing = await self.outbound.get_json(
                "muenchen_rad_jahr", muenchen.CKAN_JAHRESZAHLEN, timeout=45.0,
                limiter="muenchen", min_interval=1.0,
            )
            fund = muenchen.finde_tageswerte(listing)
            if not fund:
                raise SourceError(
                    "api_error",
                    "Keine Tageswerte-Ressource im Open-Data-Portal gefunden.",
                )
            jahr, url = fund
            text = await self.outbound.get_text(
                "muenchen_rad_jahr", url, timeout=60.0,
                limiter="muenchen", min_interval=1.0,
            )
            stationen = muenchen.parse_tageswerte(text)
            if not stationen:
                raise SourceError(
                    "parse", f"Tageswerte {jahr} ließen sich nicht lesen."
                )
            return SourceResult(
                name="muenchen_rad_jahr", ok=True,
                data={"jahr": jahr, "stationen": stationen},
            )

        res = await self._cached("muenchen_rad_jahr", "muenchen_rad_jahr", laden)
        if not res.ok:
            raise SourceError(
                (res.error or {}).get("kind", "unknown"),
                (res.error or {}).get("message", "unbekannter Fehler"),
            )
        return res.data

    async def _indikatoren_stadt(self):
        """Indikatorenatlas: eine CKAN-Suche plus sechs CSVs — **einmal**
        stadtweit gecacht und schon auf die kompakten Reihen reduziert.
        Jeder Münchner Punkt rechnet danach nur noch lokal."""

        async def laden() -> SourceResult:
            listing = await self.outbound.get_json(
                "muenchen_indikatoren", indikatoren_mod.CKAN_SEARCH_URL,
                params=indikatoren_mod.CKAN_SEARCH_PARAMS, timeout=45.0,
                limiter="muenchen", min_interval=1.0,
            )
            urls, fehlend = indikatoren_mod.finde_csv_urls(listing)
            if not urls:
                raise SourceError(
                    "api_error",
                    "Keine Indikatorenatlas-CSVs im Open-Data-Portal gefunden.",
                )
            texte: dict[str, str] = {}
            for datei, url in urls.items():
                texte[datei] = await self.outbound.get_text(
                    "muenchen_indikatoren", url, timeout=60.0,
                    limiter="muenchen", min_interval=1.0,
                )
            kompakt = indikatoren_mod.reduzieren(texte)
            if not kompakt:
                raise SourceError(
                    "parse", "Indikatorenatlas-CSVs ließen sich nicht lesen."
                )
            jahre = [
                reihe[-1][0]
                for raeume in kompakt.values()
                for reihe in raeume.values()
                if reihe
            ]
            stand = f"Jahresreihen bis {max(jahre)}" if jahre else None
            warn = [
                f"Im Open-Data-Portal nicht gefunden: {t}" for t in fehlend
            ]
            return SourceResult(
                name="muenchen_indikatoren", ok=True,
                data={"kompakt": kompakt, "stand": stand,
                      "fehlend_warnungen": warn},
            )

        res = await self._cached(
            "muenchen_indikatoren", "muenchen_indikatoren", laden
        )
        if not res.ok:
            raise SourceError(
                (res.error or {}).get("kind", "unknown"),
                (res.error or {}).get("message", "unbekannter Fehler"),
            )
        return res.data

    async def indikatoren(self, adresse: dict[str, Any] | None):
        """Viertel-Steckbrief. Braucht Gemeinde und Ortsteil aus der schon
        geladenen Adresse — deshalb nach dem Sammeln, ohne eigene Anfrage
        außerhalb Münchens."""
        a = adresse or {}
        return await indikatoren_mod.load(
            self.outbound, self.settings,
            a.get("gemeinde"), a.get("ortsteil"),
            self._indikatoren_stadt,
        )

    async def radzaehlung(self, lat: float, lon: float, radius: int, refresh: bool = False):
        # Die sechs Zählstellen ändern sich nicht stündlich; der Cache-Schlüssel
        # rundet ohnehin auf 4 Nachkommastellen. TTL wie OSM: 24 h.
        key = cache_key("muenchen_rad", lat, lon, radius)
        return await self._cached(
            "muenchen_rad",
            key,
            lambda: muenchen.zaehlstellen(
                self.outbound, self.settings, lat, lon, radius,
                jahresgang_laden=self._rad_jahresgang,
            ),
            refresh=refresh,
        )

    async def maerkte(self, lat: float, lon: float, radius: int, refresh: bool = False):
        """Städtische Märkte München. Außerhalb des Stadtgebiets entscheidet
        die Quelle selbst — dann geht keine Anfrage hinaus."""
        key = cache_key("muenchen_maerkte", lat, lon, radius)
        return await self._cached(
            "muenchen_maerkte",
            key,
            lambda: maerkte_mod.load(self.outbound, self.settings, lat, lon, radius),
            refresh=refresh,
        )

    async def baustellen(self, lat: float, lon: float, radius: int, refresh: bool = False):
        """Baustellen-Vorschau der Stadt München. Außerhalb des Stadtgebiets
        entscheidet die Quelle selbst — dann geht keine Anfrage hinaus."""
        key = cache_key("muenchen_baustellen", lat, lon, radius)
        return await self._cached(
            "muenchen_baustellen",
            key,
            lambda: baustellen_mod.load(
                self.outbound, self.settings, lat, lon, radius
            ),
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

    async def einkommen(self, ags: str):
        """Verfügbares Einkommen je Einwohner (VGRdL) — je Kreis gecacht,
        denn der Wert ist für jeden Punkt im selben Kreis identisch."""
        kreis = einkommen_mod.kreis_aus_ags(ags) or "unbekannt"
        return await self._cached(
            "einkommen",
            f"einkommen|{kreis}",
            lambda: einkommen_mod.load(self.outbound, self.settings, ags),
        )

    async def kreisprofil(self, ags: str):
        """Kreisprofil (Tourismus, Arbeitsort, Arbeitsmarkt, Bevölkerung,
        Wirtschaftskraft) — wie das Einkommen je Kreis gecacht, gleicher
        Dienst, gleiche TTL. Schlüssel „v2": seit der BIP-Erweiterung wäre
        ein alter Cache-Eintrag unvollständig — er läuft einfach aus."""
        kreis = einkommen_mod.kreis_aus_ags(ags) or "unbekannt"
        return await self._cached(
            "kreisprofil",
            f"kreisprofil|v2|{kreis}",
            lambda: kreisprofil_mod.load(self.outbound, self.settings, ags),
        )

    async def pendler(self, ags: str) -> SourceResult:
        """Pendlerverflechtungen der Gemeinde (Pendleratlas).

        Die CSV-Dateien sind Deutschland- bzw. Land-weit und werden je Datei
        gecacht; das fertige Gemeindeergebnis zusätzlich je AGS. Das
        Berichtsjahr wird absteigend gesucht — der Atlas führt keinen
        „latest"-Zeiger, ein 404 heißt schlicht: Jahrgang (noch) nicht da."""
        a = "".join(c for c in str(ags) if c.isdigit())[:8]
        if len(a) < 8:
            return SourceResult(
                name="pendler", ok=True, data=None,
                warnings=["Ohne Gemeindeschlüssel lässt sich keine Gemeinde zuordnen."],
            )

        async def laden() -> SourceResult:
            started = time.perf_counter()
            warnungen: list[str] = []

            async def datei(key: str, url: str, als_json: bool) -> Any:
                cache_id = f"pendler_datei|{key}"

                async def holen() -> SourceResult:
                    if als_json:
                        data = await self.outbound.get_json(
                            "pendler", url, timeout=self.settings.zensus_timeout
                        )
                    else:
                        data = await self.outbound.get_text(
                            "pendler", url, timeout=self.settings.zensus_timeout
                        )
                    return SourceResult(name="pendler", ok=True, data=data)

                res = await self._cached("pendler", cache_id, holen)
                if not res.ok:
                    raise SourceError(
                        (res.error or {}).get("kind", "unknown"),
                        (res.error or {}).get("message", "unbekannter Fehler"),
                    )
                return res.data

            # Berichtsjahr absteigend suchen (der Atlas begann mit 2021).
            jahr = None
            heute = time.gmtime().tm_year
            letzte: SourceError | None = None
            for kandidat in range(heute, 2020, -1):
                try:
                    await datei(
                        f"{kandidat}|EIP_Karte",
                        pendler_mod.datei_urls(kandidat, a[:2])["EIP_Karte"],
                        als_json=False,
                    )
                    jahr = kandidat
                    break
                except SourceError as err:
                    letzte = err
                    continue
            if jahr is None:
                return SourceResult.failed(
                    "pendler",
                    letzte or SourceError("api_error",
                                          "Kein Berichtsjahr im Pendleratlas erreichbar."),
                    int((time.perf_counter() - started) * 1000),
                )

            urls = pendler_mod.datei_urls(jahr, a[:2])
            karten_texte: dict[str, str] = {}
            for datei_name, _, _ in pendler_mod.KARTEN:
                try:
                    karten_texte[datei_name] = await datei(
                        f"{jahr}|{datei_name}", urls[datei_name], als_json=False
                    )
                except SourceError as err:
                    warnungen.append(f"{datei_name}: {err.message}")
            try:
                gemeinden = (await datei(
                    f"{jahr}|gemeinden", urls["gemeinden"], als_json=True
                )).get("features") or []
            except SourceError as err:
                return SourceResult.failed(
                    "pendler", err, int((time.perf_counter() - started) * 1000)
                )
            verfl = None
            try:
                verfl = await datei(f"{jahr}|Verfl_L{a[:2]}", urls["Verfl"],
                                    als_json=False)
            except SourceError as err:
                warnungen.append(f"Verflechtungen: {err.message}")

            data = pendler_mod.auswerten(a, jahr, gemeinden, karten_texte, verfl)
            return pendler_mod.ergebnis(data, started, warnungen, jahr)

        return await self._cached("pendler", f"pendler|{a}", laden)

    async def liefergebiet(self, lat: float, lon: float, minuten: int) -> SourceResult:
        """Rad-Liefergebiet — wie der Gehweg-Block nur auf Anforderung, denn
        das Wegenetz für 10 Minuten Rad ist eine große Overpass-Abfrage.
        Die Zensuszellen für das größere Gebiet laufen über den normalen
        Zensus-Cache."""
        from .sources import liefergebiet as liefer_mod

        minuten = max(liefer_mod.MIN_MINUTEN,
                      min(liefer_mod.MAX_MINUTEN, int(minuten)))
        key = cache_key("liefergebiet", lat, lon, minuten)

        async def laden() -> SourceResult:
            radius = int(minuten * liefer_mod.RADTEMPO_M_PRO_MIN)
            zellen = None
            zensus_res = await self.zensus(lat, lon, radius)
            if zensus_res.ok and zensus_res.data:
                zellen = zensus_res.data.get("zellen")
            return await liefer_mod.load(
                self.outbound, self.settings, lat, lon, minuten, zellen
            )

        return await self._cached("liefergebiet", key, laden)

    async def dynamik(self, lat: float, lon: float, radius: int, refresh: bool = False):
        """Gastro-Dynamik aus der OSM-Historie (ohsome). Zwei kleine
        POST-Anfragen je Punkt; der jüngste Datenpunkt ist der 1. Januar,
        entsprechend lange darf das Ergebnis liegen bleiben."""
        key = cache_key("dynamik", lat, lon, radius)
        return await self._cached(
            "dynamik",
            key,
            lambda: dynamik_mod.load(self.outbound, self.settings, lat, lon, radius),
            refresh=refresh,
        )

    async def laerm(self, lat: float, lon: float, bundesland_code: str | None):
        """Straßenlärm am Punkt (LfU Bayern). Braucht das Bundesland aus dem
        Zensus — außerhalb Bayerns bleibt der Block mit Begründung leer,
        ohne dass eine Anfrage hinausgeht."""
        key = cache_key("laerm", lat, lon, 0) + f"|{bundesland_code or '-'}"
        return await self._cached(
            "laerm",
            key,
            lambda: laerm_mod.load(
                self.outbound, self.settings, lat, lon, bundesland_code
            ),
        )

    async def klima(self, lat: float, lon: float) -> SourceResult:
        """Klimanormalwerte der nächsten DWD-Station.

        Gecacht werden die **Deutschland-weiten Dateien je Parameter** —
        nicht der Punkt: dieselben zehn Dateien beantworten jede Anfrage im
        ganzen Land, und die Normalperiode 1991–2020 ändert sich nicht.
        Die Stationswahl je Punkt ist danach reine lokale Rechnung."""
        started = time.perf_counter()

        async def datei(eintrag: dict) -> SourceResult:
            key = f"klima_datei|{eintrag['datei']}"

            async def laden() -> SourceResult:
                data = await klima_mod.lade_parameter(
                    self.outbound, self.settings, eintrag
                )
                return SourceResult(name="klima", ok=True, data=data)

            return await self._cached("klima", key, laden)

        results = await asyncio.gather(
            *(datei(e) for e in klima_mod.PARAMETER), return_exceptions=True
        )
        dateien: dict[str, Any] = {}
        warnungen: list[str] = []
        for eintrag, res in zip(klima_mod.PARAMETER, results):
            if isinstance(res, BaseException):
                warnungen.append(f"{eintrag['titel']}: {res}")
            elif res.ok and res.data:
                dateien[eintrag["schluessel"]] = res.data
            else:
                grund = (res.error or {}).get("message", "unbekannter Fehler")
                warnungen.append(f"{eintrag['titel']}: {grund}")
        return klima_mod.ergebnis(lat, lon, dateien, started, warnungen)

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

    async def overture(self, lat: float, lon: float, radius: int) -> SourceResult:
        """Zweite Wettbewerbsquelle (lokaler Overture-Import). Braucht die
        OSM-Gastronomie für den Abgleich — die kommt aus dem normalen
        OSM-Cache, es geht also keine zusätzliche Anfrage hinaus."""
        osm_res = await self.osm(lat, lon, radius)
        osm_gastro = None
        if osm_res.ok and osm_res.data:
            osm_gastro = osm_res.data.get("gastronomie")
        return await asyncio.to_thread(
            overture_mod.load, self.settings, lat, lon, radius, osm_gastro
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
            self.klima(lat, lon),
            self.dynamik(lat, lon, radius, refresh),
            self.baustellen(lat, lon, radius, refresh),
            self.maerkte(lat, lon, radius, refresh),
            return_exceptions=True,
        )
        names = ["adresse", "zensus", "osm", "gtfs", "radzaehlung", "verkehrsmenge",
                 "planung", "klima", "dynamik", "baustellen", "maerkte"]
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

        # Einkommen und Kreisprofil brauchen den Gemeindeschlüssel aus dem
        # Zensus — deshalb nach dem Sammeln, nicht parallel dazu. Je Kreis
        # gecacht; untereinander laufen die beiden wieder parallel.
        # Overture-Abgleich: rein lokal, braucht die schon geladene
        # OSM-Gastronomie — deshalb nach dem Sammeln.
        try:
            blocks["overture"] = (await self.overture(lat, lon, radius)).to_dict()
        except Exception as exc:  # noqa: BLE001
            blocks["overture"] = SourceResult.failed(
                "overture", SourceError("unknown", f"{type(exc).__name__}: {exc}")
            ).to_dict()

        # Viertel-Steckbrief: braucht Gemeinde/Ortsteil aus der Adresse.
        try:
            blocks["indikatoren"] = (await self.indikatoren(adresse)).to_dict()
        except Exception as exc:  # noqa: BLE001
            blocks["indikatoren"] = SourceResult.failed(
                "indikatoren", SourceError("unknown", f"{type(exc).__name__}: {exc}")
            ).to_dict()

        bl_code = zensus_data.get("bundesland_code")
        if ags:
            kreis_results = await asyncio.gather(
                self.einkommen(ags), self.kreisprofil(ags), self.pendler(ags),
                self.laerm(lat, lon, bl_code),
                return_exceptions=True,
            )
            for name, res in zip(("einkommen", "kreisprofil", "pendler", "laerm"),
                                 kreis_results):
                if isinstance(res, BaseException):
                    blocks[name] = SourceResult.failed(
                        name, SourceError("unknown", f"{type(res).__name__}: {res}")
                    ).to_dict()
                else:
                    blocks[name] = res.to_dict()
        else:
            for name in ("einkommen", "kreisprofil", "pendler"):
                blocks[name] = SourceResult(
                    name=name, ok=True, data=None,
                    warnings=["Ohne Gemeindeschlüssel lässt sich kein Kreiswert zuordnen."],
                ).to_dict()
            blocks["laerm"] = SourceResult(
                name="laerm", ok=True, data=None,
                warnings=["Ohne Bundesland (aus dem Zensusblock) lässt sich "
                          "kein Lärmdienst zuordnen."],
            ).to_dict()
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
    "Öffnungszeiten aus OSM werden nur bewertet, wo die Angabe vollständig aus "
    "einfachen Wochentag-Uhrzeit-Regeln besteht — Feiertags-, Saison- und "
    "Sonderregeln bleiben unbewertet. Alle Öffnungszeiten-Zahlen sind deshalb "
    "Mindestzahlen („mindestens X von Y“).",
    "Passantenströme fehlen komplett. Fußgängerzone und Seitenstraße sind in diesen "
    "Daten nicht unterscheidbar. Dafür hystreet, GTFS-Abfahrten und eigene Zählung.",
    "Die Umsatzstärke der Wettbewerber ist unbekannt.",
]
