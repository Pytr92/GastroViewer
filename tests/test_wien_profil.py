"""Wien: Zählbezirks-Steckbrief und Lage-Indikatoren — Live-Antworten vom 18.09.2026."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from gastroviewer.sources import wien_profil
from gastroviewer.sources.base import SourceError

AT = Path(__file__).resolve().parent.parent / "fixtures" / "at"
STEPHANSPLATZ = (48.2082, 16.3738)


def _lies(n):
    return json.loads((AT / n).read_text("utf-8"))


@pytest.fixture(scope="module")
def zb():
    return wien_profil.zb_reduzieren((AT / "wien_bev_zaehlbezirk_auszug.csv").read_text("utf-8"))


def test_zaehlbezirk_code():
    assert wien_profil.zaehlbezirk_code(_lies("wien_r5_zaehlbezirkogd.json")["features"][0]) == "90101"
    assert wien_profil.zaehlbezirk_code(None) is None


def test_zb_reduzieren(zb):
    assert "90101" in zb and wien_profil.STADT_RAUM in zb
    j = zb["90101"]
    assert "2008" in j and "2024" in j or "2025" in j
    w = j[max(j)]
    assert 1000 < w["einwohner"] < 20000, "Zählbezirk 01.01 (Teil der Inneren Stadt)"
    assert 0 < w["auslaenderanteil"] < 60 and 0 < w["unter15"] < 20 and 10 < w["ab65"] < 40
    stadt = zb[wien_profil.STADT_RAUM]
    assert stadt[max(stadt)]["einwohner"] > 1_900_000


def test_zb_auswerten_blockform(zb):
    d = wien_profil.zb_auswerten(zb, "90101", "Innere Stadt")
    assert d["bezirk"] == "Zählbezirk 01.01 (Innere Stadt)" and d["stadt_raum"] == "Wien gesamt"
    schl = {z["schluessel"]: z for z in d["indikatoren"]}
    assert schl["einwohner"]["bezirk"]["wert"] > 1000 and schl["einwohner"]["stadt"]["wert"] > 1_900_000
    assert schl["einwohner"]["bezirk"]["von_jahr"] is not None and schl["einwohner"]["reihe"]
    assert schl["auslaenderanteil"]["einheit"] == "%"
    ohne = wien_profil.zb_auswerten(zb, None, None)
    assert ohne["bezirk"] is None and ohne["indikatoren"][0]["bezirk"] is None


class _Out:
    def __init__(self, wfs, fehler=()):
        self.wfs, self.fehler, self.typen = wfs, set(fehler), []

    async def get_json(self, quelle, url, **kw):
        typ = kw["params"]["typeName"].split(":")[1]
        self.typen.append(typ)
        if typ in self.fehler:
            raise SourceError("timeout", "weg")
        return self.wfs.get(typ) or {"features": []}


def _wfs():
    # Die Realnutzung kam mit Runde 9 dazu (Jahrgang 2024, umbenannte Felder),
    # die übrigen Layer stammen aus Runde 5.
    layer = {t: _lies(f"wien_r5_{t.lower()}.json") for t in
             ("KURZPARKZONEOGD", "FUSSGEHERZONEOGD", "BEGEGNUNGSZONEOGD", "STRUKGESCHSTROGD",
              "GEBAEUDEINFOOGD", "ZAEHLBEZIRKOGD")}
    layer["REALNUT2024OGD"] = _lies("wien_r9_realnut2024ogd.json")
    return layer


def test_zaehlbezirk_load(zb):
    async def laden():
        return zb

    res = asyncio.run(wien_profil.zaehlbezirk_load(_Out(_wfs()), *STEPHANSPLATZ, "Innere Stadt", laden))
    assert res.ok and res.name == "indikatoren" and res.data["bezirk"].startswith("Zählbezirk 01.01")
    assert not res.warnings and "MA 23" in res.provenance.source


def test_lage_load_stephansplatz():
    out = _Out(_wfs())
    res = asyncio.run(wien_profil.lage_load(out, *STEPHANSPLATZ, 600))
    assert res.ok and res.name == "lage"
    l = res.data
    assert l["kurzparkzone"]["dauer"] == "2 h" and "9-22" in l["kurzparkzone"]["zeitraum"]
    assert len(l["fussgaengerzonen"]) >= 10 and l["fussgaengerzonen"][0]["distanz_m"] <= l["fussgaengerzonen"][-1]["distanz_m"]
    assert all(z["adresse"] for z in l["fussgaengerzonen"][:5])
    assert l["begegnungszonen"] and l["begegnungszonen"][0]["adresse"]
    assert l["geschaeftsstrasse"]["naechste"] is not None and l["geschaeftsstrasse"]["im_radius"] >= 1
    # Jahrgang 2024 des Realnutzungs-Layers: Felder heißen LEV1..3 statt
    # NUTZUNG_LEVEL1..3 — der Block liest beide Schemata (Runde 9).
    # Am Stephansplatz steht der Dom — im Jahrgang 2024 wie schon 2022
    # „Kultur, Freizeit, Messe". Dass beide Jahrgänge dasselbe sagen, belegt
    # nebenbei, dass die umbenannten Felder richtig zugeordnet sind.
    assert l["realnutzung"]["stufe3"] == "Kultur, Freizeit, Messe"
    assert l["realnutzung"]["stufe1"] == "Baulandnutzung" and l["realnutzung"]["jahr"] == 2024
    assert l["gebaeude"] and l["gebaeude"][0]["baujahr"] and l["gebaeude"][0]["distanz_m"] <= 150 and "\n" not in l["gebaeude"][1]["architekt"]
    assert set(out.typen) == {"KURZPARKZONEOGD", "FUSSGEHERZONEOGD", "BEGEGNUNGSZONEOGD", "STRUKGESCHSTROGD",
                              "REALNUT2024OGD", "GEBAEUDEINFOOGD"}


def test_lage_load_ausserhalb_und_ausfall():
    res = asyncio.run(wien_profil.lage_load(_Out({}), 48.1372, 11.5755, 600))
    assert res.ok and res.data is None and "nur für Wien" in res.warnings[0]
    alle = {"KURZPARKZONEOGD", "FUSSGEHERZONEOGD", "BEGEGNUNGSZONEOGD", "STRUKGESCHSTROGD", "REALNUT2024OGD", "GEBAEUDEINFOOGD"}
    res = asyncio.run(wien_profil.lage_load(_Out({}, fehler=alle), *STEPHANSPLATZ, 600))
    assert res.ok is False
    res = asyncio.run(wien_profil.lage_load(_Out(_wfs(), fehler={"GEBAEUDEINFOOGD"}), *STEPHANSPLATZ, 600))
    assert res.ok and res.data["gebaeude"] == [] and any("GEBAEUDEINFOOGD" in w for w in res.warnings)
