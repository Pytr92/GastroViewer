"""Bevölkerungsraster Österreich — Eurostat GEOSTAT Census Grid 2021, 1 km.

Statistik Austria bietet ihr 100-m-Raster nur als Geometrie an; die
Einwohner je Zelle kosten Geld. Offen ist die europäische Fassung: das
Eurostat-Raster der Registerzählung 2021 mit 1-km-Zellen (ETRS89-LAEA,
EPSG:3035) — für alle EU-Länder, also auch Deutschland, hier aber nur für
Österreich genutzt, weil Deutschland den feineren Zensus-Gitterdienst hat.

Live belegt am 18.09.2026 (fixtures/at, AT-Probe): Das ZIP
``Eurostat_Census-GRID_2021_V1-0.zip`` (186 MB) enthält ein GeoPackage
``ESTAT_Census_2011_V1-0.gpkg`` (1,27 GB, Tabellenname trotz Zensus 2021
mit „2011“), Spalten ``GRD_ID`` (``CRS3035RES1000mN2800000E4800000``) und
``OBS_VALUE_T`` (Einwohner gesamt) — **nur** die Gesamtzahl, keine
Altersgruppen. Laut ``read.me`` sind die Daten „provisional, under
validation“. Ein GeoPackage ist eine SQLite-Datei; die Geometrie steckt
schon in der Zell-ID (linke untere Ecke in Metern), deshalb wird das
Geometrie-Blob nicht gelesen.

Import wie beim Fahrplan: einmalig per ``gastroviewer import-raster-at``,
danach liegt ``raster_at.sqlite`` mit den österreichischen Zellen lokal —
kein Netzabruf je Punkt.

Die Umrechnung EPSG:3035 → WGS84 ist die inverse Lambert-Azimutal-
Flächentreue Projektion auf dem GRS80-Ellipsoid (Snyder 1987, S. 187 ff.,
über die authalische Breite), ohne Zusatzbibliothek. Gegenprobe im Test:
der Projektionsursprung (4 321 000 / 3 210 000) ist exakt 52° N / 10° O.
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Callable

from ..config import Settings
from .base import Provenance, SourceError, SourceResult, now_iso

QUELLE_URL = "https://gisco-services.ec.europa.eu/census/2021/Eurostat_Census-GRID_2021_V1-0.zip"
LICENSE = ("Eurostat, GEOSTAT Census Grid 2021 (© EuroGeographics für die "
           "Verwaltungsgrenzen; Nutzung frei mit Quellenangabe, Eurostat-"
           "Download-Regeln)")
STAND = "Registerzählung 2021 (Stichtag 31.10.2021), Eurostat-Fassung V1-0, provisorisch"
ZELLE_M = 1000

# ETRS89-LAEA (EPSG:3035): Ursprung 52° N / 10° O, GRS80.
_A = 6378137.0
_F = 1 / 298.257222101
_E2 = 2 * _F - _F * _F
_E = math.sqrt(_E2)
_LAT0 = math.radians(52.0)
_LON0 = math.radians(10.0)
_X0 = 4321000.0
_Y0 = 3210000.0

# Grober Kasten Österreichs in EPSG:3035-Metern (aus dem Kasten der Registry
# projiziert, mit Rand) — nur, damit der Import nicht 4,7 Millionen Zellen
# durchgeht; entschieden wird je Zelle nach dem WGS84-Kasten.
AT_E = (4260000, 4890000)
AT_N = (2560000, 2920000)


def _q(lat: float) -> float:
    """Snyder (3-12): q(φ) für die authalische Breite."""
    s = math.sin(lat)
    return (1 - _E2) * (s / (1 - _E2 * s * s) - (1 / (2 * _E)) * math.log((1 - _E * s) / (1 + _E * s)))


_QP = _q(math.pi / 2)
_RQ = _A * math.sqrt(_QP / 2)
_BETA1 = math.asin(_q(_LAT0) / _QP)
_M1 = math.cos(_LAT0) / math.sqrt(1 - _E2 * math.sin(_LAT0) ** 2)
_D = _A * _M1 / (_RQ * math.cos(_BETA1))


def laea_zu_wgs84(x: float, y: float) -> tuple[float, float]:
    """EPSG:3035 (Ost, Nord in Metern) → (Breite, Länge in Grad)."""
    dx = (x - _X0) / _D
    dy = (y - _Y0) * _D
    rho = math.hypot(dx, dy)
    if rho < 1e-9:
        return math.degrees(_LAT0), math.degrees(_LON0)
    ce = 2 * math.asin(rho / (2 * _RQ))
    sin_ce, cos_ce = math.sin(ce), math.cos(ce)
    beta = math.asin(cos_ce * math.sin(_BETA1) + (dy * sin_ce * math.cos(_BETA1) / rho))
    lon = _LON0 + math.atan2(dx * sin_ce,
                             rho * math.cos(_BETA1) * cos_ce - dy * math.sin(_BETA1) * sin_ce)
    # Authalische → geodätische Breite (Snyder 3-18, Reihe)
    e4, e6 = _E2 * _E2, _E2 * _E2 * _E2
    lat = (beta
           + (_E2 / 3 + 31 * e4 / 180 + 517 * e6 / 5040) * math.sin(2 * beta)
           + (23 * e4 / 360 + 251 * e6 / 3780) * math.sin(4 * beta)
           + (761 * e6 / 45360) * math.sin(6 * beta))
    return math.degrees(lat), math.degrees(lon)


def wgs84_zu_laea(lat_deg: float, lon_deg: float) -> tuple[float, float]:
    """WGS84 → EPSG:3035 — für Tests und die Bounding-Box-Suche."""
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    beta = math.asin(_q(lat) / _QP)
    b = _RQ * math.sqrt(2 / (1 + math.sin(_BETA1) * math.sin(beta)
                             + math.cos(_BETA1) * math.cos(beta) * math.cos(lon - _LON0)))
    x = _X0 + b * _D * math.cos(beta) * math.sin(lon - _LON0)
    y = _Y0 + (b / _D) * (math.cos(_BETA1) * math.sin(beta)
                          - math.sin(_BETA1) * math.cos(beta) * math.cos(lon - _LON0))
    return x, y


_ID = re.compile(r"CRS3035RES(\d+)mN(\d+)E(\d+)")


def zelle_aus_id(grd_id: str) -> tuple[int, int, int] | None:
    """``CRS3035RES1000mN2800000E4800000`` → (Kantenlänge, Nord, Ost) der
    linken unteren Ecke in Metern."""
    m = _ID.fullmatch(str(grd_id or "").strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def ring_wgs84(n: int, e: int, kante: int = ZELLE_M) -> list[list[float]]:
    """Zellumriss als [lon, lat]-Ring (geschlossen) — dieselbe Form wie die
    Zensus-Zellen aus dem ArcGIS-Dienst."""
    ecken = [(e, n), (e + kante, n), (e + kante, n + kante), (e, n + kante), (e, n)]
    ring = []
    for x, y in ecken:
        lat, lon = laea_zu_wgs84(x, y)
        ring.append([round(lon, 7), round(lat, 7)])
    return ring


# ------------------------------------------------------------- Import

SCHEMA = """
CREATE TABLE IF NOT EXISTS zellen (
    grd_id     TEXT PRIMARY KEY,
    e          INTEGER NOT NULL,
    n          INTEGER NOT NULL,
    lat        REAL NOT NULL,
    lon        REAL NOT NULL,
    einwohner  REAL
);
CREATE INDEX IF NOT EXISTS idx_zellen_lat_lon ON zellen(lat, lon);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _gpkg_tabelle(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT table_name FROM gpkg_contents WHERE data_type = 'features' LIMIT 1"
    ).fetchone()
    if row is None:
        raise SourceError("parse", "Im GeoPackage steht keine Feature-Tabelle (gpkg_contents leer).")
    return str(row[0])


def gpkg_aus_zip(zip_path: Path, ziel: Path, progress: Callable[[str], None]) -> Path:
    """Das GeoPackage aus dem Eurostat-ZIP nach ``ziel`` strömen (1,27 GB —
    nicht in den Speicher)."""
    with zipfile.ZipFile(zip_path) as z:
        namen = [n for n in z.namelist() if n.lower().endswith(".gpkg")]
        if not namen:
            raise SourceError("parse", "Im ZIP liegt kein GeoPackage (.gpkg) — falsche Datei?")
        progress(f"GeoPackage {namen[0]} entpacken …")
        with z.open(namen[0]) as quelle, open(ziel, "wb") as out:
            while True:
                stueck = quelle.read(16 * 1024 * 1024)
                if not stueck:
                    break
                out.write(stueck)
    return ziel


def import_gpkg(settings: Settings, gpkg_path: Path, *, quelle: str = QUELLE_URL,
                bbox: tuple[float, float, float, float] | None = None,
                progress: Callable[[str], None] = lambda _m: None) -> dict[str, Any]:
    """Zellen aus dem GeoPackage in ``raster_at.sqlite`` übernehmen.

    ``bbox`` (Süd, West, Nord, Ost) begrenzt auf ein Land — Vorgabe ist der
    Kasten Österreichs aus der Länder-Registry. Erst wird über die Zell-ID
    grob nach EPSG:3035-Metern gefiltert (Millionen Zellen ohne Geometrie-
    Lesen), dann je Zelle nach dem WGS84-Mittelpunkt entschieden."""
    from ..laender import AT

    sued, west, nord, ost = bbox or AT.bbox
    db_path = settings.raster_at_db_path
    tmp_path = db_path.with_name(db_path.name + ".neu")
    quelle_conn = sqlite3.connect(f"file:{gpkg_path}?mode=ro", uri=True)
    try:
        tabelle = _gpkg_tabelle(quelle_conn)
        spalten = {r[1] for r in quelle_conn.execute(f'PRAGMA table_info("{tabelle}")')}
        if "GRD_ID" not in spalten or "OBS_VALUE_T" not in spalten:
            raise SourceError(
                "parse", f"Tabelle {tabelle} hat nicht die erwarteten Spalten "
                f"GRD_ID/OBS_VALUE_T, sondern {sorted(spalten)} — Format geändert?")
        progress(f"Tabelle {tabelle}: Zellen im Kasten lesen …")
        if tmp_path.exists():
            tmp_path.unlink()
        conn = sqlite3.connect(tmp_path)
        conn.executescript(SCHEMA)
        gelesen = uebernommen = 0
        batch: list[tuple] = []
        cur = quelle_conn.execute(
            f'SELECT "GRD_ID", "OBS_VALUE_T" FROM "{tabelle}" WHERE "GRD_ID" LIKE ?',
            ("CRS3035RES1000mN%",))
        for grd_id, wert in cur:
            gelesen += 1
            teile = zelle_aus_id(grd_id)
            if not teile:
                continue
            kante, n, e = teile
            if not (AT_N[0] <= n < AT_N[1] and AT_E[0] <= e < AT_E[1]):
                continue
            lat, lon = laea_zu_wgs84(e + kante / 2, n + kante / 2)
            if not (sued <= lat <= nord and west <= lon <= ost):
                continue
            einwohner = float(wert) if isinstance(wert, (int, float)) else None
            batch.append((grd_id, e, n, round(lat, 6), round(lon, 6), einwohner))
            uebernommen += 1
            if len(batch) >= 5000:
                conn.executemany("INSERT OR REPLACE INTO zellen VALUES (?,?,?,?,?,?)", batch)
                batch.clear()
                progress(f"  … {uebernommen:,} Zellen übernommen ({gelesen:,} gelesen)")
        conn.executemany("INSERT OR REPLACE INTO zellen VALUES (?,?,?,?,?,?)", batch)
        einwohner_gesamt = conn.execute(
            "SELECT COALESCE(SUM(einwohner), 0) FROM zellen").fetchone()[0]
        meta = {
            "quelle": quelle, "tabelle": tabelle, "stand": STAND,
            "importiert_am": now_iso(), "zellen": str(uebernommen),
            "einwohner": str(int(einwohner_gesamt)),
            "bbox": json.dumps([sued, west, nord, ost]),
        }
        conn.executemany("INSERT OR REPLACE INTO meta VALUES (?,?)", list(meta.items()))
        conn.commit()
        conn.close()
    finally:
        quelle_conn.close()
    if uebernommen == 0:
        tmp_path.unlink(missing_ok=True)
        raise SourceError("leer", "Keine Zelle im Kasten — falsche Datei oder falscher Kasten?")
    # Erst die fertige Datei an ihren Platz — ein Abbruch hinterlässt die alte.
    os.replace(tmp_path, db_path)
    progress(f"{uebernommen:,} Zellen, {int(einwohner_gesamt):,} Einwohner → {db_path}")
    return {"zellen": uebernommen, "gelesen": gelesen, "einwohner": int(einwohner_gesamt),
            "datenbank": str(db_path)}


def import_zip(settings: Settings, zip_path: Path, *, quelle: str = QUELLE_URL,
               progress: Callable[[str], None] = lambda _m: None) -> dict[str, Any]:
    tmpdir = Path(tempfile.mkdtemp(prefix="gastroviewer-raster-"))
    try:
        gpkg = gpkg_aus_zip(zip_path, tmpdir / "census.gpkg", progress)
        return import_gpkg(settings, gpkg, quelle=quelle, progress=progress)
    finally:
        for f in tmpdir.glob("*"):
            f.unlink(missing_ok=True)
        tmpdir.rmdir()


def status(settings: Settings) -> dict[str, Any]:
    db = settings.raster_at_db_path
    if not db.exists():
        return {"importiert": False, "datenbank": str(db)}
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        meta = {k: v for k, v in conn.execute("SELECT key, value FROM meta")}
    finally:
        conn.close()
    return {"importiert": True, "datenbank": str(db),
            "groesse_mb": round(db.stat().st_size / 1024 / 1024, 1), **meta}


# ------------------------------------------------------------- Abfrage

def zellen_im_umkreis(db_path: Path, lat: float, lon: float, radius: int) -> list[dict[str, Any]]:
    """Alle Zellen, deren Umriss den Kreis berührt — dieselbe Regel wie der
    Zensus-Dienst (Intersects), dieselbe Form (``Einwohner``, ``_center``,
    ``_ring``), damit Gewichtung, Karte, Gehweg und Kannibalisierung
    unverändert damit rechnen."""
    from .base import haversine_m

    dlat = (radius + ZELLE_M) / 111_320.0
    dlon = (radius + ZELLE_M) / (111_320.0 * max(math.cos(math.radians(lat)), 0.01))
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT grd_id, e, n, lat, lon, einwohner FROM zellen "
            "WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
            (lat - dlat, lat + dlat, lon - dlon, lon + dlon)).fetchall()
    finally:
        conn.close()
    zellen = []
    halbe_diagonale = ZELLE_M * math.sqrt(2) / 2
    for r in rows:
        d = haversine_m(lat, lon, r["lat"], r["lon"])
        if d > radius + halbe_diagonale:
            continue
        ring = ring_wgs84(r["n"], r["e"])
        # Genauer: berührt der Kreis den Umriss? Ecken oder Kanten innerhalb.
        if d > radius and not _kreis_beruehrt_ring(lat, lon, radius, ring):
            continue
        zellen.append({
            "GRD_ID": r["grd_id"],
            "Einwohner": r["einwohner"],
            "_center": [r["lat"], r["lon"]],
            "_ring": ring,
        })
    return zellen


def _kreis_beruehrt_ring(lat: float, lon: float, radius: float, ring: list[list[float]]) -> bool:
    """Kreis (Meter) gegen Polygon: Abstand des Mittelpunkts zu jeder Kante
    im lokalen Meter-Raster."""
    kx = 111_320.0 * math.cos(math.radians(lat))
    ky = 111_320.0
    px, py = 0.0, 0.0
    pts = [((p[0] - lon) * kx, (p[1] - lat) * ky) for p in ring]
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        dx, dy = x2 - x1, y2 - y1
        laenge2 = dx * dx + dy * dy
        t = 0.0 if laenge2 == 0 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / laenge2))
        nx, ny = x1 + t * dx, y1 + t * dy
        if math.hypot(nx - px, ny - py) <= radius:
            return True
    return False


def summarize(cells: list[dict[str, Any]], lat: float, lon: float) -> dict[str, Any]:
    """Dieselbe Antwortform wie ``zensus.summarize`` — mit dem, was das
    1-km-Raster hergibt (Einwohner), und ``None`` für alles andere. Die
    Oberfläche zeigt für fehlende Felder „keine Angabe“, nicht 0."""
    from .zensus import Aggregate, pick_center_cell

    agg = Aggregate(cells)
    center = pick_center_cell(cells, lat, lon)
    einwohner = agg.sum("Einwohner")
    return {
        "zellen_gefunden": len(cells),
        "zelle_am_punkt": (
            {k: v for k, v in center.items() if not k.startswith("_")} if center else None),
        "ags": None,
        "ags_quelle": None,
        "ags_im_umkreis": {},
        "bundesland_code": None,
        "bundesland": None,
        "bevoelkerung": {
            "einwohner": einwohner,
            "altersgruppen": {},
            "durchschnittsalter": None, "haushaltsgroesse": None,
            "anteil_auslaender": None, "anteil_unter18": None, "anteil_ueber65": None,
        },
        "wohnen": {
            "miete_qm": None, "eigentuemerquote": None, "leerstandsquote": None,
            "ma_leerstandsquote": None, "flaeche_je_wohnung": None,
            "flaeche_je_bewohner": None, "gebaeude": None, "baualter": {},
            "neubau_anteil": None,
        },
        "raster": {"kante_m": ZELLE_M, "quelle": "Eurostat GEOSTAT 2021"},
        "hinweise": [
            "1-km-Raster (Eurostat, Registerzählung 2021) statt 100-m-Gitter: "
            "Bei kleinen Radien deckt eine Zelle den ganzen Umkreis — die "
            "Einwohnerzahl ist dann ein Flächenanteil einer Zelle, kein "
            "Nachbarschaftswert.",
            "Nur die Einwohnerzahl liegt offen vor; Alter, Haushalte, Mieten, "
            "Gebäude bietet Statistik Austria für das Raster nur kostenpflichtig an.",
        ],
    }


async def load(settings: Settings, lat: float, lon: float, radius: int) -> SourceResult:
    started = time.perf_counter()
    db = settings.raster_at_db_path
    if not db.exists():
        return SourceResult(
            name="zensus", ok=True, data=None,
            warnings=["Kein Bevölkerungsraster für Österreich importiert. Einmalig "
                      "ausführen: `gastroviewer import-raster-at` (lädt das "
                      "Eurostat-Raster, 186 MB, und behält nur Österreich)."],
            provenance=Provenance(source="Eurostat GEOSTAT Census Grid 2021 (nicht importiert)",
                                  license=LICENSE),
        )
    import asyncio

    from .zensus import gewichten

    cells = await asyncio.to_thread(zellen_im_umkreis, db, lat, lon, radius)
    gewichten(cells, lat, lon, radius)
    data = summarize(cells, lat, lon)
    data["zellen"] = cells
    warnings: list[str] = []
    if not cells:
        warnings.append("Keine Rasterzelle im Umkreis — im Eurostat-Raster fehlen "
                        "unbewohnte Zellen nicht, das deutet auf einen Punkt außerhalb "
                        "des importierten Kastens hin.")
    meta = status(settings)
    return SourceResult(
        name="zensus", ok=True, data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnings,
        provenance=Provenance(
            source="Eurostat GEOSTAT Census Grid 2021, 1-km-Raster (Registerzählung 2021, Statistik Austria)",
            license=LICENSE,
            endpoint=str(meta.get("quelle") or QUELLE_URL),
            stand=str(meta.get("stand") or STAND),
            retrieved_at=str(meta.get("importiert_am") or now_iso()),
            note=("Lokal importiertes Raster, kein Netzabruf je Punkt. Randzellen gehen "
                  "anteilig nach der vom Umkreis überdeckten Fläche ein. Die Eurostat-"
                  "Fassung ist als provisorisch gekennzeichnet."),
        ),
    )
