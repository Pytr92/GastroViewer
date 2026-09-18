"""Länder-Registry: Kästen, Zuordnung, Quellen je Land."""

from __future__ import annotations

from gastroviewer import laender

MUENCHEN = (48.1334, 11.5674)
WIEN = (48.2082, 16.3738)
KLAGENFURT = (46.6247, 14.3050)
SALZBURG = (47.8095, 13.0550)
BERLIN = (52.52, 13.405)
PARIS = (48.8566, 2.3522)


def test_kaesten_und_eindeutigkeit():
    assert laender.unterstuetzt(*WIEN) and laender.unterstuetzt(*KLAGENFURT)
    assert laender.unterstuetzt(*BERLIN) and not laender.unterstuetzt(*PARIS)
    assert laender.land_eindeutig(*BERLIN) is laender.DE
    assert laender.land_eindeutig(*KLAGENFURT) is laender.AT, "südlich des deutschen Kastens"
    assert laender.land_eindeutig(*WIEN) is laender.AT, "östlich des deutschen Kastens"
    # München und Salzburg liegen in beiden Kästen — da entscheidet der Geocoder.
    assert laender.land_eindeutig(*MUENCHEN) is None
    assert laender.land_eindeutig(*SALZBURG) is None
    assert [x.code for x in laender.laender_fuer_punkt(*SALZBURG)] == ["DE", "AT"]


def test_iso_und_geocoder_codes():
    assert laender.land_aus_code("at") is laender.AT
    assert laender.land_aus_code("DE") is laender.DE
    assert laender.land_aus_code("ch") is None and laender.land_aus_code(None) is None
    assert laender.land_aus_iso("AT-9") == (laender.AT, "9", "Wien")
    assert laender.land_aus_iso("DE-BY") == (laender.DE, "09", "Bayern")
    assert laender.land_aus_iso("AT-99") is None
    assert laender.iso_aus_schluessel(laender.DE, "09") == "DE-BY"
    assert laender.iso_aus_schluessel(laender.AT, "9") == "AT-9"


def test_quellen_je_land():
    assert laender.quelle_fehlt("zensus", laender.DE) is None
    grund = laender.quelle_fehlt("zensus", laender.AT)
    assert grund and "Deutschland" in grund and "Österreich" in grund
    assert laender.quelle_fehlt("osm", laender.AT) is None, "OSM gilt überall"
    assert laender.GESAMT_BBOX == (46.35, 5.5, 55.5, 17.2)
