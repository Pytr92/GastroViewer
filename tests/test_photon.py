"""Photon-Rückfall fürs Geocoding — gegen die echten Antworten von
photon.komoot.io vom 2026-08-07 (Suche „Sendlinger Str 10 München",
Reverse am Sendlinger Tor)."""

from __future__ import annotations

import asyncio

from gastroviewer.sources import nominatim
from gastroviewer.sources.base import SourceError


class NominatimTotPhotonLebt:
    """Nominatim-Aufrufe scheitern, Photon antwortet mit der Fixture."""

    def __init__(self, photon_antwort):
        self.photon_antwort = photon_antwort
        self.urls: list[str] = []

    async def get_json(self, source, url, **kw):
        self.urls.append(url)
        if "photon" in url:
            return self.photon_antwort
        raise SourceError("timeout", "Zeitüberschreitung — Dienst antwortet nicht.")


class BeideTot:
    async def get_json(self, source, url, **kw):
        raise SourceError(
            "timeout" if "photon" not in url else "connect",
            "Zeitüberschreitung — Dienst antwortet nicht."
            if "photon" not in url else "Photon auch nicht erreichbar.")


def test_photon_shape_suche_hausnummerngenau(photon):
    d = nominatim.photon_shape(photon["search"]["features"][0])
    assert d["strasse"] == "Sendlinger Straße"
    assert d["hausnummer"] == "10"
    assert d["plz"] == "80331"
    assert d["gemeinde"] == "München"
    assert d["bundesland"] == "Bayern"
    assert d["bundesland_iso"] is None, "Photon führt kein ISO — nie raten"
    assert d["lat"] and d["lon"]
    assert "OpenStreetMap" in d["licence"]


def test_photon_shape_reverse(photon):
    d = nominatim.photon_shape(photon["reverse"]["features"][0])
    assert d["gemeinde"] == "München"
    assert d["ortsteil"] in ("Altstadt", "Hackenviertel")
    assert d["plz"] == "80336"


def test_reverse_faellt_auf_photon_zurueck(settings, photon):
    out = NominatimTotPhotonLebt(photon["reverse"])
    res = asyncio.run(nominatim.reverse(out, settings, 48.1334, 11.5674))
    assert res.ok
    assert res.data["gemeinde"] == "München"
    assert any("Photon" in w for w in res.warnings)
    assert "Photon" in res.provenance.source
    # Reihenfolge: erst Nominatim versucht, dann Photon.
    assert "photon" in out.urls[-1]


def test_suche_faellt_auf_photon_zurueck_mit_de_filter(settings, photon):
    out = NominatimTotPhotonLebt(photon["search"])
    res = asyncio.run(nominatim.search(out, settings, "Sendlinger Str 10 München"))
    assert res.ok
    assert res.data[0]["hausnummer"] == "10"
    assert all((f["adresse_roh"].get("countrycode") or "DE") == "DE"
               for f in res.data)


def test_beide_geocoder_tot_meldet_nominatim_fehler(settings):
    res = asyncio.run(nominatim.reverse(BeideTot(), settings, 48.1, 11.5))
    assert not res.ok
    # Der urspruengliche Nominatim-Fehler zaehlt, nicht der Photon-Fehler.
    assert "Zeitüberschreitung" in res.error["message"]
