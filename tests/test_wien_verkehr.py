"""Wien: Kfz-Dauerzählstellen (Verkehrsmenge) und Luftgütemessnetz (Luft)
gegen die Live-Aufzeichnungen vom 18.09.2026 (Runden 6 und 7)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from gastroviewer.sources import wien_verkehr as wv
from gastroviewer.sources.base import SourceError

AT = Path(__file__).resolve().parent.parent / "fixtures" / "at"
STEPHANSPLATZ = (48.2082, 16.3738)


def _kfz_csv():
    return (AT / "wien_r7_dauerzaehlstellen_2025.csv").read_text("utf-8")


def _lumes():
    return (AT / "wien_r7_luft_lumes.csv").read_text("cp1252")


def _wfs(typ):
    return json.loads((AT / f"wien_r6_{typ.lower()}.json").read_text("utf-8"))


class _Out:
    def __init__(self, wfs, texte, fehler=()):
        self.wfs, self.texte, self.fehler = wfs, texte, set(fehler)
        self.typen = []

    async def get_json(self, source, url, params=None, **kw):
        typ = (params or {}).get("typeName", "").split(":")[-1]
        self.typen.append(typ)
        if typ in self.fehler:
            raise SourceError("timeout", "Zeitüberschreitung")
        return self.wfs.get(typ) or {"features": []}

    async def get_text(self, source, url, **kw):
        if "csv" in self.fehler:
            raise SourceError("http_status", "HTTP 503")
        for k, v in self.texte.items():
            if k in url:
                return v
        raise SourceError("http_status", "HTTP 404")


def test_kfz_reduzieren_westbahnhof():
    w = wv.kfz_reduzieren(_kfz_csv())
    assert w["jahr"] == 2025 and len(w["stellen"]) == 71
    wb = w["stellen"]["1078"]
    assert wb["name"] == "Westbahnhof" and wb["strasse"] == "B221" and wb["monate"] == 12
    # Mittel der zwölf DTVMS-Monatswerte (Gesamt, Kfz): 65 606 … 69 370
    assert 66_000 < wb["dtv_kfz"] < 67_500
    assert wb["dtv_sonntag"] < wb["dtv_werktag"] and wb["dtv_schwerverkehr"] < 2_000
    assert wb["spitzentag"]["tag"] == "Sa,05.04." and wb["spitzentag"]["kfz"] == 76094


def test_kfz_aufbereiten_stephansplatz():
    w = wv.kfz_reduzieren(_kfz_csv())
    d = wv.kfz_aufbereiten(_wfs("DAUERZAEHLOGD")["features"], w, *STEPHANSPLATZ, 600)
    assert d["dienst"] == "wien" and d["jahr"] == 2025 and d["stadt"] == "Wien"
    assert d["naechste"]["strasse"].startswith("Franz-Josefs-Kai") and d["naechste"]["distanz_m"] < 600
    assert d["naechste"]["im_radius"] is True
    assert d["staerkste"]["dtv_kfz"] > 10_000 and d["staerkste"]["schwerverkehr_anteil"] is not None
    assert all(z["distanz_m"] <= wv.MAX_DISTANZ_M for z in d["zaehlstellen"])
    # Zählstellen ohne Werte im jüngsten Jahr stehen ohne Zahl, nicht mit 0.
    assert any(z["dtv_kfz"] is None for z in d["zaehlstellen"])


def test_kfz_load_und_ausfall():
    out = _Out({"DAUERZAEHLOGD": _wfs("DAUERZAEHLOGD")}, {})

    async def werte():
        return wv.kfz_reduzieren(_kfz_csv())

    res = asyncio.run(wv.kfz_load(out, *STEPHANSPLATZ, 600, werte))
    assert res.ok and res.name == "verkehrsmenge" and res.data["zaehlstellen"]
    assert "MA 46" in res.provenance.source and res.data["portal_titel"]
    res = asyncio.run(wv.kfz_load(_Out({}, {}, fehler={"DAUERZAEHLOGD"}), *STEPHANSPLATZ, 600, werte))
    assert not res.ok and res.error["kind"] == "timeout"


def test_lumes_parsen_und_index():
    lum = wv.lumes_parsen(_lumes())
    assert set(lum) >= {"STEF", "TAB", "AKC", "LOB"}
    assert lum["STEF"]["werte"]["NO2"]["HMW"] == 9.09 and lum["STEF"]["werte"]["NO2"]["_einheit"] == "µg/m³"
    assert lum["TAB"]["werte"]["PM10"]["MW24"] == 11.46 and lum["TAB"]["werte"]["PM10"]["HMW"] == 8.7
    assert wv.teilindex("NO2", 9.09) == 1 and wv.teilindex("NO2", 41) == 3 and wv.teilindex("PM10", 101) == 5
    assert wv.teilindex("SO2", 5) is None and wv.teilindex("O3", None) is None


def test_luft_auswerten_stephansplatz():
    lum = wv.lumes_parsen(_lumes())
    e = wv.luft_auswerten(lum["STEF"], "Stephansplatz")
    assert e["index"] == 2 and e["index_label"] == "gut" and e["stand"] == "2026-09-18T21:30"
    namen = [k["komponente"] for k in e["komponenten"]]
    assert namen[0].startswith("Stickstoffdioxid") and any(k.startswith("Ozon") for k in namen)
    assert all(k["wert"] is not None for k in e["komponenten"]) and not e["unvollstaendig"]
    # Dachstation ohne Luftkomponenten → keine Auswertung
    assert wv.luft_auswerten(lum["AKA"], "AKH-Dach") is None


def test_luft_load_stephansplatz_und_ausfall():
    out = _Out({"LUFTGUETENETZOGD": _wfs("LUFTGUETENETZOGD")}, {"l9lumesakt": _lumes()})
    res = asyncio.run(wv.luft_load(out, *STEPHANSPLATZ))
    assert res.ok and res.name == "luft" and res.data["station"]["code"] == "STEF"
    assert res.data["station"]["distanz_m"] < 100 and res.data["dienst"] == "wien"
    assert "MA 22" in res.provenance.source and not res.warnings
    # Taborstraße näher als Stephansplatz von der Leopoldstadt aus
    res = asyncio.run(wv.luft_load(out, 48.2155, 16.3800))
    assert res.ok and res.data["station"]["code"] == "TAB" and res.data["index_label"] == "sehr gut"
    # weit weg: keine Station
    res = asyncio.run(wv.luft_load(out, 48.35, 16.60))
    assert res.ok and res.data is None and "innerhalb von 6 km" in res.warnings[0]
    res = asyncio.run(wv.luft_load(_Out({}, {}, fehler={"csv"}), *STEPHANSPLATZ))
    assert not res.ok and res.error["kind"] == "http_status"
