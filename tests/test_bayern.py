"""Verkehrsmengen aus der bayerischen Straßenverkehrszählung (BAYSIS).

Die Beispieldaten sind wortgetreue Auszüge aus der echten WFS-Antwort vom
2026-08-01, inklusive der Feldnamen mit Umlauten, die der Dienst liefert.
"""

from __future__ import annotations

import pytest

from gastroviewer.sources import bayern

# A9 bei Fröttmaning — dort liegen echte Zählstellen.
LAT, LON = 48.2100, 11.6150

ECHTE_ANTWORT = {
    "type": "FeatureCollection",
    "features": [
        {
            # 701 m vom Prüfpunkt
            "geometry": {"type": "Point", "coordinates": [11.62429668, 48.21114948]},
            "properties": {
                "OBJECTID": 1,
                "Straße": "A 9",
                "Zählstelle": "9001",
                "Zählart": "TM19",
                "DTV_Kfz": 111624.0,
                "DTV_LV": 105971.0,
                "DTV_SV": 5653.0,
            },
        },
        {
            # 1.638 m — geringere Verkehrsstärke, aber deutlich mehr Schwerverkehr
            "geometry": {"type": "Point", "coordinates": [11.62305891, 48.22372009]},
            "properties": {
                "Straße": "A 99",
                "Zählstelle": "9002",
                "DTV_Kfz": 79216.0,
                "DTV_LV": 68474.0,
                "DTV_SV": 10742.0,
            },
        },
        {
            # 2.691 m — über der Reichweite, muss herausfallen
            "geometry": {"type": "Point", "coordinates": [11.64139872, 48.19338859]},
            "properties": {"Straße": "St 2053", "DTV_Kfz": 10229.0, "DTV_SV": 415.0},
        },
    ],
}


def test_bayerngrenze_spart_den_netzaufruf():
    assert bayern.in_bayern(48.1334, 11.5674) is True   # München
    assert bayern.in_bayern(49.4521, 11.0767) is True   # Nürnberg
    assert bayern.in_bayern(53.0210, 13.2100) is False  # Brandenburg
    assert bayern.in_bayern(50.9413, 6.9583) is False   # Köln


def test_werte_werden_gelesen():
    d = bayern.aufbereiten(ECHTE_ANTWORT["features"], LAT, LON, 600)
    a9 = d["naechste"]
    assert a9["strasse"] == "A 9"
    assert a9["dtv_kfz"] == 111_624
    assert a9["dtv_leichtverkehr"] == 105_971
    assert a9["dtv_schwerverkehr"] == 5_653
    assert a9["distanz_m"] == 701


def test_schwerverkehrsanteil_wird_berechnet():
    d = bayern.aufbereiten(ECHTE_ANTWORT["features"], LAT, LON, 600)
    a99 = next(z for z in d["zaehlstellen"] if z["strasse"] == "A 99")
    assert a99["schwerverkehr_anteil"] == pytest.approx(10742 / 79216 * 100, abs=0.1)
    a9 = next(z for z in d["zaehlstellen"] if z["strasse"] == "A 9")
    assert a9["schwerverkehr_anteil"] < a99["schwerverkehr_anteil"], (
        "die Autobahnring-Zählstelle hat den höheren Schwerverkehrsanteil"
    )


def test_staerkste_wird_getrennt_von_der_naechsten_ausgewiesen():
    """Für die Standortbewertung zählt die stärkste Achse im Umkreis — sie muss
    nicht die nächstgelegene sein."""
    d = bayern.aufbereiten(ECHTE_ANTWORT["features"], LAT, LON, 600)
    assert d["naechste"]["distanz_m"] == min(z["distanz_m"] for z in d["zaehlstellen"])
    assert d["staerkste"]["dtv_kfz"] == max(
        z["dtv_kfz"] for z in d["zaehlstellen"] if z["dtv_kfz"]
    )


def test_ferne_zaehlstellen_fallen_heraus():
    d = bayern.aufbereiten(ECHTE_ANTWORT["features"], LAT, LON, 600)
    assert "St 2053" not in {z["strasse"] for z in d["zaehlstellen"]}
    assert d["max_distanz_m"] == 2000
    assert all(z["distanz_m"] <= 2000 for z in d["zaehlstellen"])


def test_im_radius_wird_getrennt_ausgewiesen():
    d = bayern.aufbereiten(ECHTE_ANTWORT["features"], LAT, LON, 600)
    assert d["im_radius"] == [], "beide Zählstellen liegen weiter als 600 m entfernt"
    weit = bayern.aufbereiten(ECHTE_ANTWORT["features"], LAT, LON, 1800)
    assert len(weit["im_radius"]) == 2


def test_sortierung_nach_entfernung():
    d = bayern.aufbereiten(ECHTE_ANTWORT["features"], LAT, LON, 600)
    e = [z["distanz_m"] for z in d["zaehlstellen"]]
    assert e == sorted(e)


def test_fehlender_dtv_wird_nicht_zu_null():
    features = [{"geometry": {"type": "Point", "coordinates": [11.62429668, 48.21114948]},
                 "properties": {"Straße": "St 2050", "DTV_Kfz": None, "DTV_SV": None}}]
    d = bayern.aufbereiten(features, LAT, LON, 600)
    z = d["zaehlstellen"][0]
    assert z["dtv_kfz"] is None
    assert z["schwerverkehr_anteil"] is None
    assert d["staerkste"] is None, "ohne Wert gibt es keine stärkste Zählstelle"


def test_leere_antwort_bricht_nicht():
    d = bayern.aufbereiten([], LAT, LON, 600)
    assert d["zaehlstellen"] == [] and d["naechste"] is None and d["staerkste"] is None


def test_hinweise_benennen_die_grenzen():
    text = " ".join(bayern.HINWEISE)
    assert "klassifizierte Straßennetz" in text
    assert "Jahresmittel" in text
    assert "keine Kundschaft" in text


async def test_abruf_setzt_bbox_und_format(settings):
    gesehen: dict = {}

    class FakeOut:
        async def get_json(self, source, url, params=None, **kw):
            gesehen.update(params)
            return ECHTE_ANTWORT

    res = await bayern.verkehrsmengen(FakeOut(), settings, LAT, LON, 600)
    assert res.ok
    assert gesehen["typeNames"] == bayern.TYPENAME
    assert gesehen["outputFormat"] == "GEOJSON"
    assert gesehen["srsName"] == "EPSG:4326"
    assert "urn:ogc:def:crs:EPSG::4326" in gesehen["bbox"]
    assert "CC BY 4.0" in res.provenance.license
    assert "Bayerische Straßenbauverwaltung" in res.provenance.license
    assert "Keine Passantenzählung" in res.provenance.note


async def test_ausserhalb_bayerns_kein_netzaufruf(settings):
    class FakeOut:
        async def get_json(self, *a, **kw):
            raise AssertionError("außerhalb Bayerns darf nichts abgerufen werden")

    res = await bayern.verkehrsmengen(FakeOut(), settings, 53.0210, 13.2100, 900)
    assert res.ok and res.data is None
    assert "nur Bayern" in res.warnings[0]


async def test_ohne_zaehlstelle_meldet_das(settings):
    class FakeOut:
        async def get_json(self, *a, **kw):
            return {"type": "FeatureCollection", "features": []}

    res = await bayern.verkehrsmengen(FakeOut(), settings, 48.1334, 11.5674, 600)
    assert res.ok
    assert res.data["zaehlstellen"] == []
    assert "klassifizierte Straßennetz" in res.warnings[0]


async def test_ausfall_wird_benannt(settings):
    from gastroviewer.sources.base import SourceError

    class FakeOut:
        async def get_json(self, *a, **kw):
            raise SourceError("http_status", "HTTP 503 — Serverfehler beim Dienst.")

    res = await bayern.verkehrsmengen(FakeOut(), settings, LAT, LON, 600)
    assert res.ok is False
    assert res.error["kind"] == "http_status"
