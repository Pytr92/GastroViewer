"""Importe aus der Oberfläche heraus — im Hintergrund, mit Fortschritt.

Bis 0.4.0 waren die großen Einmal-Downloads (Fahrplan, Bevölkerungsraster
Österreich, Handelsregister) reine Kommandozeilenschritte. Für Deutschland
ist das vertretbar, weil das Werkzeug dort auch ohne Fahrplan fast alles
zeigt. Für Österreich fehlt ohne das Eurostat-Raster die Einwohnerzahl —
der wichtigste Block. Deshalb bietet die Oberfläche dort einen Knopf, der
den Import anstößt; er läuft hier als Thread, der Zustand ist abfragbar.

Grundsatz bleibt: **Nichts lädt ungefragt.** Der Knopf nennt Quelle und
Größe, erst der Klick startet den Download. Je Import läuft höchstens ein
Lauf; ein zweiter Klick während des Laufs ist ein Fehler, kein Neustart.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import Settings

ARTEN: dict[str, dict[str, Any]] = {
    "raster_at": {
        "titel": "Bevölkerungsraster Österreich (Eurostat, 1 km)",
        "groesse_mb": 186,
        "quelle": "https://gisco-services.ec.europa.eu/census/2021/Eurostat_Census-GRID_2021_V1-0.zip",
        "lizenz": "Eurostat GEOSTAT — freie Nutzung mit Quellenangabe",
        "beschreibung": ("Einwohner je 1-km-Zelle aus dem europäischen Zensusraster 2021. "
                         "Einmaliger Download von rund 186 MB (ganz Europa), es bleiben "
                         "die österreichischen Zellen — danach rein lokal."),
    },
    "gtfs_wien": {
        "titel": "Fahrplan Wiener Linien (GTFS)",
        "groesse_mb": 91,
        "quelle": "https://www.wienerlinien.at/ogd_realtime/doku/ogd/gtfs/gtfs.zip",
        "lizenz": "Wiener Linien OGD — CC BY 4.0",
        "beschreibung": ("Abfahrten je Haltestelle und Stunde für Wien und Umland. "
                         "Rund 91 MB, ersetzt einen bereits importierten Fahrplan."),
    },
}


@dataclass
class Lauf:
    art: str
    status: str = "laeuft"          # laeuft | fertig | fehler
    schritt: str = "gestartet"
    fortschritt: float | None = None  # 0–100 während des Downloads
    begonnen: float = field(default_factory=time.time)
    beendet: float | None = None
    fehler: str | None = None
    ergebnis: dict[str, Any] | None = None


def herunterladen(url: str, ziel: Path, melden: Callable[[str, float | None], None]) -> Path:
    """Wie ``__main__._download``, nur mit Rückruf statt Terminalausgabe."""
    with urllib.request.urlopen(url, timeout=120) as resp:  # noqa: S310 — feste, konfigurierte URL
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(ziel, "wb") as fh:
            while chunk := resp.read(1024 * 256):
                fh.write(chunk)
                done += len(chunk)
                pct = done / total * 100 if total else None
                melden(f"Download {done // (1024 * 1024)} MB"
                       + (f" von {total // (1024 * 1024)} MB" if total else ""), pct)
    return ziel


def _raster_at(settings: Settings, lauf: Lauf, melden) -> dict[str, Any]:
    from .sources import raster_at

    tmpdir = Path(tempfile.mkdtemp(prefix="gastroviewer-raster-"))
    try:
        pfad = herunterladen(ARTEN["raster_at"]["quelle"], tmpdir / "census.zip", melden)
        lauf.fortschritt = None
        return raster_at.import_zip(settings, pfad, quelle=ARTEN["raster_at"]["quelle"],
                                    progress=lambda m: melden(m, None))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _gtfs_wien(settings: Settings, lauf: Lauf, melden) -> dict[str, Any]:
    from .__main__ import REGIONEN
    from .sources import gtfs

    tmpdir = Path(tempfile.mkdtemp(prefix="gastroviewer-gtfs-"))
    try:
        pfad = herunterladen(ARTEN["gtfs_wien"]["quelle"], tmpdir / "gtfs.zip", melden)
        lauf.fortschritt = None
        _, bbox = REGIONEN["wien"]
        return gtfs.import_feed(settings, pfad, bbox=bbox, quelle=ARTEN["gtfs_wien"]["quelle"],
                                progress=lambda m: melden(m, None))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


AUSFUEHREN: dict[str, Callable[[Settings, Lauf, Callable[[str, float | None], None]], dict[str, Any]]] = {
    "raster_at": _raster_at,
    "gtfs_wien": _gtfs_wien,
}


class Importe:
    """Ein Lauf je Art; Zustand für die Oberfläche."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._laeufe: dict[str, Lauf] = {}
        self._sperre = threading.Lock()

    def start(self, art: str) -> Lauf:
        if art not in ARTEN:
            raise KeyError(art)
        with self._sperre:
            alt = self._laeufe.get(art)
            if alt is not None and alt.status == "laeuft":
                raise RuntimeError(f"Import {art} läuft bereits.")
            lauf = Lauf(art=art)
            self._laeufe[art] = lauf

        def melden(schritt: str, fortschritt: float | None) -> None:
            lauf.schritt = schritt
            if fortschritt is not None:
                lauf.fortschritt = round(fortschritt, 1)

        def arbeit() -> None:
            try:
                lauf.ergebnis = AUSFUEHREN[art](self.settings, lauf, melden)
                lauf.status, lauf.schritt = "fertig", "abgeschlossen"
            except Exception as exc:  # noqa: BLE001 — der Fehler gehört in den Zustand
                lauf.status, lauf.fehler = "fehler", f"{type(exc).__name__}: {exc}"
                lauf.schritt = "abgebrochen"
            finally:
                lauf.beendet = time.time()

        threading.Thread(target=arbeit, name=f"import-{art}", daemon=True).start()
        return lauf

    def zustand(self) -> dict[str, Any]:
        from .sources import gtfs, raster_at

        vorhanden = {"raster_at": raster_at.status(self.settings),
                     "gtfs_wien": gtfs.status(self.settings)}
        out: dict[str, Any] = {}
        for art, meta in ARTEN.items():
            lauf = self._laeufe.get(art)
            out[art] = {**meta, "importiert": bool(vorhanden[art].get("importiert")),
                        "bestand": vorhanden[art],
                        "lauf": asdict(lauf) if lauf else None}
        return out

    def warten(self, art: str, sekunden: float = 60.0) -> Lauf | None:
        """Für Tests: bis der Lauf endet."""
        lauf = self._laeufe.get(art)
        frist = time.time() + sekunden
        while lauf and lauf.status == "laeuft" and time.time() < frist:
            time.sleep(0.05)
        return lauf
