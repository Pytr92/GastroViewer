"""Gegenprobe der Datenverträge — vier leichte Metadaten-Abrufe, einmal im Monat.

Alle Tests der Suite laufen offline gegen aufgezeichnete Antworten. Ändert
ein Anbieter ein Feld, einen Dateinamen oder eine Dienst-URL, merkt das
niemand, bis ein Block leer bleibt. Dieses Skript fragt bei den vier
Verträgen nach, die ohne Nutzdaten prüfbar sind:

1. Zensus-Gitterdienst: Layer-Metadaten (``?f=json``) gegen ``zensus.FIELDS``
   und die Seitengröße.
2. Landes-Kartendienste: ``wms.pruefe_dienste`` (das ist ``gastroviewer
   check-wms``).
3. DWD Open Data: Verzeichnislisting gegen die Dateinamen in
   ``klima.PARAMETER``.
4. Open-Data-Portal München: CKAN-Suche gegen ``indikatoren.DATEIEN``.

Läuft über das projekteigene ``Outbound`` (User-Agent, Limiter, Protokoll).
Exitcode 0 = alle Verträge halten, 1 = mindestens eine Abweichung, die
Ausgabe nennt sie mit Datum. Bewusst außerhalb der pytest-Suite: der
Push-Lauf bleibt offline.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gastroviewer.cache import AsyncCache  # noqa: E402
from gastroviewer.config import Settings  # noqa: E402
from gastroviewer.http import Outbound  # noqa: E402
from gastroviewer.sources import indikatoren, klima, wms, zensus  # noqa: E402
from gastroviewer.sources.base import SourceError  # noqa: E402


async def zensus_felder(out: Outbound, s: Settings) -> list[str]:
    meta = await out.get_json(
        "zensus", f"{s.zensus_base}/{s.zensus_layer}", params={"f": "json"},
        timeout=s.zensus_timeout)
    vorhanden = {f.get("name") for f in meta.get("fields") or []}
    befunde = [f"Zensus: Feld {f!r} fehlt im Dienst" for f in zensus.FIELDS
               if f not in vorhanden]
    grenze = meta.get("maxRecordCount")
    if not isinstance(grenze, int) or grenze < s.zensus_page_size:
        befunde.append(
            f"Zensus: maxRecordCount {grenze!r} < Seitengröße {s.zensus_page_size}")
    return befunde


async def wms_dienste(out: Outbound, s: Settings) -> list[str]:
    befunde = []
    for e in await wms.pruefe_dienste(out, s):
        if not e.get("ok"):
            grund = e.get("fehler") or (
                "Layer fehlen: " + ", ".join(e.get("fehlende_layer") or []))
            befunde.append(f"WMS {e['land']}: {grund} ({e['url']})")
    return befunde


async def dwd_dateien(out: Outbound, s: Settings) -> list[str]:
    listing = await out.get_text("klima", f"{s.dwd_base}/", timeout=s.zensus_timeout)
    befunde = []
    for p in klima.PARAMETER:
        for name in (f"{p['datei']}.txt", f"{p['datei']}_Stationsliste.txt"):
            if name not in listing:
                befunde.append(f"DWD: {name} nicht mehr im Verzeichnis")
    return befunde


async def ckan_indikatoren(out: Outbound, s: Settings) -> list[str]:
    payload = await out.get_json(
        "muenchen_indikatoren", indikatoren.CKAN_SEARCH_URL,
        params=indikatoren.CKAN_SEARCH_PARAMS, timeout=45.0)
    urls, warnungen = indikatoren.finde_csv_urls(payload)
    befunde = [f"Indikatorenatlas: Datensatz {k!r} ({t}) nicht gefunden"
               for k, t in indikatoren.DATEIEN.items() if k not in urls]
    befunde.extend(f"Indikatorenatlas: {w}" for w in warnungen)
    return befunde


PRUEFUNGEN = [
    ("Zensus-Gitterdienst: Felder und Seitengröße", zensus_felder),
    ("Landes-Kartendienste (WMS GetCapabilities)", wms_dienste),
    ("DWD Open Data: Dateinamen der Klimanormalwerte", dwd_dateien),
    ("Open-Data-Portal München: Indikatorenatlas-Dateien", ckan_indikatoren),
]


async def lauf() -> list[tuple[str, list[str]]]:
    s = Settings()
    s.ensure_dirs()
    out = Outbound(s, AsyncCache(s.db_path))
    await out.start()
    ergebnisse = []
    try:
        for name, fn in PRUEFUNGEN:
            try:
                befunde = await fn(out, s)
            except SourceError as err:
                befunde = [f"{name}: nicht prüfbar — {err.kind}: {err.message}"]
            ergebnisse.append((name, befunde))
    finally:
        await out.aclose()
    return ergebnisse


def main() -> int:
    heute = dt.date.today().isoformat()
    zeilen = [f"Kontrakt-Check {heute}", "=" * 60]
    ergebnisse = asyncio.run(lauf())
    gesamt = 0
    for name, befunde in ergebnisse:
        zeilen.append(f"[{'OK  ' if not befunde else 'FEHL'}] {name}")
        for b in befunde:
            zeilen.append(f"       · {b}")
        gesamt += len(befunde)
    zeilen.append("=" * 60)
    zeilen.append("Alle Verträge halten." if not gesamt else f"{gesamt} Abweichung(en).")
    text = "\n".join(zeilen)
    print(text)
    zusammenfassung = os.environ.get("GITHUB_STEP_SUMMARY")
    if zusammenfassung:
        with open(zusammenfassung, "a", encoding="utf-8") as f:
            f.write("```\n" + text + "\n```\n")
    return 1 if gesamt else 0


if __name__ == "__main__":
    sys.exit(main())
