"""Raddauerzählstellen München.

Die Beispieldaten sind ein wortgetreuer Auszug aus der echten WFS-Antwort vom
2026-08-01 — inklusive der Eigenheiten, die der Code aushalten muss: Zahlen als
Zeichenketten, HTML im Infofeld, „Derzeit keine Daten" statt eines Werts.
"""

from __future__ import annotations

import pytest

from gastroviewer.sources import muenchen

# Sendlinger Tor, derselbe Punkt wie in den übrigen Tests.
LAT, LON = 48.1334, 11.5674

ECHTE_ANTWORT = {
    "type": "FeatureCollection",
    "features": [
        {
            "geometry": {"type": "Point", "coordinates": [11.58469, 48.13192]},
            "properties": {
                "zaehlstelle": "Erhardt",
                "zaehlstelle_lang": "Erhardtstr. (Deutsches Museum)",
                "richtung_1": "Süd",
                "richtung_2": "Nord",
                "besonderheiten": "Es wird auf dem Fahrradweg als auch auf dem Fußweg gezählt.",
                "info": '<p><a href="https://opendata.muenchen.de/">Zu den Rohdaten</a></p>',
                "gesamt_sum_2025": "1415000",
                "gesamt_sum_monat_2026": "115000",
            },
        },
        {
            "geometry": {"type": "Point", "coordinates": [11.53599, 48.12032]},
            "properties": {
                "zaehlstelle": "Margareten",
                "zaehlstelle_lang": "Margaretenstr. (Harras)",
                "richtung_1": "West",
                "richtung_2": "Ost",
                "zaehler_kaputt_sum_2025": "Derzeit keine Daten",
                "zaehler_kaputt_sum_monat": "Derzeit keine Daten",
            },
        },
        {
            # Olympiapark — über 3 km entfernt, muss aus der Reichweite fallen.
            "geometry": {"type": "Point", "coordinates": [11.55005, 48.16887]},
            "properties": {
                "zaehlstelle": "Olympia",
                "zaehlstelle_lang": "Rudolf-Harbig-Weg (Olympiapark)",
                "gesamt_sum_2025": "831000",
            },
        },
    ],
}


def test_werte_werden_aus_zeichenketten_gelesen():
    d = muenchen.aufbereiten(ECHTE_ANTWORT["features"], LAT, LON, 600)
    erhardt = d["naechste"]
    assert erhardt["kurzname"] == "Erhardt"
    assert erhardt["summe_vorjahr"] == 1_415_000
    assert erhardt["je_tag_vorjahr"] == round(1_415_000 / 365)
    assert erhardt["summe_laufender_monat"] == 115_000
    assert erhardt["richtungen"] == ["Süd", "Nord"]


def test_keine_daten_wird_nicht_zu_null():
    """„Derzeit keine Daten" darf nicht als 0 Radfahrende erscheinen."""
    d = muenchen.aufbereiten(ECHTE_ANTWORT["features"], LAT, LON, 600)
    margareten = next(s for s in d["in_reichweite"] if s["kurzname"] == "Margareten")
    assert margareten["summe_vorjahr"] is None
    assert margareten["je_tag_vorjahr"] is None
    assert margareten["stoerung"] == "Derzeit keine Daten"


@pytest.mark.parametrize(
    "roh,erwartet",
    [
        ("1415000", 1_415_000),
        ("1.415.000", 1_415_000),
        (" 42000 ", 42_000),
        ("Derzeit keine Daten", None),
        ("", None),
        (None, None),
    ],
)
def test_zahlenparser(roh, erwartet):
    assert muenchen._zahl(roh) == erwartet


def test_html_wird_aus_den_hinweisen_entfernt():
    assert muenchen._ohne_html('<p><a href="x">Zu den Rohdaten</a></p>') == "Zu den Rohdaten"
    assert muenchen._ohne_html("") is None


def test_entfernte_grenze_haelt_ferne_stellen_heraus():
    """Sechs Stellen decken München nicht ab. Eine Zahl von der anderen
    Stadtseite wäre schlimmer als keine."""
    d = muenchen.aufbereiten(ECHTE_ANTWORT["features"], LAT, LON, 600)
    namen = {s["kurzname"] for s in d["in_reichweite"]}
    assert "Olympia" not in namen, "über 3 km entfernt"
    assert namen == {"Erhardt", "Margareten"}
    assert d["zaehlstellen_gesamt"] == 3
    assert d["max_distanz_m"] == 3000


def test_sortierung_nach_entfernung():
    d = muenchen.aufbereiten(ECHTE_ANTWORT["features"], LAT, LON, 600)
    entfernungen = [s["distanz_m"] for s in d["in_reichweite"]]
    assert entfernungen == sorted(entfernungen)


def test_im_radius_wird_getrennt_ausgewiesen():
    """Eine Zählstelle 1,3 km entfernt liegt nicht im 600-m-Umkreis — das darf
    die Ausgabe nicht verwischen."""
    d = muenchen.aufbereiten(ECHTE_ANTWORT["features"], LAT, LON, 600)
    assert d["im_radius"] == []
    assert d["in_reichweite"], "in Reichweite aber außerhalb des Radius"
    weit = muenchen.aufbereiten(ECHTE_ANTWORT["features"], LAT, LON, 1400)
    assert {s["kurzname"] for s in weit["im_radius"]} == {"Erhardt"}


def test_leere_antwort_bricht_nicht():
    d = muenchen.aufbereiten([], LAT, LON, 600)
    assert d["in_reichweite"] == [] and d["naechste"] is None


def test_features_ohne_punktgeometrie_werden_uebersprungen():
    kaputt = [{"geometry": {"type": "LineString", "coordinates": [[1, 2], [3, 4]]},
               "properties": {"zaehlstelle": "X"}},
              {"geometry": None, "properties": {"zaehlstelle": "Y"}}]
    assert muenchen.aufbereiten(kaputt, LAT, LON, 600)["zaehlstellen_gesamt"] == 0


def test_hinweise_benennen_die_grenzen():
    text = " ".join(muenchen.HINWEISE)
    assert "Radfahrende" in text and "keine Fußgänger" in text
    assert "sechs Zählstellen" in text


async def test_abruf_und_quellenangabe(settings):
    class FakeOut:
        async def get_json(self, source, url, params=None, **kw):
            assert params["typeName"] == muenchen.TYPENAME
            assert params["outputFormat"] == "application/json"
            assert params["srsName"] == "EPSG:4326"
            return ECHTE_ANTWORT

    res = await muenchen.zaehlstellen(FakeOut(), settings, LAT, LON, 600)
    assert res.ok
    assert res.data["naechste"]["kurzname"] == "Erhardt"
    assert "dl-de/by-2-0" in res.provenance.license
    assert "Landeshauptstadt München" in res.provenance.license
    assert "Keine Fußgängerzählung" in res.provenance.note
    assert any("Margareten" in w for w in res.warnings)


async def test_ausfall_wird_benannt(settings):
    from gastroviewer.sources.base import SourceError

    class FakeOut:
        async def get_json(self, *a, **kw):
            raise SourceError("timeout", "Zeitüberschreitung — Dienst antwortet nicht.")

    res = await muenchen.zaehlstellen(FakeOut(), settings, LAT, LON, 600)
    assert res.ok is False
    assert res.error["kind"] == "timeout"


async def test_punkt_ausserhalb_muenchens_meldet_das(settings):
    class FakeOut:
        async def get_json(self, *a, **kw):
            return ECHTE_ANTWORT

    res = await muenchen.zaehlstellen(FakeOut(), settings, 53.0210, 13.2100, 900)
    assert res.ok
    assert res.data["in_reichweite"] == []
    assert "decken München nicht flächig ab" in res.warnings[0]


# ------------------------------------------- Jahresgang aus den Tages-Rohdaten


def test_finde_tageswerte_nimmt_das_juengste_jahr(muenchen_rad_tage):
    fund = muenchen.finde_tageswerte(muenchen_rad_tage["ckan"])
    assert fund is not None
    jahr, url = fund
    assert jahr == 2025
    assert url.endswith("rad_2025_tage_export_19_01_25.csv")


def test_finde_tageswerte_ohne_treffer():
    assert muenchen.finde_tageswerte({"result": {"resources": []}}) is None
    assert muenchen.finde_tageswerte(None) is None


def test_parse_tageswerte_gegen_die_echten_zahlen(muenchen_rad_tage):
    """Kontrollwerte aus den echten CSV-Zeilen selbst errechnet: Arnulf 365
    Messtage, Mittel 1.184, Spitzentag 2.510; Kreuther nur 92 Tage (Okt–Dez,
    echtes Teiljahr)."""
    st = muenchen.parse_tageswerte(muenchen_rad_tage["tageswerte_2025"])
    a = st["Arnulf"]
    assert a["messtage"] == 365
    assert a["je_tag_mittel"] == 1184
    assert a["spitzentag"] == 2510
    # Jahresgang: Juli fast dreimal Januar — der Winter halbiert die Achse.
    assert a["monatsmittel"][0] == 645
    assert a["monatsmittel"][6] == 1662

    k = st["Kreuther"]
    assert k["messtage"] == 92
    assert k["je_tag_mittel"] == 453
    # Monate ohne Messtage sind None, nicht 0 — keine erfundene Flaute.
    assert k["monatsmittel"][0] is None
    assert k["monatsmittel"][9] is not None


def test_parse_tageswerte_mit_aufgefuellten_feldern():
    """Die Monatsdateien füllen Felder mit Leerzeichen auf — strip überall."""
    text = (
        "﻿datum     ,uhrzeit_start,uhrzeit_ende,zaehlstelle,richtung_1,"
        "richtung_2,gesamt\n"
        "2026.07.01,00:00        ,       23:59,Kreuther   ,       350,"
        "       297,   647\n"
    )
    st = muenchen.parse_tageswerte(text)
    assert st["Kreuther"]["je_tag_mittel"] == 647
    assert st["Kreuther"]["messtage"] == 1


def test_parse_tageswerte_unlesbares_bricht_nicht():
    assert muenchen.parse_tageswerte("") == {}
    assert muenchen.parse_tageswerte("voellig,anderes,format\n1,2,3") == {}


# ------------------------------------------ Jahresfelder und Tagesmittel


def test_jahresfelder_werden_aus_den_schluesseln_gelesen():
    """Nach dem Jahreswechsel heißen die Felder anders — fest kodierte Namen
    lieferten stille Nullen."""
    import copy

    kopie = copy.deepcopy(ECHTE_ANTWORT)
    for f in kopie["features"]:
        p = f["properties"]
        for alt_k in list(p):
            if alt_k.endswith("_2025"):
                p[alt_k.replace("_2025", "_2026")] = p.pop(alt_k)
            elif alt_k.endswith("_2026"):
                p[alt_k.replace("_2026", "_2027")] = p.pop(alt_k)
    d = muenchen.aufbereiten(kopie["features"], LAT, LON, 600)
    assert d["jahr_summe"] == 2026 and d["jahr_monat"] == 2027
    erhardt = next(s for s in d["in_reichweite"] if s["kurzname"] == "Erhardt")
    assert erhardt["summe_vorjahr"] == 1415000 and erhardt["summe_vorjahr_jahr"] == 2026
    assert erhardt["summe_laufender_monat"] == 115000
    assert d["schema_warnung"] is None


def test_fehlende_jahresfelder_werden_gemeldet():
    features = [{"geometry": {"type": "Point", "coordinates": [11.58469, 48.13192]},
                 "properties": {"zaehlstelle": "Erhardt", "zaehlstelle_lang": "Erhardtstr."}}]
    d = muenchen.aufbereiten(features, LAT, LON, 600)
    assert d["jahr_summe"] is None
    assert "Schema" in d["schema_warnung"]
    assert d["in_reichweite"][0]["summe_vorjahr"] is None


async def test_tagesmittel_aus_messtagen_wenn_der_jahresgang_passt(settings):
    """Eine Station mit 92 Messtagen: Summe ÷ 365 wäre 4× zu niedrig."""
    class FakeOut:
        async def get_json(self, source, url, **kw):
            return ECHTE_ANTWORT

    async def jahresgang():
        return {"jahr": 2025, "stationen": {
            "Erhardt": {"messtage": 92, "je_tag_mittel": 15380, "spitzentag": 20000}}}

    res = await muenchen.zaehlstellen(FakeOut(), settings, LAT, LON, 600, jahresgang)
    assert res.ok
    erhardt = next(s for s in res.data["in_reichweite"] if s["kurzname"] == "Erhardt")
    assert erhardt["je_tag_vorjahr"] == 15380 and erhardt["je_tag_basis"] == "messtage"
    assert res.data["naechste"]["je_tag_vorjahr"] == 15380
    assert any("92 Messtage" in w for w in res.warnings)
    assert "2025" in res.provenance.stand and "2026" in res.provenance.stand


async def test_tagesmittel_bleibt_kalendertage_bei_anderem_jahr(settings):
    class FakeOut:
        async def get_json(self, source, url, **kw):
            return ECHTE_ANTWORT

    async def jahresgang():
        return {"jahr": 2026, "stationen": {"Erhardt": {"messtage": 40, "je_tag_mittel": 9}}}

    res = await muenchen.zaehlstellen(FakeOut(), settings, LAT, LON, 600, jahresgang)
    erhardt = next(s for s in res.data["in_reichweite"] if s["kurzname"] == "Erhardt")
    assert erhardt["je_tag_vorjahr"] == round(1415000 / 365)
    assert erhardt["je_tag_basis"] == "kalendertage"
