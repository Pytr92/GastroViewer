#!/usr/bin/env python3
"""Hilfsskript für die Abnahmeprüfung §7.6.

Startet die Anwendung mit einem absichtlich toten Overpass-Endpunkt und gibt als
JSON zurück, wie sich die Blöcke verhalten. Läuft in einem eigenen Prozess, damit
die kaputte Konfiguration den laufenden Server nicht berührt.
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile

# Auch lauffähig, wenn das Paket nicht installiert ist (`pip install -e .` fehlt).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from gastroviewer.api import create_app  # noqa: E402
from gastroviewer.config import Settings  # noqa: E402

s = Settings()
s.data_dir = pathlib.Path(tempfile.mkdtemp(prefix="gv-ausfall-"))
s.overpass_endpoints = ("http://127.0.0.1:9/tot",)  # Port 9 = discard, nimmt nichts an
s.overpass_timeout = 3

# Der Lifespan muss laufen, sonst gibt es keinen initialisierten Dienst.
with TestClient(create_app(s)) as c:
    d = c.get("/api/point", params={"lat": 48.1334, "lon": 11.5674, "r": 600}).json()

print(
    json.dumps(
        {
            "osm_ok": d["bloecke"]["osm"]["ok"],
            "osm_fehler": (d["bloecke"]["osm"]["error"] or {}).get("message"),
            "zensus_ok": d["bloecke"]["zensus"]["ok"],
            "zellen": (d["bloecke"]["zensus"]["data"] or {}).get("zellen_gefunden"),
            "gemeinde": d["punkt"]["gemeinde"],
            "http_status": 200,
        },
        ensure_ascii=False,
    )
)
