"""Flächen-Scan: Kachelrundung, Umfeldrechnung, Zusammenspiel der Quellen.

Die Umfeldrechnung wird an konstruierten Zellen mit bekannten Abständen
geprüft; das Zusammenspiel läuft wie überall gegen die echten Phase-0-Fixtures.
"""

from __future__ import annotations

import asyncio

from gastroviewer.sources import scan
from gastroviewer.sources.base import SourceError

LAT, LON = 48.1000, 11.5000


def _zelle(kennung: str, lat: float, lon: float, einwohner):
    ring = [
        [lon - 0.0005, lat - 0.00045],
        [lon + 0.0005, lat - 0.00045],
        [lon + 0.0005, lat + 0.00045],
        [lon - 0.0005, lat + 0.00045],
    ]
    return {
        "attributes": {"GITTER_ID_100m": kennung, "Einwohner": einwohner},
        "geometry": {"rings": [ring]},
    }


def test_kachelrundung_ist_gleitkommafest():
    """11,4 / 0,01 ist in Gleitkommadarstellung 1139,999… — ohne Rundung vor
    floor/ceil fiele der Westrand um eine ganze Kachel zu weit hinaus."""
    w, s, o, n = scan.scan_kachel(11.4, 48.1, 11.42, 48.13)
    assert (w, s, o, n) == (11.4, 48.1, 11.42, 48.13)
    # Werte zwischen den Rastern werden nach außen gerundet.
    w, s, o, n = scan.scan_kachel(11.401, 48.101, 11.419, 48.129)
    assert (w, s, o, n) == (11.4, 48.1, 11.42, 48.13)


def test_umfeldrechnung_mit_bekannten_abstaenden():
    """Drei Zellen: A und B liegen 200 m auseinander (im 300-m-Umfeld
    voneinander), C liegt 1 km entfernt. Ein Betrieb sitzt in A."""
    features = [
        _zelle("A", LAT, LON, 100),
        _zelle("B", LAT + 0.0018, LON, 40),   # ~200 m nördlich
        _zelle("C", LAT + 0.009, LON, 7),     # ~1 km nördlich
    ]
    betriebe = [{"lat": LAT, "lon": LON, "name": "Imbiss A", "typ": "Schnellrestaurant"}]

    zellen, uebersprungen = scan.bewerte(features, betriebe)
    assert uebersprungen == 0
    je_id = {z["id"]: z for z in zellen}

    assert je_id["A"]["einwohner_umfeld"] == 140, "A muss B mitzählen"
    assert je_id["A"]["betriebe_umfeld"] == 1
    assert je_id["A"]["je_betrieb"] == 140

    assert je_id["B"]["betriebe_umfeld"] == 1, "der Betrieb in A liegt 200 m entfernt"
    assert je_id["B"]["je_betrieb"] == 140

    assert je_id["C"]["einwohner_umfeld"] == 7
    assert je_id["C"]["betriebe_umfeld"] == 0
    assert je_id["C"]["je_betrieb"] is None, (
        "kein Betrieb im Umfeld ist eine eigene Aussage, kein hoher Wert"
    )


def test_zellen_ohne_einwohnerangabe_werden_ausgelassen():
    features = [_zelle("A", LAT, LON, 100), _zelle("X", LAT, LON + 0.002, None)]
    zellen, uebersprungen = scan.bewerte(features, [])
    assert uebersprungen == 1
    assert [z["id"] for z in zellen] == ["A"]


class FakeOut:
    """Nur die Netz-Ebene, nach URL verteilt — wie in test_api."""

    def __init__(self, zensus, overpass):
        self.zensus = zensus
        self.overpass = overpass
        self.calls: list[str] = []

    async def post_json(self, source, url, **kw):
        if "arcgis" in url:
            self.calls.append("zensus")
            return self.zensus
        if "interpreter" in url:
            self.calls.append("overpass")
            return self.overpass
        raise AssertionError(f"unerwartete URL: {url}")


def test_load_verbindet_zensus_und_osm(settings, zensus_600, overpass_combined):
    settings.overpass_endpoints = ("https://overpass-api.de/api/interpreter",)
    out = FakeOut(zensus_600, overpass_combined)
    res = asyncio.run(scan.load(out, settings, 11.56, 48.12, 11.58, 48.14))

    assert res.ok
    d = res.data
    assert d["zellen"], "keine Zellen aus dem Fixture"
    assert d["betriebe_gesamt"] > 50, "die Innenstadt-Fixture hat >100 Betriebe"
    # Die kombinierte Punktabfrage enthält auch Haltestellen und Routen — der
    # Scan darf nur Gastronomie zählen.
    assert d["betriebe_gesamt"] < len(overpass_combined["elements"])

    for z in d["zellen"]:
        if z["betriebe_umfeld"] == 0:
            assert z["je_betrieb"] is None
        else:
            assert z["je_betrieb"] == round(z["einwohner_umfeld"] / z["betriebe_umfeld"])

    p = res.provenance
    assert "Zensus" in p.source and "OpenStreetMap" in p.source
    assert "ODbL" in p.license and "Statistische Ämter" in p.license
    assert "15.05.2022" in p.stand
    assert d["hinweise"], "die Grenzen der Kennzahl gehören in die Antwort"
    assert out.calls == ["zensus", "overpass"], "je Quelle genau eine Abfrage"


def test_load_meldet_zensus_fehler_statt_zu_raten(settings, overpass_combined):
    settings.overpass_endpoints = ("https://overpass-api.de/api/interpreter",)

    class Kaputt(FakeOut):
        async def post_json(self, source, url, **kw):
            if "arcgis" in url:
                raise SourceError("timeout", "Zeitüberschreitung.")
            return await super().post_json(source, url, **kw)

    res = asyncio.run(
        scan.load(Kaputt(None, overpass_combined), settings, 11.56, 48.12, 11.58, 48.14)
    )
    assert not res.ok
    assert res.error["kind"] == "timeout"
