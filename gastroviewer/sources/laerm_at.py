"""Umgebungslärm Österreich — lärminfo.at (BMK/Umweltbundesamt, Betrieb LFRZ).

Gegenstück zum UBA-Pfad in ``laerm.py``: Lärmzonen der EU-Umgebungslärm-
kartierung 2022 als 5-dB-Klassen, Straße und Schiene, Lden und Lnight.
Dieselbe Blockform (``dienst``, ``lden``, ``lnight`` mit ``klasse``,
``von_db``, ``bis_db``, ``kartierung``, ``weitere_quellen``, ``kartiert``).

Live belegt am 18.09.2026 (fixtures/at, AT-Probe): OGC API – Features
unter ``https://gis.lfrz.gv.at/api/geodata/i000804/ogc/features/v1``,
Collections ``i000804:laerm_2022_strasse_lden`` (und ``…_lnight``,
``…_schiene_lden``, ``…_schiene_lnight``), ``items?bbox=…&limit=…&f=json``
liefert GeoJSON-Polygone (CRS84) mit ``category`` (``Lden5559``,
``Lden6064`` … ``LdenGreaterThan75``; ``Lnight5054`` … ``LnightGreaterThan70``)
und ``source`` (``majorRoadsIncludingAgglomeration``). Am Stephansplatz
antwortet die Straßenschicht mit 68 Polygonen im 400-m-Kasten, an der A23
mit 23 — die Zone am Punkt ist die, deren Polygon ihn enthält.
"""

from __future__ import annotations

import re
import time
from typing import Any

from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, now_iso
from .zensus import _point_in_ring

BASIS = "https://gis.lfrz.gv.at/api/geodata/i000804/ogc/features/v1/collections"
LICENSE = ("lärminfo.at — BMK / Umweltbundesamt / LFRZ, INSPIRE-Umgebungslärm; "
           "Creative Commons Namensnennung 4.0 (CC BY 4.0, data.gv.at)")
KARTIERUNG = 2022
SCHICHTEN = {
    "strasse": {"lden": "i000804:laerm_2022_strasse_lden", "lnight": "i000804:laerm_2022_strasse_lnight"},
    "schiene": {"lden": "i000804:laerm_2022_schiene_lden", "lnight": "i000804:laerm_2022_schiene_lnight"},
}
BOX = 0.0006  # Grad, rund 50 m — der Kasten muss das Polygon am Punkt treffen
HINWEISE = [
    "Berechnete Pegel aus der EU-Umgebungslärmkartierung (Runde 2022): "
    "Hauptverkehrsstraßen, Ballungsräume und Haupteisenbahnstrecken — "
    "keine Messung, keine Nebenstraßen. Außerhalb der kartierten Zonen "
    "heißt „nicht kartiert“ nicht „leise“.",
    "Lden ist der Tag-Abend-Nacht-Pegel, Lnight der Nachtpegel (22–6 Uhr); "
    "die Karte führt 5-dB-Klassen, keinen Punktwert.",
]

_KLASSE = re.compile(r"^(Lden|Lnight)(?:(\d{2})(\d{2})|GreaterThan(\d{2}))$")


def klasse(category: str | None) -> dict[str, Any] | None:
    """``Lden5559`` → 55–59 dB(A); ``LdenGreaterThan75`` → über 75 dB(A)."""
    m = _KLASSE.match(str(category or ""))
    if not m:
        return None
    if m.group(4):
        von = int(m.group(4))
        return {"klasse": f"über {von} dB(A)", "von_db": von, "bis_db": None}
    von, bis = int(m.group(2)), int(m.group(3))
    return {"klasse": f"{von}–{bis} dB(A)", "von_db": von, "bis_db": bis}


def zone_am_punkt(features: list[dict[str, Any]], lat: float, lon: float) -> dict[str, Any] | None:
    """Das Polygon, das den Punkt enthält (äußerer Ring minus Löcher); bei
    mehreren die lauteste Klasse — Zonen überlappen an Kanten."""
    treffer = []
    for f in features:
        g = f.get("geometry") or {}
        polys = [g["coordinates"]] if g.get("type") == "Polygon" else (
            g.get("coordinates") or [] if g.get("type") == "MultiPolygon" else [])
        for poly in polys:
            if not poly or not _point_in_ring(lat, lon, poly[0]):
                continue
            if any(_point_in_ring(lat, lon, loch) for loch in poly[1:]):
                continue
            k = klasse((f.get("properties") or {}).get("category"))
            if k:
                treffer.append({**k, "quelle": (f.get("properties") or {}).get("source")})
            break
    if not treffer:
        return None
    return max(treffer, key=lambda t: t["von_db"])


async def load(out: Outbound, lat: float, lon: float) -> SourceResult:
    started = time.perf_counter()
    bbox = f"{lon - BOX},{lat - BOX},{lon + BOX},{lat + BOX}"

    async def zonen(cid: str) -> list[dict[str, Any]]:
        antwort = await out.get_json(
            "laerm_at", f"{BASIS}/{cid}/items",
            params={"f": "json", "bbox": bbox, "limit": 50},
            timeout=45.0, limiter="laerminfo", min_interval=0.5)
        return (antwort or {}).get("features") or [] if isinstance(antwort, dict) else []

    ergebnis: dict[str, dict[str, Any]] = {}
    fehler: list[str] = []
    for quelle, schichten in SCHICHTEN.items():
        for art, cid in schichten.items():
            try:
                ergebnis[f"{quelle}_{art}"] = zone_am_punkt(await zonen(cid), lat, lon) or {}
            except SourceError as err:
                fehler.append(f"{quelle} {art}: {err.message}")
                ergebnis[f"{quelle}_{art}"] = {}
    if len(fehler) == 4:
        return SourceResult.failed(
            "laerm", SourceError("api_error", "lärminfo.at nicht erreichbar: " + fehler[0]),
            int((time.perf_counter() - started) * 1000))

    def pegel(art: str) -> dict[str, Any]:
        s = ergebnis.get(f"strasse_{art}") or {}
        return {"wert_db": None, "klasse": s.get("klasse"), "kartierung": KARTIERUNG,
                "abdeckung": "Hauptverkehrsstraßen und Ballungsräume (Runde 2022)",
                "von_db": s.get("von_db"), "bis_db": s.get("bis_db")}

    weitere = {}
    for art in ("lden", "lnight"):
        s = ergebnis.get(f"schiene_{art}") or {}
        if s.get("klasse"):
            weitere[f"Schiene {art.capitalize()}"] = s["klasse"]
    lden, lnight = pegel("lden"), pegel("lnight")
    kartiert = lden["klasse"] is not None or lnight["klasse"] is not None
    return SourceResult(
        name="laerm", ok=True,
        data={"dienst": "laerminfo", "lden": lden, "lnight": lnight,
              "weitere_quellen": weitere, "kartiert": kartiert,
              "hinweise": HINWEISE + (
                  ["Am Punkt liegt keine kartierte Straßen-Lärmzone — er liegt "
                   "abseits der Hauptverkehrsstraßen, oder die Zone endet davor."]
                  if not kartiert else [])},
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=fehler,
        provenance=Provenance(
            source="lärminfo.at — Umgebungslärmkartierung Österreich (BMK, Umweltbundesamt, LFRZ)",
            license=LICENSE, endpoint=BASIS, stand=f"Kartierungsrunde {KARTIERUNG}",
            retrieved_at=now_iso(),
            note="OGC API Features, Polygon am Punkt (Lden/Lnight in 5-dB-Klassen).",
        ),
    )
