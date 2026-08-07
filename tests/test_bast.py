"""BASt-Dauerzählstellen (bundesweiter Kfz-Fallback) — gegen den echten
Auszug der Jahresdatei Jawe2024.csv vom 2026-08-07. Sollwerte aus der
Datei: Britz (A 100) DTV 128 167 / SV 4 540; Köln-Longerich (A 57)
97 192 / 2 102; „AD HH-Südost (O)" ohne Jahreswert (Netzmodernisierung)."""

from __future__ import annotations

import asyncio

import pytest

from gastroviewer.sources import bast
from gastroviewer.sources.base import SourceError

BERLIN = (52.4869, 13.4247)   # Hermannplatz
KOELN = (50.9386, 6.9400)     # Hohenzollernring


def test_zahl_und_koordinate_deutsches_format():
    assert bast._zahl("128.167") == 128167
    assert bast._zahl("2.102") == 2102
    assert bast._zahl("") is None
    assert bast._koordinate("53,50754848") == pytest.approx(53.50754848)
    assert bast._koordinate("") is None


def test_parse_zaehlstellen(bast_jawe):
    stellen = bast.parse_zaehlstellen(bast_jawe["csv"])
    assert len(stellen) == 11
    britz = next(s for s in stellen if s["name"] == "Britz")
    assert britz["strasse"] == "A 100"
    assert britz["dtv_kfz"] == 128167
    assert britz["dtv_schwerverkehr"] == 4540
    # Ausfalljahr: leere DTV-Felder werden None, nicht 0.
    leer = next(s for s in stellen if "HH-Südost" in (s["name"] or ""))
    assert leer["dtv_kfz"] is None


def test_parse_lehnt_fremdes_format_ab():
    with pytest.raises(SourceError) as err:
        bast.parse_zaehlstellen("Name;Wert\nx;1\n")
    assert "unerwartete Spalten" in err.value.message


def test_berlin_hermannplatz_findet_britz(bast_jawe):
    stellen = bast.parse_zaehlstellen(bast_jawe["csv"])
    d = bast.aufbereiten(stellen, *BERLIN, 600)
    assert d["naechste"]["zaehlstelle"] == "Britz"
    assert d["naechste"]["distanz_m"] == pytest.approx(3002, abs=30)
    assert d["staerkste"]["dtv_kfz"] == 128167
    assert d["staerkste"]["schwerverkehr_anteil"] == 3.5
    # Friedenau (6,9 km) liegt außerhalb des Suchradius.
    assert all(z["distanz_m"] <= bast.MAX_DISTANZ_M for z in d["zaehlstellen"])
    assert len(d["zaehlstellen"]) == 2


def test_koeln_ring_bleibt_ehrlich_leer(bast_jawe):
    """Die nächste Zählstelle (Rheinbrücke Rodenkirchen) liegt 5,8 km
    entfernt — außerhalb des 5-km-Radius bleibt der Block leer statt eine
    irrelevante Autobahnzahl als Standortwert auszugeben."""
    stellen = bast.parse_zaehlstellen(bast_jawe["csv"])
    d = bast.aufbereiten(stellen, *KOELN, 600)
    assert d["zaehlstellen"] == []
    assert d["naechste"] is None


def test_load_liefert_blockform(bast_jawe):
    stellen = bast.parse_zaehlstellen(bast_jawe["csv"])

    async def lade():
        return stellen

    res = asyncio.run(bast.verkehrsmengen(*BERLIN, 600, lade))
    assert res.ok
    assert res.data["dienst"] == "bast"
    assert res.data["jahr"] == 2024
    assert res.data["staerkste"]["dtv_kfz"] == 128167
    assert "BASt" in res.provenance.source

    leer = asyncio.run(bast.verkehrsmengen(*KOELN, 600, lade))
    assert leer.ok and not leer.data["zaehlstellen"]
    assert any("Autobahnen und Bundesstraßen" in w for w in leer.warnings)
