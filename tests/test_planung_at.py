"""Planungsrecht Österreich: LFRZ-Hochwasser und Wiener Schutzzonen."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from gastroviewer.sources import planung_at, wien
from gastroviewer.sources.base import SourceError

AT = Path(__file__).resolve().parent.parent / "fixtures" / "at"
KREMS = (48.4020, 15.6100)
STEPHANSPLATZ = (48.2082, 16.3738)


def _lies(name: str):
    return json.loads((AT / name).read_text("utf-8"))


def test_gfi_params_fragen_alle_layer_in_crs84():
    p = planung_at.gfi_params(list(planung_at.HOCHWASSER_LAYER) + [planung_at.RISIKO_LAYER],
                              *KREMS)
    assert p["crs"] == "CRS:84" and p["info_format"] == "application/json"
    assert p["layers"] == p["query_layers"]
    assert "Hochwasserueberflutungsflaechen HQ100" in p["layers"]
    assert p["layers"].endswith("Hochwasserrisikogebiete HQ100")
    w, s, o, n = (float(x) for x in p["bbox"].split(","))
    assert w < KREMS[1] < o and s < KREMS[0] < n


def test_risikogebiet_wachau_wird_getrennt_gefuehrt():
    """Live-Antwort am Kremser Donauufer: ein Risikogebiet (HWRM-RL), keine
    Überflutungsfläche — der Block darf daraus kein „betroffen" machen."""
    hw = planung_at.hochwasser_aufbereiten(_lies("hochwasser_gfi_risikogebiet_hq100_krems_kurz.json"))
    assert hw["betroffen"] is False and hw["gebiete"] == []
    assert hw["hq_haeufig"] is False and hw["hq_100"] is False and hw["hq_extrem"] is False
    assert len(hw["risikogebiete"]) == 1
    r = hw["risikogebiete"][0]
    assert r["gewaesser"] == "Wachau" and r["jaehrlichkeit"] == "Risikogebiet HQ100"
    assert r["bundesland"] == "Niederösterreich" and r["ermittelt"] == "2013-07-19"
    assert r["layer"] == "Hochwasserrisikogebiete HQ100"


def test_leere_antwort_heisst_nicht_betroffen():
    hw = planung_at.hochwasser_aufbereiten(_lies("hochwasser_gfi_leer.json"))
    assert hw == {"betroffen": False, "gebiete": [], "risikogebiete": [],
                  "hq_haeufig": False, "hq_100": False, "hq_extrem": False}


def test_ueberflutungsflaechen_werden_nach_layer_eingestuft():
    """Für die Überflutungs-Layer fehlt ein positiver Live-Beleg — die
    Einstufung hängt deshalb nur am Layer-Präfix der id bzw. am Szenario."""
    payload = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": "Hochwasserueberflutungsflaechen HQ300.17",
         "properties": {"SZENARIO": "HQ300", "LABEL": "Donau"}},
        {"type": "Feature", "id": "Hochwasserueberflutungsflaechen HQ30.5",
         "properties": {"SZENARIO": "HQ30", "LABEL": "Donau"}},
        {"type": "Feature", "id": "Rote Gefahrenzonen aus der Gefahrenzonenplanung.9",
         "properties": {"LABEL": "Wildbach"}},
        {"type": "Feature", "id": "unbekannt.1", "properties": {"SZENARIO": "HQ100"}},
    ]}
    hw = planung_at.hochwasser_aufbereiten(payload)
    assert hw["betroffen"] and hw["hq_haeufig"] and hw["hq_100"] and hw["hq_extrem"]
    assert [g["jaehrlichkeit"] for g in hw["gebiete"]] == [
        "HQ30 (häufig)", "Rote Gefahrenzone", "HQ100", "HQ300 (extrem)"]
    assert hw["gebiete"][0]["gewaesser"] == "Donau"


class _Out:
    def __init__(self, antworten):
        self.antworten = antworten
        self.urls = []

    async def get_json(self, quelle, url, **kw):
        self.urls.append((quelle, url, kw.get("params") or {}))
        a = self.antworten.get(quelle)
        if isinstance(a, SourceError):
            raise a
        return a


def test_load_in_wien_fragt_hochwasser_und_schutzzonen():
    out = _Out({"lfrz_hochwasser": _lies("hochwasser_gfi_leer.json"),
                "wien_schutzzonen": _lies("wien_schutzzoneogd.json")})
    res = asyncio.run(planung_at.load(out, *STEPHANSPLATZ))
    assert res.ok and res.name == "planung"
    assert res.data["hochwasser"]["dienst"] == "lfrz" and res.data["land"] == "AT"
    assert res.data["erhaltungssatzung"]["betroffen"] is False
    assert res.data["texte"]["erhaltungssatzung_titel"].startswith("Schutzzone")
    assert [u[0] for u in out.urls] == ["lfrz_hochwasser", "wien_schutzzonen"]
    assert out.urls[1][2]["typeName"] == "ogdwien:SCHUTZZONEOGD"
    assert "Wien" in res.provenance.source and "LFRZ" in res.provenance.source


def test_load_ausserhalb_wiens_nur_hochwasser_mit_risikowarnung():
    out = _Out({"lfrz_hochwasser": _lies("hochwasser_gfi_risikogebiet_hq100_krems_kurz.json")})
    res = asyncio.run(planung_at.load(out, *KREMS))
    assert res.ok and "erhaltungssatzung" not in res.data
    assert any("Wachau" in w for w in res.warnings)
    assert any("nur für Wien" in w for w in res.warnings)
    assert [u[0] for u in out.urls] == ["lfrz_hochwasser"]


def test_load_ohne_dienst_faellt_ehrlich_aus():
    out = _Out({"lfrz_hochwasser": SourceError("timeout", "Zeitüberschreitung")})
    res = asyncio.run(planung_at.load(out, *KREMS))
    assert res.ok is False and res.error["kind"] == "timeout"


def test_baurecht_ohne_dienst_hat_blockform():
    res = planung_at.baurecht_ohne_dienst("Österreich")
    assert res.ok and res.data["stufe"] == "kein_dienst" and res.data["baugebiete"] == []
    assert any("nur Wien" in w for w in res.warnings)


def test_schutzzone_nur_bei_punkt_in_flaeche():
    features = _lies("wien_schutzzoneogd.json")["features"]
    ring = features[0]["geometry"]["coordinates"][0]
    innen_lon = sum(p[0] for p in ring) / len(ring)
    innen_lat = sum(p[1] for p in ring) / len(ring)
    drin = wien.schutzzonen_aufbereiten(features, innen_lat, innen_lon)
    if drin["betroffen"]:  # Schwerpunkt kann bei konkaven Flächen außen liegen
        assert drin["gebiete"][0]["name"].startswith("Schutzzone 20. Brigittenau")
    draussen = wien.schutzzonen_aufbereiten(features, *STEPHANSPLATZ)
    assert draussen["betroffen"] is False and draussen["gebiete"] == []


def test_sammelabfrage_krems_liefert_layerpraefix():
    """Runde 4: alle sechs Layer in einer Anfrage — GeoServer nennt den Layer
    im id-Präfix, das Risikogebiet Wachau bleibt getrennt von den
    Überflutungsflächen (die am Kremser Ufer leer antworten)."""
    hw = planung_at.hochwasser_aufbereiten(_lies("hochwasser_r4_sammel_krems_kurz.json"))
    assert hw["betroffen"] is False and [r["gewaesser"] for r in hw["risikogebiete"]] == ["Wachau"]
    assert planung_at.hochwasser_aufbereiten(_lies("hochwasser_r4_sammel_stephansplatz.json"))["risikogebiete"] == []


def test_schutzzone_innere_stadt_am_stephansplatz():
    sz = wien.schutzzonen_aufbereiten(_lies("wien_r4_schutzzoneogd_stephansplatz.json")["features"], *STEPHANSPLATZ)
    assert sz["betroffen"] and sz["gebiete"][0]["name"] == "Schutzzone 1. Innere Stadt"
    assert sz["titel"].startswith("Schutzzone")

