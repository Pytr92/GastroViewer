"""Baustellen München — gegen die echte WFS-Antwort vom 07.08.2026
(30 Features aus dem Innenstadt-Kilometer um den Marienplatz, beide Arten,
Gehweg- und Sperrungs-Fälle enthalten)."""

from __future__ import annotations

from datetime import date

from gastroviewer.sources import baustellen

PUNKT = (48.1374, 11.5755)  # Marienplatz
HEUTE = date(2026, 8, 7)


class FakeOut:
    def __init__(self, payload):
        self.payload = payload
        self.calls: list[dict] = []

    async def get_json(self, source, url, params=None, **kw):
        self.calls.append({"source": source, "url": url, "params": params})
        return self.payload


def test_datum_und_link():
    assert baustellen._datum("01.05.2026") == date(2026, 5, 1)
    assert baustellen._datum("2026-05-01") is None
    assert baustellen._datum(None) is None
    assert baustellen._href(
        '<a href="https://stadt.muenchen.de/x.html" target="_blank">i</a>'
    ) == "https://stadt.muenchen.de/x.html"
    assert baustellen._href("kein Link") is None


def test_aufbereiten_zaehlt_und_sortiert(muenchen_baustellen):
    data = baustellen.aufbereiten(
        muenchen_baustellen["features"], *PUNKT, 400, HEUTE
    )
    assert data["gesamt"] == 23
    assert data["baumassnahmen"] == 17
    assert data["haltverbote"] == 6
    assert data["laufend"] == 15
    assert data["geplant"] == 8
    assert data["gehweg_betroffen"] == 7
    assert data["gekappt"] is False
    # Laufende zuerst, dann nach Entfernung.
    erste = data["liste"][0]
    assert erste["ort"] == "Rosenstraße 8"
    assert erste["status"] == "laufend"
    assert erste["distanz_m"] == 151
    stati = [e["status"] for e in data["liste"]]
    assert stati.index("geplant") >= data["laufend"]


def test_flags_aus_echten_feldern(muenchen_baustellen):
    data = baustellen.aufbereiten(
        muenchen_baustellen["features"], *PUNKT, 400, HEUTE
    )
    je_ort = {e["ort"]: e for e in data["liste"]}
    # Gehweg-Betroffenheit steht teils nur in betroffene_bereiche.
    assert je_ort["Theatinerstraße 7"]["gehweg_betroffen"] is True
    assert je_ort["Oberanger 4"]["mit_sperrung"] is True
    # Umriss in [lat, lon] für Leaflet, Schwerpunkt gesetzt.
    assert len(je_ort["Rosenstraße 8"]["umriss"]) >= 4
    assert 48.0 < je_ort["Rosenstraße 8"]["lat"] < 48.3


def test_radius_und_ablauf_filtern(muenchen_baustellen):
    fs = muenchen_baustellen["features"]
    assert baustellen.aufbereiten(fs, *PUNKT, 150, HEUTE)["gesamt"] == 0
    # 2028 sind alle 30 Maßnahmen der Fixture beendet.
    assert baustellen.aufbereiten(fs, *PUNKT, 400, date(2028, 1, 1))["gesamt"] == 0


def test_punkt_im_umriss_ist_null_meter():
    ring = [[11.0, 48.0], [11.002, 48.0], [11.002, 48.002], [11.0, 48.002], [11.0, 48.0]]
    assert baustellen._distanz_m(48.001, 11.001, [ring]) == 0.0
    assert baustellen._distanz_m(48.01, 11.001, [ring]) > 800


async def test_load_fragt_mit_lonlat_bbox(settings, muenchen_baustellen):
    out = FakeOut(muenchen_baustellen)
    res = await baustellen.load(out, settings, *PUNKT, 400, heute=HEUTE)
    assert res.ok and res.data["gesamt"] == 23
    assert res.data["hinweise"]
    p = out.calls[0]["params"]
    w, s, o, n = (float(x) for x in p["bbox"].split(",")[:4])
    # lon,lat-Reihenfolge: West/Ost sind Längengrade um 11,57.
    assert 11.5 < w < o < 11.65 and 48.1 < s < n < 48.2
    assert p["srsName"] == "EPSG:4326"
    assert "Vier-Wochen" in res.provenance.stand or "vier Wochen" in res.provenance.stand


async def test_ausserhalb_muenchens_keine_anfrage(settings, muenchen_baustellen):
    out = FakeOut(muenchen_baustellen)
    res = await baustellen.load(out, settings, 53.55, 9.99, 400, heute=HEUTE)
    assert res.ok and res.data is None
    assert out.calls == []
    assert any("Datenlücke" in w for w in res.warnings)
