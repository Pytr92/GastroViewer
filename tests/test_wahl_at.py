"""Nationalratswahl 2024 (BMI) — gegen die Live-Dateien vom 18.09.2026."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from gastroviewer.sources import wahl_at
from gastroviewer.sources.base import SourceError

AT = Path(__file__).resolve().parent.parent / "fixtures" / "at"


@pytest.fixture(scope="module")
def daten():
    erg = wahl_at.parse_ergebnisse(wahl_at.dekodieren((AT / "nrw2024_ergebnisse.txt").read_bytes()))
    gkz = wahl_at.parse_gkz(wahl_at.dekodieren((AT / "nrw2024_gkz.txt").read_bytes()))
    return erg, gkz


def test_dekodieren_cp1252_und_utf8_bom():
    assert "Ungültige;Gültige;ÖVP;SPÖ;FPÖ" in wahl_at.dekodieren((AT / "nrw2024_ergebnisse.txt").read_bytes())
    g = wahl_at.dekodieren((AT / "nrw2024_gkz.txt").read_bytes())
    assert g.startswith("LAND;RWK;BEZ;GKZ;NAME") and "Kärnten" in g


def test_parse_ergebnisse_und_gkz(daten):
    erg, gkz = daten
    assert len(erg) == 2444 and len(gkz) == 2444
    oe = erg["G00000"]
    assert oe["name"] == "Österreich" and oe["wahlberechtigte"] == 6346059 and oe["gueltige"] == 4882888
    assert [p["partei"] for p in oe["parteien"]][:5] == ["ÖVP", "SPÖ", "FPÖ", "GRÜNE", "NEOS"]
    assert next(p for p in oe["parteien"] if p["partei"] == "FPÖ")["stimmen"] == 1408514
    assert all(p["partei"].lower() not in wahl_at.NICHT_PARTEI for p in oe["parteien"])


def test_ist_gemeinde():
    assert wahl_at.ist_gemeinde("G30101") and wahl_at.ist_gemeinde("G90000") is False
    assert not wahl_at.ist_gemeinde("G30100") and not wahl_at.ist_gemeinde("G3B000")
    assert not wahl_at.ist_gemeinde("G30199")


def test_finde_gebiet_gemeinden_und_rueckfall(daten):
    _, gkz = daten
    assert wahl_at.finde_gebiet(gkz, "9", "Wien")[0]["gkz"] == "G90000"
    assert wahl_at.finde_gebiet(gkz, "3", "Krems an der Donau") == (
        {"land": "3", "rwk": "3B", "bez": "301", "gkz": "G30101", "name": "Krems an der Donau"}, "Gemeinde")
    assert wahl_at.finde_gebiet(gkz, "3", "Sankt Pölten")[0]["name"] == "St. Pölten"
    assert wahl_at.finde_gebiet(gkz, "2", "Klagenfurt am Wörthersee")[0]["gkz"] == "G20101"
    geb, ebene = wahl_at.finde_gebiet(gkz, "3", "Gibt es nicht")
    assert geb["gkz"] == "G30000" and ebene == "Bundesland"
    assert wahl_at.finde_gebiet(gkz, "3", None)[1] == "Bundesland"


def test_auswerten_wien(daten):
    erg, gkz = daten
    geb, ebene = wahl_at.finde_gebiet(gkz, "9", "Wien")
    a = wahl_at.auswerten(erg, geb, ebene)
    assert a["wahl"] == "Nationalratswahl 29.09.2024" and a["ebene"] == "Gemeinde"
    assert a["stimmen_label"] == "Stimmen" and a["mehrere_wahlkreise"] is False
    assert a["beteiligung_prozent"] == 71.9
    assert [(p["partei"], p["prozent"]) for p in a["parteien"][:3]] == [("SPÖ", 29.9), ("FPÖ", 20.7), ("ÖVP", 17.4)]
    assert all(p["diff_prozentpunkte"] is None for p in a["parteien"])
    assert len(a["parteien"]) == 8


def test_load_mit_adresse_und_ohne(daten):
    async def laden():
        return daten

    res = asyncio.run(wahl_at.load({"gemeinde": "Graz", "bundesland_iso": "AT-6"}, laden))
    assert res.ok and res.data["wahlkreise"][0]["name"] == "Graz" and not res.warnings
    res = asyncio.run(wahl_at.load({"gemeinde": "Nirgendwo", "bundesland_iso": "AT-6"}, laden))
    assert res.ok and res.data["ebene"] == "Bundesland" and any("Landesergebnis" in w for w in res.warnings)
    res = asyncio.run(wahl_at.load({"gemeinde": "Graz"}, laden))
    assert res.ok and res.data is None

    async def kaputt():
        raise SourceError("timeout", "weg")

    res = asyncio.run(wahl_at.load({"bundesland_iso": "AT-6"}, kaputt))
    assert res.ok is False and res.error["kind"] == "timeout"
