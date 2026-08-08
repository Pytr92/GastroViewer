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
from .sources import (airbnb as airbnb_mod,
                      bast as bast_mod,
                      baustellen as baustellen_mod, bayern,
                      berlin as berlin_mod, boris,
                      dynamik as dynamik_mod,
                      hamburg as hamburg_mod,
                      einkommen as einkommen_mod, gehweg,
                      genesis as genesis_mod,
                      indikatoren as indikatoren_mod,
                      klima as klima_mod, kreisprofil as kreisprofil_mod,
                      laerm as laerm_mod, links,
                      maerkte as maerkte_mod,
                      marke as marke_mod, messe as messe_mod,
                      muenchen, nominatim, overpass,
                      overture as overture_mod,
                      leerstandsmelder as lsm_mod,
                      luft as luft_mod,
                      pendler as pendler_mod, pks as pks_mod, planung,
                      register as register_mod, scan as scan_mod,
                      sonne as sonne_mod,
                      tourismus as tourismus_mod, wahl as wahl_mod, zensus)
from .sources.base import Provenance, SourceError, SourceResult, now_iso

Loader = Callable[[], Awaitable[SourceResult]]


class PointService:
    def __init__(self, settings: Settings, cache: AsyncCache, outbound: Outbound) -> None:
        self.settings = settings
        self.cache = cache
        self.outbound = outbound
        # Laufende Abrufe je Cache-Key. Die Block-Endpunkte treffen parallel
        # ein — ohne Deduplizierung lösten z. B. /api/point/osm und
        # /api/point/gehweg bei kaltem Cache zwei identische Overpass-Abfragen
        # aus. Der Rate-Limiter serialisiert Duplikate nur, verhindern muss
        # sie diese Stelle (§7: Spendendienste nicht doppelt fragen).
        self._laufend: dict[str, asyncio.Task] = {}

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

        laufend = self._laufend.get(key)
        if laufend is None:
            # Als eigenständige Task, damit der Abruf weiterläuft, falls der
            # anstoßende Request abbricht — Mitwartende bekommen ihn trotzdem.
            laufend = asyncio.create_task(self._laden(source, key, loader, ttl))
            self._laufend[key] = laufend
            laufend.add_done_callback(lambda _t: self._laufend.pop(key, None))
        return await laufend

    async def _laden(
        self, source: str, key: str, loader: Loader, ttl: int
    ) -> SourceResult:
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

    async def vorschlaege(self, query: str):
        """Autocomplete-Vorschläge (nur Photon) — je Eingabe gecacht."""
        key = f"vorschlaege|{query.strip().lower()}"
        return await self._cached(
            "vorschlaege",
            key,
            lambda: nominatim.vorschlaege(self.outbound, self.settings, query),
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
            # Parser mit Sekunden-Laufzeit gehören in einen Thread — sonst
            # steht der ganze Server, solange die Jahresdatei gelesen wird.
            stationen = await asyncio.to_thread(muenchen.parse_tageswerte, text)
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
            kompakt = await asyncio.to_thread(indikatoren_mod.reduzieren, texte)
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

    async def _airbnb_stadt(self, slug: str, refresh: bool = False) -> dict[str, Any]:
        """Stadtweiter Inside-Airbnb-Datensatz, reduziert — **einmal** je
        Stadt gecacht (30 Tage): Datenseite nach der aktuellen Snapshot-URL
        fragen, CSV laden, auf fünf Felder je Inserat eindampfen. Jeder
        Punkt in der Stadt rechnet danach nur noch lokal."""

        async def laden() -> SourceResult:
            index_html = await self.outbound.get_text(
                "airbnb", airbnb_mod.INDEX_URL, timeout=60.0,
                limiter="airbnb", min_interval=1.0,
            )
            urls = airbnb_mod.finde_stadt_urls(index_html)
            fund = urls.get(slug)
            if fund is None:
                raise SourceError(
                    "api_error",
                    f"Die Datenseite von Inside Airbnb führt „{slug}“ nicht "
                    "(mehr) — Stadtliste geändert?",
                )
            csv_text = await self.outbound.get_text(
                "airbnb", fund["url"], timeout=120.0,
                limiter="airbnb", min_interval=1.0,
            )
            listings = await asyncio.to_thread(airbnb_mod.reduzieren, csv_text)
            if not listings:
                raise SourceError(
                    "parse", "Die listings.csv ließ sich nicht lesen."
                )
            return SourceResult(
                name="airbnb", ok=True,
                data={"listings": listings, "stichtag": fund["datum"],
                      "quelle_url": fund["url"]},
            )

        res = await self._cached("airbnb", f"airbnb|{slug}", laden, refresh=refresh)
        if not res.ok:
            raise SourceError(
                (res.error or {}).get("kind", "unknown"),
                (res.error or {}).get("message", "unbekannter Fehler"),
            )
        return res.data

    async def airbnb(
        self, lat: float, lon: float, radius: int,
        adresse: dict[str, Any] | None, refresh: bool = False,
    ):
        """Kurzzeitvermietung im Umkreis. Braucht die Gemeinde aus der schon
        geladenen Adresse — außerhalb der abgedeckten Städte geht keine
        Anfrage hinaus."""
        a = adresse or {}
        return await airbnb_mod.load(
            self.settings, a.get("gemeinde"), lat, lon, radius,
            lambda slug: self._airbnb_stadt(slug, refresh),
        )

    async def genesis(self, ags: str):
        """Amtliche Gastro-Anker (Regionaldatenbank, Opt-in mit Kennung) —
        je Kreis gecacht. Ohne Kennung wird **nichts** gecacht: sobald die
        Kennung hinterlegt ist, soll der erste Abruf sofort laufen, statt
        30 Tage auf einen leeren Cache-Eintrag zu warten."""
        if genesis_mod.lade_zugang(self.settings) is None:
            return await genesis_mod.load(self.outbound, self.settings, ags)
        # Gemeindegenau cachen — seit den Gemeindetabellen unterscheiden
        # sich die Blockdaten innerhalb desselben Kreises.
        gemeinde = "".join(c for c in str(ags) if c.isdigit())[:8] or "unbekannt"
        return await self._cached(
            "genesis",
            f"genesis|{gemeinde}",
            lambda: genesis_mod.load(self.outbound, self.settings, ags),
        )

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
        # Zählstellen ändern sich nicht stündlich; der Cache-Schlüssel
        # rundet ohnehin auf 4 Nachkommastellen. TTL wie OSM: 24 h.
        if hamburg_mod.in_hamburg(lat, lon):
            key = cache_key("hamburg_rad", lat, lon, radius)
            return await self._cached(
                "hamburg_rad",
                key,
                lambda: hamburg_mod.rad_load(
                    self.outbound, self.settings, lat, lon, radius),
                refresh=refresh,
            )
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
        """Städtische Märkte (München oder Hamburg). Außerhalb der
        Stadtgebiete entscheidet die Quelle selbst — dann geht keine
        Anfrage hinaus."""
        if hamburg_mod.in_hamburg(lat, lon):
            key = cache_key("hamburg_maerkte", lat, lon, radius)
            return await self._cached(
                "hamburg_maerkte",
                key,
                lambda: hamburg_mod.maerkte_load(
                    self.outbound, self.settings, lat, lon, radius),
                refresh=refresh,
            )
        key = cache_key("muenchen_maerkte", lat, lon, radius)
        return await self._cached(
            "muenchen_maerkte",
            key,
            lambda: maerkte_mod.load(self.outbound, self.settings, lat, lon, radius),
            refresh=refresh,
        )

    async def baustellen(self, lat: float, lon: float, radius: int, refresh: bool = False):
        """Baustellen: München (Vier-Wochen-Vorschau), Hamburg
        („Bauweiser"-Steckbriefe) oder Berlin (VIZ). Außerhalb entscheidet
        die Münchner Quelle selbst — dann geht keine Anfrage hinaus."""
        if hamburg_mod.in_hamburg(lat, lon):
            key = cache_key("hamburg_baustellen", lat, lon, radius)
            return await self._cached(
                "hamburg_baustellen",
                key,
                lambda: hamburg_mod.baustellen_load(
                    self.outbound, self.settings, lat, lon, radius),
                refresh=refresh,
            )
        if berlin_mod.in_berlin(lat, lon):
            key = cache_key("berlin_baustellen", lat, lon, radius)
            return await self._cached(
                "berlin_baustellen",
                key,
                lambda: berlin_mod.baustellen_load(
                    self.outbound, self.settings, lat, lon, radius),
                refresh=refresh,
            )
        key = cache_key("muenchen_baustellen", lat, lon, radius)
        return await self._cached(
            "muenchen_baustellen",
            key,
            lambda: baustellen_mod.load(
                self.outbound, self.settings, lat, lon, radius
            ),
            refresh=refresh,
        )

    async def messe(self, lat: float, lon: float, refresh: bool = False):
        """Messe-Kalender München. Jenseits von 20 km um die Gelände
        entscheidet die Quelle selbst — dann geht keine Anfrage hinaus.
        Standard-TTL 24 h: der Kalender lebt vom aktuellen „heute"."""
        key = cache_key("muenchen_messe", lat, lon, 0)
        return await self._cached(
            "muenchen_messe",
            key,
            lambda: messe_mod.load(self.outbound, self.settings, lat, lon),
            refresh=refresh,
        )

    async def tourismus(self, lat: float, lon: float, refresh: bool = False):
        """Tourismus-Saisonalität München (stadtweite Monatszahlen).
        Außerhalb des Stadtgebiets entscheidet die Quelle selbst."""
        key = cache_key("muenchen_tourismus", lat, lon, 0)
        return await self._cached(
            "muenchen_tourismus",
            key,
            lambda: tourismus_mod.load(self.outbound, self.settings, lat, lon),
            refresh=refresh,
        )

    async def _bast_zaehlstellen(self, refresh: bool = False) -> list[dict[str, Any]]:
        """Bundesweite BASt-Jahresdatei, **einmal** geladen und als
        reduzierte Zählstellenliste gecacht (Jahresdatei — lange TTL).
        Jeder Punkt außerhalb Bayerns rechnet danach lokal."""

        async def laden() -> SourceResult:
            csv_text = await self.outbound.get_text(
                "bast", bast_mod.CSV_URL, timeout=120.0,
                limiter="bast", min_interval=1.0,
                encoding="latin-1",
            )
            stellen = await asyncio.to_thread(bast_mod.parse_zaehlstellen, csv_text)
            if not stellen:
                raise SourceError(
                    "parse", "BASt-Jahresdatei ohne verwertbare Zählstellen.")
            return SourceResult(name="bast", ok=True,
                                data={"zaehlstellen": stellen})

        res = await self._cached("bast", f"bast|{bast_mod.JAHR}", laden,
                                 refresh=refresh)
        if not res.ok or not res.data:
            raise SourceError(
                (res.error or {}).get("kind", "unknown"),
                (res.error or {}).get("message", "unbekannter Fehler"),
            )
        return res.data["zaehlstellen"]

    async def verkehrsmenge(self, lat: float, lon: float, radius: int, refresh: bool = False):
        """In Bayern BAYSIS (9 441 Zählstellen, ganzes klassifiziertes
        Netz), sonst die bundesweiten BASt-Dauerzählstellen."""
        if bayern.in_bayern(lat, lon):
            key = cache_key("baysis", lat, lon, radius)
            return await self._cached(
                "baysis",
                key,
                lambda: bayern.verkehrsmengen(self.outbound, self.settings, lat, lon, radius),
                refresh=refresh,
            )
        key = cache_key("bast_punkt", lat, lon, radius)
        return await self._cached(
            "bast_punkt",
            key,
            lambda: bast_mod.verkehrsmengen(
                lat, lon, radius,
                lambda: self._bast_zaehlstellen(refresh)),
            refresh=refresh,
        )

    async def _pks_kreise(self, refresh: bool = False) -> dict[str, Any]:
        """Bundesweite BKA-Kreistabelle (XLSX), **einmal** geladen und
        reduziert gecacht (Berichtsjahr — lange TTL). Jeder Punkt schlägt
        danach nur noch lokal nach."""

        async def laden() -> SourceResult:
            daten = await self.outbound.get_bytes(
                "pks", pks_mod.XLSX_URL, timeout=120.0,
                limiter="pks", min_interval=1.0,
            )
            # Die bundesweite XLSX per ElementTree zu lesen dauert mehrere
            # Sekunden CPU-Zeit — im Event-Loop fröre derweil alles ein.
            kreise = await asyncio.to_thread(
                lambda: pks_mod.aufbereiten(pks_mod.zeilen_aus_xlsx(daten)))
            return SourceResult(name="pks", ok=True, data={"kreise": kreise})

        res = await self._cached("pks", f"pks|{pks_mod.JAHR}", laden,
                                 refresh=refresh)
        if not res.ok or not res.data:
            raise SourceError(
                (res.error or {}).get("kind", "unknown"),
                (res.error or {}).get("message", "unbekannter Fehler"),
            )
        return res.data["kreise"]

    async def pks(self, ags: str, refresh: bool = False):
        """Sicherheitslage des Kreises aus der PKS-Kreistabelle."""
        key = f"pks_kreis|{pks_mod.JAHR}|{(ags or '')[:5]}"
        return await self._cached(
            "pks_kreis",
            key,
            lambda: pks_mod.load(ags, lambda: self._pks_kreise(refresh)),
            refresh=refresh,
        )

    async def _lsm_meldungen(self, refresh: bool = False) -> list[dict[str, Any]]:
        """Leerstandsmelder-Weltbestand (ein 3-MB-Abruf), reduziert
        gecacht — jeder Punkt filtert danach lokal nach Entfernung."""

        async def laden() -> SourceResult:
            roh = await self.outbound.get_json(
                "leerstandsmelder", lsm_mod.API_URL, timeout=120.0,
                limiter="leerstandsmelder", min_interval=1.0,
            )
            meldungen = lsm_mod.parse_meldungen(roh)
            if not meldungen:
                raise SourceError(
                    "parse", "Leerstandsmelder-Bestand ohne verwertbare "
                    "Meldungen — Format geändert?")
            return SourceResult(name="leerstandsmelder", ok=True,
                                data={"meldungen": meldungen})

        res = await self._cached("leerstandsmelder", "leerstandsmelder|welt",
                                 laden, refresh=refresh)
        if not res.ok or not res.data:
            raise SourceError(
                (res.error or {}).get("kind", "unknown"),
                (res.error or {}).get("message", "unbekannter Fehler"),
            )
        return res.data["meldungen"]

    async def leerstandsmelder(self, lat: float, lon: float, radius: int,
                               refresh: bool = False):
        key = cache_key("leerstandsmelder_punkt", lat, lon, radius)
        return await self._cached(
            "leerstandsmelder_punkt",
            key,
            lambda: lsm_mod.load(
                lat, lon, radius, lambda: self._lsm_meldungen(refresh)),
            refresh=refresh,
        )

    async def _luft_stationen(self, refresh: bool = False) -> list[dict[str, Any]]:
        """Stationsliste des Luftmessnetzes, **einmal** geladen und
        reduziert gecacht — je Punkt wird nur die nächste Station
        abgefragt."""

        async def laden() -> SourceResult:
            roh = await self.outbound.get_json(
                "luft_stationen", luft_mod.STATIONS_URL, timeout=60.0,
                limiter="luft", min_interval=1.0,
            )
            return SourceResult(name="luft_stationen", ok=True,
                                data={"stationen": luft_mod.parse_stationen(roh)})

        res = await self._cached("luft_stationen", "luft|stationen", laden,
                                 refresh=refresh)
        if not res.ok or not res.data:
            raise SourceError(
                (res.error or {}).get("kind", "unknown"),
                (res.error or {}).get("message", "unbekannter Fehler"),
            )
        return res.data["stationen"]

    async def luft(self, lat: float, lon: float, refresh: bool = False):
        key = cache_key("luft_punkt", lat, lon, 0)
        return await self._cached(
            "luft_punkt",
            key,
            lambda: luft_mod.load(
                self.outbound, lat, lon,
                lambda: self._luft_stationen(refresh)),
            refresh=refresh,
        )

    async def sonne(self, lat: float, lon: float, refresh: bool = False):
        """Besonnung am Punkt. Der Gebäudebestand ändert sich langsam, das
        Ergebnis darf deshalb lange liegen bleiben; das Jahr geht in den
        Schlüssel ein, damit die Stichtage zum Kalender passen."""
        jahr = int(now_iso()[:4])
        key = cache_key(f"sonne_{jahr}", lat, lon, sonne_mod.UMKREIS_M)
        return await self._cached(
            "sonne",
            key,
            lambda: sonne_mod.load(self.outbound, self.settings, lat, lon, jahr),
            refresh=refresh,
        )

    async def _wahl_daten(self, refresh: bool = False):
        """kerg2 + Wahlkreis-Zuordnung, **einmal** geladen (endgültiges
        Ergebnis — ändert sich bis zur nächsten Wahl nicht)."""

        async def laden() -> SourceResult:
            kerg2 = await self.outbound.get_text(
                "wahl", wahl_mod.KERG2_URL, timeout=120.0,
                limiter="wahl", min_interval=1.0)
            zuordnung = await self.outbound.get_text(
                "wahl", wahl_mod.MAPPING_URL, timeout=120.0,
                limiter="wahl", min_interval=1.0)
            return SourceResult(name="wahl", ok=True, data={
                "zuordnung": await asyncio.to_thread(
                    wahl_mod.parse_mapping, zuordnung),
                "kreise": await asyncio.to_thread(wahl_mod.parse_kerg2, kerg2),
            })

        res = await self._cached("wahl", "wahl|btw25", laden, refresh=refresh)
        if not res.ok or not res.data:
            raise SourceError(
                (res.error or {}).get("kind", "unknown"),
                (res.error or {}).get("message", "unbekannter Fehler"),
            )
        return res.data["zuordnung"], res.data["kreise"]

    async def wahl(self, ags: str, refresh: bool = False):
        key = f"wahl_gemeinde|{(ags or '')[:8]}"
        return await self._cached(
            "wahl_gemeinde",
            key,
            lambda: wahl_mod.load(
                self.outbound, ags, lambda: self._wahl_daten(refresh)),
            refresh=refresh,
        )

    async def register(self, plz: str | None, refresh: bool = False):
        """Handelsregister-Umfeld (OffeneRegister, Stand 2019) — rein
        lokal aus der einmal importierten Datenbank."""
        if not self.settings.register_db_path.exists():
            # Nicht cachen: direkt nach dem Import soll der Block Zahlen
            # zeigen, nicht die 30 Tage alte „bitte importieren"-Antwort.
            return await register_mod.load(self.settings, plz)
        key = f"register|{plz or 'ohne'}"
        return await self._cached(
            "register",
            key,
            lambda: register_mod.load(self.settings, plz),
            refresh=refresh,
        )

    async def oepnv_einzug(
        self, lat: float, lon: float, minuten: int = 30,
        refresh: bool = False,
    ) -> SourceResult:
        """ÖPNV-Einzugsgebiet aus dem lokal importierten GTFS-Fahrplan —
        auf Anforderung (wie die Gehweg-Auswertung), weil die Rechnung
        einige Sekunden dauert. Einwohner-Näherung über das 1-km-Gitter:
        Zellen, in deren Nähe ein erreichter Halt liegt."""
        if not self.settings.gtfs_db_path.exists():
            # Nicht cachen — wie beim Register: direkt nach `import-gtfs`
            # soll der Block rechnen, nicht die alte „nicht importiert"-
            # Antwort bis zu 24 h aus dem Cache wiederholen.
            from .sources import gtfs as gtfs_mod
            return SourceResult(
                name="oepnv_einzug", ok=True, data=None,
                warnings=[
                    "Kein GTFS-Fahrplan importiert — einmalig "
                    "`gastroviewer import-gtfs` ausführen."],
                provenance=Provenance(
                    source="GTFS-Fahrplan (nicht importiert)",
                    license=gtfs_mod.LICENSE),
            )
        key = cache_key("oepnv_einzug", lat, lon, minuten)

        async def laden() -> SourceResult:
            started = time.perf_counter()
            from .sources import gtfs as gtfs_mod
            from .sources.base import haversine_m

            data = await asyncio.to_thread(
                gtfs_mod.einzugsgebiet, self.settings, lat, lon, minuten)
            if data is None:
                return SourceResult(
                    name="oepnv_einzug", ok=True, data=None,
                    warnings=[
                        "Kein GTFS-Fahrplan importiert — einmalig "
                        "`gastroviewer import-gtfs` ausführen."],
                    provenance=Provenance(
                        source="GTFS-Fahrplan (nicht importiert)",
                        license=gtfs_mod.LICENSE),
                )

            halte = data["halte"]
            warnungen: list[str] = []
            if halte:
                # Einwohner-Näherung: 1-km-Zellen, deren Mittelpunkt
                # höchstens ~700 m von einem erreichten Halt liegt.
                w = min(h["lon"] for h in halte) - 0.02
                o = max(h["lon"] for h in halte) + 0.02
                s = min(h["lat"] for h in halte) - 0.015
                n = max(h["lat"] for h in halte) + 0.015
                gitter = await self.gitter("1km", w, s, o, n)
                if gitter.ok and gitter.data:
                    einwohner = 0
                    zellen_mit_halt = 0
                    for z in gitter.data["zellen"]:
                        ring = z.get("ring") or []
                        if not ring:
                            continue
                        clat = sum(p[1] for p in ring) / len(ring)
                        clon = sum(p[0] for p in ring) / len(ring)
                        if any(haversine_m(clat, clon, h["lat"], h["lon"]) <= 700
                               for h in halte):
                            zellen_mit_halt += 1
                            ew = z.get("einwohner")
                            if isinstance(ew, (int, float)) and ew > 0:
                                einwohner += ew
                    data["einwohner_naeherung"] = round(einwohner)
                    data["einwohner_zellen"] = zellen_mit_halt
                    warnungen.extend(gitter.warnings or [])
                else:
                    warnungen.append(
                        "Einwohner-Näherung nicht möglich — das "
                        "Zensus-Gitter war nicht erreichbar.")
            data["hinweise"] = [
                "Runden-Router mit benannten Vereinfachungen: Ankunft = "
                "Abfahrtszeit am Halt, Fußwege als Luftlinie (75 m/min, "
                "Einstieg ≤ 600 m, Umstieg ≤ 200 m + 2 min), höchstens "
                "zwei Umstiege, Referenz-Dienstag 12:00 — dieselbe "
                "Tageskonvention wie der Abfahrten-Block.",
                "Es gilt der beim GTFS-Import gewählte Ausschnitt — "
                "Halte außerhalb existieren für die Rechnung nicht.",
                "Die Einwohnerzahl ist eine grobe Näherung über das "
                "1-km-Zensusgitter (Zellen nahe erreichter Halte) — keine "
                "Gehweg-Genauigkeit.",
            ]
            return SourceResult(
                name="oepnv_einzug", ok=True, data=data,
                duration_ms=int((time.perf_counter() - started) * 1000),
                warnings=warnungen,
                provenance=Provenance(
                    source="GTFS-Fahrplan (lokal importiert) + Zensus 2022 "
                           "1-km-Gitter",
                    license=gtfs_mod.LICENSE,
                    stand=f"Referenztag {data['referenztag']['date']}",
                    retrieved_at=now_iso(),
                    note="Rechnung läuft vollständig lokal; nur die "
                         "Einwohner-Näherung fragt das Zensus-Gitter "
                         "(mit Kachel-Cache).",
                ),
            )

        return await self._cached("oepnv_einzug", key, laden, refresh=refresh)

    async def kannibalisierung(
        self, a: dict[str, Any], b: dict[str, Any]
    ) -> dict[str, Any]:
        """Kannibalisierungs-Check zweier gespeicherter Punkte: Welche
        Einwohner liegen in **beiden** Umkreisen? Gerechnet über die
        100-m-Zensuszellen (Luftlinie, Zensus 2022) — die Merkliste warnt
        bislang nur, DASS sich Kreise überschneiden; hier steht, wie viele
        Menschen sich die Kandidaten teilen."""
        from .sources.base import haversine_m
        from .sources.zensus import build_cells, fetch_cells

        dist = haversine_m(a["lat"], a["lon"], b["lat"], b["lon"])
        grunddaten = {
            "a": {"label": a.get("label"), "radius_m": a["radius"]},
            "b": {"label": b.get("label"), "radius_m": b["radius"]},
            "distanz_m": round(dist),
        }
        if dist >= a["radius"] + b["radius"]:
            return {**grunddaten, "ueberlappung": False,
                    "gemeinsame_einwohner": 0}

        def ew(zelle: dict[str, Any]) -> float:
            v = zelle.get("Einwohner")
            return v if isinstance(v, (int, float)) and v > 0 else 0

        def innerhalb(zelle, lat, lon, radius):
            c = zelle.get("_center")
            return bool(c) and haversine_m(lat, lon, c[0], c[1]) <= radius

        zellen_a = build_cells((await fetch_cells(
            self.outbound, self.settings, a["lat"], a["lon"], a["radius"]))[0])
        zellen_b = build_cells((await fetch_cells(
            self.outbound, self.settings, b["lat"], b["lon"], b["radius"]))[0])

        ew_a = sum(ew(z) for z in zellen_a)
        ew_b = sum(ew(z) for z in zellen_b)
        gemeinsam = sum(
            ew(z) for z in zellen_a
            if innerhalb(z, b["lat"], b["lon"], b["radius"]))

        return {
            **grunddaten,
            "ueberlappung": True,
            "einwohner_a": round(ew_a),
            "einwohner_b": round(ew_b),
            "gemeinsame_einwohner": round(gemeinsam),
            "anteil_an_a_prozent": round(gemeinsam / ew_a * 100, 1) if ew_a else None,
            "anteil_an_b_prozent": round(gemeinsam / ew_b * 100, 1) if ew_b else None,
            "hinweise": [
                "Luftlinien-Umkreise auf dem 100-m-Zensusgitter "
                "(Stichtag 15.05.2022) — Flüsse, Gleise und Gehstrecken "
                "sieht die Rechnung nicht; die Gehweg-Auswertung je Punkt "
                "bleibt der genauere Blick.",
                "Gezählt werden Zellen, deren Mittelpunkt in beiden "
                "Umkreisen liegt — Randzellen können leicht abweichen.",
            ],
        }

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
            self.messe(lat, lon, refresh),
            self.tourismus(lat, lon, refresh),
            self.leerstandsmelder(lat, lon, radius, refresh),
            self.luft(lat, lon, refresh),
            return_exceptions=True,
        )
        names = ["adresse", "zensus", "osm", "gtfs", "radzaehlung", "verkehrsmenge",
                 "planung", "klima", "dynamik", "baustellen", "maerkte",
                 "messe", "tourismus", "leerstandsmelder", "luft"]
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

        # Kurzzeitvermietung: braucht die Gemeinde aus der Adresse.
        try:
            blocks["airbnb"] = (
                await self.airbnb(lat, lon, radius, adresse, refresh)
            ).to_dict()
        except Exception as exc:  # noqa: BLE001
            blocks["airbnb"] = SourceResult.failed(
                "airbnb", SourceError("unknown", f"{type(exc).__name__}: {exc}")
            ).to_dict()

        # Registerumfeld: braucht die Postleitzahl aus der Adresse.
        try:
            blocks["register"] = (
                await self.register(adresse.get("plz"), refresh)
            ).to_dict()
        except Exception as exc:  # noqa: BLE001
            blocks["register"] = SourceResult.failed(
                "register", SourceError("unknown", f"{type(exc).__name__}: {exc}")
            ).to_dict()

        bl_code = zensus_data.get("bundesland_code")
        if ags:
            kreis_results = await asyncio.gather(
                self.einkommen(ags), self.kreisprofil(ags), self.pendler(ags),
                self.laerm(lat, lon, bl_code), self.genesis(ags),
                self.pks(ags), self.wahl(ags),
                return_exceptions=True,
            )
            for name, res in zip(("einkommen", "kreisprofil", "pendler", "laerm",
                                  "genesis", "pks", "wahl"),
                                 kreis_results):
                if isinstance(res, BaseException):
                    blocks[name] = SourceResult.failed(
                        name, SourceError("unknown", f"{type(res).__name__}: {res}")
                    ).to_dict()
                else:
                    blocks[name] = res.to_dict()
        else:
            for name in ("einkommen", "kreisprofil", "pendler", "genesis", "pks",
                         "wahl"):
                blocks[name] = SourceResult(
                    name=name, ok=True, data=None,
                    warnings=["Ohne Gemeindeschlüssel lässt sich kein Kreiswert zuordnen."],
                ).to_dict()
            # Der Lärmdienst braucht keinen Gemeindeschlüssel — der
            # UBA-Bundesdienst deckt ganz Deutschland ab.
            try:
                blocks["laerm"] = (await self.laerm(lat, lon, bl_code)).to_dict()
            except Exception as exc:  # noqa: BLE001
                blocks["laerm"] = SourceResult.failed(
                    "laerm",
                    SourceError("unknown", f"{type(exc).__name__}: {exc}"),
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
