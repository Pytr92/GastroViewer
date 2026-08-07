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


# ------------------------------------------- UBA-Bundesdienst (W3)

def test_uba_klasse_parst_live_gesehene_formen():
    assert laerm.uba_klasse("Lden6569") == {
        "von_db": 65, "bis_db": 69, "klasse": "65–69 dB(A)"}
    assert laerm.uba_klasse("Lnight5054") == {
        "von_db": 50, "bis_db": 54, "klasse": "50–54 dB(A)"}
    assert laerm.uba_klasse("LdenGreaterThan75") == {
        "von_db": 75, "bis_db": None, "klasse": "über 75 dB(A)"}
    assert laerm.uba_klasse("") is None
    assert laerm.uba_klasse("irgendwas") is None


def test_uba_ballungsraum_abfrage_sendlinger_tor(uba_laerm):
    """Layer 35 am Sendlinger Tor: vier überlappende Polygone — es zählt
    je Quelle das lauteste Band; ein Polygon trägt zusätzlich Schiene."""
    b = laerm.uba_abfrage_auswerten(uba_laerm["ballungsraum"])
    assert b["gemeinde"] == "München"
    assert b["road_den"]["klasse"] == "65–69 dB(A)"
    assert b["road_night"]["klasse"] == "55–59 dB(A)"
    assert b["rail_den"]["klasse"] == "60–64 dB(A)"
    assert "air_den" not in b or b.get("air_den") is None


def test_uba_abfrage_leer_heisst_kein_ballungsraum(uba_laerm):
    assert laerm.uba_abfrage_auswerten(uba_laerm["leer"]) is None


def test_uba_einzel_layer_nimmt_lauteste_klasse(uba_laerm):
    """Berlin Hermannplatz, Layer 30: LdenGreaterThan75 und Lden7074 —
    das lautere Band gewinnt."""
    k = laerm.uba_einzel_auswerten(uba_laerm["hlq_den"])
    assert k == {"von_db": 75, "bis_db": None, "klasse": "über 75 dB(A)"}
    n = laerm.uba_einzel_auswerten(uba_laerm["hlq_night"])
    assert n["klasse"] == "65–69 dB(A)"


async def test_ausserhalb_bayerns_uebernimmt_der_uba_dienst(
        settings, uba_laerm):
    """Köln (Bundesland 05): Ballungsraum-Abfrage zuerst; ist sie leer,
    liefern die HLQ-Straßenlayer."""
    out = FakeOut({laerm.UBA_LAYER_ABFRAGE: uba_laerm["leer"],
                   laerm.UBA_LAYER_HLQ_DEN: uba_laerm["hlq_den"],
                   laerm.UBA_LAYER_HLQ_NIGHT: uba_laerm["hlq_night"]})
    res = await laerm.load(out, settings, 50.94, 6.96, "05")
    assert res.ok
    assert res.data["dienst"] == "uba"
    assert res.data["lden"]["wert_db"] is None      # Klassen, kein Rasterwert
    assert res.data["lden"]["klasse"] == "über 75 dB(A)"
    assert res.data["lnight"]["klasse"] == "65–69 dB(A)"
    assert res.data["kartiert"] is True
    assert out.calls == [laerm.UBA_LAYER_ABFRAGE, laerm.UBA_LAYER_HLQ_DEN,
                         laerm.UBA_LAYER_HLQ_NIGHT]
    assert "Umweltbundesamt" in res.provenance.source


async def test_uba_ballungsraum_eine_anfrage_alle_quellen(
        settings, uba_laerm):
    """Trifft Layer 35, entfallen die Einzel-Layer — und Schiene/Flug
    stehen als weitere Quellen dabei."""
    out = FakeOut({laerm.UBA_LAYER_ABFRAGE: uba_laerm["ballungsraum"]})
    res = await laerm.load(out, settings, 48.1334, 11.5674, "02")
    assert res.ok
    assert out.calls == [laerm.UBA_LAYER_ABFRAGE]
    assert res.data["lden"]["klasse"] == "65–69 dB(A)"
    assert res.data["lden"]["abdeckung"] == "Ballungsraum (München)"
    assert res.data["weitere_quellen"] == {"schiene": "60–64 dB(A)"}


async def test_bayern_bleibt_beim_lfu_dienst(settings, laerm_bayern):
    out = FakeOut(laerm_bayern)
    res = await laerm.load(out, settings, 48.1597, 11.5385, "09")
    assert res.data["dienst"] == "lfu"
    assert "LfU" in res.provenance.source


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
