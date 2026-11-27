"""Nominatim: Such- und Reverse-Pfad sowie Fehlerantworten mit Photon-Rückfall.

Gültige Antworten stammen aus den aufgezeichneten Fixtures. Die Fehler-Payloads
(``{"error": ...}``, Liste statt Objekt) sind bewusst minimal konstruiert: Der
Dienst liefert sie nur sporadisch, eine Aufzeichnung ist nicht reproduzierbar."""

from __future__ import annotations

import asyncio

import pytest

from gastroviewer.sources import nominatim
from gastroviewer.sources.base import SourceError


class Fake:
    """Nominatim antwortet mit ``nominatim_antwort``; Photon mit ``photon_antwort``
    (``None`` = Photon nicht erreichbar)."""

    def __init__(self, nominatim_antwort, photon_antwort=None):
        self.nominatim_antwort = nominatim_antwort
        self.photon_antwort = photon_antwort
        self.urls: list[str] = []

    async def get_json(self, source, url, **kw):
        self.urls.append(url)
        if "photon" in url:
            if self.photon_antwort is None:
                raise SourceError("connect", "Photon nicht erreichbar.")
            return self.photon_antwort
        return self.nominatim_antwort


def test_suche_gueltige_antwort(settings, nominatim_search):
    out = Fake(nominatim_search)
    res = asyncio.run(nominatim.search(out, settings, "Sendlinger Str 10 München"))
    assert res.ok and res.data
    assert res.provenance.source.startswith("Nominatim")
    assert not any("photon" in u for u in out.urls)


def test_suche_leere_liste_ist_keine_treffer(settings):
    out = Fake([])
    res = asyncio.run(nominatim.search(out, settings, "Xyzzy"))
    assert res.ok and res.data == []
    assert any("Keine Treffer" in w for w in res.warnings)
    assert not any("photon" in u for u in out.urls), "leere Liste ist gültig"


def test_suche_error_dict_loest_photon_rueckfall_aus(settings, photon):
    out = Fake({"error": "Rate limit exceeded"}, photon["search"])
    res = asyncio.run(nominatim.search(out, settings, "Sendlinger Str 10 München"))
    assert res.ok and res.data
    assert "Photon" in res.provenance.source
    assert any("Rate limit exceeded" in w for w in res.warnings)


def test_suche_nicht_liste_loest_photon_rueckfall_aus(settings, photon):
    out = Fake("<html>Bad Gateway</html>", photon["search"])
    res = asyncio.run(nominatim.search(out, settings, "Sendlinger Str 10 München"))
    assert res.ok and res.data
    assert "Photon" in res.provenance.source
    assert any("str" in w for w in res.warnings)


def test_suche_nicht_liste_und_photon_tot_ist_fehler(settings):
    res = asyncio.run(nominatim.search(Fake({"error": "kaputt"}), settings, "x"))
    assert not res.ok, "Ausfall darf nie als „keine Treffer“ erscheinen"
    assert res.error["kind"] == "api_error"
    assert "kaputt" in res.error["message"]


def test_reverse_gueltige_antwort(settings, nominatim_reverse):
    out = Fake(nominatim_reverse)
    res = asyncio.run(nominatim.reverse(out, settings, 48.1334, 11.5674))
    assert res.ok and res.data["gemeinde"]
    assert not any("photon" in u for u in out.urls)


def test_reverse_error_dict_ist_keine_adresse(settings):
    # Nominatim: Punkt ohne Adresse — gültige Antwort, kein Rückfall.
    out = Fake({"error": "Unable to geocode"})
    res = asyncio.run(nominatim.reverse(out, settings, 0.0, 0.0))
    assert res.ok and res.data is None
    assert any("Unable to geocode" in w for w in res.warnings)


def test_reverse_nicht_dict_ist_sourceerror_wenn_photon_tot(settings):
    res = asyncio.run(nominatim.reverse(Fake([]), settings, 48.1, 11.5))
    assert not res.ok
    assert res.error["kind"] == "parse"
    assert "list" in res.error["message"]


def test_reverse_nicht_dict_faellt_auf_photon_zurueck(settings, photon):
    out = Fake([], photon["reverse"])
    res = asyncio.run(nominatim.reverse(out, settings, 48.1334, 11.5674))
    assert res.ok and res.data["gemeinde"] == "München"
    assert "Photon" in res.provenance.source
