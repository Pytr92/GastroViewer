"""Gastro-Dynamik (ohsome) — gegen die echte Antwort vom 04.08.2026.

Marienplatz r=600: 326 (1.1.2019) → 369 (1.1.2026) Gastro-Objekte. Die
Fixture ist die unveränderte API-Antwort; jede erwartete Zahl unten stammt
daraus, nichts ist ausgedacht.
"""

from __future__ import annotations

from gastroviewer.sources import dynamik


def test_fixture_ist_die_echte_antwort(ohsome_dynamik):
    assert ohsome_dynamik["gastro"]["attribution"]["text"] == "© OpenStreetMap contributors"
    assert len(ohsome_dynamik["gastro"]["result"]) == 8


def test_parse_reihe(ohsome_dynamik):
    reihe = dynamik.parse_reihe(ohsome_dynamik["gastro"])
    assert reihe[0] == {"jahr": 2019, "anzahl": 326}
    assert reihe[-1] == {"jahr": 2026, "anzahl": 369}
    assert [r["jahr"] for r in reihe] == list(range(2019, 2027))


def test_auswerten_veraenderung(ohsome_dynamik):
    d = dynamik.auswerten(
        dynamik.parse_reihe(ohsome_dynamik["gastro"]),
        dynamik.parse_reihe(ohsome_dynamik["fast_food"]),
    )
    v = d["veraenderung"]
    assert v["von"] == 326 and v["bis"] == 369
    assert v["absolut"] == 43
    assert v["prozent"] == 13.2  # 43/326
    assert d["reihe"][0]["schnellgastronomie"] == 29
    assert d["reihe"][-1]["schnellgastronomie"] == 33
    # Die zentrale Grenze muss in den Daten selbst stehen, nicht nur in der UI.
    assert any("Kartierer" in h for h in d["hinweise"])


def test_auswerten_ohne_startwert_kein_prozent():
    d = dynamik.auswerten(
        [{"jahr": 2019, "anzahl": 0}, {"jahr": 2026, "anzahl": 5}], []
    )
    assert d["veraenderung"]["prozent"] is None
    assert d["veraenderung"]["absolut"] == 5
    assert d["reihe"][0]["schnellgastronomie"] is None


def test_leere_reihe_bricht_nicht():
    d = dynamik.auswerten([], [])
    assert d["reihe"] == [] and d["veraenderung"] is None


def test_zeitraum_und_filter():
    assert dynamik.zeitraum(2026) == "2019-01-01/2026-01-01/P1Y"
    # Derselbe Gastronomiebegriff wie im OSM-Block — acht amenity-Typen.
    for typ in ("restaurant", "fast_food", "biergarten", "ice_cream"):
        assert typ in dynamik.GASTRO_FILTER
