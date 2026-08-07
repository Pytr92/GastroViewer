"""Messe-Kalender München — gegen den echten Download vom 2026-08-07.

Sollwerte aus der Datei selbst nachgerechnet: 95 Münchner Zeilen, davon eine
mit unlesbarem Termin („Mai 2.2026“) → 94 verwertbare Veranstaltungen.
Jahresbilanz 2025: 13 Veranstaltungen, 1.301.376 Besucher aus 12 mit Zahl.
Größte aufgezeichnete Veranstaltung: bauma 2025 mit 605.974 Besuchern.
"""

from __future__ import annotations

import pytest

from gastroviewer.sources import messe
from gastroviewer.sources.base import SourceError

MARIENPLATZ = (48.1374, 11.5755)
HEUTE = "2026-08-07"


@pytest.fixture(scope="module")
def events(messe_muenchen):
    ev, verworfen = messe.parse_veranstaltungen(messe_muenchen["csv"])
    assert verworfen == 1, "genau die Zeile „Mai 2.2026“ fällt raus"
    return ev


def test_nur_muenchen_und_echte_termine(events):
    assert len(events) == 94
    assert all(e["start"] <= e["ende"] for e in events)
    # Die Messe München veranstaltet weltweit — Delhi & Co. sind gefiltert.
    assert all(e["gelaende"] in messe.GELAENDE for e in events)


def test_datum_wird_iso(events):
    assert messe._datum_iso("11.12.2024") == "2024-12-11"
    assert messe._datum_iso("Mai 2.2026") is None
    assert messe._datum_iso("6") is None


def test_jahresbilanz_2025(events):
    d = messe.auswerten(events, *MARIENPLATZ, HEUTE)
    j2025 = next(j for j in d["jahresreihe"] if j["jahr"] == 2025)
    assert j2025["veranstaltungen"] == 13
    assert j2025["besucher"] == 1_301_376
    assert j2025["mit_besucherzahl"] == 12
    # Vor 2022 stehen keine Besucherzahlen in der Datei — dann None, nicht 0.
    j2021 = next(j for j in d["jahresreihe"] if j["jahr"] == 2021)
    assert j2021["besucher"] is None


def test_groesste_veranstaltung_ist_die_bauma(events):
    d = messe.auswerten(events, *MARIENPLATZ, HEUTE)
    top = d["groesste"][0]
    assert top["titel"] == "bauma"
    assert top["besucher"] == 605_974
    assert top["start"].startswith("2025")


def test_naechstes_gelaende_vom_marienplatz(events):
    d = messe.auswerten(events, *MARIENPLATZ, HEUTE)
    # Vom Marienplatz ist das MOC (Freimann) näher als das Gelände in Riem.
    assert d["naechstes_gelaende"]["name"] == "M,O,C,"
    assert 6_000 < d["naechstes_gelaende"]["distanz_m"] < 8_000
    assert len(d["gelaende"]) == 3


def test_kommend_und_laufend_nach_stichtag(events):
    # Am Prüftag führte der Datensatz keine kommenden Münchner Termine —
    # er wird als „bisherige Veranstaltungen" nachlaufend gepflegt.
    d = messe.auswerten(events, *MARIENPLATZ, HEUTE)
    assert d["kommend"] == [] and d["laufend"] == []
    # Mit einem Stichtag mitten in der bauma 2025 (07.–13.04.) ist sie laufend.
    d2 = messe.auswerten(events, *MARIENPLATZ, "2025-04-08")
    assert any(e["titel"] == "bauma" for e in d2["laufend"])
    assert d2["kommend"], "nach dem 08.04.2025 kommen weitere Termine"
    assert len(d2["kommend"]) <= messe.MAX_KOMMENDE


async def test_load_block(settings, messe_muenchen):
    class FakeOut:
        def __init__(self):
            self.urls = []

        async def get_text(self, source, url, **kw):
            self.urls.append(url)
            return messe_muenchen["csv"]

    out = FakeOut()
    res = await messe.load(out, settings, *MARIENPLATZ)
    assert res.ok and res.data
    assert out.urls == [messe.CSV_URL]
    assert "dl-de/by-2-0" in res.provenance.license
    assert any("unlesbarem Termin" in w for w in res.warnings)
    assert res.data["hinweise"]


async def test_weit_weg_kein_netzaufruf(settings):
    class Nie:
        async def get_text(self, *a, **kw):
            raise AssertionError("jenseits von 20 km darf nichts abgerufen werden")

    res = await messe.load(Nie(), settings, 49.4521, 11.0767)  # Nürnberg
    assert res.ok and res.data is None
    assert "20 km" in res.warnings[0]


async def test_kaputte_csv_wird_benannt(settings):
    class FakeOut:
        async def get_text(self, *a, **kw):
            return "voellig;andere;spalten\n1;2;3\n"

    res = await messe.load(FakeOut(), settings, *MARIENPLATZ)
    assert res.ok is False
    assert "Spalten" in res.error["message"]


async def test_ausfall_wird_durchgereicht(settings):
    class FakeOut:
        async def get_text(self, *a, **kw):
            raise SourceError("timeout", "Zeitüberschreitung nach 60 s.")

    res = await messe.load(FakeOut(), settings, *MARIENPLATZ)
    assert res.ok is False and res.error["kind"] == "timeout"
