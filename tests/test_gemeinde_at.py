"""Gemeindeprofil Österreich — gegen den Auszug der Statistik-Austria-Tabelle
(Live 18.09.2026, Jahre 2011 und 2019–2021)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from gastroviewer.sources import gemeinde_at
from gastroviewer.sources.base import SourceError

WURZEL = Path(__file__).resolve().parent.parent / "fixtures" / "at"

AT = Path(__file__).resolve().parent.parent / "fixtures" / "at"


@pytest.fixture(scope="module")
def daten():
    return gemeinde_at.reduzieren((AT / "stat_OGDEXT_AEST_GEMTAB_1_auszug.csv").read_text("utf-8"))


def test_reduzieren_gemeinden_und_aggregate(daten):
    g = daten["gemeinden"]
    assert len(g) > 2000 and g["60101"]["name"] == "Graz" and g["60101"]["land"] == "6"
    assert g["90101"]["name"] == "Wien-Innere Stadt" and g["90101"]["land"] == "9"
    graz = g["60101"]["jahre"]["2020"]
    assert graz["BEV_ABSOLUT"] > 280000 and 0 < graz["ALQ_15PLUS"] < 20
    agg = daten["aggregate"]
    assert set(agg) >= {"1", "2", "3", "4", "5", "6", "7", "8", "9", "AT"}
    at2020 = agg["AT"]["2020"]
    assert 8_500_000 < at2020["BEV_ABSOLUT"] < 9_500_000, "Summe aller Gemeinden ≈ Österreich"
    assert 10 < at2020["BEV_UNTER15"] < 20 and 1.5 < at2020["HH_SIZE"] < 3
    wien2020 = agg["9"]["2020"]
    assert 1_800_000 < wien2020["BEV_ABSOLUT"] < 2_100_000


def test_finde_gemeinde(daten):
    assert gemeinde_at.finde_gemeinde(daten, "6", "Graz") == "60101"
    assert gemeinde_at.finde_gemeinde(daten, "3", "Krems an der Donau") == "30101"
    assert gemeinde_at.finde_gemeinde(daten, "4", "Linz") == "40101"
    assert gemeinde_at.finde_gemeinde(daten, "9", "Wien", "Innere Stadt") == "90101"
    assert gemeinde_at.finde_gemeinde(daten, "9", "Wien", "Leopoldstadt") == "90201"
    assert gemeinde_at.finde_gemeinde(daten, "9", "Wien", None) is None
    assert gemeinde_at.finde_gemeinde(daten, "3", "Gibt es nicht") is None


def test_auswerten_graz_hat_blockform(daten):
    d = gemeinde_at.auswerten(daten, "6", "60101", "Steiermark")
    assert d["gebiete"]["kreis"]["name"] == "Graz" and d["gebiete"]["land"]["name"] == "Steiermark"
    assert d["gebiete"]["bund"]["name"] == "Österreich" and d["gebiete"]["kreis"]["ebene"] == "Gemeinde"
    schl = {i["schluessel"]: i for i in d["indikatoren"]}
    assert schl["einwohner"]["kreis"] > 280000 and schl["einwohner"]["bund"] > 8_500_000
    assert schl["einwohner"]["land"] < schl["einwohner"]["bund"]
    assert schl["arbeitslosenquote"]["einheit"] == "%" and schl["arbeitslosenquote"]["land"] is not None
    assert schl["et_je_1000_ew"]["kreis"] > 500, "Graz hat viele Arbeitsplätze je Einwohner"
    assert [r["jahr"] for r in schl["einwohner"]["reihe"]] == sorted(r["jahr"] for r in schl["einwohner"]["reihe"])
    assert d["jahr"] in (2020, 2021)
    themen = [i["thema"] for i in d["indikatoren"]]
    assert themen == sorted(themen, key=["Bevölkerung", "Arbeit", "Bildung", "Wirtschaft"].index)


def test_auswerten_landeswert_ohne_gemeinde(daten):
    d = gemeinde_at.auswerten(daten, "3", None, "Niederösterreich")
    assert d["gebiete"]["kreis"]["name"].startswith("Niederösterreich") and d["gebiete"]["kreis"]["gkz"] is None
    schl = {i["schluessel"]: i for i in d["indikatoren"]}
    assert schl["einwohner"]["kreis"] == schl["einwohner"]["land"]


def test_load_wien_innere_stadt(daten):
    async def laden():
        return daten

    res = asyncio.run(gemeinde_at.load({"bundesland_iso": "AT-9", "gemeinde": "Wien", "ortsteil": "Innere Stadt"}, laden))
    assert res.ok and res.data["gebiete"]["kreis"]["name"] == "Wien-Innere Stadt"
    assert res.data["gebiete"]["kreis"]["ebene"] == "Gemeindebezirk"
    assert not any("nicht eindeutig" in w for w in res.warnings)
    res = asyncio.run(gemeinde_at.load({"bundesland_iso": "AT-3", "gemeinde": "Nirgendwo"}, laden))
    assert res.ok and any("Landeswert" in w for w in res.warnings)
    assert asyncio.run(gemeinde_at.load({"gemeinde": "Graz"}, laden)).data is None

    async def kaputt():
        raise SourceError("timeout", "weg")

    assert asyncio.run(gemeinde_at.load({"bundesland_iso": "AT-6"}, kaputt)).ok is False


def test_gkz_am_punkt_ueber_geodata():
    """Runde 6: Punktkasten am Stephansplatz liefert zwei Gemeindebezirke,
    Punkt-in-Fläche entscheidet für 90101; Graz und Krems eindeutig."""
    from gastroviewer.sources.base import SourceError

    class Out:
        def __init__(self, payload):
            self.payload, self.params = payload, None

        async def get_json(self, source, url, params=None, **kw):
            self.params = params
            if self.payload is None:
                raise SourceError("timeout", "x")
            return self.payload

    lies = lambda n: json.loads((WURZEL / n).read_text("utf-8"))  # noqa: E731
    out = Out(lies("stat_r6_gem_stephansplatz.json"))
    assert asyncio.run(gemeinde_at.gkz_am_punkt(out, 48.2082, 16.3738)) == {"gkz": "90101", "name": "Wien-Innere Stadt"}
    assert out.params["typeName"].startswith("GEODATA:STATISTIK_AUSTRIA_GEM_") and "EPSG:4326" in out.params["bbox"]
    assert asyncio.run(gemeinde_at.gkz_am_punkt(Out(lies("stat_r6_gem_graz.json")), 47.0707, 15.4395))["gkz"] == "60101"
    assert asyncio.run(gemeinde_at.gkz_am_punkt(Out(lies("stat_r6_gem_krems.json")), 48.4100, 15.6140))["gkz"] == "30101"
    assert asyncio.run(gemeinde_at.gkz_am_punkt(Out({"features": []}), 48.2, 16.3)) is None


def test_load_mit_gkz_hat_vorrang_vor_dem_namen(daten):
    async def laden():
        return daten

    # Adresse nennt einen falschen Ortsteil — die GKZ vom WFS gewinnt.
    res = asyncio.run(gemeinde_at.load({"bundesland_iso": "AT-9", "gemeinde": "Wien", "ortsteil": "Nirgendwo"},
                                       laden, gkz="90101"))
    assert res.ok and res.data["gebiete"]["kreis"]["gkz"] == "90101"
    assert not any("nicht eindeutig" in w for w in res.warnings)
    assert res.data["zuordnung"] == "Gemeindegrenzen-WFS"
    # Ohne Bundesland in der Adresse reicht die GKZ (erste Ziffer = Land).
    res = asyncio.run(gemeinde_at.load({}, laden, gkz="90101"))
    assert res.ok and res.data["gebiete"]["land"]["name"] == "Wien"
    # Unbekannte GKZ (nicht in der Tabelle) → Namenssuche wie bisher.
    res = asyncio.run(gemeinde_at.load({"bundesland_iso": "AT-9", "gemeinde": "Wien", "ortsteil": "Innere Stadt"},
                                       laden, gkz="99999"))
    assert res.ok and res.data["gebiete"]["kreis"]["gkz"] == "90101" and res.data["zuordnung"] == "Name aus der Adresse"
