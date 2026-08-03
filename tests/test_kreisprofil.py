"""Kreisprofil (Regionalatlas): Auswertung der echten Tabellenantworten.

Die Fixture ``raw_kreisprofil_muenchen.json`` ist die unveränderte Antwort des
Dienstes vom 03.08.2026 für München (09162), Bayern (09) und Deutschland (DG).
Die Sollwerte unten sind die live gegengeprüften Zahlen aus dem Abruf — kein
Wert ist ausgedacht.
"""

from __future__ import annotations

from gastroviewer.sources.kreisprofil import TABELLEN, _wert, auswerten_tabelle


def _tabelle(name):
    return next(e for e in TABELLEN if e["tabelle"] == name)


def _indikator(liste, schluessel):
    return next(i for i in liste if i["schluessel"] == schluessel)


def test_sperrwerte_werden_zu_fehlend():
    assert _wert(13.2) == 13.2
    assert _wert(0) == 0
    assert _wert(None) is None
    assert _wert("x") is None
    # Regionalatlas-Platzhalter für gesperrte/fehlende Werte.
    assert _wert(2222222222) is None
    assert _wert(5555555555) is None
    assert _wert(-9999999) is None


def test_beherbergung_muenchen(kreisprofil_muenchen):
    payload = kreisprofil_muenchen["regionalatlas.ai012_5"]
    erg = auswerten_tabelle(payload, _tabelle("regionalatlas.ai012_5"),
                            "09162", "09")
    ue = _indikator(erg, "uebernachtungen_je_ew")
    assert ue["jahr"] == 2024
    assert ue["kreis"] == 13.2
    assert ue["land"] == 7.8
    assert ue["bund"] == 5.9
    assert ue["verlauf_kreis"][-1] == {"jahr": 2024, "wert": 13.2}
    dauer = _indikator(erg, "aufenthaltsdauer")
    assert dauer["kreis"] == 2.1


def test_erwerbstaetige_am_arbeitsort(kreisprofil_muenchen):
    payload = kreisprofil_muenchen["regionalatlas.ai007_1"]
    erg = auswerten_tabelle(payload, _tabelle("regionalatlas.ai007_1"),
                            "09162", "09")
    et = _indikator(erg, "et_je_1000_ew")
    # München ist Einpendler-Magnet: mehr Erwerbstätige am Arbeitsort als
    # Erwerbsfähige — der Wert liegt über 1.000, Bayern und Bund darunter.
    assert et["kreis"] == 1159.1
    assert et["land"] == 923.8
    assert et["bund"] == 868.5
    assert et["kreis"] > 1000 > et["land"]


def test_arbeitsmarkt_und_bevoelkerung(kreisprofil_muenchen):
    quote = auswerten_tabelle(
        kreisprofil_muenchen["regionalatlas.ai008_1_5"],
        _tabelle("regionalatlas.ai008_1_5"), "09162", "09")
    alq = _indikator(quote, "arbeitslosenquote")
    assert alq["jahr"] == 2025
    assert alq["kreis"] == 5.4
    assert alq["land"] == 4
    assert alq["bund"] == 6.3

    bev = auswerten_tabelle(
        kreisprofil_muenchen["regionalatlas.ai002_1_5"],
        _tabelle("regionalatlas.ai002_1_5"), "09162", "09")
    entw = _indikator(bev, "bev_entwicklung")
    assert entw["kreis"] == 108.8
    saldo = _indikator(bev, "wanderungssaldo")
    assert saldo["kreis"] == 81.2


def test_fremder_kreis_liefert_nichts(kreisprofil_muenchen):
    erg = auswerten_tabelle(
        kreisprofil_muenchen["regionalatlas.ai012_5"],
        _tabelle("regionalatlas.ai012_5"), "05315", "05")
    assert erg == []
