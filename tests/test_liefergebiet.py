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
    assert "cycleway" in RADWEGE
    # Fußwege sind bewusst drin: ohne sie zerfiel das Netz am Marienplatz
    # in Inseln (Live-Test 03.08.2026: 21.214 Knoten, 2 erreichbar).
    assert "footway" in RADWEGE


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


# ------------------------------------------------------ load: Thread-Rechnung


async def test_load_rechnet_im_thread_und_liefert_ein_gebiet(elemente, settings):
    """Der Rechenteil läuft seit der Bestandsaufnahme außerhalb des
    Event-Loops — load() muss trotzdem dasselbe Ergebnis liefern."""
    from gastroviewer.sources import liefergebiet

    class FakeOut:
        async def post_json(self, source, url, **kw):
            return {"elements": elemente, "osm3s": {"timestamp_osm_base": "2026-08-01T00:00:00Z"}}

    zellen = [{"_center": [ISAR[0] + 0.002, ISAR[1]], "Einwohner": 120},
              {"_center": [ISAR[0] + 0.5, ISAR[1]], "Einwohner": 9999}]  # 55 km weit weg
    res = await liefergebiet.load(FakeOut(), settings, *ISAR, 10, zellen)
    assert res.ok, res.error
    assert res.data["minuten"] == 10
    assert res.data["erreichbare_knoten"] > 10
    assert res.data["einwohner_liefergebiet"] == 120
    assert res.data["zellen_im_liefergebiet"] == 1
    assert res.data["flaeche"]


async def test_load_ohne_netz_ist_ein_befund_kein_absturz(settings):
    from gastroviewer.sources import liefergebiet

    class FakeOut:
        async def post_json(self, source, url, **kw):
            return {"elements": []}

    res = await liefergebiet.load(FakeOut(), settings, *ISAR, 10, None)
    assert res.ok and res.data is None
    assert any("kein befahrbares Wegenetz" in w for w in res.warnings)


async def test_zensus_ausfall_wird_benannt(elemente, settings):
    from gastroviewer.sources import liefergebiet

    class FakeOut:
        async def post_json(self, source, url, **kw):
            return {"elements": elemente}

    res = await liefergebiet.load(FakeOut(), settings, *ISAR, 10, None,
                                  zensus_warnungen=["Zeitüberschreitung"])
    assert res.ok and res.data["einwohner_liefergebiet"] is None
    assert any("Zensus" in w and "Zeitüberschreitung" in w for w in res.warnings)
    assert "Zensus" not in res.provenance.source

    leer = await liefergebiet.load(FakeOut(), settings, *ISAR, 10, [])
    assert leer.data["einwohner_liefergebiet"] == 0 and leer.data["zellen_im_liefergebiet"] == 0
    assert not any("Zensus-Abruf" in w for w in leer.warnings)
