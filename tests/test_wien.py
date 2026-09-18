"""Stadt-Adapter Wien: Märkte, Baustellen, Widmung — gegen die Live-Antworten
vom 18.09.2026 (fixtures/at)."""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path

from gastroviewer.sources import wien
from gastroviewer.sources.base import SourceError

AT = Path(__file__).resolve().parent.parent / "fixtures" / "at"
STEPHANSPLATZ = (48.2082, 16.3738)
HEUTE = date(2026, 9, 18)


def _lies(name: str):
    return json.loads((AT / name).read_text("utf-8"))


def _innen(feature):
    ring = feature["geometry"]["coordinates"][0]
    return (sum(p[1] for p in ring) / len(ring), sum(p[0] for p in ring) / len(ring))


def test_stadtkasten():
    assert wien.in_wien(*STEPHANSPLATZ)
    assert not wien.in_wien(48.3100, 14.2900), "Linz"
    assert not wien.in_wien(48.1374, 11.5755), "München"


def test_maerkte_stadtweit_mit_kategorie_und_link():
    d = wien.maerkte_aufbereiten(_lies("wien_maerkteogd.json")["features"], *STEPHANSPLATZ, 600)
    assert d["stadtweit"] == 23 and d["stadt"] == "Wien"
    assert d["naechster"]["name"] and d["naechster"]["distanz_m"] <= wien.MAX_MARKT_DISTANZ_M
    assert d["naechster"]["oeffnungszeiten"] is None, "der Datensatz führt keine"
    assert d["naechster"]["link"].startswith("http")
    assert set(d["nach_rubrik"]) <= {"Lebensmittel und Waren aller Art", "Flohmarkt",
                                     "Kunst- und Antiquitätenmarkt"}
    assert d["in_reichweite"] == sorted(d["in_reichweite"], key=lambda m: m["distanz_m"])


def test_baustellen_punkte_und_linien_im_radius():
    features = (_lies("wien_baustellenpktogd.json")["features"]
                + _lies("wien_baustellenlinienogd.json")["features"])
    d = wien.baustellen_aufbereiten(features, *STEPHANSPLATZ, 1500, HEUTE)
    assert d["stadt"] == "Wien" and d["gesamt"] >= 1 and d["haltverbote"] == 0
    assert d["baumassnahmen"] == d["gesamt"]
    arten = {e["art"] for e in d["liste"]}
    assert arten & {"Straßenbau", "Kanalbau", "U-Bahnbau", "Brückenbau", "Rohrlegung",
                    "Baustelleneinrichtung für Hochbau", "Arbeiten an Sonderbauwerken"}
    linien = [e for e in d["liste"] if e["linie"]]
    assert linien, "Linienbaustellen über den nächsten Stützpunkt"
    assert all(e["distanz_m"] <= 1500 for e in d["liste"])
    assert all(e["beginn"] is None or len(e["beginn"]) == 10 for e in d["liste"])
    # Abgelaufene Baustellen fallen weg.
    spaeter = wien.baustellen_aufbereiten(features, *STEPHANSPLATZ, 1500, date(2030, 1, 1))
    assert spaeter["gesamt"] == 0


def test_baustelle_status_und_gehweg():
    f = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [16.3738, 48.2082]},
         "properties": {"BEZEICHNUNG": "Stephansplatz", "BEHINDERUNGSART": "Straßenbau",
                        "PRESSETEXT": "Der Gehsteig wird gesperrt.  Ein Fahrstreifen bleibt.",
                        "OBJEKT_BEGINN": "2026-10-01Z", "OBJEKT_ENDE": "2026-12-01Z", "BEZIRK": 1}}
    d = wien.baustellen_aufbereiten([f], *STEPHANSPLATZ, 300, HEUTE)
    e = d["liste"][0]
    assert e["status"] == "geplant" and e["gehweg_betroffen"] and e["mit_sperrung"]
    assert e["distanz_m"] == 0 and e["richtung"] is None
    assert e["betroffene_bereiche"] == "Bezirk 1" and e["beginn"] == "2026-10-01"


def test_widmung_gemischtes_baugebiet_am_punkt():
    features = _lies("wien_r2_genflwidmungogd.json")["features"]
    lat, lon = _innen(features[0])
    fl = wien.widmung_aufbereiten(features, lat, lon)
    assert len(fl) == 1
    assert fl[0]["art"] == "Gemischtes Baugebiet Bauklasse 3"
    assert fl[0]["deutung"]["kuerzel"] == "GB" and "zulässig" in fl[0]["deutung"]["gastronomie"]
    assert fl[0]["aufschrift"] == "GB3" and fl[0]["plan"].endswith("1. Bezirk")
    assert wien.widmung_aufbereiten(features, 48.3, 16.5) == []


def test_widmung_deutung_kennt_wohngebiet_und_unbekanntes():
    assert "Belästigung" in wien.widmung_deuten("W", "Wohngebiet")["gastronomie"]
    u = wien.widmung_deuten("XYZ", "Sonstiges")
    assert u["art"] == "Sonstiges" and "Plandokument" in u["gastronomie"]
    assert wien.widmung_deuten(None, None) is None


class _Out:
    def __init__(self, antworten, fehler=()):
        self.antworten, self.fehler, self.params = antworten, set(fehler), []

    async def get_json(self, quelle, url, **kw):
        p = kw.get("params") or {}
        self.params.append(p)
        typ = p["typeName"].split(":")[1]
        if typ in self.fehler:
            raise SourceError("timeout", "Zeitüberschreitung")
        return self.antworten.get(typ) or {"features": []}


def test_baurecht_load_liefert_gebietsart():
    antwort = _lies("wien_r2_genflwidmungogd.json")
    lat, lon = _innen(antwort["features"][0])
    res = asyncio.run(wien.baurecht_load(_Out({"GENFLWIDMUNGOGD": antwort}), lat, lon))
    assert res.ok and res.data["stufe"] == "gebietsart" and res.data["gebiet"] == "Wien"
    assert res.data["baugebiete"][0]["deutung"]["kuerzel"] == "GB"
    assert "Sperrstunde" in " ".join(res.data["hinweise"])


def test_baurecht_load_ohne_treffer_ist_kein_plan():
    res = asyncio.run(wien.baurecht_load(_Out({}), *STEPHANSPLATZ))
    assert res.ok and res.data["stufe"] == "kein_plan" and res.warnings


def test_baustellen_load_uebersteht_einen_ausfall():
    out = _Out({"BAUSTELLENPKTOGD": _lies("wien_baustellenpktogd.json")}, fehler={"BAUSTELLENLINOGD"})
    res = asyncio.run(wien.baustellen_load(out, *STEPHANSPLATZ, 1500, HEUTE))
    assert res.ok and res.data["gesamt"] >= 1
    assert any("BAUSTELLENLINOGD" in w for w in res.warnings)
    assert [p["typeName"] for p in out.params] == ["ogdwien:BAUSTELLENPKTOGD", "ogdwien:BAUSTELLENLINOGD"]
    assert all(p["bbox"].endswith("EPSG:4326") and p["outputFormat"] == "json" for p in out.params)
    beide = _Out({}, fehler={"BAUSTELLENPKTOGD", "BAUSTELLENLINOGD"})
    assert asyncio.run(wien.baustellen_load(beide, *STEPHANSPLATZ, 1500, HEUTE)).ok is False


def test_maerkte_load_ohne_bbox():
    out = _Out({"MAERKTEOGD": _lies("wien_maerkteogd.json")})
    res = asyncio.run(wien.maerkte_load(out, *STEPHANSPLATZ, 600))
    assert res.ok and res.data["stadtweit"] == 23 and "bbox" not in out.params[0]
