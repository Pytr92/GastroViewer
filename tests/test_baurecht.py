"""Baurecht am Punkt — gegen die am 2026-08-08 aufgezeichneten echten
WFS-Antworten aus Hamburg, Freiburg und Berlin."""

from __future__ import annotations

import asyncio

import pytest

from gastroviewer.sources import baurecht
from gastroviewer.sources.base import SourceError


def test_bbox_nutzt_crs84_in_lon_lat():
    """Mit EPSG::4326 liefern die deegree-Dienste stumm null Treffer —
    die Achsenreihenfolge ist die zentrale Implementierungsfalle."""
    b = baurecht._bbox(53.5503, 9.9937)
    lon_min, lat_min, lon_max, lat_max, crs = b.split(",")
    assert crs == "urn:ogc:def:crs:OGC:1.3:CRS84"
    assert float(lon_min) < 9.9937 < float(lon_max)
    assert float(lat_min) < 53.5503 < float(lat_max)


def test_dienst_nur_im_zustaendigen_gebiet():
    assert baurecht.dienst_fuer(53.5503, 9.9937)["gebiet"] == "Hamburg"
    assert baurecht.dienst_fuer(47.9959, 7.8522)["gebiet"].startswith("Freiburg")
    # München hat keine offenen Bauleitplandaten.
    assert baurecht.dienst_fuer(48.1334, 11.5674) is None


def test_baunvo_deutung_trennt_zulaessig_von_unzulaessig():
    mk = baurecht.deuten("Kerngebiet")
    assert mk["kuerzel"] == "MK" and "allgemein zulässig" in mk["gastronomie"]
    wr = baurecht.deuten("ReinesWohngebiet")
    assert wr["kuerzel"] == "WR" and "unzulässig" in wr["gastronomie"]
    gi = baurecht.deuten("Industriegebiet")
    assert "unzulässig" in gi["gastronomie"]
    # Unbekannte Arten werden nicht erfunden.
    unbekannt = baurecht.deuten("Phantasiegebiet")
    assert unbekannt["kuerzel"] is None
    assert baurecht.deuten(None) is None


def test_hamburg_innenstadt_ist_kerngebiet(baurecht_fixture):
    """Die Bbox liefert sechs Kandidaten — nur einer enthält den Punkt.
    Ohne die Geometrieprüfung stünde hier womöglich die Gebietsart des
    Nachbargrundstücks."""
    p = baurecht_fixture["hamburg_innenstadt_punkt"]
    roh = baurecht_fixture["hamburg_innenstadt"]
    assert len(roh["features"]) == 6, "Fixture soll Nachbarflächen enthalten"
    flaechen = baurecht.parse_baugebiete(roh, p["lat"], p["lon"])
    assert len(flaechen) == 1
    f = flaechen[0]
    assert f["plan"] == "BSInnenstadt"
    assert f["art"] == "Kerngebiet"
    assert f["deutung"]["kuerzel"] == "MK"
    assert f["allgemeine_art"] == "GemischteBauflaeche"
    assert "Geschäftsgebiet" in f["text"]


def test_freiburg_innenstadt_ist_kerngebiet(baurecht_fixture):
    flaechen = baurecht.parse_baugebiete(
        baurecht_fixture["freiburg_innenstadt"])
    assert flaechen and flaechen[0]["art"] == "Kerngebiet"


def test_berlin_umring_filtert_untergegangene_plaene(baurecht_fixture):
    plaene = baurecht.parse_berlin_bplan(
        baurecht_fixture["berlin_bplan_alexanderplatz"])
    namen = [p["plan"] for p in plaene]
    # I-B4a ist „Teilweise untergegangen" und gehört nicht in die Anzeige.
    assert "I-B4a" not in namen
    assert "I-B4ba" in namen
    assert all(p["rechtsstand"] == "In Kraft getreten" for p in plaene)
    assert all(p["pdf"].endswith(".pdf") for p in plaene)


def test_berlin_sanierung_und_denkmal(baurecht_fixture):
    s = baurecht.parse_berlin_sanierung(
        baurecht_fixture["berlin_sanierung_luisenstadt"])
    assert s[0]["name"] == "Nördliche Luisenstadt"
    assert s[0]["verfahren"] == "umfassend"
    dn = baurecht.parse_berlin_denkmal(
        baurecht_fixture["berlin_denkmale_alexanderplatz"])
    assert len(dn) == 5
    assert all(x["link"].startswith("https://") for x in dn)


def test_load_hamburg_meldet_gebietsart(baurecht_fixture):
    class Fake:
        async def get_json(self, source, url, **kw):
            assert kw["params"]["TYPENAMES"] == "xplan:BP_BaugebietsTeilFlaeche"
            return baurecht_fixture["hamburg_innenstadt"]

    p = baurecht_fixture["hamburg_innenstadt_punkt"]
    res = asyncio.run(baurecht.load(Fake(), p["lat"], p["lon"]))
    assert res.ok
    assert res.data["stufe"] == "gebietsart"
    assert res.data["gebiet"] == "Hamburg"
    assert res.data["baugebiete"][0]["deutung"]["kuerzel"] == "MK"
    assert "dl-de/by-2-0" in res.provenance.license


def test_load_berlin_warnt_bei_sanierung_und_denkmal(baurecht_fixture):
    class Fake:
        async def get_json(self, source, url, **kw):
            if "sanier" in url:
                return baurecht_fixture["berlin_sanierung_luisenstadt"]
            if "denkmale" in url:
                return baurecht_fixture["berlin_denkmale_alexanderplatz"]
            return baurecht_fixture["berlin_bplan_alexanderplatz"]

    res = asyncio.run(baurecht.load(Fake(), 52.5210, 13.4130))
    assert res.ok and res.data["stufe"] == "umring"
    assert any("144/145" in w for w in res.warnings)
    assert any("Denkmalschutz" in w for w in res.warnings)


def test_load_ohne_plan_nennt_paragraf_34(baurecht_fixture):
    """Kein Plan ist eine echte Aussage, keine Fehlanzeige."""

    class Leer:
        async def get_json(self, *a, **kw):
            return {"features": []}

    res = asyncio.run(baurecht.load(Leer(), 53.5503, 9.9937))
    assert res.ok
    assert res.data["stufe"] == "kein_plan" and res.data["paragraf_34"]
    assert any("§ 34 BauGB" in w for w in res.warnings)


def test_load_ohne_dienst_sagt_das_offen():
    class Nie:
        async def get_json(self, *a, **kw):  # pragma: no cover
            raise AssertionError("Ohne Dienst darf nichts hinausgehen.")

    res = asyncio.run(baurecht.load(Nie(), 48.1334, 11.5674))
    assert res.ok and res.data["stufe"] == "kein_dienst"
    assert any("München behält sich" in w for w in res.warnings)


def test_tls_fehler_wird_uebersetzt():
    """Berlins Geodienst nutzt ein Wurzelzertifikat, das ältere
    Zertifikatsspeicher nicht kennen — der Nutzer soll das verstehen."""

    class Kaputt:
        async def get_json(self, *a, **kw):
            raise SourceError("network", "SSL: certificate verify failed",
                              detail="unable to get local issuer certificate")

    # ``load`` wirft; der Service macht daraus ein Fehlerergebnis je Block.
    with pytest.raises(SourceError) as err:
        asyncio.run(baurecht.load(Kaputt(), 52.5210, 13.4130))
    assert err.value.kind == "tls"
    assert "certifi" in err.value.message
    assert "Wurzelzertifikat" in err.value.message


def test_sperrzeiten_werden_als_nicht_vorhanden_benannt():
    assert any("Sperrzeiten" in h for h in baurecht.HINWEISE)


def test_xplan_verlangt_geojson_format(baurecht_fixture):
    """Die XPlanSyn-Dienste antworten nur auf „application/geo+json";
    mit „application/json" gibt es HTTP 400 (in Phase 0 belegt)."""
    formate = []

    class Fake:
        async def get_json(self, source, url, **kw):
            formate.append(kw["params"]["outputFormat"])
            return baurecht_fixture["hamburg_innenstadt"]

    p = baurecht_fixture["hamburg_innenstadt_punkt"]
    asyncio.run(baurecht.load(Fake(), p["lat"], p["lon"]))
    assert formate == ["application/geo+json"]


def test_berlin_bleibt_bei_application_json(baurecht_fixture):
    formate = []

    class Fake:
        async def get_json(self, source, url, **kw):
            formate.append(kw["params"]["outputFormat"])
            if "sanier" in url:
                return baurecht_fixture["berlin_sanierung_luisenstadt"]
            if "denkmale" in url:
                return baurecht_fixture["berlin_denkmale_alexanderplatz"]
            return baurecht_fixture["berlin_bplan_alexanderplatz"]

    asyncio.run(baurecht.load(Fake(), 52.5210, 13.4130))
    assert set(formate) == {"application/json"}


def test_punkt_in_polygon():
    """Strahlverfahren, an einem Quadrat und einem Polygon mit Loch."""
    quadrat = {"type": "Polygon",
               "coordinates": [[[0, 0], [0, 2], [2, 2], [2, 0], [0, 0]]]}
    assert baurecht.enthaelt_punkt(quadrat, 1, 1)
    assert not baurecht.enthaelt_punkt(quadrat, 3, 1)
    mit_loch = {"type": "Polygon", "coordinates": [
        [[0, 0], [0, 4], [4, 4], [4, 0], [0, 0]],
        [[1, 1], [1, 3], [3, 3], [3, 1], [1, 1]]]}
    assert baurecht.enthaelt_punkt(mit_loch, 0.5, 0.5)
    assert not baurecht.enthaelt_punkt(mit_loch, 2, 2), "Loch zählt nicht"
    assert not baurecht.enthaelt_punkt(None, 1, 1)


def test_freiburg_punktpruefung_greift_auch_dort(baurecht_fixture):
    """Ohne Koordinaten bleiben alle Kandidaten, mit Koordinaten eines
    fernen Punktes keiner."""
    roh = baurecht_fixture["freiburg_innenstadt"]
    assert baurecht.parse_baugebiete(roh)
    assert baurecht.parse_baugebiete(roh, 48.13, 11.57) == []
