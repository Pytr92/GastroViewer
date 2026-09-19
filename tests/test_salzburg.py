"""Stadt Salzburg (WFS data.stadt-salzburg.at) gegen die Live-Aufzeichnungen
vom 18.09.2026: Baurecht (Bebauungsplan + Planblatt), Altstadtschutzzone,
Märkte, Baustellen, Kurzparkzone — und die Anbindung über die API."""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path

from gastroviewer.sources import salzburg as sb
from gastroviewer.sources.base import SourceError
from tests.test_api import FakeOutbound, client  # noqa: F401

AT = Path(__file__).resolve().parent.parent / "fixtures" / "at"
PROBE = (47.8095, 13.0550)          # Probepunkt der AT-Probe (Schallmoos)
GETREIDEGASSE = (47.8003, 13.0430)  # Altstadt, Schutzzone I


def _lies(n):
    return json.loads((AT / f"{n}.json").read_text("utf-8"))


class _Out:
    def __init__(self, wfs, fehler=()):
        self.wfs, self.fehler, self.typen = wfs, set(fehler), []

    async def get_json(self, source, url, params=None, **kw):
        typ = params["typeName"].split(":")[1]
        self.typen.append(typ)
        if typ in self.fehler:
            raise SourceError("timeout", "Zeitüberschreitung")
        return self.wfs.get(typ) or {"type": "FeatureCollection", "features": []}


def _wfs():
    return {"flaechenwidmung": _lies("salzburg_r6_flaechenwidmung"),
            "bebauungsplan_rechtswirksam": _lies("salzburg_r6_bebauungsplan_rechtswirksam"),
            "altstadtschutzzone": _lies("salzburg_r7_altstadtschutzzone"),
            "kurzparkzone": _lies("salzburg_r6_kurzparkzone"),
            "markt": _lies("salzburg_r6_markt"),
            "baustelle_aktuell": _lies("salzburg_r6_baustelle_aktuell")}


def test_in_salzburg():
    assert sb.in_salzburg(*PROBE) and sb.in_salzburg(*GETREIDEGASSE)
    assert not sb.in_salzburg(48.2082, 16.3738) and not sb.in_salzburg(48.1372, 11.5755)


def test_baurecht_plan_und_planblatt():
    res = asyncio.run(sb.baurecht_load(_Out(_wfs()), *PROBE))
    assert res.ok and res.name == "baurecht" and res.data["stufe"] == "plan" and res.data["gebiet"] == "Salzburg"
    assert res.data["planblatt"]["nummer"] == "4330-5103" and res.data["planblatt"]["pdf"].endswith("4330-5103.pdf")
    plan = res.data["plaene"][0]
    assert plan["plan"] == "SCHALLMOOS - WEST 1/G1" and plan["art"] == "Bebauungsplan (Grundstufe)"
    assert plan["rechtsstand"] == "rechtswirksam" and plan["festgesetzt_am"] == "1998-11-20" and plan["pdf"]
    assert res.data["baugebiete"] == [] and res.data["paragraf_34"] is False
    assert "Planblatt" in res.data["hinweise"][1] and not res.warnings


def test_baurecht_ohne_plan_und_ausfall():
    res = asyncio.run(sb.baurecht_load(_Out(_wfs()), 47.8300, 13.0300))
    assert res.ok and res.data["stufe"] == "kein_plan" and "Planblatt" in res.warnings[0]
    res = asyncio.run(sb.baurecht_load(_Out(_wfs(), fehler={"flaechenwidmung"}), *PROBE))
    assert res.ok and res.data["stufe"] == "plan" and res.data["planblatt"] is None and "Flächenwidmung" in res.warnings[0]
    res = asyncio.run(sb.baurecht_load(_Out({}, fehler={"flaechenwidmung", "bebauungsplan_rechtswirksam"}), *PROBE))
    assert not res.ok and res.error["kind"] == "api_error"


def test_altstadtschutzzone():
    treffer = asyncio.run(sb.altstadtschutzzone(_Out(_wfs()), *GETREIDEGASSE))
    assert treffer["betroffen"] is True and treffer["gebiete"][0]["name"] == "Altstadtschutzzone I"
    assert treffer["titel"].startswith("Altstadtschutzzone")
    leer = asyncio.run(sb.altstadtschutzzone(_Out(_wfs()), *PROBE))
    assert leer["betroffen"] is False and leer["gebiete"] == []


def test_maerkte_schrannenmarkt():
    res = asyncio.run(sb.maerkte_load(_Out(_wfs()), *PROBE, 600))
    d = res.data
    assert res.ok and d["stadt"] == "Salzburg" and d["stadtweit"] == 15
    assert d["naechster"]["name"] == "Schrannenmarkt" and d["naechster"]["oeffnungszeiten"].startswith("Jeden Donnerstag")
    assert d["naechster"]["adresse"] == "Mirabellplatz" and d["naechster"]["link"]
    assert d["nach_rubrik"]["Ganzjähriger Markt"] >= 2 and d["nach_rubrik"]["Adventmarkt"] >= 5
    assert all("\r" not in (m["oeffnungszeiten"] or "") for m in d["in_reichweite"])
    assert "2019" in res.provenance.stand


def test_baustellen_punkt_und_linie():
    heute = date(2026, 9, 19)
    res = asyncio.run(sb.baustellen_load(_Out(_wfs()), *PROBE, 1500, heute))
    d = res.data
    assert res.ok and d["stadt"] == "Salzburg" and d["gesamt"] == 3 and d["haltverbote"] == 0
    assert d["liste"][0]["status"] == "laufend" and d["liste"][0]["beginn"] and d["liste"][0]["ende"] >= "2026-09-19"
    assert all(e["distanz_m"] <= 1500 for e in d["liste"])
    assert any(e["linie"] for e in d["liste"]) or any(e["lat"] for e in d["liste"])
    # dieselbe Maßnahme (Punkt + Linie) zählt einmal
    nummern = [e["ort"] for e in d["liste"]]
    assert len(nummern) == len(set(nummern))
    # nach Bauende verschwindet die Maßnahme
    res = asyncio.run(sb.baustellen_load(_Out(_wfs()), *PROBE, 1500, date(2028, 1, 1)))
    assert res.data["gesamt"] == 0
    res = asyncio.run(sb.baustellen_load(_Out(_wfs(), fehler={"baustelle_aktuell"}), *PROBE, 600))
    assert not res.ok


def test_lage_kurzparkzone():
    res = asyncio.run(sb.lage_load(_Out(_wfs()), 47.8085, 13.0560, 600))
    assert res.ok and res.data["stadt"] == "Salzburg" and res.data["geschaeftsstrasse"]["ohne_dienst"] is True
    kp = res.data["kurzparkzone"]
    if kp is not None:
        assert kp["dauer"] and kp["zeitraum"]
    res = asyncio.run(sb.lage_load(_Out(_wfs(), fehler={"kurzparkzone"}), *PROBE, 600))
    assert not res.ok


def test_api_salzburger_punkt(client, zensus_600, overpass_combined, nominatim_reverse_wien,
                              geosphere_at, laerminfo_at, lfrz_hochwasser_at, salzburg_wfs,
                              wahl_at_dateien, statistik_at):
    """Der Geocoder-Fixture ist Wiener (nur das Land zählt); die Stadt-
    dienste kommen aus dem Salzburger WFS — kein Wiener Abruf."""
    fake = FakeOutbound(zensus_600, overpass_combined, nominatim_reverse_wien,
                        geosphere=geosphere_at, laerminfo=laerminfo_at,
                        lfrz=lfrz_hochwasser_at, salzburg=salzburg_wfs,
                        wahl_at=wahl_at_dateien, statistik_at=statistik_at)
    lat, lon = GETREIDEGASSE
    with client.make(fake) as c2:
        for pfad, params in (("/api/point/baurecht", {"lat": lat, "lon": lon}),
                             ("/api/point/planung", {"lat": lat, "lon": lon, "r": 600}),
                             ("/api/point/maerkte", {"lat": lat, "lon": lon, "r": 600}),
                             ("/api/point/baustellen", {"lat": lat, "lon": lon, "r": 600}),
                             ("/api/point/lage", {"lat": lat, "lon": lon, "r": 600})):
            r = c2.get(pfad, params=params)
            assert r.status_code == 200, pfad
            d = r.json()
            assert d["ok"], (pfad, d.get("error"))
            if pfad.endswith("baurecht"):
                assert d["data"]["gebiet"] == "Salzburg" and d["data"]["stufe"] in ("plan", "kein_plan")
            if pfad.endswith("planung"):
                assert d["data"]["erhaltungssatzung"]["betroffen"] is True
                assert d["data"]["texte"]["erhaltungssatzung_titel"].startswith("Altstadtschutzzone")
                assert "Salzburg" in d["provenance"]["source"]
            if pfad.endswith("maerkte"):
                assert d["data"]["stadt"] == "Salzburg" and d["data"]["naechster"]
            if pfad.endswith("baustellen"):
                assert d["data"]["stadt"] == "Salzburg"
            if pfad.endswith("lage"):
                assert d["data"]["stadt"] == "Salzburg"
    assert not any(c.startswith("wien_") for c in fake.calls)
    assert "salzburg_altstadtschutzzone" in fake.calls and "salzburg_markt" in fake.calls
