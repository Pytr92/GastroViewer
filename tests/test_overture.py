"""Overture Places — gegen die echten Downloads vom 04.08.2026.

Der Phase-0-Befund, der diese Quelle begründet: Am Einkaufszentrum MIRA kennt
OSM 3 Gastro-Betriebe, Overture 15 — darunter Hans im Glück, Thai Curry,
Veneras Pizza, Van Hoa Sushi. Beide Fixtures sind unveränderte Features der
echten Antworten (Marienplatz: Teilmenge im 600-m-Umkreis).
"""

from __future__ import annotations

import struct

import pytest

from gastroviewer.config import Settings
from gastroviewer.sources import overpass, overture

LAT, LON, R = 48.1334, 11.5674, 600


def _zeilen(geojson):
    out = []
    for f in geojson["features"]:
        lon, lat = f["geometry"]["coordinates"]
        z = overture.zeile_aus_properties(f["properties"], lat, lon)
        if z:
            out.append(z)
    return out


# ------------------------------------------------------------- Kategorien


def test_gruppen_zuordnung():
    assert overture.gruppe_fuer(["burger_restaurant"]) == "restaurant"
    assert overture.gruppe_fuer(["fast_food_restaurant"]) == "schnellgastronomie"
    assert overture.gruppe_fuer(["coffee_shop"]) == "cafe"
    assert overture.gruppe_fuer(["wine_bar"]) == "bar"
    assert overture.gruppe_fuer(["gelato"]) == "eisdiele"
    assert overture.gruppe_fuer(["bakery"]) == "baeckerei_snack"
    assert overture.gruppe_fuer(["clothing_store"]) is None


def test_primaerkategorie_entscheidet():
    """Über die Alternativkategorien rutschten Hotels, ein REWE und Vereine
    als „Gastronomie" hinein — die Primärkategorie ist die Selbstauskunft."""
    assert overture.gruppe_fuer(["hotel", "restaurant"]) is None
    assert overture.gruppe_fuer(["grocery_store", "deli_restaurant"]) is None
    # Ohne Primärkategorie zählen die Alternativen.
    assert overture.gruppe_fuer([None, "cafe"]) == "cafe"


def test_mira_liefert_die_fehlenden_betriebe(overture_mira):
    """Der Kernbefund: 15 echte Gastro-Orte am MIRA — OSM kennt dort 3."""
    zeilen = _zeilen(overture_mira)
    namen = {z["name"] for z in zeilen}
    assert len(zeilen) == 15
    for erwartet in ("Hans im Glück", "Thai Curry", "Veneras Pizza",
                     "Van Hoa Sushi im MIRA", "McDonald's"):
        assert erwartet in namen
    # Die Ausreißer der Rohdaten (REWE, Studentenwohnheim, Verein) sind draußen.
    assert "REWE" not in namen
    assert "Studentenwohnheim" not in namen


def test_zeile_traegt_alle_felder(overture_mira):
    z = next(x for x in _zeilen(overture_mira) if x["name"] == "Hans im Glück")
    assert z["gruppe"] == "restaurant"
    assert 0 < z["confidence"] <= 1
    assert 48.2 < z["lat"] < 48.22 and 11.55 < z["lon"] < 11.58
    assert "AllThePlaces" in z["quellen"] or "meta" in z["quellen"]


# -------------------------------------------------------------------- WKB


def test_wkb_punkt():
    blob = struct.pack("<BIdd", 1, 1, 11.5755, 48.1372)
    assert overture.wkb_punkt(blob) == (48.1372, 11.5755)
    assert overture.wkb_punkt(b"") is None
    assert overture.wkb_punkt(struct.pack("<BIdd", 1, 2, 1, 2)) is None  # kein Punkt


# ---------------------------------------------------------------- Abgleich


def test_namen_aehnlich():
    assert overture.namen_aehnlich("McDonald's", "Mc Donalds")
    assert overture.namen_aehnlich("Café Rischart", "Rischart")
    assert not overture.namen_aehnlich("Burgerhaus", "Sushi Zen")
    assert not overture.namen_aehnlich(None, "x")


def test_abgleich_gegen_die_echte_osm_fixture(overture_marienplatz, overpass_combined):
    """Marienplatz: 390 sichere Overture-Orte gegen 270 OSM-Betriebe —
    169 in beiden, 221 nur in Overture. Alles aus den echten Fixtures."""
    ov = [z for z in _zeilen(overture_marienplatz)
          if z["confidence"] >= overture.SCHWELLE]
    gast = overpass.classify(overpass_combined["elements"], LAT, LON, R)["gastronomie"]
    nur, beide = overture.abgleichen(ov, gast)
    assert len(ov) == 390
    assert beide == 169
    assert len(nur) == 221
    assert beide + len(nur) == len(ov)
    # Ketten mit OSM-Eintrag dürfen nicht doppelt zählen:
    nur_namen = {z["name"] for z in nur}
    beide_erwartet = {"Hard Rock Cafe", "Vapiano"}
    # mindestens eine bekannte Kette wurde als „beide" erkannt
    assert beide_erwartet - nur_namen, "kein einziger Ketten-Abgleich gelungen?"


# ------------------------------------------------------------------- load()


def _db_aus_fixture(tmp_path, geojson) -> Settings:
    s = Settings()
    s.data_dir = tmp_path
    conn = overture.db_init(s.overture_db_path)
    for z in _zeilen(geojson):
        conn.execute(
            "INSERT OR REPLACE INTO places VALUES "
            "(:id,:name,:kategorie,:gruppe,:confidence,:lat,:lon,"
            ":adresse,:plz,:ort,:marke,:quellen)", z)
    conn.executemany("INSERT OR REPLACE INTO meta VALUES (?, ?)", [
        ("release", "2026-06-25.0"), ("region", "test"),
        ("bbox", "48.0,11.4,48.3,11.8"), ("importiert_am", "2026-08-04"),
    ])
    conn.commit()
    conn.close()
    return s


def test_load_ohne_import_gibt_anleitung(tmp_path):
    s = Settings()
    s.data_dir = tmp_path
    res = overture.load(s, LAT, LON, R, [])
    assert res.ok and res.data == {"importiert": False}
    assert any("import-overture" in w for w in res.warnings)


def test_load_mit_import_und_abgleich(tmp_path, overture_marienplatz,
                                      overpass_combined):
    s = _db_aus_fixture(tmp_path, overture_marienplatz)
    gast = overpass.classify(overpass_combined["elements"], LAT, LON, R)["gastronomie"]
    res = overture.load(s, LAT, LON, R, gast)
    assert res.ok and res.data["importiert"]
    d = res.data
    assert d["osm_gesamt"] == 270
    assert d["beide"] == 169
    assert len(d["nur_overture"]) == 221
    assert d["kombiniert_gesamt"] == 270 + 221
    assert d["schwelle"] == 0.5
    assert d["unter_schwelle"] > 0
    e = d["nur_overture"][0]
    for feld in ("name", "gruppe_label", "confidence", "distanz_m", "richtung"):
        assert feld in e
    assert "CDLA" in res.provenance.license
    assert "Overture" in res.provenance.source


def test_load_ausserhalb_des_imports_warnt(tmp_path, overture_marienplatz):
    s = _db_aus_fixture(tmp_path, overture_marienplatz)
    res = overture.load(s, 50.94, 6.96, 600, [])  # Köln, außerhalb der bbox
    assert res.ok
    assert any("außerhalb" in w for w in res.warnings)
