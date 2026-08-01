"""Planungsrecht und Hochwasserrisiko.

Die Beispieldaten sind wortgetreue Auszüge aus den echten Antworten vom
2026-08-01 — inklusive der Feldnamen mit Umlauten, die die Dienste liefern.
"""

from __future__ import annotations

import pytest

from gastroviewer.sources import planung

# Isarauen Thalkirchen — dort greift HQ 100 wirklich.
ECHTE_HOCHWASSER = {
    "type": "FeatureCollection",
    "features": [
        {
            "properties": {
                "Gewässername": "Isar",
                "Jährlichkeit": "HQ 100",
                "Ermittlungsdatum": "30.09.2016",
                "link_Zuständiges Wasserwirtschaftsamt": "http://www.wwa-m.bayern.de",
            }
        },
        {
            "properties": {
                "Gewässername": "Isar",
                "Jährlichkeit": "HQ extrem",
                "Ermittlungsdatum": "30.09.2016",
            }
        },
    ],
}

# Freiham — dort gibt es einen Bebauungsplan.
ECHTE_BPLAN = {
    "type": "FeatureCollection",
    "features": [{"properties": {"objectid": 1197, "nr_plan": "A1856", "nr_va": "unbekannt"}}],
}

LEER = {"type": "FeatureCollection", "features": []}


# ------------------------------------------------------------- Abfrage


def test_abfrage_nutzt_crs84_statt_4326():
    """Beide Dienste führen EPSG:4326 nicht in ihrer CRS-Liste und antworten
    damit mit einer leeren Trefferliste statt mit einem Fehler — das sähe aus
    wie „nicht betroffen" und wäre es nicht."""
    p = planung.feature_info_params(planung.HOCHWASSER_LAYER, 48.105, 11.553)
    assert p["crs"] == "CRS:84"
    assert "4326" not in str(p)
    # CRS:84 ist lon,lat — die Box muss in dieser Reihenfolge stehen.
    lo1, la1, lo2, la2 = (float(x) for x in p["bbox"].split(","))
    # Der Prüfpunkt liegt bei lon 11,55 / lat 48,10 — die Länge steht vorne.
    assert 11 < lo1 < 12 and 11 < lo2 < 12, (
        f"Reihenfolge vertauscht: CRS:84 ist lon,lat, bekommen {p['bbox']}"
    )
    assert 48 < la1 < 49 and 48 < la2 < 49
    assert lo1 < lo2 and la1 < la2, "die Box muss aufsteigend sein"
    assert p["i"] == "50" and p["j"] == "50", "abgefragt wird die Bildmitte"


def test_regionen_sparen_den_netzaufruf():
    assert planung.in_bayern(48.1372, 11.5755) is True
    assert planung.in_bayern(50.9413, 6.9583) is False
    assert planung.in_muenchen(48.1372, 11.5755) is True
    assert planung.in_muenchen(49.4521, 11.0767) is False, "Nürnberg ist nicht München"


# --------------------------------------------------------- Hochwasser


def test_hochwasser_wird_nach_jaehrlichkeit_geordnet():
    d = planung.hochwasser_aufbereiten(ECHTE_HOCHWASSER)
    assert d["betroffen"] is True
    assert d["hq_100"] is True and d["hq_extrem"] is True
    assert d["hq_haeufig"] is False, "HQhäufig war in dieser Antwort nicht dabei"
    assert d["gebiete"][0]["gewaesser"] == "Isar"
    assert d["gebiete"][0]["ermittelt"] == "30.09.2016"
    assert "wwa-m" in d["gebiete"][0]["amt"]


def test_ohne_treffer_ist_der_punkt_nicht_betroffen():
    d = planung.hochwasser_aufbereiten(LEER)
    assert d["betroffen"] is False
    assert d["gebiete"] == []
    assert not any((d["hq_haeufig"], d["hq_100"], d["hq_extrem"]))


def test_rohwerte_bleiben_erhalten():
    """Spec §5: der Nutzer muss sehen können, was der Dienst wirklich sagte."""
    d = planung.hochwasser_aufbereiten(ECHTE_HOCHWASSER)
    assert d["gebiete"][0]["rohwerte"]["Jährlichkeit"] == "HQ 100"


# ------------------------------------------------------ Bebauungsplan


def test_bebauungsplan_liefert_die_nummer():
    d = planung.bplan_aufbereiten(ECHTE_BPLAN)
    assert d["vorhanden"] is True
    assert d["plaene"][0]["nummer"] == "A1856"
    assert d["plaene"][0]["verfahren"] is None, "'unbekannt' ist keine Verfahrensnummer"


def test_ohne_plan_wird_nichts_behauptet():
    d = planung.bplan_aufbereiten(LEER)
    assert d["vorhanden"] is False and d["plaene"] == []


def test_hinweise_widersprechen_dem_fehlschluss():
    text = " ".join(planung.HINWEISE)
    assert "§ 34 BauGB" in text, (
        "kein Plan heisst nicht 'alles erlaubt' — das muss dastehen"
    )
    assert "nicht, was er" in text, "die Nummer allein sagt nichts über den Inhalt"
    assert "keine Zusage" in text


# ------------------------------------------------------------- Ablauf


async def test_ausserhalb_bayerns_kein_netzaufruf(settings):
    class FakeOut:
        async def get_json(self, *a, **kw):
            raise AssertionError("außerhalb Bayerns darf nichts abgerufen werden")

    res = await planung.load(FakeOut(), settings, 50.9413, 6.9583, 600)
    assert res.ok and res.data is None
    assert "Bayern" in res.warnings[0]


async def test_ausserhalb_muenchens_nur_hochwasser(settings):
    gesehen = []

    class FakeOut:
        async def get_json(self, source, url, **kw):
            gesehen.append(source)
            return ECHTE_HOCHWASSER

    res = await planung.load(FakeOut(), settings, 49.4521, 11.0767, 600)  # Nürnberg
    assert res.ok
    assert gesehen == ["lfu_hochwasser"], "der Münchner Dienst darf nicht gefragt werden"
    assert "bebauungsplan" not in res.data
    assert any("München" in w for w in res.warnings)


async def test_in_muenchen_werden_beide_dienste_gefragt(settings):
    class FakeOut:
        async def get_json(self, source, url, **kw):
            return ECHTE_HOCHWASSER if source == "lfu_hochwasser" else ECHTE_BPLAN

    res = await planung.load(FakeOut(), settings, 48.1450, 11.4200, 600)
    assert res.ok
    assert res.data["hochwasser"]["hq_100"] is True
    assert res.data["bebauungsplan"]["plaene"][0]["nummer"] == "A1856"
    assert "CC BY 4.0" in res.provenance.license
    assert "dl-de/by-2-0" in res.provenance.license


async def test_ausfall_des_staedtischen_dienstes_reisst_den_block_nicht(settings):
    """Der Hochwasserteil muss stehen bleiben, wenn München ausfällt."""
    from gastroviewer.sources.base import SourceError

    class FakeOut:
        async def get_json(self, source, url, **kw):
            if source == "muenchen_bplan":
                raise SourceError("timeout", "Zeitüberschreitung nach 60 s.")
            return ECHTE_HOCHWASSER

    res = await planung.load(FakeOut(), settings, 48.1450, 11.4200, 600)
    assert res.ok is True
    assert res.data["hochwasser"]["betroffen"] is True
    assert "bebauungsplan" not in res.data
    assert any("Zeitüberschreitung" in w for w in res.warnings)


async def test_ausfall_des_hochwasserdienstes_wird_benannt(settings):
    from gastroviewer.sources.base import SourceError

    class FakeOut:
        async def get_json(self, *a, **kw):
            raise SourceError("http_status", "HTTP 503 — Serverfehler beim Dienst.")

    res = await planung.load(FakeOut(), settings, 48.1450, 11.4200, 600)
    assert res.ok is False
    assert res.error["kind"] == "http_status"
