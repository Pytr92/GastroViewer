"""OSM-Auswertung gegen die echte Overpass-Antwort aus Phase 0."""

from __future__ import annotations

import pytest

from gastroviewer.sources import overpass
from gastroviewer.sources.base import SourceError

LAT, LON, R = 48.1334, 11.5674, 600


def test_fixture_ist_die_echte_antwort(overpass_combined):
    """Absicherung gegen versehentlich ausgedachte Testdaten. Die Zahl stammt aus
    der aufgezeichneten Antwort: 843 Elemente, nachdem die Abfrage um Märkte,
    Busbahnhöfe, Tankstellen, Behörden und Alltagsversorger erweitert wurde
    (vorher 801)."""
    assert overpass_combined["osm3s"]["copyright"].startswith("The data included")
    assert len(overpass_combined["elements"]) == 843


def test_abfrage_enthaelt_alle_geforderten_kategorien():
    q = overpass.build_query(LAT, LON, R)
    for tag in ("fast_food", "restaurant", "supermarket", "fitness_centre",
                "bus_stop", "disused:shop", "office", "hotel"):
        assert tag in q, f"{tag} fehlt in der Abfrage"
    assert "nwr[" in q, "Spec §4.2 verlangt nwr statt getrennter Bloecke"
    assert "[timeout:" in q


def test_ways_und_relationen_liefern_center(overpass_combined):
    """out center tags gibt bei Ways und POI-Relationen kein lat/lon."""
    ways = [e for e in overpass_combined["elements"] if e["type"] == "way"]
    assert ways
    assert all(overpass.element_coords(w) is not None for w in ways)


def test_routenrelationen_werden_als_linien_erkannt(overpass_combined):
    cls = overpass.classify(overpass_combined["elements"], LAT, LON, R)
    assert len(cls["linien"]) == 66
    arten = {r["route"] for r in cls["linien"]}
    assert arten == {"tram", "bus", "subway"}
    assert all(r["ref"] for r in cls["linien"] if r["route"] == "subway")


def test_routenrelationen_landen_nicht_in_der_poi_liste(overpass_combined):
    cls = overpass.classify(overpass_combined["elements"], LAT, LON, R)
    ids = {e["id"] for lst in ("gastronomie", "frequenzbringer", "oepnv", "leerstand")
           for e in cls[lst]}
    route_ids = {r["id"] for r in cls["linien"]}
    assert not (ids & route_ids)


def test_gastronomie_wird_vollstaendig_erfasst(overpass_combined):
    cls = overpass.classify(overpass_combined["elements"], LAT, LON, R)
    erwartet = sum(
        1
        for e in overpass_combined["elements"]
        if (e.get("tags") or {}).get("amenity") in overpass.GASTRO_AMENITIES
    )
    assert len(cls["gastronomie"]) == erwartet
    assert erwartet > 100, "Innenstadt-Fixture sollte viele Betriebe enthalten"


def test_abfrage_enthaelt_die_ergaenzten_frequenzbringer():
    """Über §4.2 hinaus ergänzt: Märkte, Busbahnhöfe, Tankstellen, Behörden und
    Alltagsversorger. Am Sendlinger Tor sind das 46 Objekte im 600-m-Umkreis,
    die vorher unsichtbar waren."""
    q = overpass.build_query(LAT, LON, R)
    for tag in ("marketplace", "bus_station", "fuel", "pharmacy", "bank",
                "post_office", "townhall", "courthouse", "kiosk", "greengrocer"):
        assert tag in q, f"{tag} fehlt in der Abfrage"


def test_ergaenzte_kategorien_werden_klassifiziert(overpass_combined):
    cls = overpass.classify(overpass_combined["elements"], LAT, LON, R)
    kategorien = {f["kategorie"] for f in cls["frequenzbringer"]}
    assert "Markt & Alltagsversorgung" in kategorien
    assert "Verkehr & Parken" in kategorien
    arten = {f["art"] for f in cls["frequenzbringer"]}
    assert arten & {"Apotheke", "Bank", "Post", "Kiosk"}, "keine der Ergänzungen erkannt"


def test_jeder_frequenzbringer_hat_kategorie_und_art(overpass_combined):
    cls = overpass.classify(overpass_combined["elements"], LAT, LON, R)
    for f in cls["frequenzbringer"]:
        assert f["kategorie"] and f["art"], f


def test_leerstand_hat_vorrang_vor_einkauf(overpass_combined):
    """shop=vacant darf nicht als Supermarkt-Nachbarschaft gezählt werden."""
    cls = overpass.classify(overpass_combined["elements"], LAT, LON, R)
    assert cls["leerstand"], "Fixture enthält disused:shop-Objekte"
    freq_ids = {e["id"] for e in cls["frequenzbringer"]}
    assert not ({e["id"] for e in cls["leerstand"]} & freq_ids)


def test_listen_sind_nach_distanz_sortiert(overpass_combined):
    cls = overpass.classify(overpass_combined["elements"], LAT, LON, R)
    for key in ("gastronomie", "frequenzbringer", "oepnv", "leerstand"):
        d = [e["distanz_m"] for e in cls[key]]
        assert d == sorted(d), f"{key} nicht nach Distanz sortiert"


def test_ketten_und_einzelbetriebe_summieren_sich(overpass_combined):
    cls = overpass.classify(overpass_combined["elements"], LAT, LON, R)
    z = overpass.summarize(cls)["gastronomie"]
    assert z["ketten"] + z["einzelbetriebe"] == z["gesamt"]
    assert sum(z["nach_typ"].values()) == z["gesamt"]


def test_linien_eindeutig_zaehlt_richtungen_nicht_doppelt(overpass_combined):
    cls = overpass.classify(overpass_combined["elements"], LAT, LON, R)
    z = overpass.summarize(cls)["oepnv"]
    assert z["linien_gesamt"] == 66
    assert z["linien_eindeutig"] < z["linien_gesamt"], (
        "Hin- und Rückrichtung sind je eine Relation — eindeutige Linien müssen weniger sein"
    )
    assert z["linien_eindeutig"] == sum(len(v) for v in z["linien_refs"].values())


def test_distanzen_sind_plausibel(overpass_combined):
    cls = overpass.classify(overpass_combined["elements"], LAT, LON, R)
    alle = [e for k in ("gastronomie", "frequenzbringer", "oepnv") for e in cls[k]]
    assert all(e["richtung"] in {"N", "NO", "O", "SO", "S", "SW", "W", "NW"} for e in alle)
    # Punkte müssen im Radius liegen (kleine Toleranz für die Geometriemessung
    # von Overpass gegenüber unserer Mittelpunktmessung).
    knoten = [e for e in alle if e["osm_type"] == "node"]
    assert knoten and all(e["distanz_m"] <= R * 1.1 for e in knoten)


def test_flaechen_mit_fernem_mittelpunkt_werden_gekennzeichnet(overpass_combined):
    """Gemessen: Die LMU ist eine stadtweite Relation, die in den Umkreis
    hineinreicht — ihr Flächenmittelpunkt liegt 5,8 km entfernt. Solche Objekte
    dürfen nicht wie ein Datenfehler aussehen."""
    cls = overpass.classify(overpass_combined["elements"], LAT, LON, R)
    alle = [e for k in ("gastronomie", "frequenzbringer", "oepnv", "leerstand")
            for e in cls[k]]
    weit = [e for e in alle if e["distanz_m"] > R]
    assert weit, "Fixture enthält solche Flächen"
    for e in weit:
        assert e["mittelpunkt_ausserhalb"] is True
        assert "Fläche reicht in den Umkreis" in e["distanz_hinweis"]
        assert e["osm_type"] in ("way", "relation")
    nah = [e for e in alle if e["distanz_m"] <= R]
    assert all(e["mittelpunkt_ausserhalb"] is False for e in nah)


async def test_load_warnt_vor_flaechenobjekten(settings, overpass_combined):
    settings.overpass_endpoints = ("https://a.example/api",)

    class FakeOut:
        async def post_json(self, source, url, **kw):
            return overpass_combined

    res = await overpass.load(FakeOut(), settings, LAT, LON, R)
    assert any("Mittelpunkt aber außerhalb" in w for w in res.warnings)


def test_osm_url_verweist_auf_das_objekt(overpass_combined):
    cls = overpass.classify(overpass_combined["elements"], LAT, LON, R)
    g = cls["gastronomie"][0]
    assert g["osm_url"] == f"https://www.openstreetmap.org/{g['osm_type']}/{g['id']}"


def test_leere_antwort_bricht_nicht():
    cls = overpass.classify([], LAT, LON, R)
    z = overpass.summarize(cls)
    assert z["gastronomie"]["gesamt"] == 0
    assert z["oepnv"]["linien_eindeutig"] == 0


async def test_fallback_geht_zum_naechsten_spiegel(settings):
    """Phase-0-Befund A-1: Spiegel können ausfallen."""
    settings.overpass_endpoints = ("https://a.example/api", "https://b.example/api")
    versuche: list[str] = []

    class FakeOut:
        async def post_json(self, source, url, **kw):
            versuche.append(url)
            if url.startswith("https://a."):
                raise SourceError("timeout", "Zeitüberschreitung")
            return {"elements": [], "osm3s": {"timestamp_osm_base": "2026-08-01T07:24:36Z"}}

    payload, endpoint, problems = await overpass.run_query(FakeOut(), settings, "q")
    assert versuche == ["https://a.example/api", "https://b.example/api"]
    assert endpoint == "https://b.example/api"
    assert problems and "Zeitüberschreitung" in problems[0]


async def test_alle_spiegel_tot_meldet_konkrete_ursache(settings):
    settings.overpass_endpoints = ("https://a.example/api",)

    class FakeOut:
        async def post_json(self, source, url, **kw):
            raise SourceError("connect", "Verbindung nicht möglich")

    with pytest.raises(SourceError) as exc:
        await overpass.run_query(FakeOut(), settings, "q")
    assert exc.value.kind == "connect"


async def test_remark_wird_als_dienstfehler_behandelt(settings):
    """Overpass meldet Überlast als remark mit HTTP 200."""
    settings.overpass_endpoints = ("https://a.example/api",)

    class FakeOut:
        async def post_json(self, source, url, **kw):
            return {"elements": [], "remark": "runtime error: Query timed out"}

    with pytest.raises(SourceError) as exc:
        await overpass.run_query(FakeOut(), settings, "q")
    assert "Query timed out" in exc.value.message


async def test_load_uebernimmt_datenstand_aus_der_antwort(settings, overpass_combined):
    settings.overpass_endpoints = ("https://a.example/api",)

    class FakeOut:
        async def post_json(self, source, url, **kw):
            return overpass_combined

    res = await overpass.load(FakeOut(), settings, LAT, LON, R)
    assert res.ok
    # Der Stand kommt aus der Antwort, nicht aus einer Konstante im Code.
    erwartet = overpass_combined["osm3s"]["timestamp_osm_base"]
    assert res.provenance.stand == f"OSM-Datenstand {erwartet}"
    assert "ODbL" in res.provenance.license
    assert "Untergrenze" in res.provenance.note


# ------------------------------------------- Öffnungszeiten-Lücken (konservativ)


class TestOeffnungszeiten:
    """Der Parser bewertet nur, was er sicher versteht — alles andere ist
    „nicht auswertbar", nie „geschlossen"."""

    def test_einfache_woche(self):
        b = overpass.bewerte_oeffnungszeiten("Mo-Fr 09:00-18:00")
        assert b == {"sonntag": False, "nach22": False, "immer": False}

    def test_ganze_woche_abends(self):
        b = overpass.bewerte_oeffnungszeiten("Mo-Su 11:00-23:00")
        assert b["sonntag"] and b["nach22"]

    def test_rund_um_die_uhr(self):
        b = overpass.bewerte_oeffnungszeiten("24/7")
        assert b["sonntag"] and b["nach22"] and b["immer"]

    def test_sonntag_ausdruecklich_zu(self):
        b = overpass.bewerte_oeffnungszeiten("Mo-Sa 10:00-20:00; Su off")
        assert b["sonntag"] is False

    def test_mitternachtsueberhang_bleibt_beim_genannten_tag(self):
        """Samstagnacht bis 4 Uhr ist nicht „sonntags geöffnet" — aber ein
        Abendangebot."""
        b = overpass.bewerte_oeffnungszeiten("Fr-Sa 20:00-04:00")
        assert b["sonntag"] is False
        assert b["nach22"] is True

    def test_mehrere_zeitfenster(self):
        b = overpass.bewerte_oeffnungszeiten("Mo-Fr 11:30-14:30,17:00-23:00")
        assert b["nach22"] is True
        assert b["sonntag"] is False

    def test_feiertagsregel_wird_geduldet(self):
        b = overpass.bewerte_oeffnungszeiten("Mo-Su 12:00-22:00; PH off")
        assert b is not None
        assert b["sonntag"] is True
        # 22:00 ist die Grenze, nicht „nach 22 Uhr".
        assert b["nach22"] is False

    def test_wochenwechsel(self):
        b = overpass.bewerte_oeffnungszeiten("Sa-Mo 10:00-15:00")
        assert b["sonntag"] is True

    @pytest.mark.parametrize("oh", [
        "Jan-Mar Mo-Fr 10:00-20:00",   # Saison
        "Mo-Su 08:00+",                # offenes Ende
        "sunrise-sunset",              # Sonnenstand
        "Mo-Fr 09:00-18:00; PH 10:00-14:00",  # Feiertag mit Zeiten
        "week 1-26 Mo 10:00-12:00",    # Wochennummern
        "Kaputt",
    ])
    def test_nicht_auswertbar_statt_falsch(self, oh):
        assert overpass.bewerte_oeffnungszeiten(oh) is None

    def test_leer_ist_nicht_auswertbar(self):
        assert overpass.bewerte_oeffnungszeiten(None) is None
        assert overpass.bewerte_oeffnungszeiten("") is None

    def test_spaetere_regel_ueberschreibt(self):
        b = overpass.bewerte_oeffnungszeiten("Mo-Su 10:00-23:00; Su 10:00-18:00")
        assert b["sonntag"] is True
        assert b["nach22"] is True  # Mo-Sa bleiben bis 23 Uhr


def test_oeffnungszeiten_luecken_am_echten_fixture(overpass_combined):
    """Aggregat über die echte Innenstadt-Antwort: Zahlen sind konsistent und
    ausschließlich Mindestzahlen."""
    cls = overpass.classify(overpass_combined["elements"], 48.1334, 11.5674, 600)
    oz = overpass.summarize(cls, 600)["gastronomie"]["oeffnungszeiten"]
    assert oz["gesamt"] == len(cls["gastronomie"])
    assert 0 < oz["mit_angabe"] <= oz["gesamt"]
    assert 0 < oz["auswertbar"] <= oz["mit_angabe"]
    assert oz["sonntag_offen"] + oz["sonntag_geschlossen"] == oz["auswertbar"]
    assert oz["nach22_offen"] <= oz["auswertbar"]
    assert "Mindestzahlen" in oz["hinweis"]
