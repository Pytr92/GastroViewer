"""Straßenlärm (LfU Bayern) — gegen die echten GetFeatureInfo-Antworten vom
04.08.2026 (Mittlerer Ring München: LDEN 65,6 / LNight 56,9, Kartierung 2017;
2022er-Schicht dort NoData, weil sie Ballungsräume nicht abdeckt)."""

from __future__ import annotations

import pytest

from gastroviewer.sources import laerm


class FakeOut:
    def __init__(self, antworten):
        self.antworten = antworten
        self.calls: list[str] = []

    async def get_json(self, source, url, params=None, **kw):
        layer = (params or {})["query_layers"]
        self.calls.append(layer)
        return self.antworten[layer]


def test_wert_aus_liest_pixelwert(laerm_bayern):
    assert laerm.wert_aus(laerm_bayern["mroadbylden2017"]) == pytest.approx(65.583473)
    assert laerm.wert_aus(laerm_bayern["mroadbylden2022"]) is None  # NoData
    assert laerm.wert_aus({}) is None
    assert laerm.wert_aus(None) is None


def test_klassenbaender():
    assert laerm.klasse(54.0) == "bis 55 dB(A)"
    assert laerm.klasse(65.6) == "über 65 bis 70 dB(A)"
    assert laerm.klasse(76.2) == "über 75 dB(A)"
    assert laerm.klasse(60.0) == "über 55 bis 60 dB(A)"


def test_params_fragen_den_mittelpixel():
    p = laerm.params_fuer("mroadbylden2022", 48.1597, 11.5385)
    assert p["i"] == p["j"] == "50" and p["width"] == p["height"] == "101"
    assert p["crs"] == "CRS:84"
    # GetMap verlangt styles; GetFeatureInfo bekommt ihn vorsorglich mit.
    assert "styles" in p


async def test_fallback_von_2022_auf_2017(settings, laerm_bayern):
    """München ist Ballungsraum: 2022 antwortet NoData, 2017 trägt den Wert.
    Das Kartierungsjahr muss am Ergebnis stehen."""
    out = FakeOut(laerm_bayern)
    res = await laerm.load(out, settings, 48.1597, 11.5385, "09")
    assert res.ok
    assert res.data["lden"]["wert_db"] == 65.6
    assert res.data["lden"]["kartierung"] == 2017
    assert res.data["lnight"]["wert_db"] == 56.9
    assert res.data["kartiert"] is True
    # Reihenfolge: jüngste Kartierung zuerst.
    assert out.calls[0] == "mroadbylden2022"
    assert out.calls[1] == "mroadbylden2017"
    assert "LfU" in res.provenance.source


async def test_ausserhalb_bayerns_keine_anfrage(settings, laerm_bayern):
    out = FakeOut(laerm_bayern)
    res = await laerm.load(out, settings, 50.94, 6.96, "05")
    assert res.ok and res.data is None
    assert out.calls == []
    assert any("Bayern" in w for w in res.warnings)


async def test_nirgends_kartiert_ist_eine_aussage(settings, laerm_bayern):
    """Beide Runden NoData: kein Wert, aber eine ehrliche Aussage — und keine
    Verwechslung mit „leise"."""
    nodata = laerm_bayern["mroadbylden2022"]
    out = FakeOut({k: nodata for k in
                   ("mroadbylden2022", "mroadbylden2017",
                    "mroadbyln2022", "mroadbyln2017")})
    res = await laerm.load(out, settings, 48.0, 11.0, "09")
    assert res.ok
    assert res.data["kartiert"] is False
    assert res.data["lden"]["wert_db"] is None
    assert any("keine kartierte" in w for w in res.warnings)
    assert len(out.calls) == 4
