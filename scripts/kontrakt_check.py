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
5. Die Dienste aus 0.6.0: Wien, Salzburg, Berlin, Hamburg, MobiData BW,
   Stuttgart, BKG-Starkregen und Statistik Austria.

Mehrere dieser Kennungen tragen ein Jahr oder ein Datum (Hamburg
``..._dtv_hvs_2019``, Berlin ``verkehrsmengen_2023``, Wien
``REALNUT2022OGD``, die ODS-Dateien der Immobilienpreise, der
Dateiname der Straßenverkehrszählung). Die Prüfungen melden deshalb
zweierlei: die benutzte Kennung ist **weg** (dann bleibt ein Block leer)
oder es gibt eine **neuere** (dann zeigt der Block veraltete Zahlen).
Beides ist ein Befund, der zweite ein freundlicher.

Läuft über das projekteigene ``Outbound`` (User-Agent, Limiter, Protokoll).
Exitcode 0 = alle Verträge halten, 1 = mindestens eine Abweichung, die
Ausgabe nennt sie mit Datum. Bewusst außerhalb der pytest-Suite: der
Push-Lauf bleibt offline.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gastroviewer.cache import AsyncCache  # noqa: E402
from gastroviewer.config import Settings  # noqa: E402
from gastroviewer.http import Outbound  # noqa: E402
from gastroviewer.sources import (berlin, gemeinde_at, hamburg, immobilien_at,  # noqa: E402
                                  indikatoren, klima, mobidata_bw, pks, salzburg, starkregen,
                                  wien, wien_profil, wien_verkehr, wms, zensus)
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



# --------------------------------------------- Quellen aus 0.6.0
# Bis hierher prüfte das Skript vier Verträge. Die Quellen aus 0.6.0 sind
# einmal live belegt (18.09.2026) und wurden danach nie wieder gegen den
# Anbieter gehalten — genau die Lücke, gegen die dieses Skript existiert.

JAHR_MUSTER = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")


def _jahr(name: str) -> int | None:
    treffer = JAHR_MUSTER.findall(name or "")
    if not treffer:
        return None
    return max(int(m.group()) for m in JAHR_MUSTER.finditer(name))


def _neuere_fassung(vorhanden: list[str], benutzt: str) -> str | None:
    """Gibt es zu einer Kennung mit Jahreszahl eine jüngere? ``dtv_hvs_2019``
    und ``dtv_hvs_2021`` unterscheiden sich nur in der Zahl — alles andere
    muss gleich sein, sonst ist es ein anderer Datensatz."""
    eigen = _jahr(benutzt)
    if eigen is None:
        return None
    rumpf = JAHR_MUSTER.sub("#", benutzt)
    kandidaten = [(j, n) for n in vorhanden
                  if (j := _jahr(n)) is not None and j > eigen and JAHR_MUSTER.sub("#", n) == rumpf]
    return max(kandidaten)[1] if kandidaten else None


async def _wfs_layer(out: Outbound, quelle: str, url: str, version: str = "1.1.0") -> list[str]:
    xml = await out.get_text(quelle, url, params={"service": "WFS", "request": "GetCapabilities",
                                                  "version": version}, timeout=60.0)
    return re.findall(r"<Name>([^<>]+)</Name>", xml)


def _fehlend(bezeichnung: str, vorhanden: list[str], gebraucht: dict[str, str]) -> list[str]:
    """``gebraucht``: Kennung → wo sie im Code steht. Meldet Fehlendes und
    weist auf jüngere Jahrgänge hin."""
    befunde = []
    for kennung, wo in gebraucht.items():
        if kennung not in vorhanden:
            befunde.append(f"{bezeichnung}: {kennung!r} nicht mehr im Dienst (benutzt in {wo})")
            continue
        neuer = _neuere_fassung(vorhanden, kennung)
        if neuer:
            befunde.append(f"{bezeichnung}: {kennung!r} ist überholt, der Dienst führt {neuer!r} ({wo})")
    return befunde


async def wien_dienste(out: Outbound, s: Settings) -> list[str]:
    """Alle Wiener WFS-Layer, die drei Module benutzen, plus die beiden
    CSV-Dateien (Dauerzählstellen, Lumes)."""
    vorhanden = await _wfs_layer(out, "wien", wien.WFS_URL)
    kurz = [n.split(":")[-1] for n in vorhanden]
    gebraucht = {
        "MAERKTEOGD": "wien.maerkte", "BAUSTELLENPKTOGD": "wien.baustellen",
        "BAUSTELLENLINOGD": "wien.baustellen", "SCHUTZZONEOGD": "wien.schutzzonen",
        "GENFLWIDMUNGOGD": "wien.baurecht", "ZAEHLBEZIRKOGD": "wien_profil.zaehlbezirk",
        "KURZPARKZONEOGD": "wien_profil.lage", "FUSSGEHERZONEOGD": "wien_profil.lage",
        "BEGEGNUNGSZONEOGD": "wien_profil.lage", "STRUKGESCHSTROGD": "wien_profil.lage",
        wien_profil.REALNUT_TYP: "wien_profil.lage", "GEBAEUDEINFOOGD": "wien_profil.lage",
        "DAUERZAEHLOGD": "wien_verkehr.kfz", "LUFTGUETENETZOGD": "wien_verkehr.luft",
    }
    befunde = _fehlend("Wien WFS", kurz, gebraucht)
    for name, url in (("Dauerzählstellen", wien_verkehr.KFZ_CSV_URL),
                      ("Lumes-Luftwerte", wien_verkehr.LUFT_CSV_URL),
                      ("Zählbezirks-Bevölkerung", wien_profil.ZB_CSV_URL)):
        r = await out.request("wien", "HEAD", url, timeout=60.0)
        if r.status_code >= 400:
            befunde.append(f"Wien: {name} — HTTP {r.status_code} ({url})")
    return befunde


async def salzburg_dienste(out: Outbound, s: Settings) -> list[str]:
    vorhanden = [n.split(":")[-1] for n in await _wfs_layer(out, "salzburg", salzburg.WFS_URL)]
    return _fehlend("Salzburg WFS", vorhanden, {
        "flaechenwidmung": "salzburg.baurecht", "bebauungsplan_rechtswirksam": "salzburg.baurecht",
        "altstadtschutzzone": "salzburg.planung", "kurzparkzone": "salzburg.lage",
        "markt": "salzburg.maerkte", "baustelle_aktuell": "salzburg.baustellen"})


async def berlin_verkehrsmengen(out: Outbound, s: Settings) -> list[str]:
    """Der Dienstname trägt das Bezugsjahr. Erst die Layer im benutzten
    Dienst, dann die Frage, ob es den Dienst für ein jüngeres Jahr gibt."""
    befunde = []
    try:
        vorhanden = [n.split(":")[-1] for n in await _wfs_layer(out, "berlin", berlin.VM_WFS_URL, "2.0.0")]
    except SourceError as err:
        return [f"Berlin Verkehrsmengen {berlin.VM_JAHR}: Dienst nicht erreichbar — {err.message}"]
    befunde += _fehlend("Berlin Verkehrsmengen", vorhanden,
                        {f"dtvw{berlin.VM_JAHR}kfz": "berlin.verkehrsmengen",
                         f"dtvw{berlin.VM_JAHR}lkw": "berlin.verkehrsmengen",
                         f"dtvw{berlin.VM_JAHR}rad": "berlin.verkehrsmengen"})
    for jahr in range(berlin.VM_JAHR + 1, dt.date.today().year + 1):
        url = berlin.VM_WFS_URL.replace(str(berlin.VM_JAHR), str(jahr))
        try:
            r = await out.request("berlin", "GET", url,
                                  params={"SERVICE": "WFS", "REQUEST": "GetCapabilities"}, timeout=45.0)
        except SourceError:
            continue
        if r.status_code < 400 and "FeatureType" in r.text:
            befunde.append(f"Berlin: Verkehrsmengen {jahr} gibt es schon, der Block nutzt {berlin.VM_JAHR}")
            break
    return befunde


async def hamburg_sammlungen(out: Outbound, s: Settings) -> list[str]:
    """Die Sammlungen der Urban Data Platform tragen das Erhebungsjahr."""
    befunde = []
    gebraucht = {
        "verkehrsstaerken": {"kfz_temporaere_zaehlungen": "hamburg.verkehrsmengen"},
        "verkehrsmengen": {hamburg.VM_HVS_SAMMLUNG: "hamburg.verkehrsmengen"},
        "regionalstatistische_daten_stadtteile": {
            "regionalstatistische_daten_stadtteile": "hamburg.stadtteil"},
        "parkhaeuser": {"parkhaeuser": "hamburg.lage"},
        "parkraum": {"parkraum": "hamburg.lage"},
        "dauerzaehlstellen_rad": {"dauerzaehlstellen_rad": "hamburg.rad"},
    }
    for datensatz, kennungen in gebraucht.items():
        try:
            payload = await out.get_json("hamburg", f"{hamburg.OAF_BASE}/{datensatz}/collections",
                                         params={"f": "json"}, timeout=45.0)
        except SourceError as err:
            befunde.append(f"Hamburg: Datensatz {datensatz!r} nicht erreichbar — {err.message}")
            continue
        ids = [c.get("id") for c in (payload.get("collections") or []) if c.get("id")]
        befunde += _fehlend(f"Hamburg {datensatz}", ids, kennungen)
    return befunde


async def mobidata_dateien(out: Outbound, s: Settings) -> list[str]:
    """Zwei Layer im GeoServer und drei Dateien. Der Dateiname der
    Straßenverkehrszählung trägt ein Erstellungsdatum — er wechselt bei
    jeder Fortschreibung, deshalb wird er hier direkt geprüft."""
    befunde = []
    try:
        vorhanden = [n.split(":")[-1] for n in await _wfs_layer(out, "mobidata", mobidata_bw.WFS_URL)]
        befunde += _fehlend("MobiData BW", vorhanden,
                            {"charge_points": "mobidata_bw.ladesaeulen", "roadworks": "mobidata_bw (WFS-Spiegel)"})
    except SourceError as err:
        befunde.append(f"MobiData BW: GeoServer nicht erreichbar — {err.message}")
    for name, url in (("Baustellen (GeoJSON)", mobidata_bw.ROADWORKS_URL),
                      ("Straßenverkehrszählung", mobidata_bw.SVZ_URL),
                      ("Eco-Counter-Tageswerte", mobidata_bw.ECO_URL),
                      ("Baustellen Stuttgart", mobidata_bw.STUTTGART_WFS_URL)):
        try:
            r = await out.request("mobidata", "HEAD", url, timeout=60.0)
        except SourceError as err:
            befunde.append(f"MobiData BW: {name} — {err.message}")
            continue
        if r.status_code >= 400:
            hinweis = (" — der Dateiname trägt ein Datum und wechselt bei jeder Fortschreibung"
                       if url == mobidata_bw.SVZ_URL else "")
            befunde.append(f"MobiData BW: {name} — HTTP {r.status_code}{hinweis} ({url})")
    return befunde


async def stuttgart_layer(out: Outbound, s: Settings) -> list[str]:
    try:
        vorhanden = await _wfs_layer(out, "stuttgart", mobidata_bw.STUTTGART_WFS_URL)
    except SourceError as err:
        return [f"Stuttgart: Baustellen-WFS nicht erreichbar — {err.message}"]
    kurz = [n.split(":")[-1] for n in vorhanden]
    return _fehlend("Stuttgart", kurz,
                    {mobidata_bw.STUTTGART_TYP.split(":")[-1]: "mobidata_bw.stuttgart_baustellen"})


async def bkg_starkregen(out: Outbound, s: Settings) -> list[str]:
    try:
        xml = await out.get_text("bkg_starkregen", starkregen.WMS_URL,
                                 params={"service": "WMS", "request": "GetCapabilities", "version": "1.3.0"},
                                 timeout=60.0)
    except SourceError as err:
        return [f"BKG-Starkregen: nicht erreichbar — {err.message}"]
    vorhanden = re.findall(r"<Name>([^<>]+)</Name>", xml)
    gebraucht = {f"{art}_{szenario}": "starkregen.load"
                 for art in ("tiefe", "geschwindigkeit") for szenario in starkregen.SZENARIEN}
    # Die Sammellayer fragen alle Länder zugleich ab; die Landeslayer
    # (``be_tiefe_agw`` …) sind nur ihre Feinstruktur und werden nicht benutzt.
    return _fehlend("BKG-Starkregen", vorhanden, gebraucht)


async def statistik_at_dateien(out: Outbound, s: Settings) -> list[str]:
    """Gemeindetabelle, Gemeindegrenzen-WFS und die drei Preis-ODS. Die
    Preisdateien tragen das Berichtsjahr im Namen; das Modul probiert die
    Jahre der Reihe nach, hier wird gemeldet, wenn das jüngste bekannte
    Jahr fehlt oder ein noch jüngeres schon da ist."""
    befunde = []
    r = await out.request("statistik_at", "HEAD", gemeinde_at.CSV_URL, timeout=60.0)
    if r.status_code >= 400:
        befunde.append(f"Statistik Austria: Gemeindetabelle — HTTP {r.status_code} ({gemeinde_at.CSV_URL})")
    try:
        vorhanden = await _wfs_layer(out, "statistik_at", gemeinde_at.GEODATA_WFS_URL)
        befunde += _fehlend("Statistik Austria GEODATA", vorhanden,
                            {gemeinde_at.GEODATA_GEM_TYP: "gemeinde_at.gkz_am_punkt"})
    except SourceError as err:
        befunde.append(f"Statistik Austria: Gemeindegrenzen-WFS nicht erreichbar — {err.message}")
    juengstes = max(immobilien_at.JAHRE)
    for jahr in (juengstes + 1, *immobilien_at.JAHRE):
        treffer = []
        for art, muster in immobilien_at.DATEIEN.items():
            url = immobilien_at.BASIS_URL + muster.format(jahr=jahr)
            try:
                r = await out.request("statistik_at", "HEAD", url, timeout=60.0)
            except SourceError:
                continue
            if r.status_code < 400:
                treffer.append(art)
        if len(treffer) == 3 and jahr > juengstes:
            befunde.append(f"Statistik Austria: Immobilienpreise {jahr} gibt es schon, "
                           f"das Modul kennt nur bis {juengstes}")
            break
        if len(treffer) == 3:
            break
        if jahr in immobilien_at.JAHRE and jahr == min(immobilien_at.JAHRE):
            befunde.append(f"Statistik Austria: Immobilienpreise {jahr} unvollständig "
                           f"(gefunden: {', '.join(treffer) or 'keine'})")
    return befunde


async def pks_jahresdatei(out: Outbound, s: Settings) -> list[str]:
    """Die BKA-Kreistabelle liegt unter einem Pfad mit Berichtsjahr. Der
    erste Live-Lauf der Vollprüfung fand den Block gescheitert vor —
    deshalb steht die Datei jetzt im Vertrag."""
    befunde = []
    try:
        r = await out.request("pks", "HEAD", pks.XLSX_URL, timeout=90.0)
    except SourceError as err:
        return [f"PKS: Kreistabelle {pks.JAHR} nicht erreichbar — {err.message}"]
    if r.status_code >= 400:
        befunde.append(f"PKS: Kreistabelle {pks.JAHR} — HTTP {r.status_code} ({pks.XLSX_URL})")
    # Gibt es schon das Folgejahr? Dann zeigt der Block veraltete Zahlen.
    naechstes = pks.XLSX_URL.replace(str(pks.JAHR), str(pks.JAHR + 1))
    try:
        r = await out.request("pks", "HEAD", naechstes, timeout=90.0)
        if r.status_code < 400:
            befunde.append(f"PKS: Kreistabelle {pks.JAHR + 1} gibt es schon, der Block nutzt {pks.JAHR}")
    except SourceError:
        pass
    return befunde


PRUEFUNGEN = [
    ("Zensus-Gitterdienst: Felder und Seitengröße", zensus_felder),
    ("Landes-Kartendienste (WMS GetCapabilities)", wms_dienste),
    ("DWD Open Data: Dateinamen der Klimanormalwerte", dwd_dateien),
    ("Open-Data-Portal München: Indikatorenatlas-Dateien", ckan_indikatoren),
    ("Stadt Wien: WFS-Layer und CSV-Dateien", wien_dienste),
    ("Stadt Salzburg: WFS-Layer", salzburg_dienste),
    ("Berlin: Verkehrsmengen-Dienst und Bezugsjahr", berlin_verkehrsmengen),
    ("Hamburg: Sammlungen der Urban Data Platform", hamburg_sammlungen),
    ("MobiData BW: Layer und Landesdateien", mobidata_dateien),
    ("Stuttgart: Baustellen-Layer", stuttgart_layer),
    ("BKG: Starkregen-Layer", bkg_starkregen),
    ("Statistik Austria: Tabellen, Grenzen, Preisdateien", statistik_at_dateien),
    ("BKA: Kriminalstatistik-Kreistabelle und Berichtsjahr", pks_jahresdatei),
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
