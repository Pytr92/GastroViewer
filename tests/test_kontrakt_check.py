"""Die Vergleichslogik des Kontrakt-Checks — offline, mit Attrappen. Den
Netzlauf macht der monatliche Workflow."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from gastroviewer.config import Settings
from gastroviewer.sources import indikatoren, klima, zensus


def _modul():
    pfad = Path(__file__).resolve().parents[1] / "scripts" / "kontrakt_check.py"
    spec = importlib.util.spec_from_file_location("kontrakt_check", pfad)
    modul = importlib.util.module_from_spec(spec)
    sys.modules["kontrakt_check"] = modul
    spec.loader.exec_module(modul)
    return modul


class FakeOut:
    def __init__(self, json=None, text=""):
        self._json, self._text = json, text

    async def get_json(self, source, url, **kw):
        return self._json

    async def get_text(self, source, url, **kw):
        return self._text


@pytest.fixture(scope="module")
def kc():
    return _modul()


async def test_zensus_felder_und_seitengroesse(kc, zensus_meta):
    s = Settings()
    assert await kc.zensus_felder(FakeOut(json=zensus_meta), s) == []
    kaputt = {"fields": [{"name": "GITTER_ID_100m"}], "maxRecordCount": 100}
    befunde = await kc.zensus_felder(FakeOut(json=kaputt), s)
    assert any("Einwohner" in b for b in befunde)
    assert any("maxRecordCount" in b for b in befunde)


async def test_dwd_dateinamen(kc):
    s = Settings()
    listing = "\n".join(f'<a href="{p["datei"]}{e}">' for p in klima.PARAMETER
                        for e in (".txt", "_Stationsliste.txt"))
    assert await kc.dwd_dateien(FakeOut(text=listing), s) == []
    befunde = await kc.dwd_dateien(FakeOut(text="<html>leer</html>"), s)
    assert len(befunde) == 2 * len(klima.PARAMETER)


async def test_ckan_indikatoren(kc, muenchen_indikatoren):
    s = Settings()
    assert await kc.ckan_indikatoren(FakeOut(json=muenchen_indikatoren["suche"]), s) == []
    befunde = await kc.ckan_indikatoren(FakeOut(json={"result": {"results": []}}), s)
    assert len(befunde) >= len(indikatoren.DATEIEN)


def test_pruefliste_deckt_vier_vertraege(kc):
    assert len(kc.PRUEFUNGEN) == 4
    assert zensus.FIELDS  # der Vertrag, den Prüfung 1 liest
