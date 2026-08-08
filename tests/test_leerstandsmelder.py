"""Leerstandsmelder.de — gegen den echten Auszug der API-Antwort vom
2026-08-08 (api.leerstandsmelder.de/api/v1/places, Weltbestand 9 318
Meldungen; Auszug: Umkreis München + Hamburg + Luxemburg)."""

from __future__ import annotations

import asyncio

import pytest

from gastroviewer.sources import leerstandsmelder as lsm
from gastroviewer.sources.base import SourceError


@pytest.fixture(scope="module")
def meldungen(lsm_places):
    return lsm.parse_meldungen(lsm_places["places"])


def test_parse_wandelt_string_koordinaten(meldungen, lsm_places):
    assert len(meldungen) == len(lsm_places["places"]) == 123
    assert all(isinstance(m["lat"], float) for m in meldungen)


def test_sendlinger_tor_naechste_meldung(meldungen):
    d = lsm.aufbereiten(meldungen, 48.1334, 11.5674, 600)
    erste = d["meldungen"][0]
    assert erste["titel"] == "Leerstand am Sendlinger Tor"
    assert erste["distanz_m"] == 127
    assert erste["url"] == (
        "https://leerstandsmelder.de/places/leerstand-am-sendlinger-tor")
    assert erste["im_radius"] is True


def test_umfeldzahlen_sendlinger_tor(meldungen):
    d = lsm.aufbereiten(meldungen, 48.1334, 11.5674, 600)
    assert d["gesamt_im_umfeld"] == 21
    assert d["offen_im_umfeld"] == 21
    assert d["im_radius"] == 8
    assert d["max_distanz_m"] == 1500
    # sortiert nach Entfernung, alles innerhalb der Obergrenze
    dist = [m["distanz_m"] for m in d["meldungen"]]
    assert dist == sorted(dist) and dist[-1] <= 1500


def test_hamburg_sieht_nur_hamburger_meldungen(meldungen):
    d = lsm.aufbereiten(meldungen, 53.55, 10.0, 600)
    assert d["gesamt_im_umfeld"] == 2
    titel = {m["titel"] for m in d["meldungen"]}
    assert "Leerstand am Sendlinger Tor" not in titel


def test_format_aenderung_meldet_parsefehler():
    with pytest.raises(SourceError):
        lsm.parse_meldungen({"kein": "array"})


def test_load_mit_warnungen_am_leeren_ort(meldungen):
    async def laden():
        return meldungen

    res = asyncio.run(lsm.load(51.0, 10.0, 600, laden))  # Mitte Deutschlands
    assert res.ok
    assert res.data["meldungen"] == []
    assert any("Freiwilligen" in w for w in res.warnings)


def test_load_lizenzlage_steht_dran(meldungen):
    async def laden():
        return meldungen

    res = asyncio.run(lsm.load(48.1334, 11.5674, 600, laden))
    assert res.ok and not res.warnings
    assert "Keine maschinenlesbare Datenlizenz" in res.provenance.license
    assert any("keine Datenlizenz" in h for h in res.data["hinweise"])
