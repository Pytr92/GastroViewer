"""Luftqualität (UBA-Luftmessnetz) — gegen die echten API-Antworten vom
2026-08-08 (Stationsliste und Tageswerte der Station 471,
DEBY037 München/Stachus)."""

from __future__ import annotations

import asyncio

import pytest

from gastroviewer.sources import luft
from gastroviewer.sources.base import SourceError


@pytest.fixture(scope="module")
def stationen(uba_luft_api):
    return luft.parse_stationen(uba_luft_api["stations"])


def test_stationsliste_mit_koordinaten(stationen):
    assert len(stationen) == 41
    stachus = next(s for s in stationen if s["code"] == "DEBY037")
    assert stachus["name"] == "München/Stachus"
    assert stachus["id"] == "471"
    assert abs(stachus["lat"] - 48.1373) < 0.001


def test_naechste_station_am_sendlinger_tor(stationen):
    nah = luft.naechste_stationen(stationen, 48.1334, 11.5674)
    assert nah[0]["code"] == "DEBY037", "Stachus ist die nächste Station"
    assert nah[0]["distanz_m"] < 1000
    assert len(nah) == 3


def test_aktuellster_eintrag_mit_indexskala(uba_luft_api):
    e = luft.aktuellster_eintrag(uba_luft_api["airquality"], "471")
    assert e is not None
    # Echter Stundenwert vom 2026-08-08: Gesamtindex 0 = „sehr gut",
    # NO₂ 13 µg/m³ mit Teilindex 0 — Beleg für die 0-basierte Skala.
    assert e["index"] == 0
    assert e["index_label"] == "sehr gut"
    no2 = next(k for k in e["komponenten"] if k["komponente"] == "NO₂")
    assert no2["wert"] == 13
    assert no2["teilindex_label"] == "sehr gut"


def test_format_aenderung_meldet_parsefehler():
    with pytest.raises(SourceError):
        luft.parse_stationen({"kein": "data"})


def test_load_faellt_auf_naechste_station_zurueck(stationen, uba_luft_api):
    class Out:
        def __init__(self):
            self.stationen_gefragt = []

        async def get_json(self, source, url, **kw):
            sid = (kw.get("params") or {}).get("station")
            self.stationen_gefragt.append(sid)
            if sid == "471":
                # Stachus liefert gerade nichts — Rückfall nötig.
                return {"data": {}}
            return {"data": {sid: uba_luft_api["airquality"]["data"]["471"]}}

    async def laden():
        return stationen

    out = Out()
    res = asyncio.run(luft.load(out, 48.1334, 11.5674, laden))
    assert res.ok and res.data is not None
    assert out.stationen_gefragt[0] == "471"
    assert res.data["station"]["code"] != "DEBY037"
    assert any("nächste Station" in w for w in res.warnings)


def test_load_ohne_station_in_reichweite(stationen):
    async def laden():
        return stationen

    class Nie:
        async def get_json(self, *a, **k):  # pragma: no cover
            raise AssertionError("ohne Station kein Abruf")

    # Flensburg liegt weit weg von allen bayerischen Fixture-Stationen.
    res = asyncio.run(luft.load(Nie(), 54.78, 9.43, laden))
    assert res.ok and res.data is None
    assert any("Messnetz" in w for w in res.warnings)
