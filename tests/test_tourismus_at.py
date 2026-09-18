"""Nächtigungsstatistik Österreich — gegen den Live-Ausschnitt vom 18.09.2026."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from gastroviewer.sources import tourismus_at
from gastroviewer.sources.base import SourceError

AT = Path(__file__).resolve().parent.parent / "fixtures" / "at"


@pytest.fixture(scope="module")
def herkunft():
    return tourismus_at.herkunft_lesen((AT / "stat_OGD_touextsai_Tour_HKL_1_C-C93-2.txt").read_text("utf-8"))


def test_herkunft_inland_sind_wien_und_bundeslaender(herkunft):
    inland, alle = herkunft
    assert len(alle) == 87 and "0" in alle and "40" in alle, "Restposten zählen mit"
    assert inland == {"01", "02", "70", "71", "72", "73", "74", "75", "76", "77"}


def test_reduzieren_wien(herkunft):
    inland, alle = herkunft
    reihen = tourismus_at.reduzieren((AT / "stat_OGD_touextsai_Tour_HKL_1_wien_ab2018.csv").read_text("utf-8"), inland, alle)
    assert list(reihen) == ["9"]
    r = reihen["9"]
    assert r["Übernachtungen|insgesamt"]["201801"] > 0
    assert r["Übernachtungen|Ausland"]["201801"] < r["Übernachtungen|insgesamt"]["201801"]
    assert r["Gäste|insgesamt"]["201801"] < r["Übernachtungen|insgesamt"]["201801"]
    # Wien 2024: 18,86 Mio. Nächtigungen — deckt sich mit der amtlichen Jahreszahl.
    assert r["Übernachtungen|insgesamt"]["2024|Summe"] == 18864964
    assert r["Übernachtungen|insgesamt"]["2025|Summe"] == 20092646
    assert "2026|Summe" not in r["Übernachtungen|insgesamt"], "unvollständiges Jahr"


def test_reduzieren_ohne_spalten_ist_parse_fehler():
    with pytest.raises(SourceError):
        tourismus_at.reduzieren("a;b\n1;2\n", set(), set())


def test_load_wien(herkunft):
    inland, alle = herkunft
    reihen = tourismus_at.reduzieren((AT / "stat_OGD_touextsai_Tour_HKL_1_wien_ab2018.csv").read_text("utf-8"), inland, alle)

    async def laden():
        return reihen

    res = asyncio.run(tourismus_at.load("9", "Wien", laden))
    assert res.ok and res.data["gebiet"] == "Wien"
    assert res.data["uebernachtungen_12m"] == 20606167 and res.data["veraenderung_vorjahr_prozent"] == 6.1
    assert res.data["aufenthaltsdauer_naechte"] == 2.34
    assert res.data["ausland_anteil_prozent"] == 82.9
    assert res.data["saison"]["jahre"] == [2021, 2022, 2023, 2024, 2025]
    assert res.data["saison"]["staerkster"]["monat"] == "Aug"
    assert res.data["jahresreihe"][-1] == {"jahr": 2025, "uebernachtungen": 20092646}
    assert res.data["rohdaten"].startswith("https://data.statistik.gv.at/")
    assert "Statistik Austria" in res.provenance.source and "202607" not in res.provenance.stand
    assert asyncio.run(tourismus_at.load("4", "Oberösterreich", laden)).data is None
    assert asyncio.run(tourismus_at.load(None, None, laden)).data is None
