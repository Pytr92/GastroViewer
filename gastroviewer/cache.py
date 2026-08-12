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
    payload     TEXT NOT NULL,
    -- Das Werkzeug bewertet bewusst nicht und stellt keine Rangfolge auf.
    -- Der Nutzer darf und soll das aber — dafür sind diese beiden Felder da.
    -- Sie sind ausdrücklich als eigene Einschätzung gekennzeichnet und werden
    -- nirgends in eine Rechnung übernommen.
    notiz       TEXT,
    bewertung   INTEGER,
    -- Wann „Neu prüfen" den Datenstand zuletzt erneuert hat.
    geprueft_am REAL
);

-- Verlauf gemerkter Punkte: „Neu prüfen" legt den bisherigen Stand hier ab,
-- bevor es ihn ersetzt. So wird aus der Momentaufnahme eine Zeitreihe —
-- eröffnete und verschwundene Betriebe sind über Monate nachvollziehbar.
CREATE TABLE IF NOT EXISTS point_verlauf (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    point_id    INTEGER NOT NULL,
    ts          REAL NOT NULL,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_verlauf_point ON point_verlauf(point_id);
"""

# Bestehende Datenbanken haben die beiden Spalten noch nicht. SQLite kennt kein
# "ADD COLUMN IF NOT EXISTS", also wird der Bestand geprüft.
NACHRUESTUNG = [
    ("saved_points", "notiz", "TEXT"),
    ("saved_points", "bewertung", "INTEGER"),
    ("saved_points", "geprueft_am", "REAL"),
    # Arbeitsstand der Standortsuche. Wer über Monate Adressen prüft, braucht
    # nicht nur die Zahlen, sondern den Stand der eigenen Arbeit — und beim
    # abgelehnten Standort den Grund, damit dieselbe Adresse nicht in einem
    # Jahr noch einmal durchgeprüft wird.
    ("saved_points", "stand", "TEXT"),
    ("saved_points", "stand_grund", "TEXT"),
]

# Die erlaubten Arbeitsstände. Bewusst eine feste Liste: Freitext wäre in der
# Vergleichstabelle nicht sortierbar und in der Auswertung wertlos.
STAENDE = [
    ("gesichtet", "gesichtet"),
    ("besichtigt", "besichtigt"),
    ("angebot", "Angebot eingeholt"),
    ("verhandlung", "in Verhandlung"),
    ("abgeschlossen", "abgeschlossen"),
    ("abgelehnt", "abgelehnt"),
]
STAND_SCHLUESSEL = [k for k, _ in STAENDE]


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
            # Eine Datenbank aus einer früheren Fassung soll weiterlaufen, statt
            # den Nutzer seine gemerkten Punkte zu kosten.
            self._nachruesten(conn)

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
            # Was in den letzten 24 Stunden wirklich hinausging, je Dienst.
            # Overpass und Nominatim sind Spendenprojekte; wer das nicht sieht,
            # merkt auch nicht, wenn er sie strapaziert.
            seit = now - 24 * 3600
            heute = conn.execute(
                "SELECT source, COUNT(*) n FROM outbound_log WHERE ts >= ?"
                " GROUP BY source ORDER BY n DESC",
                (seit,),
            ).fetchall()
        je_dienst = {r["source"]: r["n"] for r in heute}
        return {
            "entries": [dict(r) for r in rows],
            "total": sum(r["n"] for r in rows),
            "outbound_requests_total": total_out,
            "outbound_24h": sum(je_dienst.values()),
            "outbound_24h_je_dienst": je_dienst,
            # Der Gehwegblock schlägt mit 1–3 MB je Abruf am stärksten zu Buche.
            "overpass_24h": (
                je_dienst.get("overpass", 0) + je_dienst.get("gehweg", 0)
            ),
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

    def _nachruesten(self, conn) -> None:
        """Spalten ergänzen, die es in älteren Datenbanken noch nicht gibt."""
        for tabelle, spalte, typ in NACHRUESTUNG:
            vorhanden = {
                r["name"] for r in conn.execute(f"PRAGMA table_info({tabelle})").fetchall()
            }
            if spalte not in vorhanden:
                conn.execute(f"ALTER TABLE {tabelle} ADD COLUMN {spalte} {typ}")

    #: Felder, die der Nutzer selbst pflegt — und die einzigen, die dieser
    #: Weg schreiben darf.
    EIGENE_FELDER = ("notiz", "bewertung", "stand", "stand_grund")

    def set_point_felder(self, point_id: int, felder: dict[str, Any]) -> bool:
        """Schreibt **nur** die übergebenen Felder.

        Das ist der Grund für diese Methode: Früher setzte ein Aufruf immer
        Notiz *und* Note. Sobald ein drittes Feld dazukommt, würde das
        Ändern des Arbeitsstands die Notiz löschen. Übergeben wird deshalb,
        was tatsächlich geändert werden soll — der Rest bleibt unberührt.
        """
        zu_setzen = {k: v for k, v in felder.items() if k in self.EIGENE_FELDER}
        if not zu_setzen:
            return False
        satz = ", ".join(f"{k} = ?" for k in zu_setzen)
        with self._connect() as conn:
            cur = conn.execute(
                f"UPDATE saved_points SET {satz} WHERE id = ?",
                (*zu_setzen.values(), point_id),
            )
            return cur.rowcount > 0

    def set_point_notiz(
        self, point_id: int, notiz: str | None, bewertung: int | None
    ) -> bool:
        return self.set_point_felder(
            point_id, {"notiz": notiz, "bewertung": bewertung})

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

    def list_points_kurz(self) -> list[dict[str, Any]]:
        """Die Liste ohne Datenpakete — für die Karten-Ebene.

        Ein gemerkter Punkt wiegt im Mittel rund 350 kB; bei dutzenden
        Adressen käme die volle Liste auf viele Megabyte, die der Browser
        bei jeder Ebenen-Aktualisierung erneut lädt und parst. Die Ebene
        braucht davon nichts — nur Ort, Beschriftung und eigene Angaben."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, label, lat, lon, radius, created_at, notiz,"
                " bewertung, stand, stand_grund"
                " FROM saved_points ORDER BY created_at"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_point(self, point_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM saved_points WHERE id = ?", (point_id,)
            ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["payload"] = json.loads(d["payload"])
        return d

    def replace_point_payload(self, point_id: int, payload: Any) -> bool:
        """„Neu prüfen": bisherigen Stand in den Verlauf legen, neuen einsetzen.

        Der Zeitstempel des Verlaufseintrags ist der Zeitpunkt, zu dem der alte
        Stand erhoben wurde — nicht der Zeitpunkt des Ersetzens.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload, created_at, geprueft_am FROM saved_points WHERE id = ?",
                (point_id,),
            ).fetchone()
            if row is None:
                return False
            conn.execute(
                "INSERT INTO point_verlauf(point_id, ts, payload) VALUES (?,?,?)",
                (point_id, row["geprueft_am"] or row["created_at"], row["payload"]),
            )
            conn.execute(
                "UPDATE saved_points SET payload = ?, geprueft_am = ? WHERE id = ?",
                (json.dumps(payload, ensure_ascii=False), time.time(), point_id),
            )
            return True

    def list_verlauf(self, point_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM point_verlauf WHERE point_id = ? ORDER BY ts",
                (point_id,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d["payload"])
            out.append(d)
        return out

    def delete_point(self, point_id: int) -> bool:
        with self._connect() as conn:
            # Der Verlauf gehört zum Punkt; ohne ihn wären es verwaiste Zeilen.
            conn.execute("DELETE FROM point_verlauf WHERE point_id = ?", (point_id,))
            cur = conn.execute("DELETE FROM saved_points WHERE id = ?", (point_id,))
            return cur.rowcount > 0

    # ------------------------------------------------------- Datensicherung

    EXPORT_FORMAT = "gastroviewer-punkte"
    EXPORT_VERSION = 1

    def export_points(self) -> dict[str, Any]:
        """Alle gemerkten Punkte samt Verlauf und eigener Einschätzung als ein
        JSON-Dokument — Monate Sucharbeit hängen sonst an einer einzigen
        SQLite-Datei auf einem Rechner."""
        punkte = []
        for p in self.list_points():
            p["verlauf"] = [
                {"ts": v["ts"], "payload": v["payload"]}
                for v in self.list_verlauf(p["id"])
            ]
            punkte.append(p)
        return {
            "format": self.EXPORT_FORMAT,
            "version": self.EXPORT_VERSION,
            "exportiert_am": time.time(),
            "punkte": punkte,
        }

    def import_points(self, daten: dict[str, Any]) -> dict[str, int]:
        """Spielt eine Sicherung ein. Punkte bekommen neue IDs; ein Punkt gilt
        als Dublette (und wird übersprungen), wenn Label, Koordinaten, Radius
        und Anlagezeitpunkt exakt übereinstimmen."""
        if daten.get("format") != self.EXPORT_FORMAT:
            raise ValueError("Das ist keine Punkte-Sicherung dieses Werkzeugs.")
        if daten.get("version") != self.EXPORT_VERSION:
            raise ValueError(
                f"Unbekannte Sicherungsversion {daten.get('version')!r} — "
                f"dieses Werkzeug schreibt Version {self.EXPORT_VERSION}."
            )
        neu = uebersprungen = 0
        with self._connect() as conn:
            for p in daten.get("punkte") or []:
                vorhanden = conn.execute(
                    "SELECT 1 FROM saved_points WHERE label = ? AND lat = ? "
                    "AND lon = ? AND radius = ? AND created_at = ?",
                    (p["label"], p["lat"], p["lon"], p["radius"], p["created_at"]),
                ).fetchone()
                if vorhanden:
                    uebersprungen += 1
                    continue
                cur = conn.execute(
                    "INSERT INTO saved_points(label, lat, lon, radius, created_at,"
                    " payload, notiz, bewertung, geprueft_am) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        p["label"], p["lat"], p["lon"], p["radius"], p["created_at"],
                        json.dumps(p["payload"], ensure_ascii=False),
                        p.get("notiz"), p.get("bewertung"), p.get("geprueft_am"),
                    ),
                )
                pid = int(cur.lastrowid or 0)
                for v in p.get("verlauf") or []:
                    conn.execute(
                        "INSERT INTO point_verlauf(point_id, ts, payload) VALUES (?,?,?)",
                        (pid, v["ts"], json.dumps(v["payload"], ensure_ascii=False)),
                    )
                neu += 1
        return {"neu": neu, "uebersprungen": uebersprungen}


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

    async def set_point_notiz(self, point_id, notiz, bewertung):
        return await asyncio.to_thread(
            self.sync.set_point_notiz, point_id, notiz, bewertung
        )

    async def set_point_felder(self, point_id, felder):
        return await asyncio.to_thread(
            self.sync.set_point_felder, point_id, felder
        )
