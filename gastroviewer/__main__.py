"""CLI. Läuft unverändert auf macOS, Linux und Windows.

    python -m gastroviewer serve
    python -m gastroviewer import-gtfs --bbox 48.0,11.3,48.3,11.8
    python -m gastroviewer clear-cache
    python -m gastroviewer status
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from .config import Settings, get_settings


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _port_belegt(host: str, port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host if host != "0.0.0.0" else "127.0.0.1", port)) == 0


def cmd_fenster(args: argparse.Namespace, settings: Settings) -> int:
    """Das Startfenster. Fehlt tkinter, wird das gesagt statt abzustürzen."""
    from .startfenster import starte_fenster

    return starte_fenster(
        settings,
        host=args.host or settings.host,
        port=args.port or settings.port,
        sofort_starten=not getattr(args, "nicht_starten", False),
        selbsttest=getattr(args, "selbsttest", False),
    )


def cmd_serve(args: argparse.Namespace, settings: Settings) -> int:
    import uvicorn

    from .api import create_app

    host = args.host or settings.host
    port = args.port or settings.port
    adresse = f"http://{'127.0.0.1' if host == '0.0.0.0' else host}:{port}"
    if getattr(args, "browser", False):
        # Doppelklick-Komfort: läuft schon ein Terminal auf dem Port, nur das
        # Browserfenster öffnen statt mit „Adresse belegt" abzubrechen.
        if _port_belegt(host, port):
            print(f"Läuft bereits: {adresse} — öffne den Browser.")
            import webbrowser

            webbrowser.open(adresse)
            return 0
        import threading
        import webbrowser

        # Erst öffnen, wenn der Server antwortet — höchstens 15 s warten.
        def _oeffnen() -> None:
            for _ in range(30):
                if _port_belegt(host, port):
                    break
                time.sleep(0.5)
            webbrowser.open(adresse)

        threading.Thread(target=_oeffnen, daemon=True).start()
    print(f"Standort-Datenterminal → {adresse}")
    print(f"  Datenverzeichnis : {settings.data_dir}")
    print(f"  User-Agent       : {settings.user_agent}")
    if "github.com/Pytr92" in settings.contact:
        print(
            "  Hinweis          : GASTROVIEWER_CONTACT auf eine eigene Kontaktadresse\n"
            "                     setzen — die Nominatim-Nutzungsbedingungen verlangen das."
        )
    uvicorn.run(create_app(settings), host=host, port=port, log_level=args.log_level)
    return 0


def _download(url: str, target: Path) -> Path:
    print(f"Lade {url}")
    # Fortschritt nur im Terminal überschreibend ausgeben. In eine Datei oder
    # Pipe umgeleitet würde \r sonst hunderte Zeilen Rauschen erzeugen.
    tty = sys.stdout.isatty()
    naechste_meldung = 10
    with urllib.request.urlopen(url) as resp:  # noqa: S310 — feste, konfigurierte URL
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(target, "wb") as fh:
            while chunk := resp.read(1024 * 256):
                fh.write(chunk)
                done += len(chunk)
                if not total:
                    continue
                pct = done / total * 100
                if tty:
                    print(f"  {_fmt_bytes(done)} / {_fmt_bytes(total)} ({pct:.0f} %)", end="\r")
                elif pct >= naechste_meldung:
                    print(f"  {_fmt_bytes(done)} / {_fmt_bytes(total)} ({pct:.0f} %)")
                    naechste_meldung += 10
    if tty:
        print()
    return target


# Voreingestellte Ausschnitte. Spart das Nachschlagen von Koordinaten und
# verhindert den häufigsten Fehler beim Import: die vertauschte Reihenfolge.
REGIONEN: dict[str, tuple[str, tuple[float, float, float, float]]] = {
    "muenchen": ("München und unmittelbares Umland", (47.98, 11.28, 48.32, 11.82)),
    "muenchen-region": ("Region München mit S-Bahn-Umland", (47.80, 11.00, 48.55, 12.10)),
    "oberbayern": ("Regierungsbezirk Oberbayern", (47.27, 10.75, 48.95, 13.20)),
    "bayern": ("Freistaat Bayern", (47.27, 8.97, 50.57, 13.84)),
}


def cmd_import_gtfs(args: argparse.Namespace, settings: Settings) -> int:
    from .sources import gtfs

    bbox = None
    if args.region:
        if args.region not in REGIONEN:
            print(
                f"Unbekannte Region: {args.region}. Möglich: "
                + ", ".join(sorted(REGIONEN)),
                file=sys.stderr,
            )
            return 2
        beschreibung, bbox = REGIONEN[args.region]
        print(f"Ausschnitt: {beschreibung} {bbox}")
        if args.bbox:
            print("--bbox überschreibt --region", file=sys.stderr)
            bbox = None
    if args.bbox:
        try:
            parts = [float(x) for x in args.bbox.split(",")]
            if len(parts) != 4:
                raise ValueError
            bbox = (parts[0], parts[1], parts[2], parts[3])
        except ValueError:
            print("--bbox erwartet min_lat,min_lon,max_lat,max_lon", file=sys.stderr)
            return 2

    tmpdir: Path | None = None
    if args.file:
        zip_path = Path(args.file).expanduser()
        if not zip_path.exists():
            print(f"Datei nicht gefunden: {zip_path}", file=sys.stderr)
            return 2
        quelle = str(zip_path)
    else:
        quelle = args.url or settings.gtfs_url
        tmpdir = Path(tempfile.mkdtemp(prefix="gastroviewer-gtfs-"))
        zip_path = _download(quelle, tmpdir / "gtfs.zip")

    try:
        stats = gtfs.import_feed(
            settings, zip_path, bbox=bbox, quelle=quelle, progress=print
        )
    except Exception as exc:  # noqa: BLE001 — CLI soll die Ursache zeigen
        print(f"Import fehlgeschlagen: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        if tmpdir and not args.keep:
            shutil.rmtree(tmpdir, ignore_errors=True)

    for k, v in stats.items():
        print(f"  {k}: {v}")
    return 0


def cmd_import_register(args: argparse.Namespace, settings: Settings) -> int:
    """OffeneRegister-Datenspende (Handelsregister, Stand 05.02.2019) einmalig
    importieren. Wie der GTFS-Import: 260 MB laden, streamen, danach
    beantwortet eine lokale SQLite jede PLZ-Abfrage ohne Netz."""
    from .sources import register

    tmpdir: Path | None = None
    if args.file:
        dump_pfad = Path(args.file).expanduser()
        if not dump_pfad.exists():
            print(f"Datei nicht gefunden: {dump_pfad}", file=sys.stderr)
            return 2
        quelle = str(dump_pfad)
    else:
        quelle = args.url or register.DUMP_URL
        tmpdir = Path(tempfile.mkdtemp(prefix="gastroviewer-register-"))
        dump_pfad = _download(quelle, tmpdir / "register.jsonl.bz2")

    print("Baue lokale Registerdatenbank (Streaming, nichts wird entpackt "
          "zwischengespeichert) …")
    try:
        stats = register.import_dump(settings, dump_pfad, quelle=quelle,
                                     progress=print)
    except Exception as exc:  # noqa: BLE001 — CLI soll die Ursache zeigen
        print(f"Import fehlgeschlagen: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        if tmpdir and not args.keep:
            shutil.rmtree(tmpdir, ignore_errors=True)

    for k, v in stats.items():
        print(f"  {k}: {v}")
    print("Hinweis: eingefrorene Datenspende — Stand 05.02.2019, "
          "nicht fortgeschrieben.")
    return 0


def cmd_import_overture(args: argparse.Namespace, settings: Settings) -> int:
    """Overture-Places-Import (zweite Wettbewerbsquelle neben OSM).

    Wie der GTFS-Import: einmal laufen lassen, danach beantwortet eine lokale
    SQLite jede Punktabfrage ohne Netz. Braucht das Paket ``overturemaps``
    (zieht pyarrow mit — deshalb bewusst NICHT in den Basisabhängigkeiten)."""
    try:
        from overturemaps import record_batch_reader
        from overturemaps.core import get_latest_release
    except ImportError:
        print(
            "Das Paket 'overturemaps' fehlt. Einmal installieren:\n"
            "  pip install overturemaps",
            file=sys.stderr,
        )
        return 2

    from .sources import overture

    bbox = None
    region_name = None
    if args.region:
        if args.region not in REGIONEN:
            print(
                f"Unbekannte Region: {args.region}. Möglich: "
                + ", ".join(sorted(REGIONEN)),
                file=sys.stderr,
            )
            return 2
        beschreibung, bbox = REGIONEN[args.region]
        region_name = f"{args.region} ({beschreibung})"
        print(f"Ausschnitt: {beschreibung} {bbox}")
    if args.bbox:
        try:
            parts = [float(x) for x in args.bbox.split(",")]
            if len(parts) != 4:
                raise ValueError
            bbox = (parts[0], parts[1], parts[2], parts[3])
            region_name = f"bbox {args.bbox}"
        except ValueError:
            print("--bbox erwartet min_lat,min_lon,max_lat,max_lon", file=sys.stderr)
            return 2
    if bbox is None:
        print("Bitte --region oder --bbox angeben (z. B. --region muenchen).",
              file=sys.stderr)
        return 2

    try:
        release = get_latest_release()
    except Exception:  # noqa: BLE001 — Katalog nicht erreichbar: trotzdem importieren
        release = None
    # Overture erwartet (min_lon, min_lat, max_lon, max_lat).
    o_bbox = (bbox[1], bbox[0], bbox[3], bbox[2])
    print(f"Overture-Release: {release or 'Paket-Standard'} — lade Places …")

    settings.ensure_dirs()
    ziel = settings.overture_db_path
    tmp = ziel.with_suffix(".sqlite.neu")
    conn = overture.db_init(tmp)
    geprueft = uebernommen = 0
    try:
        reader = record_batch_reader("place", o_bbox, release=release)
        if reader is None:
            raise RuntimeError("Overture lieferte keinen Datenstrom.")
        for batch in reader:
            for row in batch.to_pylist():
                geprueft += 1
                punkt = overture.wkb_punkt(row.get("geometry"))
                if punkt is None:
                    continue
                zeile = overture.zeile_aus_properties(row, *punkt)
                if zeile is None:
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO places VALUES "
                    "(:id,:name,:kategorie,:gruppe,:confidence,:lat,:lon,"
                    ":adresse,:plz,:ort,:marke,:quellen)",
                    zeile,
                )
                uebernommen += 1
            print(f"  geprüft: {geprueft:,}, Gastro übernommen: {uebernommen:,}"
                  .replace(",", "."))
        conn.executemany(
            "INSERT OR REPLACE INTO meta VALUES (?, ?)",
            [
                ("release", release or "unbekannt"),
                ("region", region_name or ""),
                ("bbox", ",".join(str(x) for x in bbox)),
                ("importiert_am", time.strftime("%Y-%m-%d", time.gmtime())),
                ("geprueft", str(geprueft)),
                ("uebernommen", str(uebernommen)),
            ],
        )
        conn.commit()
    except Exception as exc:  # noqa: BLE001 — CLI soll die Ursache zeigen
        conn.close()
        tmp.unlink(missing_ok=True)
        print(f"Import fehlgeschlagen: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    conn.close()
    tmp.replace(ziel)
    print(f"Fertig: {uebernommen:,} Gastro-Orte aus {geprueft:,} geprüften "
          f"Einträgen → {ziel}".replace(",", "."))
    return 0


def cmd_clear_cache(args: argparse.Namespace, settings: Settings) -> int:
    from .cache import Cache

    cache = Cache(settings.db_path)
    n = cache.clear(args.quelle)
    print(f"{n} Cache-Einträge gelöscht ({args.quelle or 'alle Quellen'}).")
    return 0


def cmd_status(args: argparse.Namespace, settings: Settings) -> int:
    from .cache import Cache
    from .sources import gtfs

    cache = Cache(settings.db_path)
    st = cache.stats()
    print(f"Datenverzeichnis : {settings.data_dir}")
    print(f"Cache-Datei      : {settings.db_path}")
    print(f"Cache-Einträge   : {st['total']}")
    for row in st["entries"]:
        print(f"  {row['source']:<22} {row['n']:>5}  (abgelaufen: {row['stale'] or 0})")
    print(f"Outbound gesamt  : {st['outbound_requests_total']}")
    g = gtfs.status(settings)
    if g.get("importiert"):
        print(
            f"GTFS             : {g.get('groesse_mb')} MB · Referenztag "
            f"{g.get('referenzdatum')} · importiert {g.get('importiert_am')}"
        )
    else:
        print("GTFS             : nicht importiert")
    return 0


def cmd_check_wms(args: argparse.Namespace, settings: Settings) -> int:
    """Ruft bei jedem hinterlegten Landesdienst GetCapabilities ab.

    Landesdienste ändern ihre URLs — Brandenburg hat seine 2025 umgestellt.
    Ohne Gegenprobe merkt man das erst, wenn die Karte leer bleibt.
    """
    import asyncio

    from .cache import AsyncCache
    from .http import Outbound
    from .sources import wms

    async def lauf():
        cache = AsyncCache(settings.db_path)
        out = Outbound(settings, cache)
        await out.start()
        try:
            return await wms.pruefe_dienste(out, settings)
        finally:
            await out.aclose()

    ergebnisse = asyncio.run(lauf())
    kaputt = 0
    for e in ergebnisse:
        zeichen = "OK   " if e.get("ok") else "FEHLT"
        if not e.get("ok"):
            kaputt += 1
        print(f"[{zeichen}] {e['land']:22} {e['url']}")
        if e.get("fehler"):
            print(f"         {e['fehler']}")
        elif e.get("fehlende_layer"):
            print(f"         Layer nicht mehr im Dienst: {', '.join(e['fehlende_layer'])}")
    print(f"\n{len(ergebnisse) - kaputt} von {len(ergebnisse)} Diensten in Ordnung.")
    return 1 if kaputt else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gastroviewer",
        description="Standort-Datenterminal Deutschland — offene Daten zu einem Punkt.",
    )
    sub = p.add_subparsers(dest="cmd")

    f = sub.add_parser(
        "fenster",
        help="Kleines Fenster mit Status, Start-/Stopp-Knopf und Link "
             "(Standard im Doppelklick-Paket)")
    f.add_argument("--host")
    f.add_argument("--port", type=int)
    f.add_argument(
        "--nicht-starten", action="store_true",
        help="Fenster öffnen, den Server aber noch nicht starten")
    f.add_argument(
        "--selbsttest", action="store_true",
        help="Fenster aufbauen, einmal aktualisieren, schließen — prüft im "
             "Paketbau, dass das Fenster auf der Zielplattform entsteht")
    f.set_defaults(func=cmd_fenster)

    s = sub.add_parser("serve", help="Server starten (ohne Fenster)")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    s.add_argument("--log-level", default="info")
    s.add_argument(
        "--browser", action="store_true",
        help="Browser automatisch öffnen, sobald der Server antwortet "
        "(Standard im Doppelklick-Paket)",
    )
    s.set_defaults(func=cmd_serve)

    g = sub.add_parser("import-gtfs", help="GTFS-Fahrplan einmalig importieren")
    g.add_argument("--url", help="abweichende Feed-URL")
    g.add_argument("--file", help="bereits geladenes ZIP verwenden")
    g.add_argument(
        "--region",
        help="voreingestellter Ausschnitt: " + ", ".join(sorted(REGIONEN)),
    )
    g.add_argument(
        "--bbox",
        help="min_lat,min_lon,max_lat,max_lon — Import auf eine Region begrenzen "
        "(dringend empfohlen, sonst mehrere GB); überschreibt --region",
    )
    g.add_argument("--keep", action="store_true", help="ZIP nach dem Import behalten")
    g.set_defaults(func=cmd_import_gtfs)

    ov = sub.add_parser(
        "import-overture",
        help="Overture-Places importieren (zweite Wettbewerbsquelle neben OSM)",
    )
    ov.add_argument(
        "--region",
        help="voreingestellter Ausschnitt: " + ", ".join(sorted(REGIONEN)),
    )
    ov.add_argument(
        "--bbox",
        help="min_lat,min_lon,max_lat,max_lon — überschreibt --region",
    )
    ov.set_defaults(func=cmd_import_overture)

    rg = sub.add_parser(
        "import-register",
        help="OffeneRegister-Handelsregisterdaten importieren (Stand 2019)",
    )
    rg.add_argument("--url", help="abweichende Dump-URL")
    rg.add_argument("--file", help="bereits geladenen jsonl.bz2-Dump verwenden")
    rg.add_argument("--keep", action="store_true",
                    help="Dump nach dem Import behalten")
    rg.set_defaults(func=cmd_import_register)

    c = sub.add_parser("clear-cache", help="Cache leeren")
    c.add_argument("--quelle", help="nur eine Quelle (zensus, overpass, nominatim)")
    c.set_defaults(func=cmd_clear_cache)

    w = sub.add_parser(
        "check-wms", help="Bodenrichtwert-Kartendienste der Länder gegenprüfen"
    )
    w.set_defaults(func=cmd_check_wms)

    st = sub.add_parser("status", help="Cache- und GTFS-Status anzeigen")
    st.set_defaults(func=cmd_status)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        # Ohne Unterbefehl: Im Doppelklick-Paket (PyInstaller setzt
        # sys.frozen) das Startfenster — wer die Datei anklickt, hat kein
        # Terminal-Wissen und will sehen, ob etwas läuft und wo es liegt.
        # Ohne Paket bleibt es beim reinen Server; das Fenster gibt es dort
        # ausdrücklich über "gastroviewer fenster".
        standard = ["fenster"] if getattr(sys, "frozen", False) else ["serve"]
        args = parser.parse_args((argv or []) + standard)
    settings = get_settings()
    settings.ensure_dirs()
    return args.func(args, settings)


if __name__ == "__main__":
    raise SystemExit(main())
