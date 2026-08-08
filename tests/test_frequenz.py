"""Gemessene Passantenfrequenz — gegen die am 2026-08-08 aufgezeichneten
echten Antworten aus Dortmund, Würzburg und Augsburg."""

from __future__ import annotations

import asyncio

import pytest

from gastroviewer.sources import frequenz
from gastroviewer.sources.base import SourceError


def test_naechste_zaehlstelle_nur_im_engen_radius():
    """Frequenz gilt für den Straßenabschnitt, nicht fürs Viertel."""
    z = frequenz.naechste_zaehlstelle(51.5143, 7.4654)
    assert z["name"] == "Westenhellweg Ost"
    assert z["stadt"] == "Dortmund"
    assert z["distanz_m"] < 20

    # Marienplatz München: keine offene Zählstelle in Deutschland in der Nähe.
    assert frequenz.naechste_zaehlstelle(48.1374, 11.5755) is None
    # Dortmund Hauptbahnhof (~600 m weiter) liegt außerhalb des Radius.
    assert frequenz.naechste_zaehlstelle(51.5175, 7.4590) is None


def test_naechste_zaehlstelle_waehlt_die_dichteste():
    """Die drei Westenhellweg-Abschnitte liegen dicht beieinander."""
    z = frequenz.naechste_zaehlstelle(51.51398, 7.45791)
    assert z["name"] == "Westenhellweg West"


def test_tagesgang_dortmund(frequenz_fixture):
    kurve = frequenz.parse_tagesgang(
        frequenz_fixture["dortmund_westenhellweg_ost"])
    assert len(kurve) == 24
    assert [k["stunde"] for k in kurve] == list(range(24))
    z = frequenz.naechste_zaehlstelle(51.5143, 7.4654)
    r = frequenz.auswerten(z, kurve)
    assert r["spitzenstunde"] == 16
    assert r["spitze_passanten"] == 2939
    assert r["mittags"] == 2427
    assert r["abendanteil_prozent"] == 24.4


def test_tagesgang_wuerzburg_liest_den_rohen_gruppenschluessel(frequenz_fixture):
    """Würzburgs Opendatasoft-Antwort lässt den Alias „stunde" leer — die
    Stunde steht nur im rohen Gruppenschlüssel `hour(timestamp)`."""
    roh = frequenz_fixture["wuerzburg_schoenbornstrasse"]
    assert roh["results"][0]["stunde"] is None, "Fixture soll den Alias-Fall zeigen"
    kurve = frequenz.parse_tagesgang(roh)
    assert len(kurve) == 24
    z = frequenz.naechste_zaehlstelle(49.7955, 9.9311)
    r = frequenz.auswerten(z, kurve)
    assert r["spitzenstunde"] == 14
    # Die Schönbornstraße leert sich abends fast vollständig — genau die
    # Aussage, für die dieser Block da ist.
    assert r["abendanteil_prozent"] < 10


def test_augsburg_csv_stundenmittel(frequenz_fixture):
    kurve = frequenz.parse_augsburg_csv(
        frequenz_fixture["augsburg_annastrasse_csv"])
    assert kurve, "Auszug muss Stundenwerte ergeben"
    assert all(0 <= k["stunde"] <= 23 for k in kurve)
    z = frequenz.naechste_zaehlstelle(48.3700, 10.8958)
    r = frequenz.auswerten(z, kurve)
    assert r["stadt"] == "Augsburg"
    assert r["spitze_passanten"] > 0


def test_auswerten_ohne_kurve_scheitert_mit_begruendung():
    z = frequenz.naechste_zaehlstelle(51.5143, 7.4654)
    with pytest.raises(SourceError) as err:
        frequenz.auswerten(z, [])
    assert "keine Stundenwerte" in err.value.message


def test_load_ohne_zaehlstelle_bleibt_ehrlich_leer():
    """Kein Zähler in der Nähe heißt „nicht gemessen", nicht „wenig los"."""

    class Nie:
        async def get_json(self, *a, **k):  # pragma: no cover
            raise AssertionError("Ohne Zählstelle darf nichts hinausgehen.")

    res = asyncio.run(frequenz.load(Nie(), 48.1334, 11.5674))
    assert res.ok and res.data is None
    assert any("nicht gemessen" in w for w in res.warnings)
    # Oldenburg wird als bewusst nicht aufgenommen benannt.
    assert any("Oldenburg" in w for w in res.warnings)


def test_load_dortmund_baut_die_richtige_abfrage(frequenz_fixture):
    aufrufe = []

    class Fake:
        async def get_json(self, source, url, **kw):
            aufrufe.append((source, url, kw.get("params")))
            return frequenz_fixture["dortmund_westenhellweg_ost"]

    res = asyncio.run(frequenz.load(Fake(), 51.5143, 7.4654))
    assert res.ok and res.data
    assert res.data["zaehlstelle"] == "Westenhellweg Ost"
    assert "dl-de/zero-2-0" in res.provenance.license
    quelle, url, params = aufrufe[0]
    assert quelle == "frequenz_dortmund"
    assert "open-data.dortmund.de" in url
    assert params["group_by"] == "stunde"
    assert "Westenhellweg (Ost)" in params["where"]


def test_wuerzburg_lizenz_nennt_hystreet(frequenz_fixture):
    class Fake:
        async def get_json(self, *a, **kw):
            return frequenz_fixture["wuerzburg_kaiserstrasse"]

    res = asyncio.run(frequenz.load(Fake(), 49.7985, 9.9339))
    assert res.ok
    # Namensnennung ist bei dl-de/by Pflicht — hystreet muss dastehen.
    assert "hystreet" in res.provenance.license.lower()
    assert "dl-de/by-2-0" in res.provenance.license
