"""GTFS — Abfahrten je Haltestelle und Stunde (Spec §4.4, Phase 3).

Der Import ist ein eigener CLI-Schritt (``gastroviewer import-gtfs``), nicht Teil
des Serverstarts. Die Abfrage läuft danach rein lokal gegen SQLite — kein
Outbound-Traffic, kein Cache nötig.

Phase-0-Befunde (siehe ``docs/endpoints-verified.md``):

* ``https://download.gtfs.de/germany/free/latest.zip`` — 259 MB, täglich neu,
  Lizenz CC BY 4.0, **ohne Registrierung**. Der DELFI-Weg aus §4.4 ist damit optional.
* Entpackt liegt ``stop_times.txt`` im Gigabyte-Bereich. Deshalb zwei Durchgänge:
  erst ``stops.txt`` filtern (optional per Bounding-Box), dann ``stop_times.txt``
  streamend einlesen und nur Zeilen zu bekannten Haltestellen behalten.

Es wird nichts hochgerechnet: gezählt werden reale Abfahrten aus dem Fahrplan an
einem konkreten, ausgewiesenen Stichtag.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import math
import sqlite3
import time
import zipfile
from pathlib import Path
from typing import Any, Callable, Iterable

from ..config import Settings
from .base import Provenance, SourceResult, bearing_label, haversine_m, now_iso

LICENSE = "Creative Commons BY 4.0 · Datengrundlage DELFI e.V. / gtfs.de"

SCHEMA = """
PRAGMA journal_mode=OFF;
PRAGMA synchronous=OFF;
DROP TABLE IF EXISTS stops;
DROP TABLE IF EXISTS stop_times;
DROP TABLE IF EXISTS trips;
DROP TABLE IF EXISTS routes;
DROP TABLE IF EXISTS calendar;
DROP TABLE IF EXISTS calendar_dates;
DROP TABLE IF EXISTS meta;
CREATE TABLE stops (
    stop_id TEXT PRIMARY KEY, stop_name TEXT, stop_lat REAL, stop_lon REAL,
    location_type INTEGER, parent_station TEXT
);
CREATE TABLE stop_times (stop_id TEXT, trip_id TEXT, departure_time TEXT);
CREATE TABLE trips (trip_id TEXT PRIMARY KEY, route_id TEXT, service_id TEXT);
CREATE TABLE routes (route_id TEXT PRIMARY KEY, route_short_name TEXT,
                     route_long_name TEXT, route_type INTEGER);
CREATE TABLE calendar (service_id TEXT PRIMARY KEY, monday INT, tuesday INT,
    wednesday INT, thursday INT, friday INT, saturday INT, sunday INT,
    start_date TEXT, end_date TEXT);
CREATE TABLE calendar_dates (service_id TEXT, date TEXT, exception_type INTEGER);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""

INDEXES = """
CREATE INDEX idx_stops_pos ON stops(stop_lat, stop_lon);
CREATE INDEX idx_stop_times_stop ON stop_times(stop_id);
CREATE INDEX idx_stop_times_trip ON stop_times(trip_id);
CREATE INDEX idx_calendar_dates ON calendar_dates(service_id, date);
"""

# GTFS route_type -> Klartext (Grundwerte, ohne die erweiterten Codes)
ROUTE_TYPES = {
    0: "Tram",
    1: "U-Bahn",
    2: "Eisenbahn",
    3: "Bus",
    4: "Fähre",
    5: "Seilbahn",
    6: "Gondel",
    7: "Standseilbahn",
    11: "Oberleitungsbus",
    12: "Einschienenbahn",
}


def _rows(zf: zipfile.ZipFile, name: str) -> Iterable[dict[str, str]]:
    if name not in zf.namelist():
        return []
    with zf.open(name) as fh:
        text = io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")
        yield from csv.DictReader(text)


def _int(v: str | None, default: int = 0) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def _float(v: str | None) -> float | None:
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def import_feed(
    settings: Settings,
    zip_path: Path,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    quelle: str | None = None,
    progress: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Importiert ein GTFS-ZIP in ``gtfs.sqlite``.

    ``bbox`` = (min_lat, min_lon, max_lat, max_lon) begrenzt den Import auf eine
    Region. Ohne Begrenzung wird ganz Deutschland importiert — das dauert und
    braucht mehrere Gigabyte.

    ``quelle`` ist die Herkunftsangabe für die Quellenfußzeile. Bei einem
    Download muss das die Feed-URL sein — der temporäre ZIP-Pfad ist nach dem
    Import gelöscht und sagt niemandem etwas.
    """
    settings.ensure_dirs()
    db_path = settings.gtfs_db_path
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)

    started = time.perf_counter()
    stats: dict[str, Any] = {}

    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        missing = {"stops.txt", "stop_times.txt", "trips.txt"} - names
        if missing:
            raise ValueError(
                f"Im ZIP fehlen Pflichtdateien: {', '.join(sorted(missing))}. "
                f"Enthalten sind: {', '.join(sorted(names))}"
            )

        # ---------------------------------------------------------- stops
        progress("stops.txt …")
        keep: set[str] = set()
        batch = []
        total_stops = 0
        for r in _rows(zf, "stops.txt"):
            total_stops += 1
            lat, lon = _float(r.get("stop_lat")), _float(r.get("stop_lon"))
            if lat is None or lon is None:
                continue
            if bbox and not (bbox[0] <= lat <= bbox[2] and bbox[1] <= lon <= bbox[3]):
                continue
            sid = r.get("stop_id") or ""
            keep.add(sid)
            batch.append(
                (
                    sid,
                    r.get("stop_name"),
                    lat,
                    lon,
                    _int(r.get("location_type")),
                    r.get("parent_station") or None,
                )
            )
            if len(batch) >= 20000:
                conn.executemany("INSERT OR REPLACE INTO stops VALUES (?,?,?,?,?,?)", batch)
                batch.clear()
        conn.executemany("INSERT OR REPLACE INTO stops VALUES (?,?,?,?,?,?)", batch)
        conn.commit()
        stats["stops_gesamt"] = total_stops
        stats["stops_importiert"] = len(keep)
        progress(f"  {len(keep):,} von {total_stops:,} Haltestellen übernommen")

        if not keep:
            raise ValueError(
                "Keine Haltestelle im gewählten Bereich. Bounding-Box prüfen "
                "(Reihenfolge: min_lat,min_lon,max_lat,max_lon)."
            )

        # --------------------------------------------------------- trips
        progress("trips.txt …")
        batch, n = [], 0
        for r in _rows(zf, "trips.txt"):
            batch.append((r.get("trip_id"), r.get("route_id"), r.get("service_id")))
            n += 1
            if len(batch) >= 50000:
                conn.executemany("INSERT OR REPLACE INTO trips VALUES (?,?,?)", batch)
                batch.clear()
        conn.executemany("INSERT OR REPLACE INTO trips VALUES (?,?,?)", batch)
        conn.commit()
        stats["trips"] = n
        progress(f"  {n:,} Fahrten")

        # -------------------------------------------------------- routes
        progress("routes.txt …")
        batch, n = [], 0
        for r in _rows(zf, "routes.txt"):
            batch.append(
                (
                    r.get("route_id"),
                    r.get("route_short_name"),
                    r.get("route_long_name"),
                    _int(r.get("route_type"), -1),
                )
            )
            n += 1
        conn.executemany("INSERT OR REPLACE INTO routes VALUES (?,?,?,?)", batch)
        conn.commit()
        stats["routes"] = n
        progress(f"  {n:,} Linien")

        # ------------------------------------------------------ calendar
        progress("calendar.txt / calendar_dates.txt …")
        cal = [
            (
                r.get("service_id"), _int(r.get("monday")), _int(r.get("tuesday")),
                _int(r.get("wednesday")), _int(r.get("thursday")), _int(r.get("friday")),
                _int(r.get("saturday")), _int(r.get("sunday")),
                r.get("start_date"), r.get("end_date"),
            )
            for r in _rows(zf, "calendar.txt")
        ]
        conn.executemany("INSERT OR REPLACE INTO calendar VALUES (?,?,?,?,?,?,?,?,?,?)", cal)
        caldates = [
            (r.get("service_id"), r.get("date"), _int(r.get("exception_type")))
            for r in _rows(zf, "calendar_dates.txt")
        ]
        conn.executemany("INSERT INTO calendar_dates VALUES (?,?,?)", caldates)
        conn.commit()
        stats["calendar"] = len(cal)
        stats["calendar_dates"] = len(caldates)
        progress(f"  {len(cal):,} Kalendereinträge, {len(caldates):,} Ausnahmen")

        # ---------------------------------------------------- stop_times
        progress("stop_times.txt … (der große Teil)")
        batch, n, kept = [], 0, 0
        for r in _rows(zf, "stop_times.txt"):
            n += 1
            sid = r.get("stop_id") or ""
            if sid not in keep:
                continue
            dep = (r.get("departure_time") or "").strip()
            if not dep:
                continue
            batch.append((sid, r.get("trip_id"), dep))
            kept += 1
            if len(batch) >= 100000:
                conn.executemany("INSERT INTO stop_times VALUES (?,?,?)", batch)
                batch.clear()
                if kept % 1000000 < 100000:
                    progress(f"  … {kept:,} Halte übernommen (von {n:,} gelesen)")
        conn.executemany("INSERT INTO stop_times VALUES (?,?,?)", batch)
        conn.commit()
        stats["stop_times_gelesen"] = n
        stats["stop_times_importiert"] = kept
        progress(f"  {kept:,} von {n:,} Halten übernommen")

    progress("Indizes …")
    conn.executescript(INDEXES)

    ref = _reference_date(conn)
    meta = {
        "importiert_am": now_iso(),
        "quelle": quelle or str(zip_path),
        "bbox": ",".join(str(x) for x in bbox) if bbox else "",
        "referenzdatum": ref["date"],
        "referenz_wochentag": ref["weekday_de"],
        "fahrplan_von": ref["feed_start"] or "",
        "fahrplan_bis": ref["feed_end"] or "",
        "lizenz": LICENSE,
        **{k: str(v) for k, v in stats.items()},
    }
    conn.executemany(
        "INSERT OR REPLACE INTO meta VALUES (?,?)", list(meta.items())
    )
    conn.commit()
    conn.execute("PRAGMA journal_mode=WAL")
    conn.close()

    stats["dauer_s"] = round(time.perf_counter() - started, 1)
    stats["datenbank"] = str(db_path)
    stats["groesse_mb"] = round(db_path.stat().st_size / 1024 / 1024, 1)
    stats["referenzdatum"] = ref["date"]
    progress(
        f"Fertig in {stats['dauer_s']} s · {stats['groesse_mb']} MB · "
        f"Referenztag {ref['date']} ({ref['weekday_de']})"
    )
    return stats


WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def _reference_date(conn: sqlite3.Connection) -> dict[str, Any]:
    """Wählt einen konkreten Werktag im Gültigkeitszeitraum des Fahrplans.

    Gezählt wird nie „im Schnitt", sondern an einem benannten Tag. Bevorzugt der
    nächste Dienstag ab heute, sonst der erste Dienstag im Gültigkeitszeitraum.
    """
    row = conn.execute(
        "SELECT MIN(start_date) s, MAX(end_date) e FROM calendar WHERE start_date <> ''"
    ).fetchone()
    feed_start, feed_end = (row[0], row[1]) if row else (None, None)
    if not feed_start:
        row = conn.execute("SELECT MIN(date), MAX(date) FROM calendar_dates").fetchone()
        feed_start, feed_end = (row[0], row[1]) if row else (None, None)

    def parse(s: str | None) -> dt.date | None:
        try:
            return dt.datetime.strptime(str(s), "%Y%m%d").date()
        except (TypeError, ValueError):
            return None

    start, end = parse(feed_start), parse(feed_end)
    today = dt.date.today()
    candidate = today
    if start and candidate < start:
        candidate = start
    # nächsten Dienstag ab candidate
    candidate += dt.timedelta(days=(1 - candidate.weekday()) % 7)
    if end and candidate > end:
        candidate = end - dt.timedelta(days=(end.weekday() - 1) % 7)
    return {
        "date": candidate.strftime("%Y%m%d"),
        "weekday": WEEKDAYS[candidate.weekday()],
        "weekday_de": WEEKDAYS_DE[candidate.weekday()],
        "feed_start": feed_start,
        "feed_end": feed_end,
    }


def _active_services(conn: sqlite3.Connection, date: str, weekday: str) -> set[str]:
    active = {
        r[0]
        for r in conn.execute(
            f"SELECT service_id FROM calendar WHERE {weekday}=1 "
            "AND (start_date='' OR start_date<=?) AND (end_date='' OR end_date>=?)",
            (date, date),
        )
    }
    for sid, etype in conn.execute(
        "SELECT service_id, exception_type FROM calendar_dates WHERE date=?", (date,)
    ):
        if etype == 1:
            active.add(sid)
        elif etype == 2:
            active.discard(sid)
    return active


def load(settings: Settings, lat: float, lon: float, radius: int) -> SourceResult:
    """Abfahrten je Stunde im Umkreis. Rein lokal."""
    started = time.perf_counter()
    db_path = settings.gtfs_db_path
    if not db_path.exists():
        return SourceResult(
            name="gtfs",
            ok=True,
            data=None,
            duration_ms=0,
            warnings=[
                "Kein GTFS-Fahrplan importiert. Einmalig ausführen: "
                "`gastroviewer import-gtfs` (oder `python -m gastroviewer import-gtfs`). "
                "Ohne Import bleibt dieser Block leer — die übrigen Blöcke sind davon "
                "nicht betroffen."
            ],
            provenance=Provenance(
                source="GTFS-Fahrplan (nicht importiert)", license=LICENSE
            ),
        )

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        meta = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}
        date = meta.get("referenzdatum") or _reference_date(conn)["date"]
        weekday_idx = dt.datetime.strptime(date, "%Y%m%d").date().weekday()
        weekday = WEEKDAYS[weekday_idx]
        services = _active_services(conn, date, weekday)

        # Bounding-Box vorfiltern, dann exakte Distanz.
        dlat = radius / 111_320.0
        dlon = radius / (111_320.0 * max(math.cos(math.radians(lat)), 0.01))
        rows = conn.execute(
            "SELECT stop_id, stop_name, stop_lat, stop_lon FROM stops "
            "WHERE stop_lat BETWEEN ? AND ? AND stop_lon BETWEEN ? AND ?",
            (lat - dlat, lat + dlat, lon - dlon, lon + dlon),
        ).fetchall()
        nearby = []
        for r in rows:
            d = haversine_m(lat, lon, r["stop_lat"], r["stop_lon"])
            if d <= radius:
                nearby.append((r["stop_id"], r["stop_name"], r["stop_lat"], r["stop_lon"], d))

        if not nearby:
            return SourceResult(
                name="gtfs",
                ok=True,
                data={"haltestellen": [], "abfahrten_gesamt": 0, "referenzdatum": date},
                duration_ms=int((time.perf_counter() - started) * 1000),
                warnings=["Keine Haltestelle des importierten Fahrplans im Umkreis."],
                provenance=_gtfs_provenance(meta, date, weekday_idx),
            )

        if not services:
            return SourceResult(
                name="gtfs",
                ok=True,
                data={"haltestellen": [], "abfahrten_gesamt": 0, "referenzdatum": date},
                duration_ms=int((time.perf_counter() - started) * 1000),
                warnings=[
                    f"Für den Referenztag {date} ist im importierten Fahrplan kein "
                    "Verkehrstag aktiv. Der Feed ist vermutlich abgelaufen — neu importieren."
                ],
                provenance=_gtfs_provenance(meta, date, weekday_idx),
            )

        stop_ids = [n[0] for n in nearby]
        hours = [0] * 24
        per_stop: dict[str, dict[str, Any]] = {}
        route_types: dict[str, int] = {}
        total = 0

        chunk = 500
        for i in range(0, len(stop_ids), chunk):
            part = stop_ids[i : i + chunk]
            qmarks = ",".join("?" * len(part))
            sql = (
                "SELECT st.stop_id, st.departure_time, t.service_id, r.route_type, "
                "r.route_short_name FROM stop_times st "
                "JOIN trips t ON t.trip_id = st.trip_id "
                "LEFT JOIN routes r ON r.route_id = t.route_id "
                f"WHERE st.stop_id IN ({qmarks})"
            )
            for row in conn.execute(sql, part):
                if row["service_id"] not in services:
                    continue
                dep = row["departure_time"]
                try:
                    hh = int(str(dep).split(":")[0]) % 24
                except (ValueError, IndexError):
                    continue
                hours[hh] += 1
                total += 1
                s = per_stop.setdefault(
                    row["stop_id"], {"abfahrten": 0, "linien": set(), "arten": set()}
                )
                s["abfahrten"] += 1
                if row["route_short_name"]:
                    s["linien"].add(row["route_short_name"])
                art = ROUTE_TYPES.get(row["route_type"], None)
                if art:
                    s["arten"].add(art)
                    route_types[art] = route_types.get(art, 0) + 1

        haltestellen = []
        for sid, name, slat, slon, dist in sorted(nearby, key=lambda x: x[4]):
            s = per_stop.get(sid, {"abfahrten": 0, "linien": set(), "arten": set()})
            haltestellen.append(
                {
                    "stop_id": sid,
                    "name": name,
                    "lat": slat,
                    "lon": slon,
                    "distanz_m": round(dist),
                    "richtung": bearing_label(lat, lon, slat, slon),
                    "abfahrten": s["abfahrten"],
                    "linien": sorted(s["linien"]),
                    "arten": sorted(s["arten"]),
                }
            )
        haltestellen.sort(key=lambda h: (-h["abfahrten"], h["distanz_m"]))

        # GTFS kennt neben Bahnsteigen (location_type 0) auch übergeordnete
        # Stationen (location_type 1). Stationen tragen nie eigene Abfahrten —
        # sie als Haltestellen mitzuzählen, würde die Zahl aufblähen. Deshalb
        # zählt „haltestellen_gesamt" nur, was am Referenztag wirklich bedient
        # wird; der Rest wird getrennt ausgewiesen statt stillschweigend entfernt.
        bedient = [h for h in haltestellen if h["abfahrten"] > 0]
        ohne = len(haltestellen) - len(bedient)

        data = {
            "referenzdatum": f"{date[6:8]}.{date[4:6]}.{date[0:4]}",
            "referenz_wochentag": WEEKDAYS_DE[weekday_idx],
            "abfahrten_gesamt": total,
            "abfahrten_je_stunde": {f"{h:02d}": hours[h] for h in range(24)},
            "abfahrten_06_24": sum(hours[6:24]),
            "haltestellen": haltestellen,
            "haltestellen_gesamt": len(bedient),
            "haltestellen_ohne_abfahrten": ohne,
            "haltestellen_im_umkreis": len(haltestellen),
            "nach_verkehrsmittel": dict(sorted(route_types.items(), key=lambda kv: -kv[1])),
            "spitzenstunde": (
                {"stunde": f"{hours.index(max(hours)):02d}:00", "abfahrten": max(hours)}
                if total
                else None
            ),
        }
        return SourceResult(
            name="gtfs",
            ok=True,
            data=data,
            duration_ms=int((time.perf_counter() - started) * 1000),
            warnings=(
                [
                    f"{ohne} von {len(haltestellen)} Einträgen im Umkreis haben am "
                    f"Referenztag keine Abfahrt. Das sind übergeordnete Stationen "
                    "(GTFS location_type 1, reine Container ohne eigene Fahrten) oder "
                    "Haltestellen, die an diesem Tag nicht bedient werden."
                ]
                if ohne
                else []
            ),
            provenance=_gtfs_provenance(meta, date, weekday_idx),
        )
    finally:
        conn.close()


def _gtfs_provenance(meta: dict[str, str], date: str, weekday_idx: int) -> Provenance:
    return Provenance(
        source=f"GTFS-Fahrplan ({meta.get('quelle', 'lokaler Import')})",
        license=meta.get("lizenz", LICENSE),
        endpoint=None,
        stand=(
            f"Fahrplan {meta.get('fahrplan_von', '?')}–{meta.get('fahrplan_bis', '?')}, "
            f"importiert {meta.get('importiert_am', '?')}"
        ),
        retrieved_at=now_iso(),
        note=(
            f"Gezählt werden die Abfahrten des Fahrplans am {date[6:8]}.{date[4:6]}.{date[0:4]} "
            f"({WEEKDAYS_DE[weekday_idx]}), nicht ein Mittelwert. Verkehrstage aus "
            "calendar.txt inklusive der Ausnahmen aus calendar_dates.txt."
        ),
    )


def status(settings: Settings) -> dict[str, Any]:
    db = settings.gtfs_db_path
    if not db.exists():
        return {"importiert": False, "datenbank": str(db)}
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        meta = {k: v for k, v in conn.execute("SELECT key, value FROM meta")}
    finally:
        conn.close()
    return {
        "importiert": True,
        "datenbank": str(db),
        "groesse_mb": round(db.stat().st_size / 1024 / 1024, 1),
        **meta,
    }
