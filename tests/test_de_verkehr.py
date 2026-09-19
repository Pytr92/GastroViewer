"""Deutschland, Runden 6/7 (live 18.09.2026): Berlin Verkehrsmengen 2023,
Hamburg Verkehrsstärken / Stadtteil-Regionalstatistik / Parkhäuser,
MobiData BW (Baustellen, SVZ, Eco-Counter, Ladesäulen) und Stuttgart."""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path

from gastroviewer.sources import berlin, hamburg
from gastroviewer.sources import mobidata_bw as mb
from gastroviewer.sources.base import SourceError
from tests.test_api import FakeOutbound, client  # noqa: F401

DE = Path(__file__).resolve().parent.parent / "fixtures" / "de"
STUTTGART = (48.7758, 9.1829)
ALEXANDERPLATZ = (52.5219, 13.4132)
MOENCKEBERG = (53.5511, 9.9937)
HEUTE = date(2026, 9, 19)


def _lies(n):
    return json.loads((DE / f"{n}.json").read_text("utf-8"))


class _Out:
    def __init__(self, antworten, fehler=()):
        self.a, self.fehler, self.urls = antworten, set(fehler), []

    async def get_json(self, source, url, params=None, **kw):
        self.urls.append((url, params))
        for k, v in self.a.items():
            if k in url or k in json_str(params):
                if k in self.fehler:
                    raise SourceError("timeout", "x")
                return v
        raise SourceError("timeout", "x")


def json_str(params):
    return json.dumps(params or {}, ensure_ascii=False)


# ------------------------------------------------------------ MobiData BW

def test_roadworks_bw():
    fs = _lies("de_mobidata_r7_roadworks_auszug")["features"]
    d = mb.roadworks_aufbereiten(fs, 47.607, 8.109, 2000, HEUTE)
    assert d["gesamt"] == 1 and d["stadt"] == "Baden-Württemberg"
    e = d["liste"][0]
    assert e["ort"].startswith("L154") and e["art"] == "Sperrung wegen Bauarbeiten" and e["mit_sperrung"]
    assert e["status"] == "laufend" and e["ende"] == "2026-12-31" and e["linie"] and e["distanz_m"] < 200
    assert mb.roadworks_aufbereiten(fs, 47.607, 8.109, 2000, date(2027, 6, 1))["gesamt"] == 0

    async def laden():
        return fs

    res = asyncio.run(mb.roadworks_load(_Out({}), 47.607, 8.109, 2000, laden, HEUTE))
    assert res.ok and res.name == "baustellen" and "MobiData" in res.provenance.source


def test_stuttgart_baustellen():
    out = _Out({"geoserver.stuttgart.de": _lies("de_stuttgart_r6_baustellen")})
    res = asyncio.run(mb.stuttgart_baustellen_load(out, *STUTTGART, 3000, HEUTE))
    d = res.data
    assert res.ok and d["stadt"] == "Stuttgart" and d["gesamt"] >= 10 and d["laufend"] >= 1
    assert d["liste"][0]["distanz_m"] <= d["liste"][-1]["distanz_m"] or d["liste"][-1]["status"] == "geplant"
    assert all(e["ende"] is None or e["ende"] >= "2026-09-19" for e in d["liste"]) and sum(1 for e in d["liste"] if e["beginn"]) >= 10
    assert any("Sperrung" in (e["beeintraechtigung"] or "") for e in d["liste"])
    assert out.urls[0][1]["typeName"].startswith("Verkehr_Mobilitaet:") and "EPSG:4326" in out.urls[0][1]["bbox"]
    assert not asyncio.run(mb.stuttgart_baustellen_load(_Out({}), *STUTTGART, 600)).ok


def test_svz_bw():
    stellen = mb.svz_parsen((DE / "de_mobidata_r7_svz_stuttgart.csv").read_text("utf-8"))
    assert len(stellen) == 449 and stellen[0]["strasse"] == "B 10" and stellen[0]["dtv_kfz"] == 24088
    d = mb.svz_aufbereiten(stellen, *STUTTGART, 600)
    assert d["dienst"] == "svz_bw" and d["jahr"] == 2024 and d["zaehlstellen"]
    assert d["naechste"]["strasse"] == "L 1016" and 2500 < d["naechste"]["distanz_m"] < 3000
    assert d["naechste"]["zaehlart"] in ("Temporäre Zählung (Modell)", "Dauerzählstelle", "Manuelle Zählung")
    assert d["staerkste"]["dtv_kfz"] >= d["naechste"]["dtv_kfz"] and d["naechste"]["schwerverkehr_anteil"] is not None

    async def laden():
        return stellen

    res = asyncio.run(mb.svz_load(_Out({}), *STUTTGART, 600, laden))
    assert res.ok and res.name == "verkehrsmenge" and "2024" in res.provenance.source
    res = asyncio.run(mb.svz_load(_Out({}), 49.5, 8.0, 600, laden))
    assert res.ok and not res.data["zaehlstellen"] and res.warnings


def test_eco_counter_bw():
    sites = mb.eco_parsen((DE / "de_mobidata_r7_eco_tageswerte_auszug.csv").read_text("utf-8"))
    assert len(sites) == 58
    d = mb.eco_aufbereiten(sites, 48.8838, 9.1906, 600)  # Ludwigsburg
    n = d["naechste"]
    assert n["name"] == "Hohenzollernstraße Stadtauswärts" and n["distanz_m"] < 100 and n["im_radius"]
    assert n["je_tag_letzte_woche"] == 385 and n["vortag"] == 385 and n["letzter_tag"] == "2026-09-17"
    assert n["summe_vorjahr"] is None and n["besonderheiten"].startswith("Betreiber: Stadt Ludwigsburg")
    d = mb.eco_aufbereiten(sites, 48.9238, 9.5848, 600)  # Rems-Murr, 7 Tage
    assert d["naechste"]["je_tag_basis"] == "Mittel der letzten 7 Tage"

    async def laden():
        return sites

    res = asyncio.run(mb.eco_load(_Out({}), 48.8838, 9.1906, 600, laden))
    assert res.ok and res.name == "radzaehlung" and res.data["stadt"] == "Baden-Württemberg"


def test_ladesaeulen_bw():
    out = _Out({"charge_points": _lies("de_mobidata_r6_ladesaeulen_stuttgart")})
    d = asyncio.run(mb.ladesaeulen(out, *STUTTGART, 600))
    assert d["im_radius"] >= 20 and d["ladepunkte"] >= 40 and d["schnelllader"] >= 1
    assert d["naechste"]["distanz_m"] <= d["standorte"][1]["distanz_m"] and d["naechste"]["leistung_kw"]
    assert out.urls[0][1]["typeName"] == "MobiData-BW:charge_points" and out.urls[0][1]["version"] == "1.0.0"


# ---------------------------------------------------------------- Berlin

def test_berlin_verkehrsmengen():
    kfz, lkw, rad = (_lies(f"de_berlin_r6_verkehrsmengen_2023_dtvw2023{t}")["features"] for t in ("kf", "lk", "ra"))
    d = berlin.verkehrsmengen_aufbereiten(kfz, lkw, rad, *ALEXANDERPLATZ, 600)
    assert d["dienst"] == "berlin" and d["jahr"] == 2023 and len(d["zaehlstellen"]) == 12
    n = d["naechste"]
    assert n["strasse"].startswith("Alexanderstraße") and n["dtv_kfz"] == 25300 and n["dtv_schwerverkehr"] == 480
    assert n["dtv_rad"] == 6110 and n["schwerverkehr_anteil"] == 1.9 and n["im_radius"]
    assert d["staerkste"]["strasse"].startswith("Straßentunnel") and d["staerkste"]["dtv_kfz"] == 30300
    out = _Out({"dtvw2023kfz": {"features": kfz}, "dtvw2023lkw": {"features": lkw}, "dtvw2023rad": {"features": rad}})
    res = asyncio.run(berlin.verkehrsmengen_load(out, None, *ALEXANDERPLATZ, 600))
    assert res.ok and res.name == "verkehrsmenge" and not res.warnings and len(out.urls) == 3
    assert out.urls[0][1]["typeNames"] == "verkehrsmengen_2023:dtvw2023kfz" and out.urls[0][1]["version"] == "2.0.0"
    res = asyncio.run(berlin.verkehrsmengen_load(_Out({"dtvw2023kfz": {"features": kfz}}), None, *ALEXANDERPLATZ, 600))
    assert res.ok and len(res.warnings) == 2 and res.data["naechste"]["dtv_schwerverkehr"] is None
    assert not asyncio.run(berlin.verkehrsmengen_load(_Out({}), None, *ALEXANDERPLATZ, 600)).ok


# --------------------------------------------------------------- Hamburg

def test_hamburg_verkehrsmengen():
    z = _lies("de_hh_r6_verkehrsstaerken_kfz_temporaere_zaehlunge")["features"]
    h = _lies("de_hh_r6_verkehrsmengen_verkehrsmengen_dtv_hvs_2")["features"]
    d = hamburg.verkehrsmengen_aufbereiten(z, h, *MOENCKEBERG, 600)
    assert d["dienst"] == "hamburg" and d["zaehlstellen"] and d["naechste"]["distanz_m"] < 200
    arten = {s["zaehlart"] for s in d["zaehlstellen"]}
    assert any(a.startswith("Temporäre Zählung") for a in arten) and any(a.startswith("Verkehrsmengenkarte") for a in arten)
    temp = next(s for s in d["zaehlstellen"] if s["zaehlart"].startswith("Temporäre"))
    assert temp["dtv_kfz"] and temp["dtv_werktag"] and temp["jahr"] >= 2013 and temp["dtv_schwerverkehr"] is not None
    out = _Out({"kfz_temporaere_zaehlungen": {"features": z}, "verkehrsmengen_dtv_hvs_2019": {"features": h}})
    res = asyncio.run(hamburg.verkehrsmengen_load(out, None, *MOENCKEBERG, 600))
    assert res.ok and not res.warnings
    res = asyncio.run(hamburg.verkehrsmengen_load(_Out({"kfz_temporaere_zaehlungen": {"features": z}}), None, *MOENCKEBERG, 600))
    assert res.ok and res.warnings and all(s["zaehlart"].startswith("Temporäre") for s in res.data["zaehlstellen"])


def test_hamburg_stadtteil():
    fs = _lies("de_hh_r6_regionalstatistische_daten_stadtteile_regionalstatistische_dat")["features"]
    d = hamburg.stadtteil_aufbereiten(fs, 53.5503, 10.0006)
    assert d["bezirk"] == "Hamburg-Altstadt (Bezirk Hamburg-Mitte)" and d["stadt_raum"] == "Hamburg gesamt"
    ew = next(i for i in d["indikatoren"] if i["schluessel"] == "einwohner")
    assert ew["bezirk"]["jahr"] == 2016 and ew["bezirk"]["wert"] == 2257 and ew["bezirk"]["von_jahr"] == 2013
    assert ew["stadt"] is None and ew["reihe"][0] == [2013, 1675.0]
    assert {i["schluessel"] for i in d["indikatoren"]} >= {"ab65", "auslaenderanteil", "einpersonenhaushalte", "arbeitslose"}
    assert hamburg.stadtteil_aufbereiten(fs, 53.70, 10.30) is None
    res = asyncio.run(hamburg.stadtteil_load(_Out({"regionalstatistische_daten_stadtteile": {"features": fs}}), 53.5503, 10.0006))
    assert res.ok and res.name == "indikatoren" and "Statistikamt Nord" in res.provenance.source


def test_hamburg_lage_parkhaeuser():
    out = _Out({"parkhaeuser": _lies("de_hh_r6_parkhaeuser_parkhaeuser"), "parkraum": _lies("de_hh_r6_parkraum_parkraum")})
    res = asyncio.run(hamburg.lage_load(out, *MOENCKEBERG, 600))
    d = res.data
    assert res.ok and d["stadt"] == "Hamburg" and d["parkhaeuser_im_radius"] >= 5 and d["stellplaetze_im_radius"] > 1000
    p0 = d["parkhaeuser"][0]
    assert p0["name"] and p0["frei"] is not None and p0["gesamt"] and p0["distanz_m"] <= 600
    assert d["geschaeftsstrasse"]["ohne_dienst"] is True and d["kurzparkzone"] is None
    assert d["parkraum"]["bewirtschaftung"] == "Parkschein"
    res = asyncio.run(hamburg.lage_load(_Out({"parkraum": _lies("de_hh_r6_parkraum_parkraum")}), *MOENCKEBERG, 600))
    assert res.ok and res.data["parkhaeuser"] == [] and res.warnings
    assert not asyncio.run(hamburg.lage_load(_Out({}), *MOENCKEBERG, 600)).ok


# ---------------------------------------------------------- API-Rundlauf

def _punkt(c2, pfad, lat, lon, **extra):
    r = c2.get(pfad, params={"lat": lat, "lon": lon, **extra})
    assert r.status_code == 200, (pfad, r.text[:200])
    d = r.json()
    assert d["ok"], (pfad, d.get("error"))
    return d


def test_api_stuttgarter_punkt(client, zensus_600, overpass_combined, nominatim_reverse_bw, de_dienste):
    fake = FakeOutbound(zensus_600, overpass_combined, nominatim_reverse_bw,
                        mobidata=de_dienste["mobidata"], stuttgart=de_dienste["stuttgart"])
    lat, lon = STUTTGART
    with client.make(fake) as c2:
        vm = _punkt(c2, "/api/point/verkehrsmenge", lat, lon, r=600)
        assert vm["data"]["dienst"] == "svz_bw" and vm["data"]["naechste"]["strasse"] == "L 1016"
        bs = _punkt(c2, "/api/point/baustellen", lat, lon, r=3000)
        assert bs["data"]["stadt"] == "Stuttgart" and bs["data"]["gesamt"] >= 10
        rz = _punkt(c2, "/api/point/radzaehlung", lat, lon, r=600)
        assert rz["data"]["stadt"] == "Baden-Württemberg"
        lg = _punkt(c2, "/api/point/lage", lat, lon, r=600)
        assert lg["data"]["stadt"] == "Baden-Württemberg" and lg["data"]["ladesaeulen"]["ladepunkte"] >= 40
    assert "stuttgart_baustellen" in fake.calls and "mobidata_csv" in fake.calls and "BAYSIS" not in str(fake.calls)


def test_api_bw_ausserhalb_stuttgarts_nimmt_mobidata_baustellen(client, zensus_600, overpass_combined,
                                                                nominatim_reverse_bw, de_dienste):
    fake = FakeOutbound(zensus_600, overpass_combined, nominatim_reverse_bw, mobidata=de_dienste["mobidata"])
    with client.make(fake) as c2:
        bs = _punkt(c2, "/api/point/baustellen", 47.607, 8.109, r=2000)
        assert bs["data"]["stadt"] == "Baden-Württemberg" and bs["data"]["gesamt"] == 1
    assert "stuttgart_baustellen" not in fake.calls


def test_api_berliner_und_hamburger_punkt(client, zensus_600, overpass_combined, nominatim_reverse, de_dienste):
    fake = FakeOutbound(zensus_600, overpass_combined, nominatim_reverse,
                        berlin_wfs=de_dienste["berlin_wfs"], hamburg_oaf=de_dienste["hamburg_oaf"])
    with client.make(fake) as c2:
        vm = _punkt(c2, "/api/point/verkehrsmenge", *ALEXANDERPLATZ, r=600)
        assert vm["data"]["dienst"] == "berlin" and vm["data"]["naechste"]["dtv_rad"] == 6110
        vm = _punkt(c2, "/api/point/verkehrsmenge", *MOENCKEBERG, r=600)
        assert vm["data"]["dienst"] == "hamburg"
        ind = _punkt(c2, "/api/point/indikatoren", 53.5503, 10.0006)
        assert ind["data"]["stadt_raum"] == "Hamburg gesamt" and ind["data"]["bezirk"].startswith("Hamburg-Altstadt")
        lg = _punkt(c2, "/api/point/lage", *MOENCKEBERG, r=600)
        assert lg["data"]["stadt"] == "Hamburg" and lg["data"]["parkhaeuser_im_radius"] >= 5
    assert "berlin_wfs_dtvw2023kfz" in fake.calls and "hamburg_parkhaeuser" in fake.calls
