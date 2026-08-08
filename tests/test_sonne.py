"""Sonnen- und Schattenrechnung.

Zwei Prüfebenen: die Astronomie gegen bekannte Sollwerte (die hängt an
keiner Datenquelle und muss exakt stimmen), und die Verschattung gegen zwei
echte, am 2026-08-08 aufgezeichnete Overpass-Antworten aus München.
"""

from __future__ import annotations

import datetime as dt
import math

from gastroviewer.sources import sonne


# ------------------------------------------------------------ Astronomie

def test_sonnenhoehe_trifft_die_sonnenwenden():
    """Zur Sonnenwende ist die Mittagshöhe exakt 90° − Breite ± 23,44°.
    München liegt auf 48,1334° N."""
    lat, lon = 48.1334, 11.5674
    sommer = 90 - lat + 23.44
    winter = 90 - lat - 23.44

    hoch_sommer = max(
        sonne.sonnenstand(lat, lon, dt.datetime(2026, 6, 21, h, m))[0]
        for h in range(9, 14) for m in (0, 20, 40))
    hoch_winter = max(
        sonne.sonnenstand(lat, lon, dt.datetime(2026, 12, 21, h, m))[0]
        for h in range(9, 14) for m in (0, 20, 40))

    assert abs(hoch_sommer - sommer) < 0.3, f"{hoch_sommer} statt {sommer}"
    assert abs(hoch_winter - winter) < 0.3, f"{hoch_winter} statt {winter}"


def test_azimut_steht_mittags_im_sueden():
    """Zum Sonnenhöchststand steht die Sonne im Süden (Azimut ≈ 180°)."""
    lat, lon = 48.1334, 11.5674
    beste = max(
        (sonne.sonnenstand(lat, lon, dt.datetime(2026, 6, 21, 11, m))
         for m in range(0, 60, 5)), key=lambda x: x[0])
    assert abs(beste[1] - 180) < 3, f"Azimut {beste[1]}"


def test_sonne_geht_im_nordosten_auf_und_im_nordwesten_unter():
    """Zur Sommersonnenwende geht die Sonne in unseren Breiten deutlich
    nördlich von Ost auf und nördlich von West unter."""
    lat, lon = 48.1334, 11.5674
    werte = [(h + m / 60, *sonne.sonnenstand(lat, lon,
                                             dt.datetime(2026, 6, 21, h, m)))
             for h in range(24) for m in (0, 30)]
    ueber = [(t, hoehe, az) for t, hoehe, az in werte if hoehe > 0]
    assert 40 < ueber[0][2] < 70, f"Aufgang bei Azimut {ueber[0][2]}"
    assert 290 < ueber[-1][2] < 320, f"Untergang bei Azimut {ueber[-1][2]}"


def test_tageslaenge_muenchen():
    """Sonnenwenden: rund 16,1 h bzw. 8,3 h über dem Horizont."""
    lat, lon = 48.1334, 11.5674

    def stunden(datum):
        n = sum(1 for h in range(24) for m in range(0, 60, 10)
                if sonne.sonnenstand(lat, lon,
                                     dt.datetime(datum.year, datum.month,
                                                 datum.day, h, m))[0] > 0)
        return n / 6

    assert abs(stunden(dt.date(2026, 6, 21)) - 16.1) < 0.3
    assert abs(stunden(dt.date(2026, 12, 21)) - 8.3) < 0.3


def test_sommerzeit_versatz():
    assert sonne._utc_versatz(dt.date(2026, 7, 1)) == 2
    assert sonne._utc_versatz(dt.date(2026, 1, 15)) == 1
    # Umstellung: letzter Sonntag im März bzw. Oktober.
    assert sonne._utc_versatz(dt.date(2026, 3, 28)) == 1
    assert sonne._utc_versatz(dt.date(2026, 3, 29)) == 2
    assert sonne._utc_versatz(dt.date(2026, 10, 24)) == 2
    assert sonne._utc_versatz(dt.date(2026, 10, 25)) == 1


# ---------------------------------------------------------- Gebäudehöhe

def test_hoehe_aus_tags_ohne_erfundene_werte():
    assert sonne.gebaeude_hoehe({"height": "12.5"}) == 12.5
    assert sonne.gebaeude_hoehe({"height": "12,5 m"}) == 12.5
    assert sonne.gebaeude_hoehe({"building:levels": "5"}) == 5 * sonne.METER_JE_GESCHOSS
    # Höhe schlägt Geschosszahl.
    assert sonne.gebaeude_hoehe({"height": "20", "building:levels": "2"}) == 20
    # Ohne Angabe wird nichts geschätzt — das ist der Kern der Ehrlichkeit.
    assert sonne.gebaeude_hoehe({}) is None
    assert sonne.gebaeude_hoehe({"building": "yes"}) is None
    assert sonne.gebaeude_hoehe({"height": "unsinn"}) is None
    assert sonne.gebaeude_hoehe({"height": "-3"}) is None


# ------------------------------------------------- Verschattung (Modell)

def _wand(lat, lon, azimut_grad, distanz_m, hoehe_m, breite_grad=40):
    """Baut eine künstliche Wand in gegebener Richtung und Entfernung."""
    punkte = []
    for versatz in range(-breite_grad // 2, breite_grad // 2 + 1, 2):
        a = math.radians(azimut_grad + versatz)
        dy = distanz_m * math.cos(a) / 111_320.0
        dx = (distanz_m * math.sin(a)
              / (111_320.0 * math.cos(math.radians(lat))))
        punkte.append({"lat": lat + dy, "lon": lon + dx})
    return {"tags": {"height": str(hoehe_m)}, "geometry": punkte}


def test_horizont_gibt_den_geometrisch_richtigen_winkel():
    """Eine 20 m hohe Wand in 20 m Entfernung erscheint unter
    arctan((20 − 1,5) / 20) ≈ 42,8°."""
    lat, lon = 48.1334, 11.5674
    horizont, mit, ohne = sonne._horizont(
        lat, lon, [_wand(lat, lon, 180, 20, 20)])
    soll = math.degrees(math.atan2(20 - sonne.AUGENHOEHE_M, 20))
    assert abs(horizont[180][1] - soll) < 1.5, horizont[180]
    assert mit == 1 and ohne == 0
    # Rückwärtige Richtung bleibt frei.
    assert horizont[0][1] == 0.0


def test_gebaeude_ohne_hoehe_werfen_keinen_schatten_und_werden_gezaehlt():
    lat, lon = 48.1334, 11.5674
    ohne_tag = _wand(lat, lon, 180, 20, 20)
    ohne_tag["tags"] = {"building": "yes"}
    horizont, mit, ohne = sonne._horizont(lat, lon, [ohne_tag])
    assert mit == 0 and ohne == 1
    assert max(h for _a, h in horizont) == 0.0


def test_hohe_wand_im_sueden_nimmt_die_wintersonne():
    """Physikalische Gegenprobe: Die Mittagssonne steht in München im
    Winter 18,4° hoch. Eine Wand, die im Süden unter 30° erscheint, muss
    den Wintertag praktisch auslöschen, den Sommertag (65,3°) aber kaum
    antasten."""
    lat, lon = 48.1334, 11.5674
    wand = [_wand(lat, lon, 180, 20, 13, breite_grad=170)]
    d = sonne.auswerten(lat, lon, wand, 2026)
    assert d["tage"]["winter"]["stunden"] == 0.0
    assert d["tage"]["sommer"]["stunden"] > 10


# --------------------------------------------- Verschattung (echte Daten)

def test_enge_altstadt_gegen_offenen_platz(overpass_gebaeude):
    """Zwei echte Münchner Lagen. Die dichte Altstadt hat ein hohes
    Hindernis im Süden und verliert dadurch die Wintersonne; der offene
    Platz behält sie weitgehend."""
    alt = sonne.auswerten(48.13745, 11.57538,
                          overpass_gebaeude["altstadt"]["elements"], 2026)
    offen = sonne.auswerten(48.1334, 11.5674,
                            overpass_gebaeude["sendlinger_tor"]["elements"],
                            2026)

    assert alt["gebaeude_gesamt"] == 103
    assert alt["hoechstes_hindernis_richtung"] == "S"
    assert alt["hoechstes_hindernis_grad"] > 40

    # Das hohe Südgebäude löscht die Wintersonne in der Altstadt praktisch
    # aus (18,4° Mittagshöhe gegen 45° Hindernis), während der offene Platz
    # sie behält. Das ist der Kern der Auswertung.
    assert alt["tage"]["winter"]["stunden"] < 1.5
    assert offen["tage"]["winter"]["stunden"] > 5.0

    # Wirtschaftlich entscheidend ist die Abendsonne im Sommer.
    assert offen["tage"]["sommer"]["abendsonne_stunden"] > 2 * alt[
        "tage"]["sommer"]["abendsonne_stunden"]

    # Die geometrisch mögliche Tageslänge hängt nicht von der Bebauung ab.
    assert (alt["tage"]["sommer"]["moeglich_stunden"]
            == offen["tage"]["sommer"]["moeglich_stunden"] == 16.0)


def test_mittagsluecke_durch_suedgebaeude(overpass_gebaeude):
    """Zur Tagundnachtgleiche steht die Sonne mittags im Süden — genau dort,
    wo in der Altstadt das hohe Haus steht. Die Sonnenfenster müssen sich
    deshalb um die Mittagszeit teilen."""
    alt = sonne.auswerten(48.13745, 11.57538,
                          overpass_gebaeude["altstadt"]["elements"], 2026)
    fenster = alt["tage"]["uebergang"]["fenster"]
    assert len(fenster) >= 2, fenster
    luecke_beginnt = min(f["bis"] for f in fenster)
    luecke_endet = max(f["von"] for f in fenster)
    assert luecke_beginnt < "12:00" < luecke_endet, fenster


def test_fenster_haben_ein_echtes_ende(overpass_gebaeude):
    """Ein Sonnenfenster endet am Ende des letzten besonnten Rasterschritts
    — ein Einzelschritt darf nicht als „12:30–12:30" erscheinen."""
    d = sonne.auswerten(48.13745, 11.57538,
                        overpass_gebaeude["altstadt"]["elements"], 2026)
    for tag in d["tage"].values():
        for f in tag["fenster"]:
            assert f["von"] < f["bis"], f
            assert f["minuten"] >= 30


def test_abdeckung_wird_ehrlich_ausgewiesen(overpass_gebaeude):
    d = sonne.auswerten(48.1334, 11.5674,
                        overpass_gebaeude["sendlinger_tor"]["elements"], 2026)
    assert d["gebaeude_mit_hoehe"] + d["gebaeude_ohne_hoehe"] == d["gebaeude_gesamt"]
    assert 70 <= d["hoehen_abdeckung_prozent"] <= 80
    assert any("Obergrenze" in h for h in d["hinweise"])
