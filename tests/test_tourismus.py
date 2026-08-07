"""Tourismus-Saisonalität München — gegen den echten Download vom 2026-08-07.

Sollwerte aus der Datei selbst nachgerechnet: jüngster gefüllter Monat ist der
Dezember 2025. Letzte 12 gefüllte Monate (= Kalenderjahr 2025):
19.631.581 Übernachtungen (−0,3 % zum Vorjahreszeitraum), 9.289.657 Gäste
(→ 2,11 Nächte), Auslandsanteil 44,5 %. Saisonkurve über 2021–2025:
stärkster Monat Juli (Index 130), schwächster Januar (59).
"""

from __future__ import annotations

import pytest

from gastroviewer.sources import tourismus
from gastroviewer.sources.base import SourceError

MARIENPLATZ = (48.1374, 11.5755)


@pytest.fixture(scope="module")
def reihen(tourismus_muenchen):
    return tourismus.parse_monatszahlen(tourismus_muenchen["csv"])


def test_parse_kennt_alle_reihen(reihen):
    assert sorted(reihen.keys()) == [
        "Gäste|Ausland", "Gäste|Inland", "Gäste|insgesamt",
        "Übernachtungen|Ausland", "Übernachtungen|Inland",
        "Übernachtungen|insgesamt",
    ]
    # NA-Zeilen (die noch leeren 2026er-Monate) sind nicht enthalten.
    assert "202601" not in reihen["Übernachtungen|insgesamt"]
    # Jahressummen-Zeilen liegen unter eigenem Schlüssel.
    assert reihen["Übernachtungen|insgesamt"]["2025|Summe"] == 19_631_581


def test_fremde_spalten_werden_abgelehnt():
    with pytest.raises(SourceError):
        tourismus.parse_monatszahlen("a,b,c\n1,2,3\n")


def test_letzte_12_monate_und_vergleich(reihen):
    d = tourismus.auswerten(reihen)
    assert d["uebernachtungen_12m"] == 19_631_581
    assert d["letzte_12_monate"][0]["monat"] == "Jan 2025"
    assert d["letzte_12_monate"][-1]["monat"] == "Dez 2025"
    assert d["veraenderung_vorjahr_prozent"] == -0.3
    assert d["gaeste_12m"] == 9_289_657
    assert d["aufenthaltsdauer_naechte"] == 2.11
    assert d["ausland_anteil_prozent"] == 44.5


def test_saisonkurve(reihen):
    d = tourismus.auswerten(reihen)
    s = d["saison"]
    assert s["jahre"] == [2021, 2022, 2023, 2024, 2025]
    assert len(s["index"]) == 12
    assert s["staerkster"] == {"monat": "Jul", "index": 130}
    assert s["schwaechster"] == {"monat": "Jan", "index": 59}
    # Index ist gegen den Jahresdurchschnitt normiert — Mittel ≈ 100.
    mittel = sum(x["index"] for x in s["index"]) / 12
    assert 98 <= mittel <= 102


def test_jahresreihe_aus_summenzeilen(reihen):
    d = tourismus.auswerten(reihen)
    assert d["jahresreihe"][-1] == {"jahr": 2025, "uebernachtungen": 19_631_581}
    assert len(d["jahresreihe"]) == 10


async def test_load_block(settings, tourismus_muenchen):
    class FakeOut:
        def __init__(self):
            self.urls = []

        async def get_text(self, source, url, **kw):
            self.urls.append(url)
            return tourismus_muenchen["csv"]

    out = FakeOut()
    res = await tourismus.load(out, settings, *MARIENPLATZ)
    assert res.ok and res.data
    assert out.urls == [tourismus.CSV_URL]
    assert "dl-de/by-2-0" in res.provenance.license
    assert "Dez 2025" in res.provenance.stand
    assert res.data["hinweise"]


async def test_ausserhalb_muenchens_kein_netzaufruf(settings):
    class Nie:
        async def get_text(self, *a, **kw):
            raise AssertionError("außerhalb Münchens darf nichts abgerufen werden")

    res = await tourismus.load(Nie(), settings, 49.4521, 11.0767)  # Nürnberg
    assert res.ok and res.data is None
    # Die Warnung verweist ehrlich auf den bundesweiten Jahreswert im
    # Kreisprofil statt so zu tun, als gäbe es Monatswerte überall.
    assert "Kreisprofil" in res.warnings[0]


async def test_ausfall_wird_durchgereicht(settings):
    class FakeOut:
        async def get_text(self, *a, **kw):
            raise SourceError("connect", "Verbindung nicht möglich.")

    res = await tourismus.load(FakeOut(), settings, *MARIENPLATZ)
    assert res.ok is False and res.error["kind"] == "connect"
