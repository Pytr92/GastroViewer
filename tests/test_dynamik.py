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


async def test_januar_faellt_auf_das_vorjahr_zurueck(settings, ohsome_dynamik):
    """Vor dem ersten Datenstand des Jahres lehnt ohsome den 1.1. ab —
    dann endet die Reihe am 1.1. des Vorjahres, mit Warnung."""
    import time

    from gastroviewer.sources import dynamik
    from gastroviewer.sources.base import SourceError

    jahr = time.gmtime().tm_year
    aufrufe = []

    class FakeOut:
        async def post_json(self, source, url, **kw):
            t = kw["data"]["time"]
            aufrufe.append(t)
            if t.endswith(f"{jahr}-01-01/P1Y"):
                raise SourceError(
                    "http_status", "HTTP 404 — Anfrage abgelehnt.",
                    detail='{"status":404,"message":"The given time parameter is not '
                           'completely within the timeframe (2007-10-08 to '
                           f'{jahr - 1}-12-20) of the underlying osh-data."}}')
            return ohsome_dynamik["gastro"]

    res = await dynamik.load(FakeOut(), settings, 48.137, 11.575, 600)
    assert res.ok, res.error
    assert len(aufrufe) == 3
    assert aufrufe[1].endswith(f"{jahr - 1}-01-01/P1Y") and aufrufe[2] == aufrufe[1]
    assert any(f"1.1.{jahr - 1}" in w for w in res.warnings)
    assert res.provenance.stand.endswith(f"{jahr - 1}, jeweils 1. Januar")


async def test_anderer_404_bleibt_ein_fehler(settings):
    from gastroviewer.sources import dynamik
    from gastroviewer.sources.base import SourceError

    class FakeOut:
        async def post_json(self, source, url, **kw):
            raise SourceError("http_status", "HTTP 404 — Anfrage abgelehnt.", detail="not found")

    res = await dynamik.load(FakeOut(), settings, 48.137, 11.575, 600)
    assert not res.ok and res.error["kind"] == "http_status"
