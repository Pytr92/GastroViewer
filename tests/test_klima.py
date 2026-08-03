"""DWD-Klimanormalwerte: Parsen der echten Dateiformate, Stationswahl.

Die Fixture ``raw_dwd_klima.json`` enthält je Datei die unveränderte
Kopfzeile und sechs unveränderte Stationszeilen des Open-Data-Servers
(Abruf 03.08.2026) — darunter München-Stadt (3379), München-Flughafen
(1262) und als Gegenpol die Zugspitze (5792, 2.956 m, 0 Sommertage).
"""

from __future__ import annotations

from gastroviewer.sources.klima import (PARAMETER, _zahl, auswerten,
                                        naechste_station, parse_stationen,
                                        parse_werte)

MARIENPLATZ = (48.1372, 11.5755)


def _dateien(dwd_klima):
    ergebnis = {}
    for eintrag in PARAMETER:
        ergebnis[eintrag["schluessel"]] = {
            "werte": parse_werte(dwd_klima[f"{eintrag['datei']}.txt"]),
            "stationen": parse_stationen(
                dwd_klima[f"{eintrag['datei']}_Stationsliste.txt"]),
        }
    return ergebnis


def test_zahlformat_des_dwd():
    # ".6" heißt 0,6 — und Leeres wird zu „liegt nicht vor", nie zu 0.
    assert _zahl(".6") == 0.6
    assert _zahl("53.3") == 53.3
    assert _zahl("") is None
    assert _zahl("-") is None


def test_parse_werte_und_stationen(dwd_klima):
    werte = parse_werte(dwd_klima["Sommertage_1991-2020.txt"])
    assert werte["3379"]["jahr"] == 53.3
    assert werte["3379"]["monate"][6] == 16  # Juli
    assert werte["5792"]["jahr"] == 0  # Zugspitze: echte 0, kein Fehlwert

    stationen = parse_stationen(dwd_klima["Sommertage_1991-2020_Stationsliste.txt"])
    assert stationen["3379"]["name"] == "München-Stadt"
    assert stationen["3379"]["hoehe_m"] == 515.4
    assert stationen["5792"]["name"] == "Zugspitze"


def test_naechste_station_ist_muenchen_stadt(dwd_klima):
    d = _dateien(dwd_klima)["sommertage"]
    sid, dist = naechste_station(*MARIENPLATZ, d["stationen"], d["werte"])
    assert sid == "3379"
    # Marienplatz -> München-Stadt (Helene-Weber-Allee): rund 4 km.
    assert 2000 < dist < 6000


def test_auswerten_marienplatz(dwd_klima):
    data = auswerten(*MARIENPLATZ, _dateien(dwd_klima))
    werte = {k["schluessel"]: k for k in data["kennzahlen"]}
    assert set(werte) == {"sommertage", "heisse_tage", "sonnenschein",
                          "niederschlag", "temperatur"}
    assert werte["sommertage"]["wert"] == 53.3
    assert werte["sonnenschein"]["wert"] == 1841.5
    assert werte["niederschlag"]["wert"] == 939.7
    assert werte["temperatur"]["wert"] == 10.1
    assert werte["sommertage"]["station"]["name"] == "München-Stadt"
    # Alle Stationen nah genug — keine Distanzwarnung.
    assert data["hinweise"] == []


def test_distanzwarnung_bei_ferner_station(dwd_klima):
    # Ein Punkt in der Nordsee-Ecke: nächste Fixture-Station ist Großenkneten,
    # aber weit jenseits der 30-km-Schwelle.
    data = auswerten(54.5, 8.5, _dateien(dwd_klima))
    assert data["kennzahlen"], "Werte kommen trotzdem — mit Warnung"
    assert any("nur bedingt übertragbar" in h for h in data["hinweise"])
