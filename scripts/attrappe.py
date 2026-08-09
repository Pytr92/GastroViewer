#!/usr/bin/env python3
"""Die echte Anwendung mit abgefangener Datenschicht — für die CI.

Warum nicht einfach ein Server, der aufgezeichnete Antworten ausspuckt?
Weil die Hälfte der Browserprüfungen **Zustand** braucht: einen Punkt merken,
benoten, vergleichen, im Bericht öffnen, im Duell gegenüberstellen, löschen.
Ein eingefrorener Antwortstapel würde genau diese Prüfungen entwerten.

Deshalb läuft hier die richtige Anwendung, nur eben ohne Netz:

* Alles unter ``/api/points`` und die Seiten ``/bericht`` und ``/duell``
  arbeiten **echt**, gegen eine frische Datenbank in einem Wegwerfordner.
* Die datenholenden Routen (``/api/point/...``, ``/api/kreisprofil`` und so
  weiter) beantwortet eine Middleware aus der Aufzeichnung von
  ``scripts/aufzeichnen.py``.
* ``PointService.point`` — die Methode hinter „Punkt merken" und „neu
  prüfen" — liefert den aufgezeichneten Sammeldatensatz.
* Der gesamte ausgehende Verkehr ist **gesperrt**. Rutscht doch ein Aufruf
  durch, gibt es sofort eine klare Fehlermeldung statt eines Zeitablaufs.
  Das ist Absicht: Ein Loch in der Abschirmung soll auffallen.

Aufruf::

    python scripts/attrappe.py --port 8041
    python scripts/uitest.py http://127.0.0.1:8041 --attrappe

Exitcode 4, wenn die Aufzeichnung fehlt — ohne sie ist der Server sinnlos.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

AUFNAHME = (Path(__file__).resolve().parent.parent
            / "tests" / "fixtures" / "ui" / "api-antworten.json")

# Routen mit Zustand laufen echt — sie dürfen nie abgefangen werden.
ECHT_BELASSEN = ("/api/points",)


def _norm(params: dict[str, Any]) -> dict[str, str]:
    return {k: str(v) for k, v in params.items()
            if v not in (None, "") and k != "refresh"}


class Aufnahme:
    """Nachschlagewerk über den aufgezeichneten Antworten.

    Die Oberfläche schickt nicht immer exakt die Parameter, die aufgezeichnet
    wurden — Kartenausschnitte entstehen aus der Fenstergröße und wandern
    mit jeder Chromium-Version. Deshalb wird abgestuft gesucht, und jede
    Stufe ist im Antwortkopf ablesbar (``X-Attrappe``), damit ein zu grober
    Treffer nicht unbemerkt bleibt.
    """

    def __init__(self, roh: dict[str, Any]) -> None:
        self.eintraege: dict[str, dict[str, Any]] = {}
        self.nach_pfad: dict[str, list[tuple[dict[str, str], dict[str, Any]]]] = {}
        for k, wert in roh.items():
            pfad, _, query = k.partition("?")
            params = {a: b[0] for a, b
                      in urllib.parse.parse_qs(query).items()} if query else {}
            self.eintraege[k] = wert
            self.nach_pfad.setdefault(pfad, []).append((params, wert))
        self.fehlgriffe: list[str] = []

    def suche(self, pfad: str, params: dict[str, Any],
              ) -> tuple[dict[str, Any] | None, str]:
        kandidaten = self.nach_pfad.get(pfad)
        if not kandidaten:
            self.fehlgriffe.append(pfad)
            return None, "fehlt"
        gesucht = _norm(params)

        for p, wert in kandidaten:
            if p == gesucht:
                return wert, "genau"

        # Zweite Stufe: derselbe Ort, abweichender Radius o.ä.
        ort = {k: gesucht[k] for k in ("lat", "lon", "ags", "q",
                                       "bundesland_code", "ebene")
               if k in gesucht}
        if ort:
            for p, wert in kandidaten:
                if all(p.get(k) == v for k, v in ort.items()):
                    return wert, "ort"
            # Dritte Stufe: nächstgelegene aufgezeichnete Koordinate.
            if "lat" in gesucht and "lon" in gesucht:
                nah = self._naechste(kandidaten, float(gesucht["lat"]),
                                     float(gesucht["lon"]))
                if nah is not None:
                    return nah, "naechste"

        # Letzte Stufe: irgendeine Antwort dieses Pfades. Für Kartenausschnitte
        # ist das richtig — die Bbox wird bewusst ignoriert.
        return kandidaten[0][1], "pfad"

    @staticmethod
    def _naechste(kandidaten, lat: float, lon: float) -> dict[str, Any] | None:
        bester, abstand = None, None
        for p, wert in kandidaten:
            if "lat" not in p or "lon" not in p:
                continue
            d = (float(p["lat"]) - lat) ** 2 + (float(p["lon"]) - lon) ** 2
            if abstand is None or d < abstand:
                bester, abstand = wert, d
        return bester


def netz_sperren() -> None:
    """Jeden ausgehenden Aufruf mit einer klaren Meldung abweisen."""
    from gastroviewer import http as gv_http
    from gastroviewer.sources.base import SourceError

    async def verboten(self, source: str, url: str, **kw: Any):
        raise SourceError(
            "attrappe",
            f"Die Attrappe hat keinen Netzzugriff — {source} wollte {url} "
            "abrufen. Es fehlt eine Aufzeichnung für diesen Aufruf.")

    for name in ("request", "get_json", "post_json", "get_text",
                 "get_bytes", "post_text"):
        setattr(gv_http.Outbound, name, verboten)


def punkt_ersatz(aufnahme: Aufnahme) -> None:
    """``PointService.point`` aus der Aufzeichnung bedienen.

    Diese Methode steckt hinter „Punkt merken" und „neu prüfen". Ohne sie
    liefen die Prüfungen zu Vergleich, Bericht, Duell und Notizen ins Leere.
    """
    from gastroviewer.service import PointService

    async def point(self, lat: float, lon: float, radius: int,
                    refresh: bool = False) -> dict[str, Any]:
        eintrag, _ = aufnahme.suche("/api/point",
                                    {"lat": lat, "lon": lon, "r": radius})
        if eintrag is None:
            raise RuntimeError(
                "Der Aufzeichnung fehlt /api/point — bitte "
                "scripts/aufzeichnen.py erneut laufen lassen.")
        return json.loads(json.dumps(eintrag["json"]))

    async def gehweg_aus_cache(self, lat: float, lon: float,
                               radius: int) -> None:
        # Gehstrecken werden beim Merken ohnehin nur übernommen, wenn sie
        # schon im Cache liegen — in der Attrappe liegen sie nie.
        return None

    PointService.point = point
    PointService.gehweg_aus_cache = gehweg_aus_cache


def baue_app(aufnahme: Aufnahme):
    from fastapi import Request
    from fastapi.responses import JSONResponse

    from gastroviewer.api import create_app
    from gastroviewer.config import Settings

    ordner = Path(tempfile.mkdtemp(prefix="gastroviewer-attrappe-"))
    app = create_app(Settings(data_dir=ordner))

    @app.middleware("http")
    async def abspielen(request: Request, call_next):
        pfad = request.url.path
        if (request.method == "GET" and pfad.startswith("/api/")
                and not pfad.startswith(ECHT_BELASSEN)):
            eintrag, stufe = aufnahme.suche(pfad, dict(request.query_params))
            if eintrag is not None:
                return JSONResponse(
                    eintrag["json"], status_code=eintrag["status"],
                    headers={"X-Attrappe": stufe})
        return await call_next(request)

    app.state.attrappe_ordner = ordner
    return app


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port", type=int, default=8041)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--aufnahme", type=Path, default=AUFNAHME)
    args = p.parse_args(argv[1:])

    if not args.aufnahme.exists():
        print(f"Aufzeichnung fehlt: {args.aufnahme}\n"
              "Erst einmalig aufnehmen:\n"
              "  gastroviewer serve --port 8031 &\n"
              "  python scripts/aufzeichnen.py http://127.0.0.1:8031")
        return 4

    roh = json.loads(args.aufnahme.read_text(encoding="utf-8"))
    aufnahme = Aufnahme(roh)
    netz_sperren()
    punkt_ersatz(aufnahme)
    app = baue_app(aufnahme)

    print(f"Attrappe auf http://{args.host}:{args.port} — "
          f"{len(aufnahme.eintraege)} aufgezeichnete Antworten, kein Netz.")
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
