"""Gastro-Dynamik aus der OSM-Historie (ohsome-API des HeiGIT Heidelberg).

Der OSM-Block zeigt eine Momentaufnahme; dieser Block beantwortet die andere
Frage: **wächst die Gastro-Lage oder stirbt sie?** Die ohsome-API wertet die
volle OSM-Historie aus und liefert die Zahl der Gastro-Objekte zu beliebigen
Zeitpunkten — hier als Jahresreihe, jeweils zum 1. Januar.

Phase-0 verifiziert am 2026-08-04:
``POST https://api.ohsome.org/v1/elements/count`` mit ``bcircles`` (lon,lat,r),
``filter`` und ``time`` (ISO-Intervall mit Periode) — ohne Konto, ohne
Schlüssel. Marienplatz r=600: 326 (2019) → 369 (2026) Gastro-Objekte.

Die eine ehrliche Grenze, die über allem steht: die Kurve misst die
**OSM-Datenbank**, nicht direkt die Wirklichkeit. Ein Anstieg kann echte
Neueröffnungen zeigen — oder fleißigere Kartierer. Als Trend über mehrere
Jahre ist sie brauchbar, als Absolutzahl je Jahr nicht. Deshalb wird die
Reihe zusammen mit dieser Warnung ausgegeben, und es gibt keine
Prozent-Schlagzeile ohne die Rohreihe daneben.
"""

from __future__ import annotations

import time
from typing import Any

from ..config import Settings
from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, now_iso
from .overpass import GASTRO_AMENITIES

LIZENZ = (
    "© OpenStreetMap-Mitwirkende · Auswertung über die ohsome-API "
    "(HeiGIT gGmbH, Heidelberg)"
)

# Dieselben acht amenity-Typen wie im OSM-Block — damit sich Momentaufnahme
# und Zeitreihe auf denselben Gastronomiebegriff beziehen.
GASTRO_FILTER = "amenity in (" + ", ".join(GASTRO_AMENITIES) + ")"
SCHNELL_FILTER = "amenity=fast_food"

# Sieben Jahre zurück: lang genug für einen Trend, kurz genug, dass die
# OSM-Abdeckung am Anfang der Reihe nicht völlig anders war als heute.
# Ein gewählter Wert, kein Messwert.
JAHRE_ZURUECK = 7


def zeitraum(jahr_heute: int) -> str:
    return f"{jahr_heute - JAHRE_ZURUECK}-01-01/{jahr_heute}-01-01/P1Y"


def parse_reihe(payload: Any) -> list[dict[str, int]]:
    """ohsome liefert ``result: [{timestamp, value}]`` — Werte sind Floats,
    zählen aber Objekte; sie werden als Ganzzahl übernommen."""
    out: list[dict[str, int]] = []
    for r in (payload or {}).get("result") or []:
        ts, v = r.get("timestamp"), r.get("value")
        if not ts or v is None:
            continue
        out.append({"jahr": int(str(ts)[:4]), "anzahl": int(round(float(v)))})
    return out


def auswerten(
    gastro: list[dict[str, int]], schnell: list[dict[str, int]]
) -> dict[str, Any]:
    schnell_je_jahr = {r["jahr"]: r["anzahl"] for r in schnell}
    reihe = [
        {
            "jahr": r["jahr"],
            "gastro": r["anzahl"],
            "schnellgastronomie": schnell_je_jahr.get(r["jahr"]),
        }
        for r in gastro
    ]

    veraenderung = None
    if len(gastro) >= 2:
        erst, letzt = gastro[0], gastro[-1]
        absolut = letzt["anzahl"] - erst["anzahl"]
        veraenderung = {
            "von_jahr": erst["jahr"],
            "bis_jahr": letzt["jahr"],
            "von": erst["anzahl"],
            "bis": letzt["anzahl"],
            "absolut": absolut,
            "prozent": (
                round(absolut / erst["anzahl"] * 100, 1) if erst["anzahl"] else None
            ),
        }

    return {
        "reihe": reihe,
        "veraenderung": veraenderung,
        "stichtag": "jeweils 1. Januar",
        "hinweise": [
            "Die Reihe zählt Objekte in der OSM-Datenbank, nicht Betriebe in "
            "der Wirklichkeit. Ein Anstieg kann Neueröffnungen zeigen — oder "
            "fleißigere Kartierer. Als Mehrjahres-Trend brauchbar, als "
            "Absolutzahl je Jahr nicht.",
            "Schließungen erscheinen nur, wenn jemand sie in OSM einträgt. "
            "Die Reihe unterschätzt Fluktuation systematisch.",
        ],
    }


async def load(
    out: Outbound, settings: Settings, lat: float, lon: float, radius: int
) -> SourceResult:
    started = time.perf_counter()
    jahr_heute = time.gmtime().tm_year
    t = zeitraum(jahr_heute)

    async def reihe(filter_: str) -> list[dict[str, int]]:
        payload = await out.post_json(
            "dynamik",
            f"{settings.ohsome_base}/elements/count",
            data={
                "bcircles": f"{lon},{lat},{radius}",
                "filter": filter_,
                "time": t,
            },
            timeout=settings.zensus_timeout,
        )
        if isinstance(payload, dict) and payload.get("error"):
            raise SourceError(
                "api_error",
                f"ohsome meldet: {payload.get('message') or payload.get('error')}",
            )
        return parse_reihe(payload)

    try:
        gastro = await reihe(GASTRO_FILTER)
        schnell = await reihe(SCHNELL_FILTER)
    except SourceError as err:
        return SourceResult.failed(
            "dynamik", err, int((time.perf_counter() - started) * 1000)
        )

    warnungen: list[str] = []
    if not gastro:
        warnungen.append(
            "Die ohsome-API hat keine Zeitreihe geliefert — der Block bleibt leer."
        )

    data = auswerten(gastro, schnell)
    return SourceResult(
        name="dynamik",
        ok=True,
        data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnungen,
        provenance=Provenance(
            source="OSM-Historie über die ohsome-API (HeiGIT Heidelberg)",
            license=LIZENZ,
            endpoint=f"{settings.ohsome_base}/elements/count",
            stand=f"Jahreswerte {t.split('/')[0][:4]}–{jahr_heute}, jeweils 1. Januar",
            retrieved_at=now_iso(),
            note=(
                "Zeitreihe über die OSM-Datenbank, nicht über die Wirklichkeit: "
                "Kartier-Aktivität und echte Entwicklung sind darin nicht "
                "trennbar. Gleicher Gastronomiebegriff wie im OSM-Block."
            ),
        ),
    )
