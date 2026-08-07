"""Inside Airbnb — gegen den echten Münchner Datenstand vom 2026-06-29
(Fixture: alle Inserate bis 1,5 km um den Marienplatz plus 60 weitere).
Die Sollwerte unten wurden am 2026-08-07 zusätzlich gegen den vollen
stadtweiten Datensatz (6 890 Inserate) geprüft — identische Ergebnisse."""

from __future__ import annotations

import asyncio

import pytest

from gastroviewer.sources import airbnb
from gastroviewer.sources.base import SourceError

MARIENPLATZ = (48.1374, 11.5755)


def test_finde_stadt_urls_beide_staedte(airbnb_muenchen):
    urls = airbnb.finde_stadt_urls(airbnb_muenchen["index"])
    assert set(urls) == {"munich", "berlin"}
    assert urls["munich"]["datum"] == "2026-06-29"
    assert urls["berlin"]["datum"] == "2026-06-26"
    assert urls["munich"]["url"].endswith("/visualisations/listings.csv")


def test_reduzieren_behaelt_nur_fuenf_felder(airbnb_muenchen):
    listings = airbnb.reduzieren(airbnb_muenchen["csv"])
    assert len(listings) == 1054
    lat, lon, typ, preis, rev = listings[0]
    assert 47 < lat < 49 and 11 < lon < 12
    assert typ in (-1, 0, 1, 2, 3)
    assert preis is None or preis > 0
    assert rev >= 0


def test_auswerten_marienplatz_600m(airbnb_muenchen):
    listings = airbnb.reduzieren(airbnb_muenchen["csv"])
    d = airbnb.auswerten(listings, *MARIENPLATZ, 600)
    assert d["im_radius"] == 127
    assert d["nach_typ"] == {"Ganze Unterkunft": 86, "Privatzimmer": 41}
    assert d["ganze_unterkuenfte"] == 86
    assert d["bewertungen_12m"] == 1135
    assert d["preis_median_eur"] == 336
    assert d["preis_basis"] == 92
    assert d["naechstes_m"] == 181
    # Marker sortiert nach Entfernung, springbare Liste ist deren Kopf.
    assert d["marker"][0]["distanz_m"] == 181
    assert len(d["liste"]) == airbnb.MAX_LISTE
    assert d["liste"] == d["marker"][: airbnb.MAX_LISTE]
    assert d["marker_gekappt"] is False


def test_preis_median_erst_ab_fuenf_preisen(airbnb_muenchen):
    listings = airbnb.reduzieren(airbnb_muenchen["csv"])
    # Sehr kleiner Radius: weniger als fünf Inserate mit Preis -> kein Median,
    # statt eines Medians aus zwei Zufallswerten. (150 m um den Marienplatz
    # liegt im Fixture-Datenstand kein Inserat — Positionen sind ohnehin um
    # bis zu ~150 m versetzt.)
    d = airbnb.auswerten(listings, *MARIENPLATZ, 150)
    assert d["im_radius"] == 0
    assert d["preis_basis"] < 5
    assert d["preis_median_eur"] is None
    assert d["naechstes_m"] is None


def test_norm_gemeinde():
    assert airbnb.norm_gemeinde("München") == "münchen"
    assert airbnb.norm_gemeinde(" Berlin ") == "berlin"
    assert airbnb.norm_gemeinde(None) == ""


def test_load_ausserhalb_der_datenstaedte_ohne_abruf():
    async def nie(slug):  # pragma: no cover - darf nie laufen
        raise AssertionError("Für Köln darf kein Abruf hinausgehen.")

    res = asyncio.run(airbnb.load(None, "Köln", 50.94, 6.96, 600, nie))
    assert res.ok and res.data is None
    assert any("Datenlücke" in w for w in res.warnings)


def test_load_muenchen_liefert_block(airbnb_muenchen):
    listings = airbnb.reduzieren(airbnb_muenchen["csv"])

    async def stadt(slug):
        assert slug == "munich"
        return {"listings": listings, "stichtag": "2026-06-29",
                "quelle_url": "https://data.insideairbnb.com/x/listings.csv"}

    res = asyncio.run(airbnb.load(None, "München", *MARIENPLATZ, 600, stadt))
    assert res.ok and res.data["im_radius"] == 127
    assert res.data["stadt"] == "München"
    assert res.data["stichtag"] == "2026-06-29"
    assert res.provenance and "CC BY 4.0" in res.provenance.license
    assert "150 m" in res.provenance.note
    assert any("150 m" in h for h in res.data["hinweise"])


def test_load_reicht_quellfehler_durch():
    async def kaputt(slug):
        raise SourceError("api_error", "Datenseite nicht erreichbar.")

    res = asyncio.run(airbnb.load(None, "Berlin", 52.52, 13.40, 600, kaputt))
    assert not res.ok
    assert res.error["kind"] == "api_error"


def test_marker_kappung():
    # 600 künstliche Punkte direkt am Zentrum: Zählwerte bleiben vollständig,
    # Karte und Liste werden gekappt.
    listings = [[48.1374, 11.5755, 0, 100, 1] for _ in range(600)]
    d = airbnb.auswerten(listings, *MARIENPLATZ, 600)
    assert d["im_radius"] == 600
    assert len(d["marker"]) == airbnb.MAX_MARKER
    assert d["marker_gekappt"] is True
