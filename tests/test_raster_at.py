"""Eurostat-Bevölkerungsraster für Österreich: Projektion, Zell-IDs, Import
aus einem GeoPackage (SQLite), Umkreisabfrage, Blockform."""

from __future__ import annotations

import asyncio
import math
import sqlite3

import pytest

from gastroviewer.config import Settings
from gastroviewer.sources import raster_at, zensus

WIEN = (48.2082, 16.3738)


def test_projektionsursprung_und_rundlauf():
    assert raster_at.laea_zu_wgs84(4321000, 3210000) == pytest.approx((52.0, 10.0), abs=1e-9)
    for lat, lon in (WIEN, (52.52, 13.405), (46.6247, 14.305), (47.0707, 15.4395)):
        x, y = raster_at.wgs84_zu_laea(lat, lon)
        la, lo = raster_at.laea_zu_wgs84(x, y)
        assert (la, lo) == pytest.approx((lat, lon), abs=1e-7)
    # Wien liegt im Fenster, das die AT-Probe live aus dem GeoPackage gezogen hat
    # (Zell-IDs N28…E48…).
    x, y = raster_at.wgs84_zu_laea(*WIEN)
    assert 4790000 < x < 4800000 and 2800000 < y < 2820000


def test_zell_id_und_ring():
    assert raster_at.zelle_aus_id("CRS3035RES1000mN2800000E4800000") == (1000, 2800000, 4800000)
    assert raster_at.zelle_aus_id("CRS3035RES100mN28000E48000") == (100, 28000, 48000)
    assert raster_at.zelle_aus_id("unsinn") is None
    ring = raster_at.ring_wgs84(2800000, 4800000)
    assert len(ring) == 5 and ring[0] == ring[-1]
    # Eine 1-km-Zelle: rund 0,009° Breite, 0,0135° Länge bei 48° N.
    lats = [p[1] for p in ring]
    lons = [p[0] for p in ring]
    # (leicht verdreht, deshalb etwas mehr als 0,009°)
    assert 0.0085 < max(lats) - min(lats) < 0.0105
    assert 0.0125 < max(lons) - min(lons) < 0.0150


def _gpkg(pfad, zellen):
    """Ein Mini-GeoPackage wie das von Eurostat: gpkg_contents + Tabelle mit
    GRD_ID/OBS_VALUE_T (Geometrie-Blob bleibt leer — wird nicht gelesen)."""
    conn = sqlite3.connect(pfad)
    conn.executescript("""
        CREATE TABLE gpkg_contents (table_name TEXT, data_type TEXT, identifier TEXT, srs_id INTEGER);
        INSERT INTO gpkg_contents VALUES ('ESTAT_Census_2011_V1-0', 'features', 'ESTAT_Census_2011_V1-0', 3035);
        CREATE TABLE "ESTAT_Census_2011_V1-0" (fid INTEGER PRIMARY KEY, geom BLOB, GRD_ID TEXT, OBS_VALUE_T REAL);
    """)
    conn.executemany('INSERT INTO "ESTAT_Census_2011_V1-0"(geom, GRD_ID, OBS_VALUE_T) VALUES (NULL, ?, ?)', zellen)
    conn.commit()
    conn.close()


@pytest.fixture()
def importiert(tmp_path):
    s = Settings()
    s.data_dir = tmp_path
    # 5 × 5 Zellen um den Stephansplatz plus eine Zelle in Bayern und eine in Italien.
    x0, y0 = raster_at.wgs84_zu_laea(*WIEN)
    e0, n0 = int(x0 // 1000) * 1000, int(y0 // 1000) * 1000
    zellen = [(f"CRS3035RES1000mN{n0 + dn * 1000}E{e0 + de * 1000}", 100.0 * (1 + abs(dn) + abs(de)))
              for dn in range(-2, 3) for de in range(-2, 3)]
    xm, ym = raster_at.wgs84_zu_laea(49.4521, 11.0767)  # Nürnberg, nördlich des Kastens
    zellen.append((f"CRS3035RES1000mN{int(ym // 1000) * 1000}E{int(xm // 1000) * 1000}", 5000.0))
    xi, yi = raster_at.wgs84_zu_laea(45.4642, 9.19)  # Mailand
    zellen.append((f"CRS3035RES1000mN{int(yi // 1000) * 1000}E{int(xi // 1000) * 1000}", 7000.0))
    zellen.append(("CRS3035RES100mN2808700E4794200", 9.0))  # 100-m-Zelle: nicht 1 km
    _gpkg(tmp_path / "census.gpkg", zellen)
    stats = raster_at.import_gpkg(s, tmp_path / "census.gpkg", progress=lambda _m: None)
    return s, stats


def test_import_behaelt_nur_oesterreich(importiert):
    s, stats = importiert
    assert stats["zellen"] == 25, "Nürnberg, Mailand und die 100-m-Zelle bleiben draußen"
    assert s.raster_at_db_path.exists()
    st = raster_at.status(s)
    assert st["importiert"] is True and st["zellen"] == "25"
    assert "provisorisch" in st["stand"]


def test_umkreis_und_blockform(importiert):
    s, _ = importiert
    zellen = raster_at.zellen_im_umkreis(s.raster_at_db_path, WIEN[0], WIEN[1], 600)
    # r=600 m in 1-km-Zellen: die eigene Zelle plus angrenzende Nachbarn, nicht alle 25.
    assert 1 <= len(zellen) <= 9, len(zellen)
    assert all("_ring" in z and "_center" in z and "Einwohner" in z for z in zellen)
    mitte = zensus.pick_center_cell(zellen, *WIEN)
    assert mitte is not None and mitte["Einwohner"] == 100.0
    zensus.gewichten(zellen, WIEN[0], WIEN[1], 600)
    data = raster_at.summarize(zellen, *WIEN)
    e = data["bevoelkerung"]["einwohner"]
    assert e and e["wert"] < 100.0 * len(zellen), "Randzellen zählen anteilig"
    assert e["zellen_anteilig"] < e["zellen"]
    assert data["ags"] is None and data["wohnen"]["miete_qm"] is None
    assert data["raster"]["kante_m"] == 1000
    weit = raster_at.zellen_im_umkreis(s.raster_at_db_path, WIEN[0], WIEN[1], 3000)
    assert len(weit) == 25


def test_load_ohne_import_und_mit(importiert, tmp_path):
    s, _ = importiert
    leer = Settings()
    leer.data_dir = tmp_path / "leer"
    res = asyncio.run(raster_at.load(leer, WIEN[0], WIEN[1], 600))
    assert res.ok and res.data is None and "import-raster-at" in res.warnings[0]
    res = asyncio.run(raster_at.load(s, WIEN[0], WIEN[1], 600))
    assert res.ok and res.data["bevoelkerung"]["einwohner"]["wert"] > 0
    assert res.data["zellen"][0]["_anteil"] <= 1.0
    assert "Eurostat" in res.provenance.source and "provisorisch" in res.provenance.note


def test_import_weist_fremde_datei_ab(tmp_path):
    s = Settings()
    s.data_dir = tmp_path
    conn = sqlite3.connect(tmp_path / "x.gpkg")
    conn.executescript("CREATE TABLE gpkg_contents (table_name TEXT, data_type TEXT);")
    conn.commit(); conn.close()
    with pytest.raises(Exception) as info:
        raster_at.import_gpkg(s, tmp_path / "x.gpkg")
    assert "gpkg_contents" in str(info.value)
    assert not s.raster_at_db_path.exists()


def test_kreis_beruehrt_ring():
    ring = raster_at.ring_wgs84(2800000, 4800000)
    mitte_lat = sum(p[1] for p in ring[:4]) / 4
    mitte_lon = sum(p[0] for p in ring[:4]) / 4
    assert raster_at._kreis_beruehrt_ring(mitte_lat, mitte_lon, 50, ring) is False, "innen, keine Kante binnen 50 m"
    # 400 m westlich des Westrands: mit r=500 m berührt, mit r=300 m nicht.
    west = ring[0][0] - 400 / (111_320 * math.cos(math.radians(mitte_lat)))
    assert raster_at._kreis_beruehrt_ring(mitte_lat, west, 500, ring) is True
    assert raster_at._kreis_beruehrt_ring(mitte_lat, west, 300, ring) is False
