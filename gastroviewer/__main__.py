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
import urllib.request
from pathlib import Path

from .config import Settings, get_settings


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def cmd_serve(args: argparse.Namespace, settings: Settings) -> int:
    import uvicorn

    from .api import create_app

    host = args.host or settings.host
    port = args.port or settings.port
    print(f"Standort-Datenterminal → http://{host}:{port}")
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


def cmd_import_gtfs(args: argparse.Namespace, settings: Settings) -> int:
    from .sources import gtfs

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

    s = sub.add_parser("serve", help="Server starten (Standard)")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    s.add_argument("--log-level", default="info")
    s.set_defaults(func=cmd_serve)

    g = sub.add_parser("import-gtfs", help="GTFS-Fahrplan einmalig importieren")
    g.add_argument("--url", help="abweichende Feed-URL")
    g.add_argument("--file", help="bereits geladenes ZIP verwenden")
    g.add_argument(
        "--bbox",
        help="min_lat,min_lon,max_lat,max_lon — Import auf eine Region begrenzen "
        "(dringend empfohlen, sonst mehrere GB)",
    )
    g.add_argument("--keep", action="store_true", help="ZIP nach dem Import behalten")
    g.set_defaults(func=cmd_import_gtfs)

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
        args = parser.parse_args((argv or []) + ["serve"])
    settings = get_settings()
    settings.ensure_dirs()
    return args.func(args, settings)


if __name__ == "__main__":
    raise SystemExit(main())
