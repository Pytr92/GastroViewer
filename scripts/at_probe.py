"""Live-Probe der österreichischen Dienste — läuft in GitHub Actions, nicht lokal.

Aus der Entwicklungsumgebung sind die Datenhosts nicht erreichbar; die
Formate der österreichischen Gegenstücke (docs/oesterreich.md) müssen aber
belegt sein, bevor ein Modul sie liest. Dieses Skript fragt jeden Dienst
einmal an, schreibt die Antwort (gekürzt) nach ``fixtures/at/`` und ein
``manifest.json`` mit Status, Größe, Content-Type und Fehlern. Der Workflow
``at-probe.yml`` legt das Ergebnis auf dem Branch ``claude/at-probe`` ab.

Bewusst sparsam: je Dienst eine Handvoll Abrufe, keine Massendownloads
außer dem Eurostat-Raster (ein ZIP), aus dem nur drei Fenster (Wien, Graz,
Salzburg) als Fixture bleiben.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import re
import sys
import time
import zipfile
from pathlib import Path

import httpx

ZIEL = Path(__file__).resolve().parents[1] / "fixtures" / "at"
UA = "gastroviewer-at-probe/0.1 (+https://github.com/Pytr92/GastroViewer)"
GRENZE = 2 * 1024 * 1024  # je Fixture-Datei
manifest: list[dict] = []

WIEN = (48.2082, 16.3738)      # Stephansplatz
GRAZ = (47.0707, 15.4395)
SALZBURG = (47.8095, 13.0550)
DONAU_WIEN = (48.2300, 16.4100)  # Donauufer, Hochwasserprobe


def _speichern(name: str, daten: bytes) -> str:
    ZIEL.mkdir(parents=True, exist_ok=True)
    gekuerzt = len(daten) > GRENZE
    (ZIEL / name).write_bytes(daten[:GRENZE])
    return f"{name}{' (gekürzt)' if gekuerzt else ''}"


def hole(client: httpx.Client, name: str, url: str, *, params=None, methode="GET",
         headers=None, speichern=True, timeout=120.0, data=None) -> bytes | None:
    eintrag = {"name": name, "url": url, "params": params, "methode": methode}
    t0 = time.perf_counter()
    try:
        r = client.request(methode, url, params=params, headers=headers, timeout=timeout,
                           data=data)
        eintrag.update(status=r.status_code, content_type=r.headers.get("content-type"),
                       bytes=len(r.content), dauer_ms=int((time.perf_counter() - t0) * 1000),
                       final_url=str(r.url))
        if speichern and r.content:
            endung = ".json" if "json" in (r.headers.get("content-type") or "") else (
                ".xml" if "xml" in (r.headers.get("content-type") or "") else ".txt")
            eintrag["datei"] = _speichern(f"{name}{endung}", r.content)
        manifest.append(eintrag)
        print(f"[{r.status_code}] {name} {len(r.content)} B {eintrag['dauer_ms']} ms")
        return r.content if r.status_code < 400 else None
    except Exception as exc:  # noqa: BLE001 — Probe: jeder Fehler ist ein Befund
        eintrag.update(fehler=f"{type(exc).__name__}: {exc}",
                       dauer_ms=int((time.perf_counter() - t0) * 1000))
        manifest.append(eintrag)
        print(f"[ERR] {name}: {exc}")
        return None


def kopf(name: str, daten: bytes, zeilen: int = 40) -> None:
    text = daten.decode("utf-8", "replace")
    _speichern(f"{name}.txt", "\n".join(text.splitlines()[:zeilen]).encode())


# ------------------------------------------------------------------ Geocoder

def geocoder(c):
    for ort, (lat, lon) in (("wien", WIEN), ("graz", GRAZ), ("salzburg", SALZBURG)):
        hole(c, f"nominatim_reverse_{ort}", "https://nominatim.openstreetmap.org/reverse",
             params={"format": "jsonv2", "lat": lat, "lon": lon, "zoom": 18,
                     "addressdetails": 1, "accept-language": "de"})
        time.sleep(1.1)
    hole(c, "nominatim_search_wien", "https://nominatim.openstreetmap.org/search",
         params={"format": "jsonv2", "q": "Stephansplatz Wien", "countrycodes": "at",
                 "limit": 5, "addressdetails": 1, "accept-language": "de"})
    time.sleep(1.1)
    hole(c, "nominatim_search_deat", "https://nominatim.openstreetmap.org/search",
         params={"format": "jsonv2", "q": "Marienplatz", "countrycodes": "de,at",
                 "limit": 5, "addressdetails": 1, "accept-language": "de"})
    hole(c, "photon_reverse_wien", "https://photon.komoot.io/reverse",
         params={"lat": WIEN[0], "lon": WIEN[1], "lang": "de"})
    hole(c, "photon_search_wien", "https://photon.komoot.io/api",
         params={"q": "Stephansplatz Wien", "limit": 5, "lang": "de"})


# ------------------------------------------------------------------ Feiertage

def feiertage(c):
    hole(c, "openholidays_subdivisions_at", "https://openholidaysapi.org/Subdivisions",
         params={"countryIsoCode": "AT", "languageIsoCode": "DE"})
    for sub in ("AT-9", "AT-6"):
        p = {"countryIsoCode": "AT", "languageIsoCode": "DE", "subdivisionCode": sub,
             "validFrom": "2026-01-01", "validTo": "2026-12-31"}
        hole(c, f"openholidays_public_{sub.lower()}_2026",
             "https://openholidaysapi.org/PublicHolidays", params=p)
        hole(c, f"openholidays_school_{sub.lower()}_2026",
             "https://openholidaysapi.org/SchoolHolidays", params=p)


# ------------------------------------------------------------------ Karte

def karte(c):
    hole(c, "basemap_at_capabilities",
         "https://mapsneu.wien.gv.at/basemapneu/1.0.0/WMTSCapabilities.xml")
    hole(c, "basemap_at_tile", "https://mapsneu.wien.gv.at/basemap/geolandbasemap/normal/"
         "google3857/12/1410/2229.png", speichern=False)
    hole(c, "basemap_at_ortho_tile", "https://mapsneu.wien.gv.at/basemap/bmaporthofoto30cm/"
         "normal/google3857/12/1410/2229.jpeg", speichern=False)


# ------------------------------------------------------------------ Eurostat-Raster

def eurostat(c):
    url = "https://gisco-services.ec.europa.eu/census/2021/Eurostat_Census-GRID_2021_V1-0.zip"
    daten = hole(c, "eurostat_grid_zip", url, speichern=False, timeout=900.0)
    if not daten:
        return
    with zipfile.ZipFile(io.BytesIO(daten)) as z:
        namen = z.namelist()
        manifest.append({"name": "eurostat_grid_inhalt", "dateien": namen,
                         "groessen": {n: z.getinfo(n).file_size for n in namen}})
        csv_namen = [n for n in namen if n.lower().endswith(".csv")]
        for n in csv_namen[:2]:
            roh = z.read(n)
            kopf(f"eurostat_{Path(n).stem}_kopf", roh, 30)
            # Fenster: 40 × 40 km um Wien, Graz, Salzburg (EPSG:3035-Koordinaten
            # aus der Zell-ID CRS3035RES1000mN<y>E<x>).
            fenster = {"wien": (2810000, 2850000, 4780000, 4820000),
                       "graz": (2680000, 2720000, 4700000, 4740000),
                       "salzburg": (2750000, 2790000, 4530000, 4570000)}
            leser = csv.reader(io.StringIO(roh.decode("utf-8", "replace")))
            kopfzeile = next(leser)
            treffer = {k: [] for k in fenster}
            id_idx = next((i for i, h in enumerate(kopfzeile) if "GRD_ID" in h.upper()), 0)
            muster = re.compile(r"N(\d+)E(\d+)")
            for zeile in leser:
                m = muster.search(zeile[id_idx] if id_idx < len(zeile) else "")
                if not m:
                    continue
                y, x = int(m.group(1)), int(m.group(2))
                for k, (y0, y1, x0, x1) in fenster.items():
                    if y0 <= y < y1 and x0 <= x < x1:
                        treffer[k].append(zeile)
            for k, zeilen in treffer.items():
                buf = io.StringIO()
                w = csv.writer(buf)
                w.writerow(kopfzeile)
                w.writerows(zeilen)
                _speichern(f"eurostat_{Path(n).stem}_{k}.csv", buf.getvalue().encode())
                manifest.append({"name": f"eurostat_fenster_{k}", "zeilen": len(zeilen),
                                 "quelle": n})


# ------------------------------------------------------------------ GeoSphere

def geosphere(c):
    hole(c, "geosphere_datasets", "https://dataset.api.hub.geosphere.at/v1/datasets")
    meta = hole(c, "geosphere_klima_v2_1m_metadata",
                "https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1m/metadata")
    if not meta:
        return
    try:
        m = json.loads(meta)
        params = [p.get("name") for p in (m.get("parameters") or [])][:6]
        stationen = m.get("stations") or []
        nah = min(stationen, key=lambda s: abs(float(s.get("lat", 0)) - WIEN[0])
                  + abs(float(s.get("lon", 0)) - WIEN[1]))
        hole(c, "geosphere_klima_v2_1m_wien_2020",
             "https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1m",
             params={"parameters": ",".join(p for p in params if p),
                     "station_ids": nah.get("id"), "start": "2020-01-01",
                     "end": "2020-12-31", "output_format": "geojson"})
        manifest.append({"name": "geosphere_station_wien", "station": nah})
    except Exception as exc:  # noqa: BLE001
        manifest.append({"name": "geosphere_auswertung", "fehler": str(exc)})
    hole(c, "geosphere_klima_v2_1y_metadata",
         "https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1y/metadata")


# ------------------------------------------------------------------ Lärm, Hochwasser, Luft

def umwelt(c):
    basis = "https://gis.lfrz.gv.at/api/geodata/i000804/ogc/features/v1"
    coll = hole(c, "laerminfo_collections", f"{basis}/collections", params={"f": "json"})
    if coll:
        try:
            ids = [x.get("id") for x in json.loads(coll).get("collections", [])]
            manifest.append({"name": "laerminfo_collection_ids", "ids": ids})
            for cid in ids[:6]:
                hole(c, f"laerminfo_items_{re.sub(r'[^a-z0-9]+', '_', cid.lower())[:40]}",
                     f"{basis}/collections/{cid}/items",
                     params={"f": "json", "limit": 3,
                             "bbox": f"{WIEN[1]-0.01},{WIEN[0]-0.01},{WIEN[1]+0.01},{WIEN[0]+0.01}"})
        except Exception as exc:  # noqa: BLE001
            manifest.append({"name": "laerminfo_auswertung", "fehler": str(exc)})
    hole(c, "laerminfo_wms_capabilities", "https://inspire.lfrz.gv.at/000804/wms",
         params={"request": "GetCapabilities", "version": "1.3.0", "service": "WMS"})

    caps = hole(c, "hochwasser_wms_capabilities", "https://inspire.lfrz.gv.at/000801/wms",
                params={"request": "GetCapabilities", "version": "1.3.0", "service": "WMS"})
    if caps:
        layer = re.findall(r"<Name>([^<]+)</Name>", caps.decode("utf-8", "replace"))
        manifest.append({"name": "hochwasser_layer", "layer": layer[:40]})
        lat, lon = DONAU_WIEN
        d = 0.0004
        for name in [x for x in layer if x and "WMS" not in x][:6]:
            for fmt in ("application/json", "text/xml", "text/html", "text/plain"):
                hole(c, f"hochwasser_gfi_{re.sub(r'[^a-z0-9]+', '_', name.lower())[:30]}_"
                        f"{fmt.split('/')[1]}",
                     "https://inspire.lfrz.gv.at/000801/wms",
                     params={"service": "WMS", "version": "1.3.0", "request": "GetFeatureInfo",
                             "layers": name, "query_layers": name, "crs": "CRS:84",
                             "bbox": f"{lon-d},{lat-d},{lon+d},{lat+d}", "width": 101,
                             "height": 101, "i": 50, "j": 50, "info_format": fmt,
                             "styles": ""})

    hole(c, "uba_sos_capabilities", "http://luft.umweltbundesamt.at/inspire/sos",
         params={"service": "SOS", "version": "2.0.0", "request": "GetCapabilities"})
    sta = "https://airquality-frost.k8s.ilt-dmz.iosb.fraunhofer.de/v1.1"
    hole(c, "sta_things", f"{sta}/Things", params={"$top": 3, "$expand": "Locations"})
    hole(c, "sta_things_at", f"{sta}/Things",
         params={"$top": 5, "$filter": "startswith(properties/countryCode,'AT')",
                 "$expand": "Locations"})
    hole(c, "sta_observedproperties", f"{sta}/ObservedProperties", params={"$top": 20})


# ------------------------------------------------------------------ Wien

def wien(c):
    wfs = "https://data.wien.gv.at/daten/geo"
    caps = hole(c, "wien_wfs_capabilities", wfs,
                params={"service": "WFS", "request": "GetCapabilities", "version": "1.1.0"})
    typen = []
    if caps:
        typen = re.findall(r"<Name>(ogdwien:[^<]+)</Name>", caps.decode("utf-8", "replace"))
        manifest.append({"name": "wien_wfs_typen", "anzahl": len(typen),
                         "interessant": [t for t in typen if re.search(
                             r"MAERKTE|BAUSTELLEN|FLAECHENWIDMUNG|SCHUTZ|ZAEHLBEZ|RADVERK|"
                             r"LAERM|HOCHWASSER|BAUSPERRE|WOHNZONE|PLANDOK", t)]})
    lat, lon = WIEN
    bbox_klein = f"{lon-0.006},{lat-0.004},{lon+0.006},{lat+0.004},EPSG:4326"
    bbox_gross = f"{lon-0.05},{lat-0.03},{lon+0.05},{lat+0.03},EPSG:4326"
    wuensche = {
        "MAERKTEOGD": None, "BAUSTELLENPKTOGD": bbox_gross, "BAUSTELLENLINIENOGD": bbox_gross,
        "FLAECHENWIDMUNGOGD": bbox_klein, "SCHUTZZONEOGD": bbox_gross,
        "ZAEHLBEZIRKOGD": None, "RADVERKEHRSZAEHLUNGENOGD": None,
    }
    for typ, bbox in wuensche.items():
        voll = f"ogdwien:{typ}"
        if typen and voll not in typen:
            # Namen abweichend? Ähnliche Typen ins Manifest.
            aehnlich = [t for t in typen if typ[:8] in t]
            manifest.append({"name": f"wien_{typ.lower()}_fehlt", "aehnlich": aehnlich})
            if not aehnlich:
                continue
            voll = aehnlich[0]
        p = {"service": "WFS", "request": "GetFeature", "version": "1.1.0", "typeName": voll,
             "srsName": "EPSG:4326", "outputFormat": "json", "maxFeatures": 25}
        if bbox:
            p["bbox"] = bbox
        hole(c, f"wien_{typ.lower()}", wfs, params=p)
    daten = hole(c, "wien_radzaehlungen_csv",
                 "https://www.wien.gv.at/data/ogd/ma46/radverkehrszaehlungen.csv",
                 speichern=False)
    if daten:
        kopf("wien_radzaehlungen_kopf", daten, 8)


# ------------------------------------------------------------------ Statistik Austria, data.gv.at

def statistik(c):
    for ds in ("OGD_touextsai_Tour_HKL_1", "OGD__steuer_ust_UST_2", "OGD_hpivr_HPI_VR_1",
               "OGD__steuer_lst_ab_2021_4_LST_4_2"):
        hole(c, f"stat_{ds}_meta", "https://data.statistik.gv.at/ogd/json",
             params={"dataset": ds})
        daten = hole(c, f"stat_{ds}_csv", f"https://data.statistik.gv.at/data/{ds}.csv",
                     speichern=False)
        if daten:
            kopf(f"stat_{ds}_kopf", daten, 40)
        hole(c, f"stat_{ds}_header", f"https://data.statistik.gv.at/data/{ds}_HEADER.csv")
    ckan = "https://www.data.gv.at/katalog/api/3/action/package_show"
    pakete = {
        "nrw2024": "e40e3b00-1a98-4338-acb7-42547e6fee55",
        "wien_wahlsprengel": "stadt-wien_wahleninwienwahlsprengel",
        "gisa_gewerbe": "gewerbe-in-osterreich",
        "bevstand_2024": "stat_bevolkerungsstand-zu-jahresbeginn-2024",
        "pendler_erwerb": "stat_gemeindeergebnisse-der-abgestimmten-erwerbsstatistik-und-arbeitsstattenzahlung-ab-20-31-10",
        "wien_bevoelkerung_zaehlbezirk": "9ecf5866-dbe8-4cb2-b156-5097c7eec01f",
        "schutzzonen_wien": "schutzzonen-wien",
        "salzburg_baustellen": "468dc562-d99c-4ec1-9edd-8fead87c355e",
        "denkmalliste_wien": "baa72ca8",
    }
    for name, pid in pakete.items():
        daten = hole(c, f"ckan_{name}", ckan, params={"id": pid})
        if not daten:
            continue
        try:
            res = json.loads(daten)["result"]["resources"]
            manifest.append({"name": f"ckan_{name}_resources",
                             "resources": [{"name": r.get("name"), "format": r.get("format"),
                                            "url": r.get("url")} for r in res][:20]})
            for r in res[:6]:
                fmt = (r.get("format") or "").upper()
                url = r.get("url") or ""
                if fmt in ("CSV", "JSON", "TXT") or url.lower().endswith((".csv", ".json")):
                    roh = hole(c, f"ckan_{name}_{fmt.lower() or 'res'}_{res.index(r)}", url,
                               speichern=False, headers={"Range": "bytes=0-200000"})
                    if roh:
                        kopf(f"ckan_{name}_{fmt.lower() or 'res'}_{res.index(r)}_kopf", roh, 30)
                elif fmt in ("ODS", "XLSX", "ZIP"):
                    hole(c, f"ckan_{name}_{fmt.lower()}_{res.index(r)}_head", url, methode="HEAD",
                         speichern=False)
        except Exception as exc:  # noqa: BLE001
            manifest.append({"name": f"ckan_{name}_auswertung", "fehler": str(exc)})


# ------------------------------------------------------------------ Airbnb, GTFS

def sonstiges(c):
    seite = hole(c, "insideairbnb_get_the_data", "https://insideairbnb.com/get-the-data/",
                 speichern=False)
    if seite:
        links = re.findall(r'href="(https?://data\.insideairbnb\.com/austria/[^"]+)"',
                           seite.decode("utf-8", "replace"))
        manifest.append({"name": "insideairbnb_links_at", "links": sorted(set(links))[:20]})
        kandidaten = [u for u in links if u.endswith("visualisations/listings.csv")]
        if kandidaten:
            roh = hole(c, "insideairbnb_vienna_listings", kandidaten[0], speichern=False)
            if roh:
                kopf("insideairbnb_vienna_listings_kopf", roh, 10)
    hole(c, "wienerlinien_gtfs_head",
         "https://www.wienerlinien.at/ogd_realtime/doku/ogd/gtfs/gtfs.zip", methode="HEAD",
         speichern=False)
    daten = hole(c, "wienerlinien_gtfs_zip",
                 "https://www.wienerlinien.at/ogd_realtime/doku/ogd/gtfs/gtfs.zip",
                 speichern=False, timeout=600.0)
    if daten:
        try:
            with zipfile.ZipFile(io.BytesIO(daten)) as z:
                manifest.append({"name": "wienerlinien_gtfs_inhalt",
                                 "dateien": {n: z.getinfo(n).file_size for n in z.namelist()}})
                for n in ("stops.txt", "calendar.txt", "calendar_dates.txt", "trips.txt",
                          "routes.txt", "stop_times.txt", "feed_info.txt"):
                    if n in z.namelist():
                        kopf(f"wienerlinien_{n.replace('.txt', '')}_kopf", z.read(n), 6)
        except Exception as exc:  # noqa: BLE001
            manifest.append({"name": "wienerlinien_gtfs_auswertung", "fehler": str(exc)})
    hole(c, "leerstandsmelder_wien", "https://api.leerstandsmelder.de/api/v1/places",
         params={"lat": WIEN[0], "lon": WIEN[1]}, speichern=True)


TEILE = {"geocoder": geocoder, "feiertage": feiertage, "karte": karte,
         "eurostat": eurostat, "geosphere": geosphere, "umwelt": umwelt,
         "wien": wien, "statistik": statistik, "sonstiges": sonstiges}


def main(argv: list[str]) -> int:
    auswahl = argv[1:] or list(TEILE)
    with httpx.Client(headers={"User-Agent": UA, "Accept-Language": "de"},
                      follow_redirects=True) as c:
        for teil in auswahl:
            print(f"=== {teil}")
            try:
                TEILE[teil](c)
            except Exception as exc:  # noqa: BLE001
                manifest.append({"name": f"{teil}_abbruch", "fehler": f"{type(exc).__name__}: {exc}"})
                print(f"[ERR] {teil} abgebrochen: {exc}")
    ZIEL.mkdir(parents=True, exist_ok=True)
    (ZIEL / "manifest.json").write_text(
        json.dumps({"erzeugt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "eintraege": manifest}, ensure_ascii=False, indent=1), encoding="utf-8")
    fehler = sum(1 for e in manifest if e.get("fehler") or (e.get("status") or 0) >= 400)
    print(f"{len(manifest)} Einträge, {fehler} mit Fehler/HTTP ≥ 400")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
