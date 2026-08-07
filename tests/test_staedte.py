"""Stadt-Adapter Hamburg und Berlin (W6) — gegen die echten Antworten
der Urban Data Platform Hamburg und des VIZ-Feeds vom 2026-08-07."""

from __future__ import annotations

import asyncio
from datetime import date

from gastroviewer.sources import berlin, hamburg

REEPERBAHN = (53.5497, 9.9631)
ST_GEORG = (53.5553, 10.0110)
WOLFENSTEINDAMM = (52.4571, 13.3185)


class FakeOut:
    def __init__(self, antworten):
        self.antworten = antworten
        self.urls: list[str] = []

    async def get_json(self, source, url, params=None, **kw):
        self.urls.append(url)
        for schluessel, antwort in self.antworten.items():
            if schluessel in url:
                return antwort
        raise AssertionError(f"unerwartete URL: {url}")


# ------------------------------------------------------------ Hamburg

def test_hh_stadtgrenzen():
    assert hamburg.in_hamburg(*REEPERBAHN)
    assert not hamburg.in_hamburg(48.1334, 11.5674), "München ist nicht Hamburg"
    assert not hamburg.in_hamburg(*WOLFENSTEINDAMM), "Berlin ist nicht Hamburg"


def test_hh_maerkte_st_pauli(hamburg_stadt):
    d = hamburg.maerkte_aufbereiten(
        hamburg_stadt["maerkte"]["features"], *REEPERBAHN, 600, stadtweit=80)
    assert d["stadtweit"] == 80
    assert len(d["in_reichweite"]) == 4
    assert d["naechster"]["name"] == "St. Pauli Spielbudenplatz"
    assert any(m["name"] == "St. Pauli Hopfenmarkt"
               for m in d["in_reichweite"])
    # Der Hamburger Datensatz führt keine Öffnungszeiten — None, nicht "".
    assert d["naechster"]["oeffnungszeiten"] is None
    assert d["stadt"] == "Hamburg"


def test_hh_baustellen_bauweiser(hamburg_stadt):
    heute = date(2026, 8, 7)
    d = hamburg.baustellen_aufbereiten(
        hamburg_stadt["baustellen"]["features"], *REEPERBAHN, 1500, heute)
    assert d["gesamt"] >= 1
    erste = d["liste"][0]
    assert erste["ort"].startswith("St. Pauli")
    assert erste["art"] == "Baumaßnahme"
    assert erste["beginn"] == "26.01.2026" and erste["ende"] == "26.01.2029"
    assert erste["status"] == "laufend"
    assert d["stadt"] == "Hamburg"


def test_hh_baustellen_abgelaufene_fallen_raus(hamburg_stadt):
    d = hamburg.baustellen_aufbereiten(
        hamburg_stadt["baustellen"]["features"], *REEPERBAHN, 1500,
        date(2030, 1, 1))
    assert d["gesamt"] == 0


def test_hh_rad_gurlittinsel(hamburg_stadt):
    d = hamburg.rad_aufbereiten(
        hamburg_stadt["rad"]["features"], 53.5610, 10.0050, 600)
    assert d["stadtweit"] == 1
    s = d["in_reichweite"][0]
    assert s["name"] == "Gurlittinsel"
    # Sollwerte aus der echten Antwort: „2025|1926930", Vortag „…|8277".
    assert s["summe_vorjahr"] == 1926930
    assert s["summe_vorjahr_jahr"] == 2025
    assert s["vortag"] == 8277
    assert s["je_tag_vorjahr"] == round(1926930 / 365)
    assert "Zählsäule" in s["besonderheiten"]


def test_hh_milieuschutz_st_georg(hamburg_stadt):
    d = hamburg.milieuschutz_aufbereiten(
        hamburg_stadt["milieuschutz"]["features"])
    assert d["betroffen"] is True
    g = d["gebiete"][0]
    assert g["name"] == "St.Georg"
    assert g["gueltig_ab"] == "2012-02-15"
    assert g["text_pdf"].endswith(".pdf")


def test_hh_load_ende_zu_ende(hamburg_stadt, settings):
    fake = FakeOut({
        "einzelhandel/collections/wochenmarkt": hamburg_stadt["maerkte"],
    })
    res = asyncio.run(hamburg.maerkte_load(fake, settings, *REEPERBAHN, 600))
    assert res.ok
    assert res.data["naechster"]["name"] == "St. Pauli Spielbudenplatz"
    assert "Urban Data Platform" in res.provenance.source
    assert "dl-de/by-2-0" in res.provenance.license


# ------------------------------------------------------------- Berlin

def test_berlin_stadtgrenzen():
    assert berlin.in_berlin(*WOLFENSTEINDAMM)
    assert not berlin.in_berlin(*REEPERBAHN)


def test_berlin_baustellen_wolfensteindamm(berlin_baustellen):
    heute = date(2026, 8, 7)
    d = berlin.aufbereiten(
        berlin_baustellen["feed"]["features"], *WOLFENSTEINDAMM, 1000, heute)
    assert d["gesamt"] >= 2
    erste = d["liste"][0]
    assert erste["ort"].startswith("Wolfensteindamm")
    assert erste["art"] == "Baustelle"
    assert erste["distanz_m"] <= 400
    assert d["stadt"] == "Berlin"


def test_berlin_geometrycollection_wird_zerlegt(berlin_baustellen):
    f = berlin_baustellen["feed"]["features"][0]
    punkte = berlin._koordinaten(f.get("geometry"))
    assert punkte, "GeometryCollection muss Koordinaten liefern"
    assert all(50 < la < 55 and 12 < lo < 15 for la, lo in punkte)


def test_berlin_load_ende_zu_ende(berlin_baustellen, settings):
    fake = FakeOut({"baustellen_sperrungen_viz": berlin_baustellen["feed"]})
    res = asyncio.run(berlin.baustellen_load(
        fake, settings, *WOLFENSTEINDAMM, 1000, heute=date(2026, 8, 7)))
    assert res.ok
    assert res.data["gesamt"] >= 2
    assert "Verkehrsinformationszentrale" in res.provenance.source
