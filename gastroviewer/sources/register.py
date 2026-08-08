"""Handelsregister-Umfeld — OffeneRegister.de, eingefrorene Datenspende 2019.

Wer stand hinter den Betrieben im Umfeld: eingetragene Gesellschaften mit
Sitz in der Standort-PLZ, mit Registernummer und Status. Für Ketten- und
Verflechtungsfragen ist auch der alte Stand Kontext — er ist aber **alt**
und wird genau so beschriftet.

Phase-0 am 2026-08-08 mit echten Abrufen verifiziert:

* ``https://daten.offeneregister.de/de_companies_ocdata.jsonl.bz2`` —
  HTTP 200, 260 455 433 Bytes, ``Last-Modified: Tue, 05 Feb 2019``.
  Die Startseite nennt als Lizenz **Creative Commons Attribution 4.0**
  („Offene Register" von OpenCorporates/Open Knowledge Foundation DE).
* Format: eine JSON-Zeile je Gesellschaft (OpenCorporates-Schema);
  genutzte Felder: ``name``, ``current_status`` („currently registered"
  oder Löschvermerk), ``registered_address`` (Freitext **mit PLZ**),
  ``all_attributes.native_company_number`` („Hamburg HRB 150148"),
  ``all_attributes.registrar`` (Registergericht), ``retrieved_at``.
* Die frühere Abfrage-API ``db.offeneregister.de`` antwortet weiter mit
  HTTP 502 — deshalb Gesamtimport statt Einzelabfragen.

Der Import läuft **einmal** über ``python -m gastroviewer
import-register`` (Streaming: bz2 → SQLite mit PLZ-Index, nichts wird
entpackt zwischengespeichert). Ohne Import zeigt der Block die Anleitung
statt Zahlen — er erfindet nichts.
"""

from __future__ import annotations

import bz2
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Iterable

from ..config import Settings
from .base import Provenance, SourceError, SourceResult, now_iso

DUMP_URL = "https://daten.offeneregister.de/de_companies_ocdata.jsonl.bz2"
PORTAL = "https://offeneregister.de/"
LIZENZ = (
    "Creative Commons Attribution 4.0 (CC BY 4.0) — „Offene Register“, "
    "OpenCorporates / Open Knowledge Foundation Deutschland; "
    "Handelsregister-Datenspende, eingefroren am 05.02.2019"
)
STAND = "Datenspende vom 05.02.2019 — nicht fortgeschrieben"

# Letzte fünfstellige Zahl vor dem Ortsnamen: „Waidmannstraße 1, 22769
# Hamburg." — Hausnummern sind kürzer, und wenn zwei fünfstellige Zahlen
# vorkommen (Postfach), ist die PLZ die letzte.
_PLZ = re.compile(r"\b(\d{5})\b(?=[^\d]*$)")

# Namensheuristik für den Gastro-Auszug. Bewusst mit Wortgrenzen, damit
# „Barbara GmbH" und „Eisenwerk" nicht zu Bars und Eisdielen werden.
GASTRO_MUSTER = re.compile(
    r"(?i)\b(restaurant|gastronomie|gastro|caf[ée]|bar|bistro|brasserie|"
    r"imbiss|kebap|kebab|d[öo]ner|pizz\w*|sushi|burger|catering|kantine|"
    r"mensa|wirtshaus|gasthaus|gasthof|biergarten|brauerei|braugasthof|"
    r"eiscaf[ée]|eisdiele|konditorei|b[äa]ckerei|kaffeehaus|coffee|"
    r"food\w*|foodtruck|lieferdienst|hotel|hostel|systemgastronomie)\b"
)


def zeile_parsen(zeile: bytes | str) -> dict[str, Any] | None:
    """Eine JSONL-Zeile des Dumps → reduzierter Firmensatz (oder None)."""
    try:
        r = json.loads(zeile)
    except (ValueError, TypeError):
        return None
    name = (r.get("name") or "").strip()
    adresse = (r.get("registered_address") or "").strip().rstrip(".")
    if not name:
        return None
    plz = None
    m = _PLZ.search(adresse)
    if m:
        plz = m.group(1)
    attribute = r.get("all_attributes") or {}
    return {
        "name": name,
        "status": (r.get("current_status") or "").strip() or None,
        "plz": plz,
        "adresse": adresse or None,
        "register": (attribute.get("native_company_number") or "").strip() or None,
        "gericht": (attribute.get("registrar") or "").strip() or None,
        "stand": (r.get("retrieved_at") or "")[:10] or None,
    }


def import_dump(
    settings: Settings,
    dump_pfad: Path,
    quelle: str = DUMP_URL,
    progress: Callable[[str], None] = lambda s: None,
) -> dict[str, Any]:
    """Streaming-Import: bz2-Dump → SQLite mit PLZ-Index. Läuft einmal;
    danach beantwortet die lokale Datenbank jede Punktabfrage ohne Netz."""
    db_pfad = settings.register_db_path
    tmp = db_pfad.with_suffix(".import")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript(
        """
        CREATE TABLE firmen (
            name TEXT NOT NULL,
            status TEXT,
            plz TEXT,
            adresse TEXT,
            register TEXT,
            gericht TEXT,
            stand TEXT
        );
        CREATE TABLE meta (schluessel TEXT PRIMARY KEY, wert TEXT);
        """
    )
    gesamt = mit_plz = 0
    stapel: list[tuple] = []
    with bz2.open(dump_pfad, "rb") as fh:
        for zeile in fh:
            satz = zeile_parsen(zeile)
            if satz is None:
                continue
            gesamt += 1
            if satz["plz"]:
                mit_plz += 1
            stapel.append((satz["name"], satz["status"], satz["plz"],
                           satz["adresse"], satz["register"], satz["gericht"],
                           satz["stand"]))
            if len(stapel) >= 20000:
                con.executemany("INSERT INTO firmen VALUES (?,?,?,?,?,?,?)", stapel)
                stapel.clear()
                if gesamt % 500000 == 0:
                    progress(f"  {gesamt:,} Gesellschaften …".replace(",", "."))
    if stapel:
        con.executemany("INSERT INTO firmen VALUES (?,?,?,?,?,?,?)", stapel)
    con.execute("CREATE INDEX idx_firmen_plz ON firmen(plz)")
    for k, v in [("quelle", quelle), ("stand", STAND), ("lizenz", LIZENZ),
                 ("importiert_am", now_iso()), ("gesamt", str(gesamt)),
                 ("mit_plz", str(mit_plz))]:
        con.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, v))
    con.commit()
    con.close()
    db_pfad.unlink(missing_ok=True)
    tmp.rename(db_pfad)
    return {"gesellschaften": gesamt, "mit_plz": mit_plz,
            "datenbank": str(db_pfad)}


def _meta(con: sqlite3.Connection) -> dict[str, str]:
    return dict(con.execute("SELECT schluessel, wert FROM meta"))


def auswerten(db_pfad: Path, plz: str) -> dict[str, Any]:
    """Kennzahlen und Gastro-Auszug für eine PLZ — rein lokal."""
    con = sqlite3.connect(db_pfad)
    try:
        meta = _meta(con)
        gesamt = con.execute(
            "SELECT COUNT(*) FROM firmen WHERE plz = ?", (plz,)).fetchone()[0]
        aktiv = con.execute(
            "SELECT COUNT(*) FROM firmen WHERE plz = ? AND status = ?",
            (plz, "currently registered")).fetchone()[0]
        gastro = []
        for name, status, adresse, register, gericht in con.execute(
            "SELECT name, status, adresse, register, gericht FROM firmen "
            "WHERE plz = ? ORDER BY name", (plz,)
        ):
            if not GASTRO_MUSTER.search(name):
                continue
            gastro.append({
                "name": name,
                "aktiv_2019": status == "currently registered",
                "adresse": adresse,
                "register": register,
                "gericht": gericht,
            })
    finally:
        con.close()
    return {
        "plz": plz,
        "firmen_gesamt": gesamt,
        "aktiv_2019": aktiv,
        "gastro_auszug": gastro[:25],
        "gastro_gesamt": len(gastro),
        "bestand": {
            "gesellschaften": int(meta.get("gesamt", "0")),
            "importiert_am": meta.get("importiert_am"),
        },
        "portal": PORTAL,
    }


HINWEISE = [
    "Eingefrorene Datenspende: Stand ist der 5. Februar 2019. Neuere "
    "Gründungen fehlen, „aktiv“ heißt „war 2019 eingetragen“ — vor "
    "Entscheidungen im aktuellen Handelsregister (handelsregister.de) "
    "gegenprüfen.",
    "Der Gastro-Auszug ist eine Namensheuristik (Restaurant, Café, "
    "Brauerei …) — eine GmbH namens „Müller Beteiligungen“ kann trotzdem "
    "Wirtshäuser betreiben. Branchencodes führt das Handelsregister nicht.",
    "Sitz-PLZ, nicht Betriebs-PLZ: Ketten sitzen oft in einer anderen "
    "Stadt als ihre Filialen.",
    "Nur ein Teil der Datenspende trägt eine Sitzadresse mit "
    "Postleitzahl (beim Vollimport 2026: rund 1,36 von 5,3 Mio. "
    "Gesellschaften) — die Zählung je PLZ ist eine Untergrenze.",
]

ANLEITUNG = (
    "Einmalig importieren: python -m gastroviewer import-register "
    "(lädt 260 MB von daten.offeneregister.de und baut die lokale "
    "Datenbank — dauert einige Minuten)."
)


async def load(settings: Settings, plz: str | None) -> SourceResult:
    """Blockergebnis aus der lokalen Datenbank. Kein Netzzugriff."""
    started = time.perf_counter()
    db_pfad = settings.register_db_path

    def fertig(data: dict[str, Any] | None, warnungen: list[str]) -> SourceResult:
        return SourceResult(
            name="register",
            ok=True,
            data=data,
            duration_ms=int((time.perf_counter() - started) * 1000),
            warnings=warnungen,
            provenance=Provenance(
                source="OffeneRegister.de — Handelsregister-Datenspende (2019)",
                license=LIZENZ,
                endpoint=DUMP_URL,
                stand=STAND,
                retrieved_at=now_iso(),
                note=(
                    "Einmal importierter Gesamtbestand, Abfragen laufen "
                    "lokal. Die frühere Abfrage-API des Projekts ist tot "
                    "(HTTP 502, nachgeprüft 08/2026)."
                ),
            ),
        )

    if not db_pfad.exists():
        return fertig({"importiert": False, "anleitung": ANLEITUNG,
                       "portal": PORTAL}, [])
    if not plz:
        return fertig(None, [
            "Ohne Postleitzahl (aus dem Adressblock) lässt sich kein "
            "Registerumfeld zuordnen."
        ])
    try:
        import asyncio

        data = await asyncio.to_thread(auswerten, db_pfad, plz)
    except sqlite3.Error as exc:
        return SourceResult.failed(
            "register",
            SourceError("parse", "Registerdatenbank nicht lesbar — Import "
                        f"erneut ausführen? ({exc})"),
            int((time.perf_counter() - started) * 1000),
        )
    data["importiert"] = True
    data["hinweise"] = HINWEISE
    return fertig(data, [])
