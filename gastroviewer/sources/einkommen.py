"""Verfügbares Einkommen je Einwohner — die ehrliche Kaufkraft-Näherung.

Kleinräumige Kaufkraft ist ein kommerzielles Datenprodukt (GfK/NIQ); jede
„freie" Zahl dazu wäre erfunden. Was es amtlich und frei gibt, ist das
**verfügbare Einkommen der privaten Haushalte je Einwohner auf Kreisebene**
aus den Volkswirtschaftlichen Gesamtrechnungen der Länder (VGRdL) — hier
abgefragt über den Kartendienst des Regionalatlas Deutschland der
Statistischen Ämter.

Geprüft am 02.08.2026 (Phase-0-Stil, dokumentiert in
``docs/funktionen-und-vergleich.md`` und im Commit):

* Der zuerst angepeilte Weg — die experimentellen Passantenfrequenzen von
  Destatis — ist **tot**: zum 31.12.2025 eingestellt, keine Datendateien mehr.
* Der Regionalatlas läuft auf einem ArcGIS-Server der IT.NRW
  (``gis-idmz.nrw.de``); die Indikatortabellen sind über ``dynamicLayer``
  direkt abfragbar (Tabelle ``regionalatlas.ai016_1``, Feld ``ai1601``).
* Live-Gegenprobe: Deutschland 25.830 €, Bayern 28.643 €, München (Stadt)
  35.467 €, Landkreis München 35.832 € — Datenjahr 2022, deckungsgleich mit
  den VGRdL-Veröffentlichungen.

Die Grenze steht in jeder Antwort: es ist ein **Kreiswert**. Innerhalb einer
Großstadt unterscheidet er keine Viertel — dafür sind Nettokaltmiete und
Eigentümerquote aus dem Zensus die kleinräumigen Anzeiger.
"""

from __future__ import annotations

import json
import time
from typing import Any

from ..config import Settings
from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, now_iso

LICENSE = (
    "© Statistische Ämter des Bundes und der Länder · "
    "Datenlizenz Deutschland – Namensnennung – Version 2.0"
)

# Dynamische Tabellenquelle des Regionalatlas (siehe Modulkopf).
TABELLE = "regionalatlas.ai016_1"
FELD = "ai1601"


def _layer_json() -> str:
    return json.dumps({
        "source": {
            "type": "dataLayer",
            "dataSource": {
                "type": "table",
                "workspaceId": "gdb",
                "dataSourceName": TABELLE,
            },
        }
    })


def kreis_aus_ags(ags: str | None) -> str | None:
    """Kreisschlüssel = erste 5 Stellen des Gemeindeschlüssels."""
    if not ags:
        return None
    a = "".join(c for c in str(ags) if c.isdigit())
    return a[:5] if len(a) >= 5 else None


def auswerten(payload: dict[str, Any], kreis: str, land: str) -> dict[str, Any] | None:
    """Nimmt je Gebiet das jüngste gemeinsame Jahr — kein Mittel, kein Modell."""
    zeilen: dict[str, dict[int, dict[str, Any]]] = {}
    for f in payload.get("features", []):
        a = f.get("attributes") or {}
        ags2 = str(a.get("ags2") or "").strip()
        jahr = a.get("jahr2")
        if not ags2 or not isinstance(jahr, int) or a.get(FELD) is None:
            continue
        zeilen.setdefault(ags2, {})[jahr] = a

    if kreis not in zeilen:
        return None
    gemeinsame = set(zeilen[kreis])
    for schluessel in (land, "DG"):
        if schluessel in zeilen:
            gemeinsame &= set(zeilen[schluessel])
    if not gemeinsame:
        gemeinsame = set(zeilen[kreis])
    jahr = max(gemeinsame)

    def gebiet(schluessel: str) -> dict[str, Any] | None:
        a = zeilen.get(schluessel, {}).get(jahr)
        if a is None:
            return None
        return {
            "ags": schluessel,
            "name": str(a.get("gen2") or "").strip(),
            "wert_eur": a.get(FELD),
        }

    verlauf = [
        {"jahr": j, "wert_eur": a.get(FELD)}
        for j, a in sorted(zeilen[kreis].items())
    ]
    return {
        "jahr": jahr,
        "kreis": gebiet(kreis),
        "land": gebiet(land),
        "bund": gebiet("DG"),
        "verlauf_kreis": verlauf[-10:],
    }


async def load(
    out: Outbound, settings: Settings, ags: str
) -> SourceResult:
    started = time.perf_counter()
    kreis = kreis_aus_ags(ags)
    if kreis is None:
        return SourceResult(
            name="einkommen", ok=True, data=None,
            warnings=["Ohne Gemeindeschlüssel lässt sich kein Kreiswert zuordnen."],
        )
    land = kreis[:2]

    url = f"{settings.regionalatlas_base}/dynamicLayer/query"
    form = {
        "layer": _layer_json(),
        "where": f"ags2 IN ('{kreis}','{land}','DG')",
        "outFields": "*",
        "returnGeometry": "false",
        "f": "json",
    }
    try:
        payload = await out.post_json(
            "einkommen", url, data=form, timeout=settings.zensus_timeout
        )
    except SourceError as err:
        return SourceResult.failed(
            "einkommen", err, int((time.perf_counter() - started) * 1000)
        )
    if isinstance(payload, dict) and "error" in payload:
        err = payload["error"]
        return SourceResult.failed(
            "einkommen",
            SourceError("api_error",
                        f"Regionalatlas meldet Fehler {err.get('code')}: "
                        f"{err.get('message')}"),
            int((time.perf_counter() - started) * 1000),
        )

    data = auswerten(payload if isinstance(payload, dict) else {}, kreis, land)
    warnings: list[str] = []
    if data is None:
        warnings.append(
            f"Für den Kreisschlüssel {kreis} liefert der Regionalatlas keinen "
            "Einkommenswert."
        )
    return SourceResult(
        name="einkommen",
        ok=True,
        data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnings,
        provenance=Provenance(
            source=(
                "Regionalatlas Deutschland — Volkswirtschaftliche "
                "Gesamtrechnungen der Länder (VGRdL)"
            ),
            license=LICENSE,
            endpoint=url,
            stand=f"Berechnungsstand {data['jahr']}" if data else None,
            retrieved_at=now_iso(),
            note=(
                "Kreiswert — innerhalb einer Großstadt unterscheidet er keine "
                "Viertel. Verfügbares Einkommen nach VGRdL, kein Kaufkraftindex."
            ),
        ),
    )
