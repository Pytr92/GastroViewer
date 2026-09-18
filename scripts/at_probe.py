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


# ------------------------------------------------------------------ Runde 5
# Kandidaten aus docs/erweiterungen-oesterreich.md und -deutschland.md.
# Deutsche Antworten heißen de_* und wandern kuratiert nach fixtures/de.

KOELN = (50.9413, 6.9583)
BERLIN = (52.5200, 13.4050)
HAMBURG = (53.5503, 9.9937)
STUTTGART = (48.7758, 9.1829)
MUENCHEN = (48.1372, 11.5755)
GRAZ_HBF = (47.0730, 15.4160)


def _dcat_ressourcen(daten: bytes) -> list[dict]:
    try:
        graph = json.loads(daten).get("@graph", [])
    except Exception:  # noqa: BLE001
        return []
    out = []
    for g in graph:
        if g.get("@type") == "dcat:Distribution":
            titel = g.get("dct:title")
            if isinstance(titel, list):
                titel = (titel[0] or {}).get("@value") if titel else None
            elif isinstance(titel, dict):
                titel = titel.get("@value")
            fmt = g.get("dct:format")
            if isinstance(fmt, dict):
                fmt = fmt.get("@id", "").rsplit("/", 1)[-1]
            out.append({"titel": titel, "format": fmt,
                        "url": (g.get("dcat:accessURL") or {}).get("@id")})
    return out


def _ckan_show(c, name: str, pid: str) -> list[dict]:
    daten = hole(c, f"ckan_r5_{name}", "https://www.data.gv.at/katalog/api/action/package_show",
                 params={"id": pid})
    res = _dcat_ressourcen(daten) if daten else []
    manifest.append({"name": f"ckan_r5_{name}_ressourcen", "ressourcen": res[:12]})
    return res


def _ckan_suche(c, name: str, q: str) -> list[dict]:
    daten = hole(c, f"ckan_r5_suche_{name}", "https://www.data.gv.at/katalog/api/action/package_search",
                 params={"q": q, "rows": 5})
    treffer = []
    if daten:
        try:
            d = json.loads(daten)
            for r in (d.get("result") or {}).get("results") or []:
                treffer.append({"id": r.get("id"), "name": r.get("name"), "title": r.get("title"),
                                "ressourcen": [{"url": x.get("url"), "format": x.get("format"),
                                                "name": x.get("name")} for x in r.get("resources") or []][:6]})
        except Exception as exc:  # noqa: BLE001
            manifest.append({"name": f"ckan_r5_suche_{name}_fehler", "fehler": str(exc)})
    manifest.append({"name": f"ckan_r5_suche_{name}_treffer", "treffer": treffer})
    return treffer


def _erste_csv(res: list[dict]) -> str | None:
    for r in res:
        u = (r.get("url") or "")
        if u.lower().endswith(".csv") or "csv" in str(r.get("format") or "").lower():
            return u
    return res[0]["url"] if res else None


def gemeinde_r5(c):
    """Statistik Austria Gemeindeebene, AMS, Dauersiedlungsraum, Gemeindegrenzen."""
    for ds in ("OGDEXT_AEST_GEMTAB_1", "OGD_bevstandjbab2002_BevStand_2025",
               "OGD_bevstandjbab2002_BevStand_2024", "OGDEXT_GEM_1", "OGDEXT_DSR_1",
               "OGD_hpivr_HPI_VR_1"):
        hole(c, f"stat_r5_{ds}_meta", "https://data.statistik.gv.at/ogd/json", params={"dataset": ds})
        hole(c, f"stat_r5_{ds}_header", f"https://data.statistik.gv.at/data/{ds}_HEADER.csv")
    for ds in ("OGDEXT_AEST_GEMTAB_1", "OGD_bevstandjbab2002_BevStand_2025"):
        daten = hole(c, f"stat_r5_{ds}_csv", f"https://data.statistik.gv.at/data/{ds}.csv", speichern=False)
        if daten:
            kopf(f"stat_r5_{ds}_kopf", daten, 60)
            manifest.append({"name": f"stat_r5_{ds}_umfang", "bytes": len(daten), "zeilen": daten.count(b"\n")})
            if ds == "OGDEXT_AEST_GEMTAB_1":
                _speichern(f"stat_r5_{ds}.csv", daten)
    for kl in ("C-GRGEMAKT-0", "C-GALTEJ112-0", "C-C11-0"):
        hole(c, f"stat_r5_bevstand2025_{kl}", f"https://data.statistik.gv.at/data/OGD_bevstandjbab2002_BevStand_2025_{kl}.csv")
    treffer = _ckan_suche(c, "ams_gemeinden", "Arbeitslose Schulungsteilnehmer Gemeinden Geschlecht")
    for t in treffer[:2]:
        url = _erste_csv(t["ressourcen"])
        if url:
            daten = hole(c, f"ams_r5_{re.sub(r'[^a-z0-9]+', '_', (t['name'] or '')[:30])}", url, speichern=False)
            if daten:
                kopf(f"ams_r5_{re.sub(r'[^a-z0-9]+', '_', (t['name'] or '')[:30])}_kopf", daten, 30)
                manifest.append({"name": "ams_r5_umfang", "url": url, "bytes": len(daten),
                                 "zeilen": daten.count(b"\n"), "utf8": _ist_utf8(daten)})
    _ckan_show(c, "gemeindegrenzen", "stat_gliederung-osterreichs-in-gemeinden")
    _ckan_suche(c, "gemeindegrenzen", "Gliederung Österreichs in Gemeinden Gemeindegrenzen")


def wien_r5(c):
    """Wiener Datensätze: Radzählungen (voll), Kfz-Dauerzählstellen, Lage-Layer, Zählbezirke."""
    wfs = "https://data.wien.gv.at/daten/geo"
    daten = hole(c, "wien_r5_radzaehlungen_csv", "https://www.wien.gv.at/data/ogd/ma46/radverkehrszaehlungen.csv",
                 speichern=False)
    if daten:
        text = daten.decode("utf-8-sig", "replace")
        zeilen = text.splitlines()
        _speichern("wien_r5_radverkehrszaehlungen_ab2024.csv",
                   "\n".join([zeilen[0]] + [z for z in zeilen[1:] if z[:4] >= "2024"]).encode("utf-8"))
        manifest.append({"name": "wien_r5_radzaehlungen_umfang", "bytes": len(daten), "zeilen": len(zeilen),
                         "erste": zeilen[1][:60] if len(zeilen) > 1 else None, "letzte": zeilen[-1][:60]})
    daten = hole(c, "wien_r5_dauerzaehlstellen_csv", "https://www.wien.gv.at/data/ogd/ma46/dauerzaehlstellen.csv",
                 speichern=False)
    if daten:
        kopf("wien_r5_dauerzaehlstellen_kopf", daten, 30)
        manifest.append({"name": "wien_r5_dauerzaehlstellen_umfang", "bytes": len(daten), "zeilen": daten.count(b"\n")})
    lat, lon = WIEN
    d = 0.0005
    box_punkt = f"{lon-d:.6f},{lat-d:.6f},{lon+d:.6f},{lat+d:.6f},EPSG:4326"
    d2 = 0.004
    box_600 = f"{lon-d2:.6f},{lat-d2:.6f},{lon+d2:.6f},{lat+d2:.6f},EPSG:4326"
    wuensche = {"RADVERKEHRSZAEHLUNGENOGD": None, "DAUERZAEHLSTELLENOGD": None,
                "KURZPARKZONEOGD": box_punkt, "FUSSGEHERZONEOGD": box_600, "BEGEGNUNGSZONEOGD": box_600,
                "STRUKGESCHSTROGD": box_600, "GEBAEUDEINFOOGD": box_600, "ZAEHLBEZIRKOGD": box_punkt,
                "BAUPERIODEOGD": box_punkt, "BAUTYPOLOGIEOGD": box_punkt, "REALNUT2022OGD": box_punkt,
                "GEHSTEIGOGD": box_punkt}
    for typ, bbox in wuensche.items():
        p = {"service": "WFS", "request": "GetFeature", "version": "1.1.0", "typeName": f"ogdwien:{typ}",
             "srsName": "EPSG:4326", "outputFormat": "json", "maxFeatures": 60}
        if bbox:
            p["bbox"] = bbox
        hole(c, f"wien_r5_{typ.lower()}", wfs, params=p)
    caps = hole(c, "wien_r5_wfs_capabilities", wfs,
                params={"service": "WFS", "request": "GetCapabilities", "version": "1.1.0"}, speichern=False)
    if caps:
        typen = re.findall(r"<Name>(ogdwien:[^<]+)</Name>", caps.decode("utf-8", "replace"))
        manifest.append({"name": "wien_r5_typen", "treffer": [t for t in typen if re.search(
            r"ZAEHL|PARK|FUSS|BEGEGN|GESCH|GEBAEUDE|BAUPER|BAUTYP|REALNUT|LUFT|KRIMI|RAD|BEZIRK", t)]})
    daten = hole(c, "wien_r5_bev_zaehlbezirk_csv", "https://www.wien.gv.at/gogv/l9ogdviezbzpopsexagr3stknatgeo22008f",
                 speichern=False)
    if daten:
        kopf("wien_r5_bev_zaehlbezirk_kopf", daten, 40)
        manifest.append({"name": "wien_r5_bev_zaehlbezirk_umfang", "bytes": len(daten), "zeilen": daten.count(b"\n")})
        _speichern("wien_r5_bev_zaehlbezirk.csv", daten)
    for name, url in (("prognose_gebiete", "https://www.wien.gv.at/data/ogd/ma23/vieprgprojpopsexagepgeo22025.csv"),
                      ("zb_prognose_304", "https://www.wien.gv.at/data/ogd/ma23/vie_304.csv"),
                      ("wohnungen_404", "https://www.wien.gv.at/data/ogd/ma23/vie-404-2021.csv")):
        daten = hole(c, f"wien_r5_{name}", url, speichern=False)
        if daten:
            kopf(f"wien_r5_{name}_kopf", daten, 25)
    for name, pid in (("wien_luft", "d9ae1245-158e-4d79-86a4-2d9b3defbedc"),
                      ("wien_kriminalitaet", "76d09d69-4258-49e3-88ea-d87668fc30d2"),
                      ("wien_bauperioden", "38aac30b-6b79-4fee-88f0-a37b2e6c0f92"),
                      ("wien_kurzparkzonen", "stadt-wien_kurzparkzonenwien"),
                      ("wien_radzaehlungen", "2e9f926c-f688-4889-856d-5e6935440c28")):
        res = _ckan_show(c, name, pid)
        for r in res[:3]:
            u = r.get("url") or ""
            if u.lower().endswith((".csv", ".json")) and "wfs" not in u.lower():
                daten = hole(c, f"{name}_r5_{re.sub(r'[^a-z0-9]+', '_', u.rsplit('/', 1)[-1].lower())[:30]}", u, speichern=False)
                if daten:
                    kopf(f"{name}_r5_{re.sub(r'[^a-z0-9]+', '_', u.rsplit('/', 1)[-1].lower())[:30]}_kopf", daten, 30)


def staedte_r5(c):
    """Graz, Linz, Salzburg, Innsbruck: Bevölkerung, Baustellen, WFS-Muster."""
    for name, q in (("graz_bev", "Grazer Bevölkerung nach Bezirk und Alter"),
                    ("linz_bev", "Linz Altersschichtung statistische Bezirke"),
                    ("salzburg_bev", "Salzburg Einwohner Zählbezirk Alter Geschlecht"),
                    ("innsbruck_statbez", "Innsbruck statistische Bezirke Hauptwohnsitzbevölkerung"),
                    ("vorarlberg_tourismus", "Tourismusstatistik Vorarlberg Gemeinden Nächtigungen"),
                    ("noe_no2", "Land Niederösterreich Stickstoffdioxid NO2 Luftgüte"),
                    ("linz_luft", "Luftgüte und meteorologische Messwerte Linz"),
                    ("gisa", "Gewerbe in Österreich GISA"),
                    ("denkmal_ooe", "Denkmalliste Oberösterreich"),
                    ("noe_jdtv", "Straßenverkehrszählung Niederösterreich Dauerzählstellen JDTV")):
        treffer = _ckan_suche(c, name, q)
        for t in treffer[:1]:
            url = _erste_csv(t["ressourcen"])
            if url:
                daten = hole(c, f"{name}_r5_daten", url, speichern=False)
                if daten:
                    kopf(f"{name}_r5_kopf", daten, 30)
                    manifest.append({"name": f"{name}_r5_umfang", "url": url, "bytes": len(daten),
                                     "zeilen": daten.count(b"\n"), "utf8": _ist_utf8(daten)})
    sbg = "https://data.stadt-salzburg.at/geodaten/wfs"
    caps = hole(c, "salzburg_r5_wfs_capabilities", sbg,
                params={"service": "WFS", "request": "GetCapabilities", "version": "1.1.0"}, speichern=False)
    if caps:
        typen = re.findall(r"<Name>(ogdsbg:[^<]+)</Name>", caps.decode("utf-8", "replace"))
        manifest.append({"name": "salzburg_r5_typen", "anzahl": len(typen), "alle": typen[:200]})
    hole(c, "salzburg_r5_baustelle", sbg,
         params={"service": "WFS", "version": "1.1.0", "request": "GetFeature", "srsName": "EPSG:4326",
                 "outputFormat": "application/json", "typeName": "ogdsbg:baustelle", "maxFeatures": 30})
    for name, url in (("doris_hvd", "https://ags.doris.at/arcgis/services/HVD/MapServer/WFSServer"),
                      ("noe_ogd", "https://sdi.noe.gv.at/at.gv.noe.geoserver/OGD/wfs"),
                      ("sagis_gewaesser", "https://service.salzburg.gv.at/arcgis/services/OGD/OGD_Gewaesser_Land_Salzburg/MapServer/WFSServer"),
                      ("stmk_hale", "https://haleconnect.com/ows/services/org.926.4be5ef1f-2eea-42c8-b9ea-e393835f28c2_wfs")):
        caps = hole(c, f"landeswfs_r5_{name}", url,
                    params={"service": "WFS", "request": "GetCapabilities", "version": "2.0.0"}, speichern=False)
        if caps:
            t = caps.decode("utf-8", "replace")
            namen = re.findall(r"<(?:wfs:)?Name>([^<]+)</(?:wfs:)?Name>", t)
            manifest.append({"name": f"landeswfs_r5_{name}_typen", "anzahl": len(namen),
                             "widmung": [n for n in namen if re.search(r"widm|flw|nutzung|plan", n, re.I)][:40],
                             "erste": namen[:25]})
    for jahr in ("2025", "2024"):
        for art in ("Baugrundstueckspreise", "Haeuserpreise", "Wohnungspreise"):
            hole(c, f"stat_r5_immo_{art.lower()}{jahr}", f"https://www.statistik.at/fileadmin/pages/222/{art}{jahr}.ods",
                 methode="HEAD")
    daten = hole(c, "stat_r5_immo_haeuser2024_ods", "https://www.statistik.at/fileadmin/pages/222/Haeuserpreise2024.ods",
                 speichern=False)
    if daten:
        _speichern("stat_r5_haeuserpreise2024.ods", daten)
    daten = hole(c, "stat_r5_immo_bauland2024_ods", "https://www.statistik.at/fileadmin/pages/222/Baugrundstueckspreise2024.ods",
                 speichern=False)
    if daten:
        _speichern("stat_r5_baugrundstueckspreise2024.ods", daten)


def _gfi(c, name, url, layers, lat, lon, info_format="application/json", extra=None):
    d = 0.0004
    p = {"service": "WMS", "version": "1.3.0", "request": "GetFeatureInfo", "layers": layers,
         "query_layers": layers, "crs": "CRS:84", "bbox": f"{lon-d},{lat-d},{lon+d},{lat+d}",
         "width": 101, "height": 101, "i": 50, "j": 50, "info_format": info_format, "styles": "",
         "feature_count": 10}
    p.update(extra or {})
    return hole(c, name, url, params=p)


def de_r5(c):
    """Deutsche Kandidaten (docs/erweiterungen-deutschland.md)."""
    # Starkregen BKG
    caps = hole(c, "de_starkregen_capabilities", "https://sgx.geodatenzentrum.de/wms_starkregen",
                params={"request": "GetCapabilities", "service": "WMS"}, speichern=True)
    layer = []
    if caps:
        t = caps.decode("utf-8", "replace")
        layer = re.findall(r'<Layer[^>]*queryable="1"[^>]*>\s*<Name>([^<]+)</Name>', t)
        manifest.append({"name": "de_starkregen_layer", "queryable": layer[:30],
                         "alle": re.findall(r"<Name>([^<]+)</Name>", t)[:40]})
    for ort, (lat, lon) in (("marienplatz", MUENCHEN), ("koeln", KOELN), ("isarauen", (48.1050, 11.5530))):
        for ly in (layer[:3] or ["starkregen"]):
            for fmt in ("application/json", "text/plain"):
                _gfi(c, f"de_starkregen_gfi_{re.sub(r'[^a-z0-9]+', '_', ly.lower())[:20]}_{ort}_{fmt.split('/')[1]}",
                     "https://sgx.geodatenzentrum.de/wms_starkregen", ly, lat, lon, fmt)
    # Berlin: Starkregen, DTVw, Wohnlagen — Dienste über GetCapabilities entdecken
    for name in ("starkregengefahrenkarte", "starkregenhinweiskarte", "verkehrsmengen_2023", "verkehrsmengen",
                 "wohnlagen_2024", "wohnlagen", "radzaehlstellen", "dtvw2023", "verkehrsmengen_dtvw_2023"):
        hole(c, f"de_berlin_wfs_{name}", f"https://gdi.berlin.de/services/wfs/{name}",
             params={"REQUEST": "GetCapabilities", "SERVICE": "WFS"}, speichern=False)
        hole(c, f"de_berlin_wms_{name}", f"https://gdi.berlin.de/services/wms/{name}",
             params={"REQUEST": "GetCapabilities", "SERVICE": "WMS"}, speichern=False)
    # Autobahn GmbH
    hole(c, "de_autobahn_liste", "https://verkehr.autobahn.de/o/autobahn/")
    hole(c, "de_autobahn_a8_roadworks", "https://verkehr.autobahn.de/o/autobahn/A8/services/roadworks")
    hole(c, "de_autobahn_a99_closure", "https://verkehr.autobahn.de/o/autobahn/A99/services/closure")
    # MobiData BW
    hole(c, "de_mobidata_roadworks", "https://api.mobidata-bw.de/datasets/traffic/roadworks/roadworks_geojson.json",
         speichern=False)
    for pid in ("eco-counter-fahrradzahler", "baustelleninformationen-baden-wurttemberg", "e-ladesaulen",
                "karte_strassenverkehrszaehlung"):
        hole(c, f"de_mobidata_ckan_{pid[:30]}", "https://mobidata-bw.de/api/3/action/package_show", params={"id": pid})
    # Ladesäulenregister
    for name, url in (("de_ladesaeulen_csv", "https://www.bundesnetzagentur.de/SharedDocs/Downloads/DE/Sachgebiete/Energie/Unternehmen_Institutionen/E_Mobilitaet/Ladesaeulenregister.csv"),
                      ("de_ladesaeulen_xlsx", "https://www.bundesnetzagentur.de/SharedDocs/Downloads/DE/Sachgebiete/Energie/Unternehmen_Institutionen/E_Mobilitaet/Ladesaeulenregister.xlsx"),
                      ("de_ladesaeulen_api", "https://ladestationen.api.bund.dev/openapi.yaml")):
        daten = hole(c, name, url, speichern=False)
        if daten:
            kopf(f"{name}_kopf", daten[:200000], 15)
            manifest.append({"name": f"{name}_umfang", "bytes": len(daten)})
    # ParkAPI
    hole(c, "de_parkapi_index", "https://api.parkendd.de/")
    hole(c, "de_parkapi_dresden", "https://api.parkendd.de/Dresden")
    hole(c, "de_parkapi_koeln", "https://api.parkendd.de/Koeln")
    # NRW
    for name, url in (("de_nrw_strassen_wfs", "https://www.wfs.nrw.de/wfs/strassen_nrw"),
                      ("de_nrw_denkmal_wfs", "https://www.wfs.nrw.de/kultur/denkmal"),
                      ("de_nrw_bauleitplanung_wfs", "https://www.wfs.nrw.de/wfs/bauleitplanung")):
        hole(c, name, url, params={"REQUEST": "GetCapabilities", "SERVICE": "WFS", "VERSION": "2.0.0"})
    hole(c, "de_nrw_starkregen_caps", "https://www.wms.nrw.de/umwelt/starkregen",
         params={"REQUEST": "GetCapabilities", "SERVICE": "WMS"}, speichern=False)
    # Hamburg
    hole(c, "de_hh_verkehrsstaerken_caps", "https://geodienste.hamburg.de/HH_WMS_Verkehrsstaerken",
         params={"SERVICE": "WMS", "REQUEST": "GetCapabilities"})
    daten = hole(c, "de_hh_api_collections", "https://api.hamburg.de/datasets/v1/", params={"f": "json"}, speichern=False)
    if daten:
        t = daten.decode("utf-8", "replace")
        ids = re.findall(r'"id"\s*:\s*"([^"]+)"', t)
        manifest.append({"name": "de_hh_api_ids", "anzahl": len(ids),
                         "treffer": [i for i in ids if re.search(r"verkehr|stadtteil|fahrgast|profil|statistik|parken|park", i, re.I)][:40]})
    for pid in ("stadtteil-profile-hamburg10", "hvv-fahrgastzahlen1",
                "regionalstatistische-daten-der-bezirke-hamburgs-und-hamburg-insgesamt20"):
        hole(c, f"de_hh_ckan_{pid[:28]}", "https://suche.transparenz.hamburg.de/api/3/action/package_show", params={"id": pid})
    # Köln, Frankfurt, Stuttgart
    for pid in ("statistischer-datenkatalog-koeln", "baustellen-koeln", "parkhausbelegung",
                "fahrrad-verkehrsdaten-koeln-0", "wochenmaerkte-koeln"):
        hole(c, f"de_koeln_ckan_{pid[:28]}", "https://www.offenedaten-koeln.de/api/3/action/package_show", params={"id": pid})
    hole(c, "de_koeln_ckan_suche_tourismus", "https://www.offenedaten-koeln.de/api/3/action/package_search",
         params={"q": "Monatserhebung Tourismus", "rows": 3})
    hole(c, "de_ffm_ckan_stadtteilprofile", "https://www.offenedaten.frankfurt.de/api/3/action/package_show",
         params={"id": "stadtteilprofile-bevoelkerung"})
    hole(c, "de_stuttgart_ckan_suche_baustellen", "https://opendata.stuttgart.de/api/3/action/package_search",
         params={"q": "Baustellen", "rows": 3})
    # DB Stationsdaten, ohsome quality, Regionaldatenbank-Gastzugang, Landesdatenbank NRW
    hole(c, "de_db_stationsdaten", "https://download-data.deutschebahn.com/static/datasets/stationsdaten/DBSuS-Uebersicht_Bahnhoefe-Stand2020-03.csv",
         speichern=False)
    hole(c, "de_ohsome_quality_meta", "https://api.quality.ohsome.org/v1/metadata")
    hole(c, "de_ohsome_quality_indikator", "https://api.quality.ohsome.org/v1/indicators/mapping-saturation",
         methode="POST", headers={"Content-Type": "application/json"},
         data=json.dumps({"topic": "poi", "bpolys": {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {},
                          "geometry": {"type": "Polygon", "coordinates": [[[11.565, 48.13], [11.585, 48.13], [11.585, 48.145], [11.565, 48.145], [11.565, 48.13]]]}}]}}))
    hole(c, "de_regionaldb_gast_73111", "https://www.regionalstatistik.de/genesisws/rest/2020/catalogue/tables",
         params={"username": "GAST", "password": "GAST", "selection": "73111*", "pagelength": 20, "language": "de"})
    hole(c, "de_ldb_nrw_45412", "https://www.landesdatenbank.nrw.de/ldbnrw/online",
         params={"operation": "download", "code": "45412-02i", "option": "csv"}, speichern=False)


TEILE.update({"gemeinde5": gemeinde_r5, "wien5": wien_r5, "staedte5": staedte_r5, "de5": de_r5})


# ------------------------------------------------------------------ Runde 6
# Lücken aus Runde 5 schließen und Punktantworten für die Module holen.

LINZ = (48.3064, 14.2861)
DRESDEN = (51.0504, 13.7373)
ALEXANDERPLATZ = (52.5219, 13.4132)
HH_MOENCKEBERG = (53.5506, 9.9960)


def _wfs_json(c, name, url, typ, lat, lon, d=0.004, version="1.1.0", extra=None, fmt="application/json"):
    p = {"service": "WFS", "version": version, "request": "GetFeature", "srsName": "EPSG:4326",
         "outputFormat": fmt, "maxFeatures": 50, "count": 50,
         "bbox": f"{lon-d:.6f},{lat-d:.6f},{lon+d:.6f},{lat+d:.6f},EPSG:4326"}
    p["typeNames" if version.startswith("2") else "typeName"] = typ
    p.update(extra or {})
    return hole(c, name, url, params=p)


def _slugs(daten: bytes) -> list[str]:
    t = daten.decode("utf-8", "replace")
    return list(dict.fromkeys(re.findall(r'/katalog/dataset/([a-z0-9][a-z0-9_\-]{6,})"', t)))


def _datagv_html_suche(c, name: str, q: str) -> list[str]:
    daten = hole(c, f"datagv_r6_suche_{name}", "https://www.data.gv.at/katalog/dataset/", params={"q": q},
                 speichern=False)
    slugs = _slugs(daten) if daten else []
    manifest.append({"name": f"datagv_r6_suche_{name}_slugs", "slugs": slugs[:10]})
    return slugs


def at_r6(c):
    # Punkt → Gemeindekennziffer über den GeoServer von Statistik Austria
    for ort, (lat, lon) in (("stephansplatz", WIEN), ("graz", GRAZ), ("krems", (48.4020, 15.6100))):
        _wfs_json(c, f"stat_r6_gem_{ort}", "https://www.statistik.gv.at/gs-open/GEODATA/ows",
                  "GEODATA:STATISTIK_AUSTRIA_GEM_20250101", lat, lon, d=0.0005)
    hole(c, "stat_r6_gem_caps", "https://www.statistik.gv.at/gs-open/GEODATA/ows",
         params={"service": "WFS", "request": "GetCapabilities", "version": "1.1.0"}, speichern=False)
    hole(c, "stat_r6_hpi_csv", "https://data.statistik.gv.at/data/OGD_hpivr_HPI_VR_1.csv")
    for art in ("Baugrundstueckspreise", "Wohnungspreise"):
        daten = hole(c, f"stat_r6_immo_{art.lower()}2024_ods", f"https://www.statistik.at/fileadmin/pages/222/{art}2024.ods",
                     speichern=False)
        if daten:
            _speichern(f"stat_r6_{art.lower()}2024.ods", daten)
    # data.gv.at: Suche über die HTML-Seite, dann package_show
    for name, q in (("ams", "Arbeitslos vorgemerkte Personen Schulungsteilnehmer Gemeinden Geschlecht"),
                    ("gisa", "Gewerbe in Österreich GISA"), ("graz_bev", "Grazer Bevölkerung nach Bezirk und Alter"),
                    ("linz_bev", "Altersschichtung statistische Bezirke Linz"),
                    ("salzburg_bev", "Einwohner Zählbezirk Alter Geschlecht Salzburg"),
                    ("vbg_tourismus", "Tourismusstatistik Vorarlberg"), ("noe_no2", "Stickstoffdioxid NO2 Niederösterreich"),
                    ("linz_luft", "Luftgüte meteorologische Messwerte Linz"), ("denkmal_ooe", "Denkmalliste Oberösterreich"),
                    ("noe_jdtv", "Straßenverkehrszählung Dauerzählstellen JDTV Niederösterreich")):
        slugs = _datagv_html_suche(c, name, q)
        for slug in slugs[:2]:
            res = _ckan_show(c, f"{name}_{slug[:24]}", slug)
            url = _erste_csv(res)
            if url and not url.lower().endswith((".zip", ".pdf")):
                daten = hole(c, f"{name}_r6_{slug[:20]}_daten", url, speichern=False)
                if daten:
                    kopf(f"{name}_r6_{slug[:20]}_kopf", daten, 30)
                    manifest.append({"name": f"{name}_r6_{slug[:20]}_umfang", "url": url, "bytes": len(daten),
                                     "zeilen": daten.count(b"\n"), "utf8": _ist_utf8(daten)})
    # Wien: Kfz-Dauerzählstellen (Lage), Luftgütenetz, Zählgebiet, Luft-CSV, Wohnungen je Zählbezirk voll
    wfs = "https://data.wien.gv.at/daten/geo"
    for typ in ("DAUERZAEHLOGD", "LUFTGUETENETZOGD"):
        hole(c, f"wien_r6_{typ.lower()}", wfs, params={"service": "WFS", "request": "GetFeature", "version": "1.1.0",
             "typeName": f"ogdwien:{typ}", "srsName": "EPSG:4326", "outputFormat": "json"})
    _wfs_json(c, "wien_r6_zaehlgebietogd", wfs, "ogdwien:ZAEHLGEBIETOGD", *WIEN, d=0.0005)
    daten = hole(c, "wien_r6_luft_csv", "https://go.gv.at/l9lumesakt", speichern=False)
    if daten:
        kopf("wien_r6_luft_kopf", daten, 40)
    daten = hole(c, "wien_r6_wohnungen_404", "https://www.wien.gv.at/data/ogd/ma23/vie-404-2021.csv", speichern=False)
    if daten:
        _speichern("wien_r6_wohnungen_zaehlbezirk_2021.csv", daten)
    # Salzburg: Widmung, Bebauungsplan, Altstadtschutzzone, Kurzparkzone am Punkt; Märkte, Radzählstellen stadtweit
    sbg = "https://data.stadt-salzburg.at/geodaten/wfs"
    for typ in ("flaechenwidmung", "bebauungsplan_rechtswirksam", "altstadtschutzzone", "kurzparkzone", "bewohnerparkzone"):
        _wfs_json(c, f"salzburg_r6_{typ}", sbg, f"ogdsbg:{typ}", *SALZBURG, d=0.0006)
    for typ in ("markt", "radzaehlstelle", "baustelle_aktuell"):
        hole(c, f"salzburg_r6_{typ}", sbg, params={"service": "WFS", "version": "1.1.0", "request": "GetFeature",
             "srsName": "EPSG:4326", "outputFormat": "application/json", "typeName": f"ogdsbg:{typ}", "maxFeatures": 60})
    # DORIS (OÖ): Widmung am Linzer Hauptplatz, ArcGIS WFSServer 2.0
    doris = "https://ags.doris.at/arcgis/services/HVD/MapServer/WFSServer"
    for fmt in ("GEOJSON", "application/json"):
        _wfs_json(c, f"doris_r6_flwi_linz_{fmt[:4].lower()}", doris, "HVD:FLWI_Widmungen_Flächen", *LINZ, d=0.001,
                  version="2.0.0", fmt=fmt)
    p = {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": "HVD:FLWI_Widmungen_Flächen",
         "count": 5, "bbox": f"{LINZ[0]-0.001},{LINZ[1]-0.001},{LINZ[0]+0.001},{LINZ[1]+0.001},urn:ogc:def:crs:EPSG::4326"}
    hole(c, "doris_r6_flwi_linz_gml", doris, params=p)
    hole(c, "doris_r6_describe", doris, params={"service": "WFS", "version": "2.0.0", "request": "DescribeFeatureType",
                                              "typeNames": "HVD:FLWI_Widmungen_Flächen"})
    hole(c, "stmk_r6_hale_caps", "https://haleconnect.com/ows/services/org.926.4be5ef1f-2eea-42c8-b9ea-e393835f28c2_wfs",
         params={"SERVICE": "WFS", "REQUEST": "GetCapabilities", "VERSION": "2.0.0"})


def de_r6(c):
    # Berlin: Verkehrsmengen 2023 — Capabilities speichern, dann GetFeature
    caps = hole(c, "de_berlin_r6_verkehrsmengen_caps", "https://gdi.berlin.de/services/wfs/verkehrsmengen_2023",
                params={"REQUEST": "GetCapabilities", "SERVICE": "WFS"})
    typen = re.findall(r"<Name>([^<]+)</Name>", caps.decode("utf-8", "replace")) if caps else []
    manifest.append({"name": "de_berlin_r6_typen", "typen": typen[:20]})
    for typ in [t for t in typen if ":" in t][:4]:
        _wfs_json(c, f"de_berlin_r6_{re.sub(r'[^a-z0-9]+', '_', typ.lower())[:30]}",
                  "https://gdi.berlin.de/services/wfs/verkehrsmengen_2023", typ, *ALEXANDERPLATZ, d=0.004, version="2.0.0")
    for name in ("wohnlagen_2024", "mietspiegel_wohnlagen_2024", "wohnlagen_mietspiegel_2024", "starkregen_gefahrenkarte",
                 "starkregenhinweiskarte_2024", "radzaehlstellen_2024"):
        hole(c, f"de_berlin_r6_caps_{name}", f"https://gdi.berlin.de/services/wfs/{name}",
             params={"REQUEST": "GetCapabilities", "SERVICE": "WFS"}, speichern=False)
    # Starkregen: Wassertiefe und Geschwindigkeit an Punkten in fünf Ländern
    for ort, (lat, lon) in (("koeln", KOELN), ("berlin", ALEXANDERPLATZ), ("hamburg", HH_MOENCKEBERG),
                            ("dresden", DRESDEN), ("isarauen", (48.1050, 11.5530))):
        for ly in ("tiefe_agw", "tiefe_extrem", "geschwindigkeit_agw", "geschwindigkeit_extrem"):
            _gfi(c, f"de_starkregen_r6_{ly}_{ort}", "https://sgx.geodatenzentrum.de/wms_starkregen", ly, lat, lon)
    # Autobahn: zwei weitere Strecken, Warnungen
    hole(c, "de_autobahn_r6_a99_roadworks", "https://verkehr.autobahn.de/o/autobahn/A99/services/roadworks")
    hole(c, "de_autobahn_r6_a9_warning", "https://verkehr.autobahn.de/o/autobahn/A9/services/warning")
    # MobiData BW: Baustellen (Ausschnitt speichern), Eco-Counter Tages-/Stundenwerte, SVZ-Grunddaten, Ladesäulen
    daten = hole(c, "de_mobidata_r6_roadworks", "https://api.mobidata-bw.de/datasets/traffic/roadworks/roadworks_geojson.json",
                 speichern=False)
    if daten:
        try:
            d = json.loads(daten)
            fs = d.get("features", [])
            nah = [f for f in fs if _nahe(f, STUTTGART, 0.06)]
            _speichern("de_mobidata_r6_roadworks_stuttgart.json", json.dumps(
                {"type": "FeatureCollection", "features": nah[:80]}, ensure_ascii=False).encode())
            manifest.append({"name": "de_mobidata_r6_roadworks_umfang", "features": len(fs), "stuttgart": len(nah),
                             "properties": sorted((fs[0].get("properties") or {}).keys())[:40] if fs else []})
        except Exception as exc:  # noqa: BLE001
            manifest.append({"name": "de_mobidata_r6_roadworks_fehler", "fehler": str(exc)})
    for name, url in (("eco_tage", "https://mobidata-bw.de/daten/eco-counter/v2/fahrradzaehler_tageswerten.csv"),
                      ("eco_stunden", "https://mobidata-bw.de/daten/eco-counter/v2/fahrradzaehler_stundenwerten.csv"),
                      ("svz", "https://mobidata-bw.de/vm/Karte_Strassenverkehrszaehlung_BW/SVZ-Zaehlstellen_2026-06-26_augmented_SVZ2024.csv")):
        daten = hole(c, f"de_mobidata_r6_{name}", url, speichern=False)
        if daten:
            kopf(f"de_mobidata_r6_{name}_kopf", daten, 25)
            manifest.append({"name": f"de_mobidata_r6_{name}_umfang", "bytes": len(daten), "zeilen": daten.count(b"\n")})
    _wfs_json(c, "de_mobidata_r6_ladesaeulen_stuttgart", "https://api.mobidata-bw.de/geoserver/MobiData-BW/ows",
              "MobiData-BW:charge_points", *STUTTGART, d=0.01, version="1.0.0")
    _wfs_json(c, "de_mobidata_r6_roadworks_wfs_stuttgart", "https://api.mobidata-bw.de/geoserver/MobiData-BW/ows",
              "MobiData-BW:roadworks", *STUTTGART, d=0.03, version="1.0.0")
    hole(c, "de_ladesaeulen_r6_api_yaml", "https://ladestationen.api.bund.dev/openapi.yaml")
    # ParkAPI: Städte mit aktiver Pflege
    daten = hole(c, "de_parkapi_r6_index", "https://api.parkendd.de/", speichern=False)
    if daten:
        try:
            st = json.loads(daten).get("cities", {})
            manifest.append({"name": "de_parkapi_r6_aktiv", "aktiv": sorted(k for k, v in st.items() if v.get("active_support"))})
        except Exception:  # noqa: BLE001
            pass
    for stadt in ("Dresden", "Hamburg", "Muenchen", "Koeln", "Frankfurt", "Nuernberg"):
        hole(c, f"de_parkapi_r6_{stadt.lower()}", f"https://api.parkendd.de/{stadt}")
    # NRW Straßen.NRW: Zählstellen und Verkehrswerte um Köln
    for typ in ("ms:Zaehlstellen", "ms:Verkehrswerte", "ms:Zaehlstellen2019HR"):
        _wfs_json(c, f"de_nrw_r6_{typ.split(':')[1].lower()}", "https://www.wfs.nrw.de/wfs/strassen_nrw", typ, *KOELN,
                  d=0.05, version="2.0.0", fmt="geojson")
    # Hamburg: OGC API Features
    for coll in ("verkehrsstaerken", "verkehrsmengen", "verkehrszaehlstellen", "statistik_stadtteile_bevoelkerung",
                 "regionalstatistische_daten_stadtteile", "parkhaeuser", "statistik_stadtteile_wohnungsdaten", "parkraum"):
        daten = hole(c, f"de_hh_r6_{coll}_collections", f"https://api.hamburg.de/datasets/v1/{coll}/collections",
                     params={"f": "json"})
        if daten:
            try:
                ids = [x.get("id") for x in json.loads(daten).get("collections", [])]
            except Exception:  # noqa: BLE001
                ids = []
            manifest.append({"name": f"de_hh_r6_{coll}_ids", "ids": ids[:20]})
            for cid in ids[:3]:
                lat, lon = HH_MOENCKEBERG
                d = 0.01
                hole(c, f"de_hh_r6_{coll}_{cid[:24]}", f"https://api.hamburg.de/datasets/v1/{coll}/collections/{cid}/items",
                     params={"f": "json", "limit": 20, "bbox": f"{lon-d},{lat-d},{lon+d},{lat+d}"})
    hole(c, "de_hh_r6_verkehrsstaerken_gfi", "https://geodienste.hamburg.de/HH_WMS_Verkehrsstaerken",
         params={"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetFeatureInfo", "LAYERS": "verkehrsstaerken",
                 "QUERY_LAYERS": "verkehrsstaerken", "CRS": "EPSG:4326",
                 "BBOX": f"{HH_MOENCKEBERG[0]-0.002},{HH_MOENCKEBERG[1]-0.003},{HH_MOENCKEBERG[0]+0.002},{HH_MOENCKEBERG[1]+0.003}",
                 "WIDTH": 101, "HEIGHT": 101, "I": 50, "J": 50, "INFO_FORMAT": "text/plain", "FEATURE_COUNT": 10, "STYLES": ""})
    # Köln CKAN ohne www, Suche
    for pid in ("baustellen-koeln", "parkhausbelegung", "statistischer-datenkatalog-koeln", "wochenmaerkte-koeln"):
        hole(c, f"de_koeln_r6_show_{pid[:24]}", "https://offenedaten-koeln.de/api/3/action/package_show", params={"id": pid})
    hole(c, "de_koeln_r6_suche", "https://offenedaten-koeln.de/api/3/action/package_search", params={"q": "Baustellen", "rows": 3})
    # Stuttgart Baustellen als GeoJSON in WGS84
    _wfs_json(c, "de_stuttgart_r6_baustellen", "https://geoserver.stuttgart.de/gdc/Verkehr_Mobilitaet/ows",
              "Verkehr_Mobilitaet:A66_BAUM_BAUSTELLEN_DATE_WEB_im_Bau_EPSG25832", *STUTTGART, d=0.03, version="1.0.0")
    # Regionaldatenbank: Gastzugang per POST; ohsome quality mit JSON-Accept; Frankfurt über http
    hole(c, "de_regionaldb_r6_gast_73111", "https://www.regionalstatistik.de/genesisws/rest/2020/catalogue/tables",
         methode="POST", data={"username": "GAST", "password": "GAST", "selection": "73111*", "pagelength": 20, "language": "de"})
    hole(c, "de_ohsome_r6_meta", "https://api.quality.ohsome.org/v1/metadata", headers={"Accept": "application/json"})
    hole(c, "de_ohsome_r6_indikator", "https://api.quality.ohsome.org/v1/indicators/mapping-saturation", methode="POST",
         headers={"Content-Type": "application/json", "Accept": "application/json"},
         data=json.dumps({"topic": "poi", "bpolys": {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {},
                          "geometry": {"type": "Polygon", "coordinates": [[[11.565, 48.13], [11.585, 48.13], [11.585, 48.145], [11.565, 48.145], [11.565, 48.13]]]}}]}}))
    hole(c, "de_ffm_r6_stadtteilprofile", "http://www.offenedaten.frankfurt.de/api/3/action/package_show",
         params={"id": "stadtteilprofile-bevoelkerung"})


def _nahe(f, punkt, d):
    g = f.get("geometry") or {}
    c = g.get("coordinates")
    while isinstance(c, list) and c and isinstance(c[0], list):
        c = c[0]
    if not (isinstance(c, list) and len(c) >= 2):
        return False
    try:
        return abs(float(c[1]) - punkt[0]) < d and abs(float(c[0]) - punkt[1]) < d
    except (TypeError, ValueError):
        return False


TEILE.update({"at6": at_r6, "de6": de_r6})


# ------------------------------------------------------------------ Runde 7
# Auszüge für Fixtures und drei Nachzügler (BNetzA-Ladesäulen, NRW-WFS).

def r7(c):
    daten = hole(c, "wien_r7_dauerzaehlstellen_csv", "https://www.wien.gv.at/data/ogd/ma46/dauerzaehlstellen.csv",
                 speichern=False)
    if daten:
        zeilen = daten.decode("cp1252", "replace").splitlines()
        aus = [zeilen[0]] + [z for z in zeilen[1:] if z.startswith("2025;")]
        _speichern("wien_r7_dauerzaehlstellen_2025.csv", "\n".join(aus).encode("utf-8"))
        manifest.append({"name": "wien_r7_dauerzaehlstellen_umfang", "zeilen": len(zeilen), "zeilen_2025": len(aus) - 1,
                         "jahre": sorted({z[:4] for z in zeilen[1:]})})
    daten = hole(c, "wien_r7_luft_csv", "https://go.gv.at/l9lumesakt", speichern=False)
    if daten:
        _speichern("wien_r7_luft_lumes.csv", daten)
    daten = hole(c, "de_mobidata_r7_roadworks", "https://api.mobidata-bw.de/datasets/traffic/roadworks/roadworks_geojson.json",
                 speichern=False)
    if daten:
        try:
            d = json.loads(daten)
            fs = d.get("features", [])
            _speichern("de_mobidata_r7_roadworks_auszug.json", json.dumps(
                {"type": "FeatureCollection", "features": fs[:60]}, ensure_ascii=False).encode())
        except Exception as exc:  # noqa: BLE001
            manifest.append({"name": "de_mobidata_r7_roadworks_fehler", "fehler": str(exc)})
    daten = hole(c, "de_mobidata_r7_eco_tage", "https://mobidata-bw.de/daten/eco-counter/v2/fahrradzaehler_tageswerten.csv",
                 speichern=False)
    if daten:
        zeilen = daten.decode("utf-8", "replace").splitlines()
        _speichern("de_mobidata_r7_eco_tageswerte_auszug.csv", "\n".join([zeilen[0]] + zeilen[-400:]).encode("utf-8"))
    daten = hole(c, "de_mobidata_r7_svz", "https://mobidata-bw.de/vm/Karte_Strassenverkehrszaehlung_BW/SVZ-Zaehlstellen_2026-06-26_augmented_SVZ2024.csv",
                 speichern=False)
    if daten:
        zeilen = daten.decode("utf-8", "replace").splitlines()
        def nah(z):
            t = z.split(",")
            try:
                return 8.9 <= float(t[4]) <= 9.5 and 48.6 <= float(t[5]) <= 48.95
            except (ValueError, IndexError):
                return False
        _speichern("de_mobidata_r7_svz_stuttgart.csv", "\n".join([zeilen[0]] + [z for z in zeilen[1:] if nah(z)]).encode("utf-8"))
    # BNetzA Ladesäulenregister: ArcGIS FeatureServer aus der bund.dev-Doku
    basis = "https://services6.arcgis.com/6jU7RmJig2Wwo1b0/ArcGIS/rest/services/Ladesaeulenregister/FeatureServer/7"
    hole(c, "de_bnetza_r7_meta", basis, params={"f": "json"})
    for ort, (lat, lon) in (("marienplatz", MUENCHEN), ("stephansplatz", WIEN), ("koeln", KOELN)):
        hole(c, f"de_bnetza_r7_query_{ort}", f"{basis}/query",
             params={"geometry": json.dumps({"x": lon, "y": lat, "spatialReference": {"wkid": 4326}}),
                     "geometryType": "esriGeometryPoint", "inSR": 4326, "outSR": 4326, "distance": 600,
                     "units": "esriSRUnit_Meter", "outFields": "*", "f": "json", "resultRecordCount": 50})
    # NRW Straßen.NRW: Ausgabeformat
    for fmt in (None, "application/json", "application/json; subtype=geojson", "GEOJSON"):
        p = {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": "ms:Zaehlstellen",
             "srsName": "EPSG:4326", "count": 20,
             "bbox": f"{KOELN[1]-0.05},{KOELN[0]-0.05},{KOELN[1]+0.05},{KOELN[0]+0.05},EPSG:4326"}
        if fmt:
            p["outputFormat"] = fmt
        hole(c, f"de_nrw_r7_zaehlstellen_{re.sub(r'[^a-z]+', '_', (fmt or 'gml').lower())[:20]}",
             "https://www.wfs.nrw.de/wfs/strassen_nrw", params=p)
    hole(c, "salzburg_r7_altstadtschutzzone", "https://data.stadt-salzburg.at/geodaten/wfs",
         params={"service": "WFS", "version": "1.1.0", "request": "GetFeature", "srsName": "EPSG:4326",
                 "outputFormat": "application/json", "typeName": "ogdsbg:altstadtschutzzone", "maxFeatures": 5})


TEILE.update({"r7": r7})


if __name__ == "__main__":
    sys.exit(main(sys.argv))

