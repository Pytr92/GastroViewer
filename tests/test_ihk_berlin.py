"""IHK-Berlin-Gewerbedaten — gegen den am 2026-08-08 aufgezeichneten
echten Auszug der CC0-Datei."""

from __future__ import annotations

import asyncio

import pytest

from gastroviewer.sources import ihk_berlin
from gastroviewer.sources.base import SourceError


def test_nur_berlin():
    assert ihk_berlin.ist_berlin(52.5200, 13.4050)
    assert not ihk_berlin.ist_berlin(48.1334, 11.5674)   # München
    assert not ihk_berlin.ist_berlin(52.3906, 13.0645)   # Potsdam


def test_parse_filtert_auf_gastgewerbe(ihk_berlin_csv):
    betriebe = ihk_berlin.parse_gastro(ihk_berlin_csv)
    assert betriebe, "Auszug muss Gastgewerbe enthalten"
    # Nur NACE-Abschnitt 55/56 — kein Einzelhandel, keine Versicherung.
    assert {b["abschnitt"] for b in betriebe} <= {"55", "56"}
    for b in betriebe:
        assert 52.3 < b["lat"] < 52.7 and 13.0 < b["lon"] < 13.8
        assert b["plz"] and len(b["plz"]) == 5


def test_auswerten_zaehlt_nur_den_umkreis(ihk_berlin_csv):
    betriebe = ihk_berlin.parse_gastro(ihk_berlin_csv)
    eng = ihk_berlin.auswerten(betriebe, 52.5200, 13.4050, 500)
    weit = ihk_berlin.auswerten(betriebe, 52.5200, 13.4050, 5000)
    assert eng["gastronomie"] <= weit["gastronomie"]
    assert eng["radius_m"] == 500
    # Beherbergung wird getrennt geführt, nicht in die Gastronomie gezählt.
    assert weit["beherbergung"] >= 0
    for n in weit["naechste"]:
        assert n["distanz_m"] <= 5000


def test_betriebsalter_wird_ausgewertet(ihk_berlin_csv):
    betriebe = ihk_berlin.parse_gastro(ihk_berlin_csv)
    r = ihk_berlin.auswerten(betriebe, 52.5200, 13.4050, 20000)
    assert r["median_alter_jahre"] is not None
    assert r["junge_betriebe"] + r["alte_betriebe"] <= r["gastronomie"]


def test_kaputte_koordinaten_werden_uebersprungen():
    csv = ("opendata_id,city,postcode,latitude,longitude,ihk_branch_id,"
           "nace_id,branch_top_level_id,employees_range,ihk_branch_desc,"
           "nace_desc,branch_top_level_desc,business_age,business_type,"
           "Bezirk,planungsraum_id,Planungsraum,Bezirksregion,"
           "Prognoseraum,Ortsteil\n"
           "1,Berlin,10115,,,562,5610,56,0,Restaurant,x,Gastronomie,5,"
           "e,Mitte,1,PR,BR,PROG,OT\n"
           "2,Berlin,10115,52.53,13.38,562,5610,56,0,Restaurant,x,"
           "Gastronomie,5,e,Mitte,1,PR,BR,PROG,OT\n")
    b = ihk_berlin.parse_gastro(csv)
    assert len(b) == 1 and b[0]["lat"] == 52.53


def test_load_ausserhalb_berlins_bleibt_leer():
    async def nie():  # pragma: no cover
        raise AssertionError("Außerhalb Berlins darf nichts geladen werden.")

    res = asyncio.run(ihk_berlin.load(None, 48.1334, 11.5674, 600, nie))
    assert res.ok and res.data is None
    assert any("nur für Berlin" in w for w in res.warnings)


def test_load_berlin_traegt_cc0(ihk_berlin_csv):
    betriebe = ihk_berlin.parse_gastro(ihk_berlin_csv)

    async def laden():
        return betriebe

    res = asyncio.run(ihk_berlin.load(None, 52.5200, 13.4050, 3000, laden))
    assert res.ok and res.data
    assert "CC0" in res.provenance.license
    assert any("Bestand" in h for h in res.data["hinweise"])


def test_load_ohne_betriebe_scheitert_mit_begruendung():
    async def leer():
        return []

    with pytest.raises(SourceError) as err:
        asyncio.run(ihk_berlin.load(None, 52.5200, 13.4050, 600, leer))
    assert "keine Gastronomiebetriebe" in err.value.message


def test_lfs_hinweis_steht_in_der_url():
    """raw.githubusercontent.com liefert bei Git LFS nur den Zeiger —
    der Endpunkt muss media.githubusercontent.com sein."""
    assert ihk_berlin.CSV_URL.startswith("https://media.githubusercontent.com")
