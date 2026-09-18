"""GeoSphere-Klimanormalwerte gegen die Live-Antworten der AT-Probe (18.09.2026)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from gastroviewer.config import Settings
from gastroviewer.sources import klima_at

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "at"
WIEN = (48.2082, 16.3738)


def _lade(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_stationen_und_naechste():
    stationen = klima_at.stationen_aus_metadata(_lade("geosphere_klima_v2_1y_metadata_kurz.json"))
    assert stationen and all(s["id"] and s["lat"] for s in stationen)
    assert all(s["ab"] < 9999 for s in stationen)
    wahl = klima_at.naechste_station(stationen, *WIEN)
    assert wahl is not None
    station, dist = wahl
    # Die Probe hat live „Wien Innere Stadt“ (id 5925, Reihe ab 1985) gewählt.
    assert station["id"] == 5925 and station["name"] == "Wien Innere Stadt"
    assert dist < 1500 and station["ab"] <= 1991
    # Eine Station, die erst 2005 beginnt, verliert gegen eine ältere, auch wenn sie näher ist.
    jung = [{"id": 1, "name": "jung", "lat": WIEN[0], "lon": WIEN[1], "hoehe_m": 0, "ab": 2005, "sonne": True},
            {"id": 2, "name": "alt", "lat": WIEN[0] + 0.05, "lon": WIEN[1], "hoehe_m": 0, "ab": 1970, "sonne": True}]
    assert klima_at.naechste_station(jung, *WIEN)[0]["id"] == 2
    assert klima_at.naechste_station([jung[0]], *WIEN)[0]["id"] == 1, "notfalls die junge"


def test_normalwerte_aus_der_echten_antwort():
    w = klima_at.normalwerte(_lade("geosphere_klima_v2_1y_wien_1991_2020.json"))
    assert set(w) == {"tage_sommer", "tage_tropen", "so_h", "rr", "tl_mittel"}
    assert w["tl_mittel"]["jahre"] == 30
    # Wien Innere Stadt 1991–2020: rund 11,5 °C, rund 70 Sommertage, rund 1 900 h Sonne.
    assert 11.0 < w["tl_mittel"]["wert"] < 12.5
    assert 55 < w["tage_sommer"]["wert"] < 90
    assert 1700 < w["so_h"]["wert"] < 2200
    assert 450 < w["rr"]["wert"] < 750


def test_load_baut_den_klimablock():
    meta = _lade("geosphere_klima_v2_1y_metadata_kurz.json")
    daten = _lade("geosphere_klima_v2_1y_wien_1991_2020.json")
    gesehen = []

    class Fake:
        async def get_json(self, source, url, params=None, **kw):
            gesehen.append((url, dict(params or {})))
            return daten

    async def stationen():
        return klima_at.stationen_aus_metadata(meta)

    res = asyncio.run(klima_at.load(Fake(), Settings(), WIEN[0], WIEN[1], stationen))
    assert res.ok and res.name == "klima"
    k = {z["schluessel"]: z for z in res.data["kennzahlen"]}
    assert set(k) == {"sommertage", "heisse_tage", "sonnenschein", "niederschlag", "temperatur"}
    assert k["temperatur"]["station"]["name"] == "Wien Innere Stadt"
    assert k["temperatur"]["jahre"] == 30 and k["temperatur"]["monate"] is None
    assert gesehen[0][1]["station_ids"] == "5925" and gesehen[0][1]["start"] == "1991-01-01"
    assert "CC BY 4.0" in res.provenance.license and "1991–2020" in res.provenance.stand


def test_luecken_werden_benannt():
    daten = _lade("geosphere_klima_v2_1y_wien_1991_2020.json")
    p = daten["features"][0]["properties"]["parameters"]
    p["so_h"]["data"] = [None] * 30
    p["rr"]["data"] = p["rr"]["data"][:12] + [None] * 18

    class Fake:
        async def get_json(self, *a, **kw):
            return daten

    async def stationen():
        return klima_at.stationen_aus_metadata(_lade("geosphere_klima_v2_1y_metadata_kurz.json"))

    res = asyncio.run(klima_at.load(Fake(), Settings(), WIEN[0], WIEN[1], stationen))
    keys = {z["schluessel"] for z in res.data["kennzahlen"]}
    assert "sonnenschein" not in keys and "niederschlag" in keys
    assert any("ohne Werte" in w for w in res.warnings)
    assert any("von 30 Jahren" in w for w in res.warnings)
