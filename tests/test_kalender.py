"""Feiertage und Schulferien — gegen die am 2026-08-08 aufgezeichneten
echten OpenHolidaysAPI-Antworten (Bayern 2026)."""

from __future__ import annotations

import asyncio

import pytest

from gastroviewer.sources import kalender
from gastroviewer.sources.base import SourceError


def test_bundesland_aus_gemeindeschluessel():
    assert kalender.land_aus_ags("09162000") == ("DE-BY", "Bayern")
    assert kalender.land_aus_ags("11000000") == ("DE-BE", "Berlin")
    assert kalender.land_aus_ags("02000000") == ("DE-HH", "Hamburg")
    assert kalender.land_aus_ags(None) is None
    assert kalender.land_aus_ags("") is None
    # Alle 16 Länder sind hinterlegt.
    assert len(kalender.LAND_NACH_AGS) == 16


def test_feiertage_bayern_2026(kalender_fixture):
    t = kalender.parse_feiertage(kalender_fixture["feiertage_by_2026"])
    assert len(t) == 14
    assert t[0]["datum"] == "2026-01-01" and t[0]["name"] == "Neujahr"
    # Heilige Drei Könige gibt es nicht bundesweit — das muss erkennbar sein.
    dk = next(x for x in t if x["name"] == "Heilige Drei Könige")
    assert dk["bundesweit"] is False
    assert any(x["bundesweit"] for x in t)
    # Sortiert nach Datum.
    assert [x["datum"] for x in t] == sorted(x["datum"] for x in t)


def test_ferien_bayern_2026_mit_dauer(kalender_fixture):
    f = kalender.parse_ferien(kalender_fixture["ferien_by_2026"])
    assert len(f) == 8
    sommer = next(x for x in f if x["name"] == "Sommerferien")
    assert sommer["von"] == "2026-08-03" and sommer["bis"] == "2026-09-14"
    # 03.08. bis 14.09. einschließlich sind 43 Tage.
    assert sommer["tage"] == 43


def test_auswerten_hebt_die_sommerferien_hervor(kalender_fixture):
    t = kalender.parse_feiertage(kalender_fixture["feiertage_by_2026"])
    f = kalender.parse_ferien(kalender_fixture["ferien_by_2026"])
    r = kalender.auswerten(("DE-BY", "Bayern"), 2026, t, f)
    assert r["bundesland"] == "Bayern"
    assert r["feiertage_gesamt"] == 14
    assert r["feiertage_landesspezifisch"] > 0
    assert r["sommerferien"]["tage"] == 43


def test_load_ohne_ags_bleibt_leer():
    class Nie:
        async def get_json(self, *a, **kw):  # pragma: no cover
            raise AssertionError("Ohne Bundesland darf nichts hinausgehen.")

    res = asyncio.run(kalender.load(Nie(), None, 2026))
    assert res.ok and res.data is None
    assert any("Bundesland" in w for w in res.warnings)


def test_load_bayern(kalender_fixture):
    class Fake:
        async def get_json(self, source, url, **kw):
            assert kw["params"]["subdivisionCode"] == "DE-BY"
            if "SchoolHolidays" in url:
                return kalender_fixture["ferien_by_2026"]
            return kalender_fixture["feiertage_by_2026"]

    res = asyncio.run(kalender.load(Fake(), "09162000", 2026))
    assert res.ok and res.data["bundesland"] == "Bayern"
    assert "ODbL" in res.provenance.license
    # Die amtliche Herkunft der Ferientermine wird benannt.
    assert "Kultusministerkonferenz" in res.provenance.note


def test_leere_antwort_ist_kein_jahr_ohne_feiertage():
    """HTTP 200 mit leerer Liste heißt „außerhalb des Datenbestands" —
    das darf nicht als „keine Feiertage" durchgehen."""

    class Leer:
        async def get_json(self, *a, **kw):
            return []

    with pytest.raises(SourceError) as err:
        asyncio.run(kalender.load(Leer(), "09162000", 2031))
    assert "Datenbestand" in err.value.message


def test_kein_score_nur_kontext():
    """Der Block darf nichts verrechnen — das steht auch im Hinweis."""
    assert any("keine Bewertung" in h or "keine Kennzahl" in h
               for h in kalender.HINWEISE)
    assert any("Mariä Himmelfahrt" in h for h in kalender.HINWEISE)
