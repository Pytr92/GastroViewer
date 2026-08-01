"""Zensus-Auswertung gegen die echte Antwort aus Phase 0."""

from __future__ import annotations

import pytest

from gastroviewer.sources import zensus

# Der Punkt, mit dem die Fixture aufgezeichnet wurde (Sendlinger Tor, München).
LAT, LON = 48.1334, 11.5674


def test_fixture_ist_die_echte_antwort(zensus_600):
    """Absicherung gegen versehentlich ausgedachte Testdaten."""
    assert zensus_600["geometryType"] == "esriGeometryPolygon"
    assert zensus_600["spatialReference"]["wkid"] == 4326
    assert len(zensus_600["features"]) == 118


def test_alle_spec_felder_existieren_im_dienst(zensus_meta):
    """§4.1 listet die Feldnamen. Phase 0 hat sie bestätigt — hier festgehalten,
    damit eine Umbenennung beim Anbieter sofort auffällt."""
    vorhanden = {f["name"] for f in zensus_meta["fields"]}
    fehlend = [f for f in zensus.FIELDS if f not in vorhanden]
    assert not fehlend, f"Diese Felder gibt es im Dienst nicht mehr: {fehlend}"
    assert zensus_meta["maxRecordCount"] == 2000


def test_zellen_bekommen_mittelpunkt_und_ring(zensus_600):
    cells = zensus.build_cells(zensus_600["features"])
    assert len(cells) == 118
    assert all("_center" in c and "_ring" in c for c in cells)


def test_zelle_am_punkt_wird_gefunden(zensus_600):
    cells = zensus.build_cells(zensus_600["features"])
    center = zensus.pick_center_cell(cells, LAT, LON)
    assert center is not None
    assert center["ags"] == "09162000"


def test_kein_treffer_gibt_none_statt_falscher_zelle(zensus_600):
    """Lieber nichts ausweisen als die falsche Zelle als Standortzelle verkaufen."""
    cells = zensus.build_cells(zensus_600["features"])
    assert zensus.pick_center_cell(cells, 52.0, 9.0) is None


def test_summe_einwohner_ist_echte_summe(zensus_600):
    cells = zensus.build_cells(zensus_600["features"])
    data = zensus.summarize(cells, LAT, LON)
    erwartet = sum(
        f["attributes"]["Einwohner"]
        for f in zensus_600["features"]
        if f["attributes"].get("Einwohner") is not None
    )
    assert data["bevoelkerung"]["einwohner"]["wert"] == erwartet
    assert data["bevoelkerung"]["einwohner"]["zellen"] == 118


def test_null_zaehlt_nicht_als_null_wert(zensus_600):
    """durchschnMieteQM ist in einigen Zellen null. Diese Zellen dürfen den
    Mittelwert nicht nach unten ziehen."""
    cells = zensus.build_cells(zensus_600["features"])
    data = zensus.summarize(cells, LAT, LON)
    miete = data["wohnen"]["miete_qm"]
    mit_wert = [
        f["attributes"]["durchschnMieteQM"]
        for f in zensus_600["features"]
        if f["attributes"].get("durchschnMieteQM") is not None
    ]
    assert miete["zellen"] == len(mit_wert)
    assert miete["zellen"] < miete["zellen_gesamt"], "Fixture sollte Nullwerte enthalten"
    assert miete["min"] >= min(mit_wert) - 0.01
    assert miete["wert"] >= miete["min"]


def test_cell_key_abweichung_wird_ausgewiesen(zensus_600):
    """Die stochastische Überlagerung darf nicht weggerechnet werden."""
    cells = zensus.build_cells(zensus_600["features"])
    data = zensus.summarize(cells, LAT, LON)
    summe_gruppen = sum(
        v["wert"] for v in data["bevoelkerung"]["altersgruppen"].values() if v
    )
    einwohner = data["bevoelkerung"]["einwohner"]["wert"]
    if abs(summe_gruppen - einwohner) >= 1:
        assert data["hinweise"], "Abweichung vorhanden, aber kein Hinweis erzeugt"
        assert "Cell-Key" in data["hinweise"][0]


def test_bundesland_aus_ags():
    assert zensus.bundesland_from_ags("09162000") == ("09", "Bayern")
    assert zensus.bundesland_from_ags("12065256") == ("12", "Brandenburg")
    assert zensus.bundesland_from_ags(None) == (None, None)
    assert zensus.bundesland_from_ags("9") == (None, None)


def test_gewichtetes_mittel_und_median(zensus_600):
    cells = zensus.build_cells(zensus_600["features"])
    agg = zensus.Aggregate(cells)
    alter = agg.mean_weighted("Durchschnittsalter")
    assert alter["gewichtung"] == "nach Einwohner gewichtet"
    assert alter["min"] <= alter["median"] <= alter["max"]
    assert alter["min"] <= alter["wert"] <= alter["max"]


def test_leere_zellenliste_bricht_nicht():
    data = zensus.summarize([], LAT, LON)
    assert data["zellen_gefunden"] == 0
    assert data["bevoelkerung"]["einwohner"] is None
    assert data["ags"] is None


@pytest.mark.parametrize(
    "fixture_name,erwartet",
    [("zensus_exceeded", True), ("zensus_offset", None)],
)
def test_exceeded_transfer_limit_nur_wenn_true(request, fixture_name, erwartet):
    """Phase-0-Befund A-2: Der Schlüssel fehlt, wenn er false wäre."""
    payload = request.getfixturevalue(fixture_name)
    assert payload.get("exceededTransferLimit") is erwartet


async def test_paginierung_holt_alle_seiten(settings, monkeypatch, zensus_exceeded, zensus_offset):
    """Simuliert den in Phase 0 gemessenen Fall r=3000: 2000 + 6 Features."""
    seiten = [zensus_exceeded, zensus_offset]
    aufrufe: list[dict] = []

    class FakeOut:
        async def post_json(self, source, url, data=None, timeout=None, **kw):
            aufrufe.append(dict(data))
            return seiten[len(aufrufe) - 1]

    features, warnings = await zensus.fetch_cells(FakeOut(), settings, LAT, LON, 3000)
    assert len(aufrufe) == 2
    assert "resultOffset" not in aufrufe[0]
    assert aufrufe[1]["resultOffset"] == "2000"
    assert len(features) == 2006
    assert not warnings


async def test_seitenlimit_wird_gemeldet_statt_still_abzuschneiden(
    settings, zensus_exceeded
):
    settings.zensus_max_pages = 2

    class FakeOut:
        async def post_json(self, source, url, data=None, timeout=None, **kw):
            return zensus_exceeded  # meldet immer weiter „es gibt mehr"

    features, warnings = await zensus.fetch_cells(FakeOut(), settings, LAT, LON, 5000)
    assert warnings and "unvollständig" in warnings[0]


async def test_api_fehler_wird_als_solcher_gemeldet(settings):
    from gastroviewer.sources.base import SourceError

    class FakeOut:
        async def post_json(self, source, url, data=None, timeout=None, **kw):
            return {"error": {"code": 400, "message": "Unable to complete operation."}}

    with pytest.raises(SourceError) as exc:
        await zensus.fetch_cells(FakeOut(), settings, LAT, LON, 600)
    assert exc.value.kind == "api_error"
    assert "400" in exc.value.message
