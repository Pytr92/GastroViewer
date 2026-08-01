"""Bodenrichtwert-Kartendienste der Länder — Phase 4.

Die Regel aus §4.5 lautet: **keine URL raten.** Diese Tests halten fest, dass im
Register nur steht, was am 2026-08-01 verifiziert wurde, und dass für Länder ohne
Dienst ein Grund genannt wird statt einer erfundenen Adresse.

Die Antwortbeispiele stammen aus echten GetFeatureInfo-Aufrufen der jeweiligen
Dienste; sie decken alle fünf Formate ab, die die sieben Länder liefern.
"""

from __future__ import annotations

import pytest

from gastroviewer.sources import boris, wms
from gastroviewer.sources.zensus import BUNDESLAENDER

ALLE_CODES = set(BUNDESLAENDER)


# ------------------------------------------------------------- Register


def test_jedes_bundesland_ist_entweder_dienst_oder_begruendet():
    """Kein Land darf stillschweigend durchfallen."""
    abgedeckt = set(wms.DIENSTE) | set(wms.OHNE_DIENST)
    assert abgedeckt == ALLE_CODES, f"nicht behandelt: {ALLE_CODES - abgedeckt}"
    assert not (set(wms.DIENSTE) & set(wms.OHNE_DIENST)), "Land doppelt geführt"


def test_jeder_dienst_ist_vollstaendig_beschrieben():
    pflicht = {
        "land", "titel", "url", "version", "layers", "query_layers", "info_format",
        "params", "lizenz", "attribution", "stand", "portal", "abfragbar",
        "abfrage_hinweis",
    }
    for code, d in wms.DIENSTE.items():
        fehlend = pflicht - set(d)
        assert not fehlend, f"{code}: {fehlend}"
        assert d["url"].startswith("https://"), f"{code}: kein HTTPS"
        assert d["version"] in ("1.1.1", "1.3.0"), f"{code}: unbekannte WMS-Version"
        assert d["abfragbar"] in ("voll", "eingeschraenkt", "nein")


def test_kein_dienst_ohne_lizenzangabe():
    for code, d in wms.DIENSTE.items():
        assert len(d["lizenz"]) > 10, f"{code} ohne brauchbare Lizenzangabe"
        assert "©" in d["attribution"], f"{code} ohne Namensnennung"


def test_laender_ohne_dienst_bekommen_einen_grund_statt_einer_url():
    for code, grund in wms.OHNE_DIENST.items():
        assert len(grund) > 20, f"{code}: Grund zu dünn"
        assert "http" not in grund, f"{code}: enthält eine URL — nicht raten"
    cfg = wms.fuer_bundesland("09")
    assert cfg["verfuegbar"] is False
    assert "rechtlichen Gründen" in cfg["grund"]
    assert "keine URL geraten" in cfg["hinweis"]


def test_die_fuenf_laender_ohne_boris_d_haben_auch_keinen_wms():
    """§4.5 nennt BY, BW, SL, SH, MV als rechtlich ausgenommen. Wäre für eines
    davon plötzlich ein Dienst hinterlegt, wäre das ein Fehlgriff."""
    for code in boris.NICHT_IN_BORIS_D:
        assert code not in wms.DIENSTE, f"{BUNDESLAENDER[code]} unerwartet im Register"


def test_ohne_bundesland_kein_dienst():
    cfg = wms.fuer_bundesland(None)
    assert cfg["verfuegbar"] is False
    assert "Bundesland" in cfg["grund"]


def test_boris_block_traegt_den_kartendienst():
    bayern = boris.links_for("09", "München")
    assert bayern["kartendienst"]["verfuegbar"] is False
    assert "Suchlink" in " ".join(link["status"] for link in bayern["links"])

    nrw = boris.links_for("05", "Köln")
    assert nrw["kartendienst"]["verfuegbar"] is True
    assert nrw["kartendienst"]["land"] == "Nordrhein-Westfalen"
    assert "Kartendienst eingebunden" in nrw["quelle"]


# --------------------------------------------------------- Zoomableitung


@pytest.mark.parametrize(
    "max_scale,erwartet",
    [
        (56696.428571, 14),  # NRW laut Capabilities
        (100_001.0, 13),     # Thüringen
        (125_000, 13),       # Brandenburg
        (5_000_000, 7),      # Niedersachsen, Sachsen-Anhalt
        (None, 0),           # kein Limit im Dienst
    ],
)
def test_min_zoom_wird_aus_dem_dienst_abgeleitet(max_scale, erwartet):
    """Ohne diese Ableitung bliebe die Ebene bei kleinem Zoom stumm leer und
    sähe aus wie ein Fehler."""
    assert wms.min_zoom_fuer(max_scale) == erwartet


def test_min_zoom_passt_zu_den_hinterlegten_diensten():
    assert wms.fuer_bundesland("05")["min_zoom"] == 14
    assert wms.fuer_bundesland("16")["min_zoom"] == 13
    assert wms.fuer_bundesland("02")["min_zoom"] == 0


# ------------------------------------------------- Antworten zerlegen
# Alle Auszüge stammen aus echten Antworten der Dienste (2026-08-01).


def test_thueringen_format():
    text = (
        "_featuremember_$#$BODENRICHTWERT=1000$#$BODENRICHTWERTNUMMER=182272"
        "$#$STICHTAG=2026-01-01$#$ENTWICKLUNGSZUSTAND=Baureifes Land (B)"
    )
    f = {x["feld"]: x["wert"] for x in wms.werte_aus_antwort(text, "text/plain")}
    assert f["BODENRICHTWERT"] == "1000"
    assert f["STICHTAG"] == "2026-01-01"
    assert f["ENTWICKLUNGSZUSTAND"] == "Baureifes Land (B)"


def test_geojson_format_nrw():
    text = (
        '{"type":"FeatureCollection","features":[{"type":"Feature","properties":'
        '{"Bodenrichtwert":"2200","Entwicklungszustand":"baureifes Land",'
        '"Bemerkung":"Unter Sachsenhausen","Leerfeld":null,"Leerfeld2":"  "}}]}'
    )
    f = {x["feld"]: x["wert"] for x in wms.werte_aus_antwort(text, "application/geo+json")}
    assert f["Bodenrichtwert"] == "2200"
    assert "Leerfeld" not in f, "null-Werte dürfen nicht als Wert erscheinen"
    assert "Leerfeld2" not in f, "leere Zeichenketten ebenso wenig"


def test_gml_format_niedersachsen():
    text = (
        "<?xml version='1.0'?><FeatureCollection xmlns:app='x'>"
        "<gml:boundedBy xmlns:gml='y'><gml:null>missing</gml:null></gml:boundedBy>"
        "<app:bodenrichtwert>10500.0</app:bodenrichtwert>"
        "<app:bodenrichtwertNummer>04305001</app:bodenrichtwertNummer>"
        "</FeatureCollection>"
    )
    f = {x["feld"]: x["wert"] for x in wms.werte_aus_antwort(text, "text/xml")}
    assert f["bodenrichtwert"] == "10500.0"
    assert f["bodenrichtwertNummer"] == "04305001"
    assert "null" not in f, "gml:null=missing ist kein Sachwert"


def test_html_format_brandenburg():
    text = (
        "<html><body><table>"
        "<tr><td>Bodenrichtwert</td><td>1200 &euro;/m&sup2;</td></tr>"
        "<tr><td>Entwicklungszustand</td><td>Baureifes Land</td></tr>"
        "</table></body></html>"
    )
    f = {x["feld"]: x["wert"] for x in wms.werte_aus_antwort(text, "text/html")}
    assert "1200" in f["Bodenrichtwert"]
    assert f["Entwicklungszustand"] == "Baureifes Land"


def test_leere_antwort_ergibt_keine_felder():
    """Rheinland-Pfalz liefert Feature-IDs ohne Sachdaten — daraus darf nichts
    erfunden werden."""
    text = "GetFeatureInfo results:\n\nLayer 'Gemischte_Bauflaechen'\n  Feature 2388: \n"
    assert wms.werte_aus_antwort(text, "text/plain") == []
    assert wms.werte_aus_antwort("", "text/plain") == []


def test_hamburg_liefert_zone_aber_keinen_wert():
    """Festgehalten als Eigenschaft des Dienstes, damit es nicht als Fehler gilt."""
    text = (
        "<?xml version='1.0'?><FeatureCollection>"
        "<app:zonen_nr xmlns:app='x'>63682</app:zonen_nr>"
        "<app:jahrgang xmlns:app='x'>2026</app:jahrgang>"
        "</FeatureCollection>"
    )
    f = {x["feld"]: x["wert"] for x in wms.werte_aus_antwort(text, "text/xml")}
    assert f == {"zonen_nr": "63682", "jahrgang": "2026"}
    cfg = wms.fuer_bundesland("02")
    assert cfg["abfragbar"] == "eingeschraenkt"
    assert "nicht den" in cfg["abfrage_hinweis"]


# ----------------------------------------------------------- Abfrageweg


async def test_feature_info_ohne_dienst_meldet_das_ohne_fehler(settings):
    res = await wms.feature_info(None, settings, 48.1334, 11.5674, "09")
    assert res.ok is True, "fehlender Dienst darf keinen Fehlerzustand erzeugen"
    assert res.data is None
    assert "Bayern" in res.warnings[0]


async def test_feature_info_baut_die_anfrage_korrekt(settings):
    gesehen: dict = {}

    class FakeOut:
        async def request(self, source, method, url, params=None, **kw):
            gesehen["url"] = url
            gesehen["params"] = params

            class R:
                status_code = 200
                headers = {"content-type": "application/geo+json"}
                text = (
                    '{"features":[{"properties":{"Bodenrichtwert":"2200",'
                    '"Entwicklungszustand":"baureifes Land"}}]}'
                )

            return R()

    res = await wms.feature_info(FakeOut(), settings, 50.9413, 6.9583, "05")
    assert res.ok and res.data
    p = gesehen["params"]
    assert gesehen["url"] == wms.DIENSTE["05"]["url"]
    assert p["REQUEST"] == "GetFeatureInfo"
    assert p["CRS"] == "EPSG:3857", "WMS 1.3.0 nutzt CRS, nicht SRS"
    assert p["I"] == "50" and p["J"] == "50"
    assert p["TIME"] == "2026-01-01", "NRW braucht die Zeitdimension"
    assert p["QUERY_LAYERS"] == "brw_mehrgeschossige_bauweise"
    felder = {x["feld"]: x["wert"] for x in res.data["felder"]}
    assert felder["Bodenrichtwert"] == "2200"
    assert "dl-de/zero-2-0" in res.provenance.license
    assert "fiktives Grundstück" in res.provenance.note


async def test_wms_111_nutzt_srs_und_xy(settings):
    gesehen: dict = {}

    class FakeOut:
        async def request(self, source, method, url, params=None, **kw):
            gesehen.update(params)

            class R:
                status_code = 200
                headers = {"content-type": "text/plain"}
                text = "GetFeatureInfo results:"

            return R()

    await wms.feature_info(FakeOut(), settings, 49.9929, 8.2473, "07")
    assert gesehen["SRS"] == "EPSG:3857", "WMS 1.1.1 nutzt SRS"
    assert "CRS" not in gesehen
    assert gesehen["X"] == "50" and gesehen["Y"] == "50"


async def test_ausfall_des_landesdienstes_wird_benannt(settings):
    from gastroviewer.sources.base import SourceError

    class FakeOut:
        async def request(self, *a, **kw):
            raise SourceError("timeout", "Zeitüberschreitung — Dienst antwortet nicht.")

    res = await wms.feature_info(FakeOut(), settings, 50.9413, 6.9583, "05")
    assert res.ok is False
    assert res.error["kind"] == "timeout"


async def test_unauswertbare_antwort_liefert_den_rohtext(settings):
    class FakeOut:
        async def request(self, *a, **kw):
            class R:
                status_code = 200
                headers = {"content-type": "text/plain"}
                text = "Etwas völlig Unerwartetes"

            return R()

    res = await wms.feature_info(FakeOut(), settings, 50.9413, 6.9583, "05")
    assert res.ok and res.data["felder"] == []
    assert res.data["rohantwort"] == "Etwas völlig Unerwartetes"
    assert "Originaltext" in res.warnings[0]
