"""Gehstrecke statt Luftlinie.

Grundlage ist eine echte Overpass-Antwort vom Isarufer (aufgezeichnet am
2026-08-01, Datenstand 2026-07-02). Dort ist die Barriere echt: westlich und
östlich des Flusses liegen Wege dicht beieinander, verbunden sind sie nur über
die Brücken. Genau daran muss sich die Rechnung bewähren.
"""

from __future__ import annotations

import pytest

from conftest import load_fixture
from gastroviewer.sources import gehweg
from gastroviewer.sources.base import haversine_m

# Punkt, mit dem das Fixture aufgezeichnet wurde — Isarufer West.
LAT, LON = 48.1297, 11.5822


@pytest.fixture(scope="module")
def netz():
    roh = load_fixture("raw_overpass_gehweg_isar.json")
    return gehweg.baue_netz(roh["elements"])


@pytest.fixture(scope="module")
def strecken(netz):
    start, anbindung = netz.naechster_knoten(LAT, LON)
    return netz, start, anbindung, gehweg.gehstrecken(netz, start, 600.0)


# ------------------------------------------------------------------ Netzbau


def test_fixture_ist_die_echte_antwort():
    roh = load_fixture("raw_overpass_gehweg_isar.json")
    assert roh["osm3s"]["timestamp_osm_base"].startswith("2026-")
    assert sum(1 for e in roh["elements"] if e.get("type") == "way") == 562


def test_netz_verbindet_wege_an_gemeinsamen_knoten(netz):
    """OSM-Wege teilen sich an Kreuzungen denselben Knoten und damit exakt
    dieselbe Koordinate — sonst zerfiele der Graph in Einzelstücke."""
    assert len(netz) > 1000
    assert netz.kantenzahl > len(netz) * 0.9
    # Ein reiner Streckenzug hätte im Schnitt 2 Nachbarn; Kreuzungen heben das.
    grade = [len(v) for v in netz.kanten.values()]
    assert max(grade) >= 3, "ohne Kreuzungen wäre nichts verbunden"


def test_gesperrte_wege_fallen_heraus():
    elements = [
        {"type": "way", "tags": {"highway": "footway", "foot": "no"},
         "geometry": [{"lat": 48.13, "lon": 11.58}, {"lat": 48.131, "lon": 11.58}]},
        {"type": "way", "tags": {"highway": "service", "access": "private"},
         "geometry": [{"lat": 48.13, "lon": 11.58}, {"lat": 48.131, "lon": 11.581}]},
        {"type": "way", "tags": {"highway": "footway"},
         "geometry": [{"lat": 48.13, "lon": 11.58}, {"lat": 48.131, "lon": 11.582}]},
    ]
    n = gehweg.baue_netz(elements)
    assert n.wege == 1 and n.uebersprungen == 2


def test_privatweg_mit_ausdruecklichem_fussrecht_bleibt():
    """`access=private` plus `foot=yes` ist ein begehbarer Privatweg."""
    elements = [{
        "type": "way",
        "tags": {"highway": "service", "access": "private", "foot": "yes"},
        "geometry": [{"lat": 48.13, "lon": 11.58}, {"lat": 48.131, "lon": 11.58}],
    }]
    assert gehweg.baue_netz(elements).wege == 1


# ---------------------------------------------------------------- Rechnung


def test_gehstrecke_ist_nie_kuerzer_als_die_luftlinie(strecken):
    netz, start, _anbindung, dist = strecken
    verstoesse = [
        (k, d) for k, d in dist.items()
        if d + 1e-6 < haversine_m(start[0], start[1], k[0], k[1])
    ]
    assert not verstoesse, "ein Weg kann nicht kürzer sein als die Luftlinie"


def test_dijkstra_bricht_jenseits_der_reichweite_ab(strecken):
    _netz, _start, _anbindung, dist = strecken
    assert dist, "es muss etwas erreichbar sein"
    assert max(dist.values()) <= 600.0


def test_der_fluss_trennt_wirklich(netz):
    """Der Kern der Sache: Knoten jenseits der Isar liegen im Luftlinienkreis,
    sind zu Fuß aber nur über eine Brücke und damit weiter zu erreichen.

    Luftlinienkreis und Gehradius müssen dafür gleich groß sein — sonst
    vergleicht man zwei verschiedene Gebiete und findet nichts."""
    start, _anbindung = netz.naechster_knoten(LAT, LON)
    dist = gehweg.gehstrecken(netz, start, 250.0)
    im_kreis = [k for k in netz.kanten if haversine_m(LAT, LON, k[0], k[1]) <= 250]
    nicht_erreicht = [k for k in im_kreis if k not in dist]
    anteil = len(nicht_erreicht) / len(im_kreis)
    assert im_kreis, "der Kreis darf nicht leer sein"
    assert anteil > 0.15, (
        f"am Isarufer müssen Knoten im Kreis unerreichbar sein, gefunden: {anteil:.0%}"
    )


def test_umwegfaktor_ist_plausibel(strecken):
    netz, _start, _anbindung, dist = strecken
    faktoren = [
        d / haversine_m(LAT, LON, k[0], k[1])
        for k, d in dist.items()
        if haversine_m(LAT, LON, k[0], k[1]) > 50
    ]
    faktoren.sort()
    median = faktoren[len(faktoren) // 2]
    assert 1.0 <= median < 2.5, f"unplausibler Umwegfaktor: {median}"


# --------------------------------------------------------------- Anbindung


def test_punkt_ohne_weg_in_der_naehe_wird_nicht_angeschlossen(netz):
    """Lieber keine Gehstrecke als eine über 5 km Anbindung erfundene."""
    knoten, entfernung = netz.naechster_knoten(52.5200, 13.4050)  # Berlin
    assert knoten is None
    assert entfernung > gehweg.MAX_ANBINDUNG_M


def test_gitterindex_findet_denselben_knoten_wie_die_lineare_suche(netz):
    for lat, lon in ((LAT, LON), (48.1310, 11.5840), (48.1280, 11.5800)):
        schnell, d1 = netz.naechster_knoten(lat, lon)
        langsam = min(netz.kanten, key=lambda k: haversine_m(lat, lon, k[0], k[1]))
        d2 = haversine_m(lat, lon, langsam[0], langsam[1])
        assert d1 == pytest.approx(d2, abs=0.5), (
            "der Gitterindex darf kein anderes Ergebnis liefern als die volle Suche"
        )


# ---------------------------------------------------------------- Bewertung


def test_bewertung_trennt_erreichbar_von_unerreichbar(strecken):
    netz, _start, anbindung, dist = strecken
    objekte = [
        {"id": i, "lat": k[0], "lon": k[1],
         "distanz_m": round(haversine_m(LAT, LON, k[0], k[1]))}
        for i, k in enumerate(list(netz.kanten)[:400])
    ]
    im_kreis = [o for o in objekte if o["distanz_m"] <= 250]
    z = gehweg.bewerte(netz, dist, anbindung, objekte, 250)

    assert z["im_luftlinienkreis"] == len(im_kreis)
    assert z["im_gehradius"] + z["nur_luftlinie"] == len(im_kreis)
    assert 0 <= z["erschliessungsgrad"] <= 100
    for o in objekte:
        if o["gehweg_m"] is None:
            assert o["gehweg_grund"], "ein fehlender Wert braucht eine Begründung"
        else:
            assert o["gehweg_m"] >= o["distanz_m"] - 1


def test_erschliessungsgrad_ohne_objekte_ist_keine_null(strecken):
    netz, _start, anbindung, dist = strecken
    z = gehweg.bewerte(netz, dist, anbindung, [], 250)
    assert z["erschliessungsgrad"] is None, "ohne Objekte gibt es keinen Grad von 0"


def test_zellen_werden_ueber_den_mittelpunkt_zugeordnet(strecken):
    netz, _start, anbindung, dist = strecken
    knoten = list(netz.kanten)[:50]
    zellen = [{"_center": [k[0], k[1]], "Einwohner": 10} for k in knoten]
    z = gehweg.erreichbare_zellen(netz, dist, anbindung, zellen, 600)
    assert z["einwohner_luftlinie"] == 500
    assert z["einwohner_gehweg"] <= z["einwohner_luftlinie"]
    assert z["zellen_im_gehradius"] + z["zellen_nur_luftlinie"] == 50
    assert "Näherung" in z["hinweis"]


def test_zellen_ohne_einwohnerangabe_zaehlen_nicht_als_null(strecken):
    netz, _start, anbindung, dist = strecken
    k = list(netz.kanten)[0]
    zellen = [{"_center": [k[0], k[1]], "Einwohner": None}]
    z = gehweg.erreichbare_zellen(netz, dist, anbindung, zellen, 600)
    assert z["einwohner_luftlinie"] is None


# ------------------------------------------------------------------ Abfrage


def test_abfrage_holt_das_netz_mit_puffer():
    q = gehweg.build_query(LAT, LON, 600)
    assert f"around:{int(600 * gehweg.NETZ_PUFFER)}" in q
    assert "out geom;" in q
    assert "motorway" not in q, "auf der Autobahn geht niemand zu Fuss"
    assert "footway" in q and "pedestrian" in q


async def test_ausfall_wird_benannt(settings):
    from gastroviewer.sources.base import SourceError

    class FakeOut:
        async def post_json(self, *a, **kw):
            raise SourceError("timeout", "Zeitüberschreitung nach 90 s.")

    res = await gehweg.load(FakeOut(), settings, LAT, LON, 600)
    assert res.ok is False
    assert res.error["kind"] == "timeout"


async def test_ohne_wegenetz_bleibt_es_bei_der_luftlinie(settings):
    class FakeOut:
        async def post_json(self, *a, **kw):
            return {"elements": []}

    res = await gehweg.load(FakeOut(), settings, LAT, LON, 600)
    assert res.ok and res.data is None
    assert "kein begehbares Wegenetz" in res.warnings[0]


async def test_hinweis_nennt_den_flaechenunterschied(settings):
    roh = load_fixture("raw_overpass_gehweg_isar.json")

    class FakeOut:
        async def post_json(self, *a, **kw):
            return roh

    res = await gehweg.load(FakeOut(), settings, LAT, LON, 250)
    assert res.ok and res.data
    text = " ".join(res.data["hinweise"])
    assert "nicht dasselbe Gebiet" in text, (
        "der Rückgang darf nicht als Fehlerkorrektur missverstanden werden"
    )
    assert "gewählter Wert" in text, "das Gehtempo ist gewählt, nicht gemessen"
    assert res.data["rechenzeit_ms"] < 5000
