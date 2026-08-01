"""SQLite-Cache mit TTL und Outbound-Protokoll.

Zwei Aufgaben:

1. Antworten der freien Dienste zwischenspeichern (Spec §2). Schlüssel ist
   ``quelle|lat|lon|radius``, Koordinaten auf 4 Nachkommastellen gerundet
   (~11 m — feiner als die 100-m-Zensuszellen und feiner als jeder sinnvolle
   Suchradius).
2. Jeden echten ausgehenden Aufruf protokollieren. Ohne dieses Protokoll lässt
   sich das Abnahmekriterium „zweiter Aufruf erzeugt keinen Outbound-Traffic"
   nicht belegen (Spec §7).

Der Zugriff läuft über je eine kurzlebige Verbindung pro Operation. Das ist für
ein lokales Werkzeug schnell genug und vermeidet Thread-Probleme von sqlite3.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    key         TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    payload     TEXT NOT NULL,
    fetched_at  REAL NOT NULL,
    expires_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cache_source ON cache(source);
CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache(expires_at);

CREATE TABLE IF NOT EXISTS outbound_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL NOT NULL,
    source      TEXT NOT NULL,
    url         TEXT NOT NULL,
    status      INTEGER,
    duration_ms INTEGER,
    bytes       INTEGER,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_outbound_ts ON outbound_log(ts);

CREATE TABLE IF NOT EXISTS saved_points (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    label       TEXT NOT NULL,
    lat         REAL NOT NULL,
    lon         REAL NOT NULL,
    radius      INTEGER NOT NULL,
    created_at  REAL NOT NULL,
    payload     TEXT NOT NULL
);
"""


def cache_key(source: str, lat: float, lon: float, radius: float | int, *, extra: str = "") -> str:
    """Spec §2: Key = quelle|lat|lon|radius, gerundet auf 4 Nachkommastellen."""
    key = f"{source}|{lat:.4f}|{lon:.4f}|{int(radius)}"
    return f"{key}|{extra}" if extra else key


class Cache:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)

    # ------------------------------------------------------------------ Cache

    def get(self, key: str) -> dict[str, Any] | None:
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload, fetched_at, expires_at FROM cache WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        if row["expires_at"] < now:
            self.delete(key)
            return None
        return {
            "payload": json.loads(row["payload"]),
            "fetched_at": row["fetched_at"],
            "expires_at": row["expires_at"],
        }

    def set(self, key: str, source: str, payload: Any, ttl: int) -> float:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache(key, source, payload, fetched_at, expires_at)"
                " VALUES (?,?,?,?,?)",
                (key, source, json.dumps(payload, ensure_ascii=False), now, now + ttl),
            )
        return now

    def delete(self, key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM cache WHERE key = ?", (key,))

    def clear(self, source: str | None = None) -> int:
        with self._connect() as conn:
            if source:
                cur = conn.execute("DELETE FROM cache WHERE source LIKE ?", (f"{source}%",))
            else:
                cur = conn.execute("DELETE FROM cache")
            return cur.rowcount

    def stats(self) -> dict[str, Any]:
        now = time.time()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT source, COUNT(*) n, SUM(CASE WHEN expires_at < ? THEN 1 ELSE 0 END) stale"
                " FROM cache GROUP BY source ORDER BY source",
                (now,),
            ).fetchall()
            total_out = conn.execute("SELECT COUNT(*) n FROM outbound_log").fetchone()["n"]
        return {
            "entries": [dict(r) for r in rows],
            "total": sum(r["n"] for r in rows),
            "outbound_requests_total": total_out,
        }

    # -------------------------------------------------------- Outbound-Log

    def log_outbound(
        self,
        source: str,
        url: str,
        *,
        status: int | None = None,
        duration_ms: int | None = None,
        size: int | None = None,
        error: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO outbound_log(ts, source, url, status, duration_ms, bytes, error)"
                " VALUES (?,?,?,?,?,?,?)",
                (time.time(), source, url, status, duration_ms, size, error),
            )

    def outbound_since(self, ts: float) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM outbound_log WHERE ts >= ? ORDER BY ts", (ts,)
            ).fetchall()
        return [dict(r) for r in rows]

    def outbound_count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) n FROM outbound_log").fetchone()["n"]

    # ----------------------------------------------------- Gemerkte Punkte

    def save_point(self, label: str, lat: float, lon: float, radius: int, payload: Any) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO saved_points(label, lat, lon, radius, created_at, payload)"
                " VALUES (?,?,?,?,?,?)",
                (label, lat, lon, radius, time.time(), json.dumps(payload, ensure_ascii=False)),
            )
            return int(cur.lastrowid or 0)

    def list_points(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM saved_points ORDER BY created_at").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d["payload"])
            out.append(d)
        return out

    def delete_point(self, point_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM saved_points WHERE id = ?", (point_id,))
            return cur.rowcount > 0


class AsyncCache:
    """Dünne async-Hülle: SQLite-Aufrufe laufen in einem Worker-Thread,
    damit der Event-Loop nicht blockiert."""

    def __init__(self, path: Path) -> None:
        self.sync = Cache(path)

    async def get(self, key: str):
        return await asyncio.to_thread(self.sync.get, key)

    async def set(self, key: str, source: str, payload: Any, ttl: int) -> float:
        return await asyncio.to_thread(self.sync.set, key, source, payload, ttl)

    async def log_outbound(self, source: str, url: str, **kw) -> None:
        await asyncio.to_thread(self.sync.log_outbound, source, url, **kw)

    async def stats(self):
        return await asyncio.to_thread(self.sync.stats)
