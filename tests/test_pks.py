"""PKS-Kreistabelle (BKA) — gegen den echten Auszug der Datei
KR-F-01-T01-Kreise-Faelle-HZ (Berichtsjahr 2024, Download 2026-08-08).
Erwartungswerte stammen aus der Originaldatei, nicht aus Annahmen."""

from __future__ import annotations

import asyncio

import pytest

from gastroviewer.sources import pks
from gastroviewer.sources.base import SourceError


@pytest.fixture(scope="module")
def kreise(pks_auszug):
    return pks.aufbereiten(pks.zeilen_aus_xlsx(pks_auszug))


def test_alle_400_kreise_geparst(kreise):
    assert len(kreise) == 400
    assert "09162" in kreise and "05315" in kreise


def test_muenchen_werte_wie_in_der_datei(kreise):
    d = pks.auswerten(kreise, "09162000")  # 8-stelliger AGS → Kreis 09162
    assert d["kreis"] == "München"
    assert d["kreisart"] == "KfS"
    assert d["jahr"] == 2024
    insgesamt = d["delikte"][0]
    assert insgesamt["schluessel"] == "------"
    assert insgesamt["faelle"] == 93854
    assert insgesamt["hz"] == 6304.3
    assert insgesamt["aufklaerungsquote"] == 63.1


def test_muenchen_rang_unter_400_kreisen(kreise):
    insgesamt = pks.auswerten(kreise, "09162")["delikte"][0]
    # München liegt trotz Metropole nur im Mittelfeld — Rang aus allen
    # 400 Gesamtzeilen der Datei gerechnet, Median ebenso.
    assert insgesamt["vergleich"] == {"rang": 148, "von": 400,
                                      "median_hz": 5327.6}


def test_strassenkriminalitaet_ausgewaehlt(kreise):
    d = pks.auswerten(kreise, "09162")
    strasse = next(x for x in d["delikte"] if x["schluessel"] == "899000")
    assert strasse["name"] == "Straßenkriminalität"
    assert strasse["faelle"] == 18444
    assert strasse["hz"] == 1238.9


def test_koeln_hat_hoehere_hz_als_muenchen(kreise):
    koeln = pks.auswerten(kreise, "05315")["delikte"][0]
    assert koeln["faelle"] == 134209
    assert koeln["hz"] == 13101.1
    assert koeln["hz"] > pks.auswerten(kreise, "09162")["delikte"][0]["hz"]


def test_unbekannter_kreis_gibt_none(kreise):
    assert pks.auswerten(kreise, "99999") is None


def test_kaputtes_xlsx_meldet_parsefehler():
    with pytest.raises(SourceError):
        pks.zeilen_aus_xlsx(b"kein zip")


def test_geaendertes_layout_meldet_parsefehler():
    with pytest.raises(SourceError):
        pks.aufbereiten([{"A": "anders", "C": "auch anders"}])


def test_load_blockform(kreise):
    async def laden():
        return kreise

    res = asyncio.run(pks.load("09162000", laden))
    assert res.ok
    assert res.data["delikte"][0]["faelle"] == 93854
    assert res.data["hinweise"]
    assert "Bundeskriminalamt" in res.provenance.source or "BKA" in res.provenance.source
    assert "privaten Bereich" in res.provenance.license


def test_load_unbekannter_kreis_warnt_statt_zu_raten(kreise):
    async def laden():
        return kreise

    res = asyncio.run(pks.load("99999999", laden))
    assert res.ok and res.data is None
    assert any("nicht in der BKA-Kreistabelle" in w for w in res.warnings)
