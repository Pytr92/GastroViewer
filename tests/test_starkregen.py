"""Starkregen-Hinweiskarte (BKG) — gegen die Live-Antworten vom 18.09.2026."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from gastroviewer.sources import planung, starkregen
from gastroviewer.sources.base import SourceError

DE = Path(__file__).resolve().parent.parent / "fixtures" / "de"
ALEXANDERPLATZ = (52.5219, 13.4132)


def _lies(n):
    return json.loads((DE / n).read_text("utf-8"))


def test_wert_nimmt_groessten_gueltigen_wert_und_ignoriert_nodata():
    assert starkregen.wert(_lies("de_starkregen_r6_tiefe_agw_berlin.json"), "Tiefe") == 39
    assert starkregen.wert(_lies("de_starkregen_r6_tiefe_agw_koeln.json"), "Tiefe") == 0, "-9999 zählt nicht"
    assert starkregen.wert(_lies("de_starkregen_r6_tiefe_agw_dresden.json"), "Tiefe") == 3
    assert starkregen.wert(_lies("de_starkregen_r6_tiefe_agw_isarauen.json"), "Tiefe") is None, "Bayern fehlt im Dienst"
    assert starkregen.wert({"features": [{"properties": {"Tiefe": -9999}}]}, "Tiefe") is None


def test_einordnung():
    assert starkregen.einordnung(None) is None
    assert "Pfützen" in starkregen.einordnung(3)
    assert "Bordstein" in starkregen.einordnung(25)
    assert "Erdgeschosse" in starkregen.einordnung(39)
    assert "Tiefgaragen" in starkregen.einordnung(80)


def test_gfi_params_crs84_json():
    p = starkregen.gfi_params("tiefe_agw", *ALEXANDERPLATZ)
    assert p["crs"] == "CRS:84" and p["info_format"] == "application/json" and p["layers"] == "tiefe_agw"


class _Out:
    def __init__(self, antworten, fehler=False):
        self.antworten, self.fehler, self.layer = antworten, fehler, []

    async def get_json(self, quelle, url, **kw):
        layer = kw["params"]["layers"]
        self.layer.append(layer)
        if self.fehler:
            raise SourceError("timeout", "weg")
        return self.antworten.get(layer) or {"features": []}


def _berlin():
    return {n: _lies(f"de_starkregen_r6_{n}_berlin.json")
            for n in ("tiefe_agw", "tiefe_extrem", "geschwindigkeit_agw", "geschwindigkeit_extrem")}


def test_load_berlin_beide_szenarien():
    out = _Out(_berlin())
    d = asyncio.run(starkregen.load(out, *ALEXANDERPLATZ, "DE-BE"))
    assert d["abgefragt"] and d["kartiert"] and d["land"] == "BE"
    assert d["szenarien"]["agw"]["tiefe_cm"] == 39 and d["szenarien"]["agw"]["kartiert"]
    assert d["szenarien"]["extrem"]["tiefe_cm"] is not None
    assert d["tiefe_max_cm"] >= 39 and "Erdgeschosse" in d["szenarien"]["agw"]["einordnung"]
    assert out.layer == ["tiefe_agw", "geschwindigkeit_agw", "tiefe_extrem", "geschwindigkeit_extrem"]


def test_load_bayern_fragt_nicht():
    out = _Out({})
    d = asyncio.run(starkregen.load(out, 48.1372, 11.5755, "DE-BY"))
    assert d["abgefragt"] is False and "Bayern" in d["hinweis"] and out.layer == []


def test_load_ohne_wert_sagt_es():
    d = asyncio.run(starkregen.load(_Out({}), 51.05, 13.74, "DE-SN"))
    assert d["abgefragt"] and d["kartiert"] is False and "keinen Wert" in d["hinweis"]


def test_planung_bundesweit_traegt_starkregen(monkeypatch):
    """Der Planungsblock (BfG-Pfad) bekommt den Starkregen-Teilblock; ein
    Ausfall des BKG-Dienstes nimmt dem Hochwasser nichts."""
    bfg_xml = (Path(__file__).resolve().parent.parent / "fixtures" / "raw_bfg_hochwasser_koeln_ring.xml")
    xml = bfg_xml.read_text("utf-8") if bfg_xml.exists() else "<FeatureInfoResponse/>"

    class Out(_Out):
        async def get_text(self, quelle, url, **kw):
            return xml

    out = Out(_berlin())
    res = asyncio.run(planung.load(out, None, *ALEXANDERPLATZ, 600, "11"))
    assert res.ok and res.data["hochwasser"]["dienst"] == "bfg"
    assert res.data["starkregen"]["szenarien"]["agw"]["tiefe_cm"] == 39
    kaputt = Out({}, fehler=True)
    res = asyncio.run(planung.load(kaputt, None, *ALEXANDERPLATZ, 600, "11"))
    assert res.ok and res.data["starkregen"] is None
    assert any("Starkregen" in w for w in res.warnings)
