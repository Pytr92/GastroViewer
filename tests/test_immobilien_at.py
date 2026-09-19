"""Immobilien-Durchschnittspreise (Statistik Austria, ODS 2024) gegen die
Live-Dateien vom 18.09.2026: ODS-Parser, Bezirks-Zuordnung, Blockform."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from gastroviewer.sources import immobilien_at as im
from gastroviewer.sources.base import SourceError

AT = Path(__file__).resolve().parent.parent / "fixtures" / "at"


@pytest.fixture(scope="module")
def daten():
    return im.reduzieren((AT / "stat_r5_haeuserpreise2024.ods").read_bytes(),
                         (AT / "stat_r6_wohnungspreise2024.ods").read_bytes(),
                         (AT / "stat_r6_baugrundstueckspreise2024.ods").read_bytes())


def test_ods_tabellen_liest_blaetter_und_zahlen():
    t = im.ods_tabellen((AT / "stat_r6_baugrundstueckspreise2024.ods").read_bytes())
    assert set(t) == set(im.LAENDER.values())
    assert t["Salzburg"][3][:5] == ["B.Nr.", "Bezirk", "G. Nr.", "Gemeinde", "Euro/m²"]
    assert t["Salzburg"][4][0] == "501" and float(t["Salzburg"][4][4]) == 1379.3
    with pytest.raises(SourceError):
        im.ods_tabellen(b"kein zip")


def test_reduzieren_alle_bezirke_zugeordnet(daten):
    assert len(daten["bezirke"]) >= 115 and len(daten["gemeinden"]) >= 2000
    assert not [k for k in daten["bezirke"] if "xx:" in k], "Bezirksnamen der Preisblätter ohne B.Nr."
    assert daten["stand"] == "28.05.2025"
    sbg = daten["bezirke"]["501"]
    assert sbg["name"] == "Salzburg(Stadt)" and sbg["baugrund"] == 1379.3
    assert [h["titel"].split("Kategorie ")[1][:1] for h in sbg["haeuser"]] == ["A", "B", "C"]
    assert sbg["haeuser"][0]["werte"] == [6183, 4602, 3751, 6923, 5153, 4200, 9041, 6729, 5484]
    assert sbg["groessen"] == {"A": "Weniger als 420 m²", "B": "420 - 620 m²", "C": "Mehr als 620 m²"}
    # Oberösterreich: abweichende Schreibweisen („Stadt Linz“ / „Linz(Stadt)“, „Braunau“ / „Braunau am Inn“)
    assert daten["bezirke"]["401"]["haeuser"] and daten["bezirke"]["404"]["haeuser"]
    # Wien je Gemeindebezirk; Innere Stadt ohne Häuser, mit Wohnungen, Fußnoten entfernt
    w1 = daten["bezirke"]["901"]
    assert w1["name"] == "Wien 1.,Innere Stadt" and w1["haeuser"] == [] and len(w1["wohnungen"]) == 2
    assert w1["wohnungen"][0]["werte"][0] == 8230


def test_auswerten_salzburg_und_wien(daten):
    a = im.auswerten(daten, "50101", 2024)
    assert a["land"] == "Salzburg" and a["bezirk"] == {"nummer": "501", "name": "Salzburg(Stadt)"}
    assert a["gemeinde"] == {"gkz": "50101", "name": "Salzburg", "baugrund_eur_m2": 1379.3}
    assert a["baugrund_bezirk_eur_m2"] == 1379.3 and len(a["haeuser"]) == 3 and len(a["wohnungen"]) == 2
    hb = a["haeuser"][1]
    assert hb["kategorie"] == "B" and hb["perioden"][2]["periode"] == "Ab 1991"
    assert hb["perioden"][2]["klassen"][0] == {"klasse": "Weniger als 110 m²", "eur_m2": 12985.0}
    assert "¹" not in hb["titel"]
    w = im.auswerten(daten, "90101", 2024)
    assert w["bezirk"]["name"] == "Wien 1.,Innere Stadt" and w["gemeinde"] is None and w["haeuser"] == []
    assert w["wohnungen"][0]["perioden"][0]["klassen"][2]["eur_m2"] == 8948
    # Gemeinde im Bezirk Hallein: Bezirkswerte + Gemeinde-Baugrund
    h = im.auswerten(daten, "50201", 2024)
    assert h["bezirk"]["name"] == "Hallein" and h["gemeinde"]["name"] == "Abtenau" and h["gemeinde"]["baugrund_eur_m2"] == 245.7
    assert im.auswerten(daten, "99999", 2024) is None


def test_load_block_und_ausfall(daten):
    async def laden():
        return daten, 2024

    res = asyncio.run(im.load("50101", laden))
    assert res.ok and res.name == "immobilien" and res.data["jahr"] == 2024 and not res.warnings
    assert "2024" in res.provenance.source and "28.05.2025" in res.provenance.stand
    res = asyncio.run(im.load("90101", laden))
    assert res.ok and any("keine Häuserpreise" in w for w in res.warnings)
    res = asyncio.run(im.load(None, laden))
    assert res.ok and res.data is None and "Gemeindekennziffer" in res.warnings[0]

    async def kaputt():
        raise SourceError("timeout", "x")

    assert asyncio.run(im.load("50101", kaputt)).ok is False
