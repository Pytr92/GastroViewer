"""Rad-Liefergebiet: Radprofil, Netzaufbau, Reichweitenrechnung.

Baut auf derselben echten Overpass-Fixture auf wie die Gehweg-Tests
(Isarufer): dieselben Wege, anderes Profil. Die Fixture ist die
unveränderte Antwort des Dienstes — kein Weg ist ausgedacht.
"""

from __future__ import annotations

import pytest

from conftest import load_fixture
from gastroviewer.sources.gehweg import gehstrecken
from gastroviewer.sources.liefergebiet import (MAX_MINUTEN, MIN_MINUTEN,
                                               RADTEMPO_M_PRO_MIN, RADWEGE,
                                               _befahrbar, baue_radnetz,
                                               build_query)

ISAR = (48.1266, 11.5825)


@pytest.fixture(scope="module")
def elemente():
    return load_fixture("raw_overpass_gehweg_isar.json")["elements"]


def test_radprofil_schliesst_das_richtige_aus():
    assert _befahrbar({}) is True
    assert _befahrbar({"bicycle": "no"}) is False
    assert _befahrbar({"access": "private"}) is False
    # Ausdrückliches Radrecht schlägt die Zugangsbeschränkung.
    assert _befahrbar({"access": "private", "bicycle": "yes"}) is True
    # Treppen fehlen schon im Wegefilter der Abfrage, nicht erst hier.
    assert "steps" not in RADWEGE
    assert "footway" not in RADWEGE
    assert "cycleway" in RADWEGE


def test_abfrage_rechnet_reichweite_aus_der_fahrzeit():
    q = build_query(*ISAR, minuten=10)
    # 10 min x 250 m/min x Netzpuffer 1,8 = 4500 m.
    assert "around:4500" in q
    assert "steps" not in q


def test_radnetz_traegt_weiter_als_das_fussnetz(elemente):
    netz = baue_radnetz(elemente)
    assert len(netz) > 1000
    start, anbindung = netz.naechster_knoten(*ISAR)
    assert start is not None
    # 5 Minuten Rad = 1.250 m Netzstrecke.
    radius = 5 * RADTEMPO_M_PRO_MIN
    dist = gehstrecken(netz, start, radius)
    assert dist, "vom Startknoten aus muss etwas erreichbar sein"
    assert max(dist.values()) <= radius
    # Zum Vergleich: zu Fuß wären es in 5 Minuten nur 400 m Reichweite —
    # das Rad erreicht deutlich mehr Knoten desselben Netzes.
    dist_fuss = gehstrecken(netz, start, 5 * 80.0)
    assert len(dist) > len(dist_fuss) * 2


def test_minuten_grenzen():
    assert (MIN_MINUTEN, MAX_MINUTEN) == (5, 15)
