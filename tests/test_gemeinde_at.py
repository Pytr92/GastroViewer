"""Gemeindeprofil Österreich — gegen den Auszug der Statistik-Austria-Tabelle
(Live 18.09.2026, Jahre 2011 und 2019–2021)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from gastroviewer.sources import gemeinde_at
from gastroviewer.sources.base import SourceError

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
