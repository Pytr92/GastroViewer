"""Knopf-Import: Hintergrundlauf, Zustand, Endpunkte — mit untergeschobenem
Download (Mini-GeoPackage im ZIP bzw. Münchner GTFS-Ausschnitt)."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest

from gastroviewer import importe
from tests.test_api import FakeOutbound, client  # noqa: F401 — App-Fabrik der API-Tests
from tests.test_raster_at import WIEN, _gpkg
from gastroviewer.sources import raster_at

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _raster_zip(tmp_path: Path) -> Path:
    x0, y0 = raster_at.wgs84_zu_laea(*WIEN)
    e0, n0 = int(x0 // 1000) * 1000, int(y0 // 1000) * 1000
    zellen = [(f"CRS3035RES1000mN{n0 + dn * 1000}E{e0 + de * 1000}", 250.0)
              for dn in range(-1, 2) for de in range(-1, 2)]
    _gpkg(tmp_path / "census.gpkg", zellen)
    zp = tmp_path / "census.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.write(tmp_path / "census.gpkg", "Eurostat_Census-GRID_2021_V1-0.gpkg")
    return zp


@pytest.fixture()
def download_ersatz(monkeypatch, tmp_path):
    """Kein Netz: der Download kopiert eine vorbereitete Datei und meldet
    Fortschritt wie der echte."""
    quelle = _raster_zip(tmp_path)

    def kopieren(url, ziel, melden):
        melden("Download 1 MB von 1 MB", 100.0)
        src = quelle if "eurostat" in url.lower() or "gisco" in url else FIXTURES / "gtfs_muenchen_ausschnitt.zip"
        shutil.copy(src, ziel)
        return ziel

    monkeypatch.setattr(importe, "herunterladen", kopieren)
    return quelle


def test_arten_nennen_quelle_groesse_und_lizenz():
    for art, meta in importe.ARTEN.items():
        assert meta["quelle"].startswith("https://") and meta["groesse_mb"] > 0, art
        assert meta["lizenz"] and meta["titel"] and meta["beschreibung"], art


def test_raster_import_im_hintergrund(download_ersatz, settings):
    imp = importe.Importe(settings)
    assert imp.zustand()["raster_at"]["importiert"] is False
    lauf = imp.start("raster_at")
    assert lauf.status == "laeuft"
    with pytest.raises(RuntimeError):
        imp.start("raster_at")
    fertig = imp.warten("raster_at")
    assert fertig.status == "fertig", fertig.fehler
    assert fertig.ergebnis["zellen"] == 9 and fertig.fortschritt is None
    z = imp.zustand()["raster_at"]
    assert z["importiert"] is True and z["lauf"]["status"] == "fertig"
    assert raster_at.status(settings)["importiert"] is True


def test_gtfs_wien_import_mit_muenchner_ausschnitt(download_ersatz, settings, monkeypatch):
    from gastroviewer import __main__ as cli

    # Der Wiener Kasten enthält keine Münchner Haltestelle — für den Test
    # den Kasten auf München legen; der Lauf selbst ist derselbe.
    monkeypatch.setitem(cli.REGIONEN, "wien", ("Test", cli.REGIONEN["muenchen"][1]))
    imp = importe.Importe(settings)
    imp.start("gtfs_wien")
    fertig = imp.warten("gtfs_wien")
    assert fertig.status == "fertig", fertig.fehler
    assert imp.zustand()["gtfs_wien"]["importiert"] is True
    assert imp.zustand()["gtfs_wien"]["bestand"]["quelle"] == importe.ARTEN["gtfs_wien"]["quelle"]


def test_fehler_landet_im_zustand(settings, monkeypatch):
    def kaputt(url, ziel, melden):
        raise OSError("Netz weg")

    monkeypatch.setattr(importe, "herunterladen", kaputt)
    imp = importe.Importe(settings)
    imp.start("raster_at")
    lauf = imp.warten("raster_at")
    assert lauf.status == "fehler" and "Netz weg" in lauf.fehler
    with pytest.raises(KeyError):
        imp.start("unbekannt")
    # Nach einem Fehler darf ein neuer Lauf starten.
    monkeypatch.setattr(importe, "herunterladen", lambda u, z, m: (_ for _ in ()).throw(OSError("wieder")))
    assert imp.start("raster_at").status == "laeuft"


def test_endpunkte_und_wiener_zensus_danach(client, download_ersatz, zensus_600, overpass_combined,
                                             nominatim_reverse_wien):
    fake = FakeOutbound(zensus_600, overpass_combined, nominatim_reverse_wien)
    with client.make(fake) as c2:
        z = c2.get("/api/import/status").json()
        assert set(z) == {"raster_at", "gtfs_wien"} and z["raster_at"]["importiert"] is False
        assert z["raster_at"]["groesse_mb"] == 186 and z["raster_at"]["lauf"] is None
        assert c2.post("/api/import/nix").status_code == 404
        r = c2.post("/api/import/raster_at")
        assert r.status_code == 202 and r.json()["status"] == "laeuft"
        importe_obj = c2.app.state.importe
        lauf = importe_obj.warten("raster_at")
        assert lauf.status == "fertig", lauf.fehler
        z = c2.get("/api/import/status").json()["raster_at"]
        assert z["importiert"] and z["lauf"]["status"] == "fertig" and z["lauf"]["ergebnis"]["zellen"] == 9
        # Der Wiener Punkt bekommt jetzt Einwohner aus dem Raster — ohne Netz.
        p = c2.get("/api/point/zensus", params={"lat": WIEN[0], "lon": WIEN[1], "r": 600}).json()
        assert p["ok"] and p["data"] and p["data"]["raster"]["kante_m"] == 1000
        assert p["data"]["bevoelkerung"]["einwohner"]["wert"] > 0
        assert "zensus" not in fake.calls
