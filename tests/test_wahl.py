"""Wahlergebnis BTW 2025 — gegen die echten Open-Data-Auszüge der
Bundeswahlleiterin vom 2026-08-08 (kerg2.csv endgültig, Zuordnungsdatei
Gebietsstand 30.11.2024)."""

from __future__ import annotations

import asyncio

import pytest

from gastroviewer.sources import wahl
from gastroviewer.sources.base import SourceError


@pytest.fixture(scope="module")
def zuordnung(wahl_btw25):
    return wahl.parse_mapping(wahl_btw25["zuordnung"])


@pytest.fixture(scope="module")
def kreise(wahl_btw25):
    return wahl.parse_kerg2(wahl_btw25["kerg2"])


def test_zuordnung_flensburg_ein_wahlkreis(zuordnung):
    assert zuordnung["01001000"] == [
        {"nr": "001", "name": "Flensburg – Schleswig"}]


def test_zuordnung_muenchen_vier_wahlkreise(zuordnung):
    nummern = [w["nr"] for w in zuordnung["09162000"]]
    assert nummern == ["216", "217", "218", "219"]


def test_kerg2_wahlkreis_werte(kreise):
    wk = kreise["001"]
    assert wk["name"] == "Flensburg – Schleswig"
    assert wk["wahlberechtigte"] == 232131
    assert wk["beteiligung_prozent"] == pytest.approx(83.09, abs=0.01)
    spd = next(p for p in wk["parteien"] if p["partei"] == "SPD")
    assert spd["zweitstimmen"] > 0
    assert spd["diff_prozentpunkte"] is not None


def test_auswerten_einzelner_wahlkreis(zuordnung, kreise):
    d = wahl.auswerten(zuordnung, kreise, "01001000")
    assert not d["mehrere_wahlkreise"]
    assert d["parteien"][0]["prozent"] is not None
    # Anteile absteigend sortiert
    st = [p["zweitstimmen"] for p in d["parteien"]]
    assert st == sorted(st, reverse=True)


def test_auswerten_muenchen_summiert_vier_wahlkreise(zuordnung, kreise):
    d = wahl.auswerten(zuordnung, kreise, "09162000")
    assert d["mehrere_wahlkreise"]
    assert len(d["wahlkreise"]) == 4
    erste = d["parteien"][0]
    einzeln = sum(
        next(p["zweitstimmen"] for p in kreise[nr]["parteien"]
             if p["partei"] == erste["partei"])
        for nr in ("216", "217", "218", "219"))
    assert erste["zweitstimmen"] == einzeln
    # Punktdifferenzen sind über Summen nicht bildbar — ehrlich leer.
    assert erste["diff_prozentpunkte"] is None
    assert d["beteiligung_prozent"] is not None


def test_unbekannte_gemeinde_gibt_none(zuordnung, kreise):
    assert wahl.auswerten(zuordnung, kreise, "99999999") is None


def test_format_aenderung_meldet_parsefehler():
    with pytest.raises(SourceError):
        wahl.parse_kerg2("voellig;anderes;format")


def test_load_mit_warnung_und_hinweisen(zuordnung, kreise):
    async def laden():
        return zuordnung, kreise

    res = asyncio.run(wahl.load(None, "09162000", laden))
    assert res.ok
    assert any("4 Wahlkreise" in w for w in res.warnings)
    assert any("kein Kundenprofil" in h for h in res.data["hinweise"])
    assert "dl-de/by-2-0" in res.provenance.license
