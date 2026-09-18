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
import io
import sqlite3
import tempfile
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


# ------------------------------------------------------------------ Runde 2

def eurostat_gpkg(c):
    """Das Eurostat-ZIP enthält kein CSV, sondern ein 1,3-GB-GeoPackage —
    also eine SQLite-Datei. Struktur und drei Zeilen belegen."""
    url = "https://gisco-services.ec.europa.eu/census/2021/Eurostat_Census-GRID_2021_V1-0.zip"
    daten = hole(c, "eurostat_grid_zip_r2", url, speichern=False, timeout=900.0)
    if not daten:
        return
    with zipfile.ZipFile(io.BytesIO(daten)) as z:
        for n in z.namelist():
            if n.lower().endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(z.read(n))) as inner:
                    manifest.append({"name": "eurostat_inneres_zip", "datei": n,
                                     "inhalt": {m: inner.getinfo(m).file_size for m in inner.namelist()}})
                    for m in inner.namelist():
                        if m.lower().endswith((".csv", ".txt")):
                            kopf(f"eurostat_inner_{Path(m).stem[:40]}_kopf", inner.read(m), 12)
            if n.lower().endswith("read.me"):
                _speichern("eurostat_readme.txt", z.read(n))
        gpkg = [n for n in z.namelist() if n.lower().endswith(".gpkg")]
        if not gpkg:
            return
        tmp = Path(tempfile.mkdtemp()) / "census.gpkg"
        with z.open(gpkg[0]) as quelle, open(tmp, "wb") as ziel:
            while True:
                stueck = quelle.read(16 * 1024 * 1024)
                if not stueck:
                    break
                ziel.write(stueck)
    conn = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
    info = {}
    try:
        info["gpkg_contents"] = [dict(zip([d[0] for d in cur.description], r))
                                 for cur in [conn.execute("SELECT * FROM gpkg_contents")]
                                 for r in cur.fetchall()]
        info["gpkg_geometry_columns"] = conn.execute("SELECT * FROM gpkg_geometry_columns").fetchall()
        info["gpkg_spatial_ref_sys"] = conn.execute(
            "SELECT srs_id, organization, organization_coordsys_id FROM gpkg_spatial_ref_sys").fetchall()
        tabellen = [r["table_name"] for r in info["gpkg_contents"]]
        info["tabellen"] = tabellen
        for t in tabellen[:3]:
            spalten = conn.execute(f'PRAGMA table_info("{t}")').fetchall()
            info[f"spalten_{t}"] = [(sp[1], sp[2]) for sp in spalten]
            info[f"anzahl_{t}"] = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            geom = next((sp[1] for sp in spalten if sp[2].upper() in ("POLYGON", "GEOMETRY", "MULTIPOLYGON")), None)
            zeilen = conn.execute(f'SELECT * FROM "{t}" LIMIT 3').fetchall()
            namen = [sp[1] for sp in spalten]
            probe = []
            for zeile in zeilen:
                d = {}
                for name, wert in zip(namen, zeile):
                    d[name] = wert.hex()[:120] if isinstance(wert, bytes) else wert
                probe.append(d)
            info[f"zeilen_{t}"] = probe
            # Wien-Fenster über die Zell-ID (CRS3035RES1000mN<y>E<x>)
            id_spalte = next((n for n in namen if "GRD_ID" in n.upper()), None)
            if id_spalte:
                treffer = conn.execute(
                    f'SELECT * FROM "{t}" WHERE "{id_spalte}" LIKE ? LIMIT 2000',
                    ("CRS3035RES1000mN28%E48%",)).fetchall()
                wien = []
                for zeile in treffer:
                    d = {n: (w.hex() if isinstance(w, bytes) else w) for n, w in zip(namen, zeile)}
                    wien.append(d)
                _speichern(f"eurostat_gpkg_{t}_wien.json", json.dumps(wien).encode())
                info[f"wien_treffer_{t}"] = len(wien)
            # Index-Tabellen
            info[f"indizes_{t}"] = conn.execute(f'PRAGMA index_list("{t}")').fetchall()
        info["rtree"] = conn.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'rtree_%' LIMIT 5").fetchall()
    except Exception as exc:  # noqa: BLE001
        info["fehler"] = f"{type(exc).__name__}: {exc}"
    finally:
        conn.close()
    _speichern("eurostat_gpkg_struktur.json", json.dumps(info, default=str, indent=1).encode())
    manifest.append({"name": "eurostat_gpkg_struktur", "tabellen": info.get("tabellen"),
                     "fehler": info.get("fehler")})


def ckan_varianten(c):
    pid = "e40e3b00-1a98-4338-acb7-42547e6fee55"
    for i, url in enumerate((
        "https://www.data.gv.at/katalog/api/3/action/package_show",
        "https://www.data.gv.at/katalog/api/action/package_show",
        "https://data.gv.at/katalog/api/3/action/package_show",
        "https://www.data.gv.at/api/3/action/package_show",
        "https://www.data.gv.at/katalog/api/3/action/package_search",
    )):
        hole(c, f"ckan_variante_{i}", url,
             params={"id": pid} if "show" in url else {"q": "nationalratswahl 2024", "rows": 2})
    hole(c, "ckan_datensatzseite", f"https://www.data.gv.at/datasets/{pid}", params={"locale": "de"})
    hole(c, "ckan_hub_search", "https://www.data.gv.at/api/hub/search/",
         params={"q": "nationalratswahl 2024"})


def geosphere_normal(c):
    meta = hole(c, "geosphere_klima_v2_1y_metadata_r2",
                "https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1y/metadata",
                speichern=False)
    if not meta:
        return
    m = json.loads(meta)
    aktiv = [s for s in m.get("stations", []) if s.get("is_active")
             and str(s.get("valid_from", "9999"))[:4] <= "1991"]
    nah = min(aktiv, key=lambda s: (float(s["lat"]) - WIEN[0]) ** 2 + (float(s["lon"]) - WIEN[1]) ** 2)
    manifest.append({"name": "geosphere_station_wien_r2", "station": nah, "aktiv_seit_1991": len(aktiv)})
    hole(c, "geosphere_klima_v2_1y_wien_1991_2020",
         "https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1y",
         params={"parameters": "tage_sommer,tage_tropen,so_h,rr,tl_mittel",
                 "station_ids": nah["id"], "start": "1991-01-01", "end": "2020-12-31",
                 "output_format": "geojson"})
    hole(c, "geosphere_klima_v2_1y_wien_1991_2020_csv",
         "https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1y",
         params={"parameters": "tage_sommer,tage_tropen,so_h,rr,tl_mittel",
                 "station_ids": nah["id"], "start": "1991-01-01", "end": "2020-12-31",
                 "output_format": "csv"})


def hochwasser_gfi(c):
    caps = hole(c, "hochwasser_wms_capabilities_r2", "https://inspire.lfrz.gv.at/000801/wms",
                params={"request": "GetCapabilities", "version": "1.3.0", "service": "WMS"},
                speichern=False)
    if caps:
        text = caps.decode("utf-8", "replace")
        layer = re.findall(r'<Layer[^>]*queryable="1"[^>]*>\s*<Name>([^<]+)</Name>', text)
        manifest.append({"name": "hochwasser_layer_queryable", "layer": layer})
    punkte = {"donau_wien": (48.2300, 16.4100), "handelskai": (48.2450, 16.3920),
              "lobau": (48.1650, 16.5000), "stephansplatz": WIEN}
    for name in ("UEFF_HQ30", "UEFF_HQ100", "UEFF_HQ300", "RISIKOGEB_HQ100", "APSFR"):
        for ort, (lat, lon) in punkte.items():
            d = 0.0004
            hole(c, f"hochwasser_gfi_{name.lower()}_{ort}", "https://inspire.lfrz.gv.at/000801/wms",
                 params={"service": "WMS", "version": "1.3.0", "request": "GetFeatureInfo",
                         "layers": name, "query_layers": name, "crs": "CRS:84",
                         "bbox": f"{lon-d},{lat-d},{lon+d},{lat+d}", "width": 101, "height": 101,
                         "i": 50, "j": 50, "info_format": "application/json", "styles": "",
                         "feature_count": 5})


def laerminfo_r2(c):
    basis = "https://gis.lfrz.gv.at/api/geodata/i000804/ogc/features/v1"
    lat, lon = WIEN
    for cid in ("i000804:laerm_2022_strasse_lden", "i000804:laerm_2022_strasse_lnight",
                "i000804:laerm_2025_hauptverkehr", "i000804:laerm_2025_ballungsraeume",
                "i000804:laerm_2022_schiene_lden"):
        kurz = cid.split(":")[1]
        hole(c, f"laerminfo_r2_{kurz}_queryables", f"{basis}/collections/{cid}/queryables",
             params={"f": "json"})
        hole(c, f"laerminfo_r2_{kurz}_items", f"{basis}/collections/{cid}/items",
             params={"f": "json", "limit": 5,
                     "bbox": f"{lon-0.002},{lat-0.002},{lon+0.002},{lat+0.002}"})
    # Punkt an der Südosttangente (A23) — dort muss Straßenlärm sein.
    a23 = (48.1780, 16.4130)
    hole(c, "laerminfo_r2_strasse_lden_a23", f"{basis}/collections/i000804:laerm_2022_strasse_lden/items",
         params={"f": "json", "limit": 5,
                 "bbox": f"{a23[1]-0.001},{a23[0]-0.001},{a23[1]+0.001},{a23[0]+0.001}"})


def wien_r2(c):
    wfs = "https://data.wien.gv.at/daten/geo"
    caps = hole(c, "wien_wfs_capabilities_r2", wfs,
                params={"service": "WFS", "request": "GetCapabilities", "version": "1.1.0"},
                speichern=False)
    if not caps:
        return
    typen = re.findall(r"<Name>(ogdwien:[^<]+)</Name>", caps.decode("utf-8", "replace"))
    treffer = [t for t in typen if re.search(r"WIDMUNG|FLW|BEBAU|PLAN|GEBAEUDE|NUTZUNG|"
                                             r"BAUSPERRE|RADVERK|ZAEHL|ORTHO|GRUEN", t)]
    manifest.append({"name": "wien_typen_r2", "treffer": treffer, "alle": typen})
    lat, lon = WIEN
    bbox_klein = f"{lon-0.003},{lat-0.002},{lon+0.003},{lat+0.002},EPSG:4326"
    for t in treffer[:14]:
        hole(c, f"wien_r2_{t.split(':')[1].lower()}", wfs,
             params={"service": "WFS", "request": "GetFeature", "version": "1.1.0",
                     "typeName": t, "srsName": "EPSG:4326", "outputFormat": "json",
                     "maxFeatures": 5, "bbox": bbox_klein})


def luft_r2(c):
    sta = "https://airquality-frost.k8s.ilt-dmz.iosb.fraunhofer.de/v1.1"
    lat, lon = WIEN
    orte = hole(c, "sta_locations_wien", f"{sta}/Locations",
                params={"$filter": f"geo.distance(location, geography'POINT({lon} {lat})') lt 0.1 "
                                   "and Things/properties/countryCode eq 'AT'",
                        "$expand": "Things", "$top": 10})
    if not orte:
        orte = hole(c, "sta_locations_wien_einfach", f"{sta}/Locations",
                    params={"$filter": f"geo.distance(location, geography'POINT({lon} {lat})') lt 0.1",
                            "$expand": "Things", "$top": 10})
    if not orte:
        return
    try:
        things = [t for o in json.loads(orte).get("value", []) for t in o.get("Things", [])]
        if things:
            tid = things[0]["@iot.id"]
            hole(c, "sta_datastreams_wien", f"{sta}/Things({tid})/Datastreams",
                 params={"$expand": "ObservedProperty,Observations($top=2;$orderby=phenomenonTime desc)",
                         "$top": 20})
    except Exception as exc:  # noqa: BLE001
        manifest.append({"name": "sta_auswertung", "fehler": str(exc)})


def feiertage_r2(c):
    for sub in ("AT-WI", "AT-SM", "AT-VA"):
        p = {"countryIsoCode": "AT", "languageIsoCode": "DE", "subdivisionCode": sub,
             "validFrom": "2026-01-01", "validTo": "2026-12-31"}
        hole(c, f"openholidays_r2_public_{sub.lower()}", "https://openholidaysapi.org/PublicHolidays", params=p)
        hole(c, f"openholidays_r2_school_{sub.lower()}", "https://openholidaysapi.org/SchoolHolidays", params=p)
    hole(c, "openholidays_r2_public_at_gesamt", "https://openholidaysapi.org/PublicHolidays",
         params={"countryIsoCode": "AT", "languageIsoCode": "DE",
                 "validFrom": "2026-01-01", "validTo": "2026-12-31"})


TEILE.update({"eurostat_gpkg": eurostat_gpkg, "ckan": ckan_varianten,
              "geosphere_normal": geosphere_normal, "hochwasser": hochwasser_gfi,
              "laerm2": laerminfo_r2, "wien2": wien_r2, "luft2": luft_r2,
              "feiertage2": feiertage_r2})


# ------------------------------------------------------------------ Runde 3

HOCHWASSER_LAYER = ("Hochwasserueberflutungsflaechen HQ30", "Hochwasserueberflutungsflaechen HQ100",
                    "Hochwasserueberflutungsflaechen HQ300", "Hochwasserrisikogebiete HQ100",
                    "Rote Gefahrenzonen aus der Gefahrenzonenplanung",
                    "Gelbe Gefahrenzonen aus der Gefahrenzonenplanung")


def hochwasser_r3(c):
    """Layer heißen wie ihre Titel (mit Leerzeichen) — Runde 2 fragte die
    Kurznamen und bekam LayerNotDefined."""
    punkte = {"donau_wien": (48.2300, 16.4100), "handelskai": (48.2450, 16.3920),
              "lobau": (48.1650, 16.5000), "stephansplatz": WIEN,
              "linz_donau": (48.3100, 14.2900), "krems_donau": (48.4020, 15.6100),
              "graz_mur": (47.0680, 15.4330)}
    for name in HOCHWASSER_LAYER:
        kurz = re.sub(r"[^a-z0-9]+", "_", name.lower())[:36]
        for ort, (lat, lon) in punkte.items():
            d = 0.0004
            hole(c, f"hochwasser_r3_{kurz}_{ort}", "https://inspire.lfrz.gv.at/000801/ows",
                 params={"service": "WMS", "version": "1.3.0", "request": "GetFeatureInfo",
                         "layers": name, "query_layers": name, "crs": "CRS:84",
                         "bbox": f"{lon-d},{lat-d},{lon+d},{lat+d}", "width": 101, "height": 101,
                         "i": 50, "j": 50, "info_format": "application/json", "styles": "",
                         "feature_count": 5})


def ckan_r3(c):
    """data.gv.at antwortet unter /katalog/api/action/package_show mit DCAT
    (JSON-LD): @graph mit dcat:Distribution → dcat:accessURL."""
    api = "https://www.data.gv.at/katalog/api/action/package_show"
    pakete = {
        "nrw2024": "e40e3b00-1a98-4338-acb7-42547e6fee55",
        "wien_wahlsprengel": "stadt-wien_wahleninwienwahlsprengel",
        "gisa_gewerbe": "gewerbe-in-osterreich",
        "bevstand_2024": "stat_bevolkerungsstand-zu-jahresbeginn-2024",
        "pendler_erwerb": "stat_gemeindeergebnisse-der-abgestimmten-erwerbsstatistik-und-arbeitsstattenzahlung-ab-20-31-10",
        "wien_bevoelkerung_zaehlbezirk": "9ecf5866-dbe8-4cb2-b156-5097c7eec01f",
        "salzburg_baustellen": "468dc562-d99c-4ec1-9edd-8fead87c355e",
        "wien_luftmessnetz": "stadt-wien_luftmessnetzwien",
        "wien_flaechenwidmung": "stadt-wien_flchenwidmungsundbebauungsplanwien",
    }
    for name, pid in pakete.items():
        daten = hole(c, f"ckan_r3_{name}", api, params={"id": pid})
        if not daten:
            continue
        try:
            graph = json.loads(daten).get("@graph", [])
            dist = [g for g in graph if g.get("@type") == "dcat:Distribution"]
            res = [{"titel": g.get("dct:title"), "format": g.get("dct:format"),
                    "url": (g.get("dcat:accessURL") or {}).get("@id"),
                    "download": (g.get("dcat:downloadURL") or {}).get("@id")} for g in dist]
            ds = [g for g in graph if g.get("@type") == "dcat:Dataset"]
            manifest.append({"name": f"ckan_r3_{name}_resources", "resources": res[:20],
                             "titel": (ds[0].get("dct:title") if ds else None),
                             "lizenz": (ds[0].get("dct:license") if ds else None)})
            for i, r in enumerate(res[:8]):
                url = r.get("download") or r.get("url") or ""
                fmt = (r.get("format") or "").upper()
                if fmt in ("CSV", "JSON", "TXT") or url.lower().endswith((".csv", ".json")):
                    roh = hole(c, f"ckan_r3_{name}_{i}", url, speichern=False,
                               headers={"Range": "bytes=0-300000"})
                    if roh:
                        kopf(f"ckan_r3_{name}_{i}_kopf", roh, 25)
                else:
                    hole(c, f"ckan_r3_{name}_{i}_head", url, methode="HEAD", speichern=False)
        except Exception as exc:  # noqa: BLE001
            manifest.append({"name": f"ckan_r3_{name}_auswertung", "fehler": str(exc)})
    for q in ("luftgüte wien", "bevölkerungsstand gemeinden", "gemeinden österreich grenzen",
              "erwerbspendler gemeinde"):
        hole(c, f"ckan_r3_suche_{re.sub(r'[^a-z]+', '_', q)[:24]}",
             "https://www.data.gv.at/katalog/api/action/package_search", params={"q": q, "rows": 5})


TEILE.update({"hochwasser3": hochwasser_r3, "ckan3": ckan_r3})


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




# ------------------------------------------------------------------ Runde 4

HOCHWASSER_ALLE = ("Hochwasserueberflutungsflaechen HQ30", "Hochwasserueberflutungsflaechen HQ100",
                   "Hochwasserueberflutungsflaechen HQ300",
                   "Rote Gefahrenzonen aus der Gefahrenzonenplanung",
                   "Gelbe Gefahrenzonen aus der Gefahrenzonenplanung",
                   "Hochwasserrisikogebiete HQ100")


def hochwasser_r4(c):
    """Sammelabfrage: alle sechs Layer in einer GetFeatureInfo-Anfrage —
    so fragt sources/planung_at.py. Erwartet am Kremser Ufer das
    Risikogebiet Wachau mit id-Präfix des Layers."""
    punkte = {"krems_donau": (48.4020, 15.6100), "stephansplatz": WIEN,
              "handelskai": (48.2450, 16.3920), "linz_donau": (48.3100, 14.2900),
              "graz_mur": (47.0680, 15.4330), "melk_donau": (48.2290, 15.3330),
              "schwertberg_aist": (48.2740, 14.5860)}
    namen = ",".join(HOCHWASSER_ALLE)
    for ort, (lat, lon) in punkte.items():
        d = 0.0004
        hole(c, f"hochwasser_r4_sammel_{ort}", "https://inspire.lfrz.gv.at/000801/ows",
             params={"service": "WMS", "version": "1.3.0", "request": "GetFeatureInfo",
                     "layers": namen, "query_layers": namen, "crs": "CRS:84",
                     "bbox": f"{lon-d},{lat-d},{lon+d},{lat+d}", "width": 101, "height": 101,
                     "i": 50, "j": 50, "info_format": "application/json", "styles": "",
                     "feature_count": 10})


def wien_r4(c):
    """Punktkasten (rund 50 m) für Schutzzone und Widmung — so fragt
    sources/wien.py — an drei Wiener Punkten."""
    wfs = "https://data.wien.gv.at/daten/geo"
    punkte = {"stephansplatz": WIEN, "brigittenau": (48.2400, 16.3700),
              "naschmarkt": (48.1985, 16.3630), "spittelberg": (48.2035, 16.3550)}
    for ort, (lat, lon) in punkte.items():
        d = 0.0005
        bbox = f"{lon-d:.6f},{lat-d:.6f},{lon+d:.6f},{lat+d:.6f},EPSG:4326"
        for typ in ("SCHUTZZONEOGD", "GENFLWIDMUNGOGD"):
            hole(c, f"wien_r4_{typ.lower()}_{ort}", wfs,
                 params={"service": "WFS", "request": "GetFeature", "version": "1.1.0",
                         "typeName": f"ogdwien:{typ}", "srsName": "EPSG:4326",
                         "outputFormat": "json", "maxFeatures": 20, "bbox": bbox})


def statistik_r4(c):
    """Nächtigungsstatistik: Klassifikationen vollständig, Daten-CSV als
    Wien-Ausschnitt ab 2018 (die ganze Datei ist Megabytes groß)."""
    ds = "OGD_touextsai_Tour_HKL_1"
    for kl in ("C-SDB_TIT-0", "C-W96-0", "C-C93-2"):
        hole(c, f"stat_{ds}_{kl}", f"https://data.statistik.gv.at/data/{ds}_{kl}.csv")
    daten = hole(c, f"stat_{ds}_csv_r4", f"https://data.statistik.gv.at/data/{ds}.csv",
                 speichern=False)
    if daten:
        text = daten.decode("utf-8", "replace")
        zeilen = text.splitlines()
        wien = [zeilen[0]] + [z for z in zeilen[1:]
                              if z.split(";")[1:2] == ["W96-9"] and z[:4] >= "2018"]
        _speichern(f"stat_{ds}_wien_ab2018.csv", "\n".join(wien).encode("utf-8"))
        codes = sorted({z.split(";")[2] for z in zeilen[1:] if z.count(";") >= 4})
        manifest.append({"name": "stat_tour_hkl_1_umfang", "zeilen": len(zeilen),
                         "bytes": len(daten), "wien_ab2018": len(wien) - 1,
                         "herkunft_codes": codes, "erste": zeilen[1][:80],
                         "letzte": zeilen[-1][:80]})


def nrw_r4(c):
    """Nationalratswahl 2024 (BMI über data.gv.at): Ergebnisdatei, GKZ-Liste
    und Parteienreihung vollständig — als Fixtures für sources/wahl_at.py."""
    basis = "https://www.data.gv.at/katalog/dataset/e40e3b00-1a98-4338-acb7-42547e6fee55/resource"
    for name, pfad in (("nrw2024_ergebnisse", "ce85ad5c-e471-42c0-83e5-580dbb627717/download/wahl_20241003_214746.csv"),
                       ("nrw2024_gkz", "da545c2c-b421-439d-8a8a-144c81b66c2e/download/gkz-liste-.csv"),
                       ("nrw2024_parteien", "75e5129f-1fe6-4020-8454-22370c279a6a/download/parteien_reihung_nrw2024.csv")):
        daten = hole(c, name, f"{basis}/{pfad}")
        if daten:
            manifest.append({"name": f"{name}_kodierung",
                             "utf8": _ist_utf8(daten), "zeilen": daten.count(b"\n")})


def _ist_utf8(daten: bytes) -> bool:
    try:
        daten.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


TEILE.update({"hochwasser4": hochwasser_r4, "wien4": wien_r4, "statistik4": statistik_r4,
              "nrw4": nrw_r4})


if __name__ == "__main__":
    sys.exit(main(sys.argv))
