"""Umsatzschätzung — die Auflagen aus §9 der Spec sind hier als Tests festgehalten.

Der Vorgänger dieses Werkzeugs ist daran gescheitert, dass erfundene Gewichte in
einer Rechnung steckten, die präzise aussah. Diese Tests halten fest, dass das
hier nicht passieren kann: kein versteckter Faktor, immer eine Spanne, immer die
Umrechnung in Bestellungen, immer die Formel.
"""

from __future__ import annotations

import pytest

from gastroviewer import schaetzung
from gastroviewer.schaetzung import Eingaben, rechne


def basis(**kw) -> Eingaben:
    vor = {
        "einwohner": 16370,
        "wettbewerber": 26,
        "besuche_je_einwohner": 60.3,
        "bon_min": 7.15,
        "bon_max": 10.21,
    }
    vor.update(kw)
    return Eingaben(**vor)


# ------------------------------------------------------- Auflagen aus §9


def test_ausgabe_ist_immer_eine_spanne():
    """§9: „Ausgabe als Spanne, nie als Punktwert.\""""
    e = rechne(basis())["ergebnis"]
    for feld, werte in e.items():
        assert isinstance(werte, list) and len(werte) == 2, f"{feld} ist kein Intervall"
        assert werte[0] <= werte[1], f"{feld}: Untergrenze über Obergrenze"


def test_spanne_bleibt_spanne_auch_bei_festem_marktanteil():
    """Selbst wenn der Nutzer den Marktanteil auf einen Punkt setzt, bleibt die
    Bon-Annahme eine Spanne — ein Punktwert kommt nie heraus."""
    e = rechne(basis(marktanteil_min_prozent=3.0, marktanteil_max_prozent=3.0))["ergebnis"]
    assert e["jahresumsatz_eur"][0] < e["jahresumsatz_eur"][1]


def test_bestellungen_je_tag_und_stunde_sind_pflichtausgabe():
    """§9: „Pflichtausgabe daneben: die Umrechnung in Bestellungen pro Tag und
    pro Öffnungsstunde.\""""
    e = rechne(basis())["ergebnis"]
    assert "bestellungen_je_tag" in e
    assert "bestellungen_je_oeffnungsstunde" in e
    tag = e["bestellungen_je_tag"]
    stunde = e["bestellungen_je_oeffnungsstunde"]
    assert stunde[0] == pytest.approx(tag[0] / 12.0, rel=0.02)
    assert stunde[1] == pytest.approx(tag[1] / 12.0, rel=0.02)


def test_formel_wird_mitgeliefert():
    """§9: „Die Formel steht sichtbar in der UI, nicht nur im Code.\""""
    d = rechne(basis())
    assert len(d["formel"]) == 6
    text = " ".join(d["formel"])
    for teil in ("Einwohner", "Marktanteil", "Durchschnittsbon", "Öffnungstage",
                 "Öffnungsstunden"):
        assert teil in text


def test_beschriftung_sagt_vergleichsmass_nicht_prognose():
    """§9: „Beschriftung: Vergleichsmaß zwischen Standorten, keine Prognose.\""""
    d = rechne(basis())
    assert "Vergleichsmaß" in d["beschriftung"]
    assert "keine Prognose" in d["beschriftung"]


def test_jede_annahme_erscheint_in_der_ausgabe():
    """§9: „Alle Annahmen sind Eingabefelder, keine versteckten Konstanten.\"
    Gegenprobe: was die Rechnung benutzt, muss sie auch ausweisen."""
    d = rechne(basis())
    e = d["eingaben"]
    for feld in ("einwohner", "wettbewerber", "besuche_je_einwohner", "bon_min",
                 "bon_max", "marktanteil_min_prozent", "marktanteil_max_prozent",
                 "oeffnungstage", "oeffnungsstunden", "mietanteil_min_prozent",
                 "mietanteil_max_prozent"):
        assert feld in e, f"{feld} wird benutzt, aber nicht ausgewiesen"


# ------------------------------------------------------ Rechenweg prüfen


def test_rechenkette_ist_von_hand_nachrechenbar():
    """Vier Multiplikationen, sonst nichts. Wenn hier ein unsichtbarer Faktor
    hinzukäme, würde dieser Test brechen."""
    e = basis(marktanteil_min_prozent=2.0, marktanteil_max_prozent=2.0,
              bon_min=8.0, bon_max=8.0)
    d = rechne(e)
    besuche_gebiet = 16370 * 60.3
    assert d["zwischenschritte"]["besuche_im_einzugsgebiet_je_jahr"] == round(besuche_gebiet)
    besuche_betrieb = besuche_gebiet * 0.02
    assert d["zwischenschritte"]["besuche_des_betriebs_je_jahr"][0] == round(besuche_betrieb)
    assert d["ergebnis"]["jahresumsatz_eur"][0] == round(besuche_betrieb * 8.0)
    assert d["ergebnis"]["bestellungen_je_tag"][0] == round(besuche_betrieb / 360, 1)


def test_naiver_marktanteil_ist_gleichverteilung():
    assert basis(wettbewerber=0).naiver_marktanteil_prozent() == 100.0
    assert basis(wettbewerber=1).naiver_marktanteil_prozent() == 50.0
    assert basis(wettbewerber=9).naiver_marktanteil_prozent() == 10.0


def test_marktanteil_ohne_angabe_kommt_aus_dem_sichtbaren_faktor():
    d = rechne(basis(unsicherheitsfaktor=2.0))
    naiv = d["zwischenschritte"]["naiver_marktanteil_prozent"]
    assert d["eingaben"]["marktanteil_min_prozent"] == pytest.approx(naiv / 2, rel=1e-3)
    assert d["eingaben"]["marktanteil_max_prozent"] == pytest.approx(naiv * 2, rel=1e-3)
    assert "keine Datengrundlage" in d["zwischenschritte"]["marktanteil_herkunft"]


def test_gesetzter_marktanteil_hat_vorrang():
    d = rechne(basis(marktanteil_min_prozent=1.0, marktanteil_max_prozent=5.0))
    assert d["eingaben"]["marktanteil_min_prozent"] == 1.0
    assert d["eingaben"]["marktanteil_max_prozent"] == 5.0
    assert d["zwischenschritte"]["marktanteil_herkunft"] == "vom Nutzer gesetzt"


def test_vertauschte_grenzen_werden_geordnet():
    d = rechne(basis(bon_min=10.0, bon_max=6.0,
                     marktanteil_min_prozent=8.0, marktanteil_max_prozent=2.0))
    assert d["eingaben"]["bon_min"] == 6.0
    assert d["eingaben"]["marktanteil_min_prozent"] == 2.0
    assert d["ergebnis"]["jahresumsatz_eur"][0] <= d["ergebnis"]["jahresumsatz_eur"][1]


def test_marktanteil_wird_bei_100_prozent_gedeckelt():
    d = rechne(basis(wettbewerber=0, unsicherheitsfaktor=3.0))
    assert d["eingaben"]["marktanteil_max_prozent"] == 100.0


def test_mehr_wettbewerber_senkt_den_umsatz():
    wenig = rechne(basis(wettbewerber=2))["ergebnis"]["jahresumsatz_eur"]
    viel = rechne(basis(wettbewerber=40))["ergebnis"]["jahresumsatz_eur"]
    assert viel[1] < wenig[1]


def test_ohne_einwohner_kommt_null_heraus_und_kein_fehler():
    """Ländlicher Punkt ohne Zensuszelle: die Rechnung muss 0 liefern, nicht raten."""
    d = rechne(basis(einwohner=0))
    assert d["ok"]
    assert d["ergebnis"]["jahresumsatz_eur"] == [0, 0]
    assert d["ergebnis"]["bestellungen_je_oeffnungsstunde"] == [0.0, 0.0]


@pytest.mark.parametrize(
    "kw,teil",
    [
        ({"oeffnungstage": 0}, "Öffnungstage"),
        ({"oeffnungsstunden": 0}, "Öffnungsstunden"),
        ({"unsicherheitsfaktor": 0.5}, "Unsicherheitsfaktor"),
        ({"einwohner": -1}, "Einwohnerzahl"),
    ],
)
def test_unsinnige_eingaben_werden_benannt(kw, teil):
    d = rechne(basis(**kw))
    assert d["ok"] is False
    assert any(teil in f for f in d["fehler"])


# ------------------------------------------------------- Referenzwerte


def test_jeder_referenzwert_nennt_quelle_und_stand():
    for r in schaetzung.REFERENZWERTE:
        assert r["titel"] and r["quelle"] and r["stand"], r
        # Nur die Branchenfaustregel aus den Notizen hat keine URL.
        if r["schluessel"] != "mietanteil":
            assert r["url"], f"{r['schluessel']} ohne Fundstelle"
            assert r["abgerufen"] == "2026-08-01"


def test_besuche_je_einwohner_ist_hergeleitet_nicht_gesetzt():
    h = schaetzung.besuche_je_einwohner_und_jahr()
    # 36 Mrd. € / 7,15 € = 5,035 Mrd. Besuche; / 83,5 Mio. = 60,3
    assert h["wert"] == pytest.approx(60.3, abs=0.1)
    assert "÷" in h["herleitung"]
    assert len(h["quellen"]) == 3
    assert all(q["url"] for q in h["quellen"])


def test_warnungen_benennen_die_bekannten_luecken():
    text = " ".join(schaetzung.WARNUNGEN)
    for begriff in ("keine Prognose", "Distanzgewichte", "Untergrenze",
                    "Einpendler", "Marktanteil"):
        assert begriff in text


def test_vorgaben_aus_punkt_uebernimmt_die_echten_zahlen(zensus_600, overpass_combined):
    """Gegen die Phase-0-Fixtures: 118 Zellen, 16.370 Einwohner, 26 Schnellrestaurants."""
    from gastroviewer.sources import overpass, zensus

    cells = zensus.build_cells(zensus_600["features"])
    zdata = zensus.summarize(cells, 48.1334, 11.5674)
    cls = overpass.classify(overpass_combined["elements"], 48.1334, 11.5674, 600)
    odata = {**cls, "zusammenfassung": overpass.summarize(cls)}

    punkt = {
        "punkt": {"radius_m": 600},
        "bloecke": {
            "zensus": {"data": zdata},
            "osm": {"data": odata},
        },
    }
    v = schaetzung.vorgaben_aus_punkt(punkt)
    assert v["einwohner"] == 16370.0
    assert v["wettbewerber"] == 26
    assert "118 Gitterzellen" in v["einwohner_herkunft"]
    assert "Untergrenze" in v["wettbewerber_herkunft"]
    assert v["wettbewerber_alternative"]["alle_gastronomie"] == 270
    assert v["bon_min"] == 7.15


def test_vorgaben_ohne_daten_bricht_nicht():
    """An einem Punkt ohne Zensuszelle ist 0 die zutreffende Aussage. Ein leeres
    Pflichtfeld würde die Rechnung dagegen mit HTTP 422 abbrechen — das sähe aus
    wie ein Fehler des Werkzeugs statt wie eine Aussage über die Lage."""
    v = schaetzung.vorgaben_aus_punkt({"punkt": {"radius_m": 600}, "bloecke": {}})
    assert v["einwohner"] == 0
    assert v["wettbewerber"] == 0
    assert "keine Zensuszelle" in v["einwohner_herkunft"]
    d = rechne(basis(einwohner=v["einwohner"], wettbewerber=v["wettbewerber"]))
    assert d["ok"] and d["ergebnis"]["jahresumsatz_eur"] == [0, 0]


# ------------------------------------------------------------ Prüfstein


def test_kalibrierung_erkennt_zu_niedrige_rechnung():
    """Ein bekannter Umsatz sagt mehr über die Brauchbarkeit als jede weitere
    Verfeinerung der Formel."""
    k = schaetzung.kalibrierung(300_000, 50_000, 150_000, "eigener Imbiss")
    assert k["faktor"] == 3.0
    assert k["innerhalb_der_spanne"] is False
    assert "zu niedrig" in k["befund"]
    assert k["bezeichnung"] == "eigener Imbiss"


def test_kalibrierung_erkennt_zu_hohe_rechnung():
    k = schaetzung.kalibrierung(50_000, 150_000, 250_000)
    assert k["faktor"] == 0.25
    assert "zu hoch" in k["befund"]
    assert "4.00" in k["befund"], "die Richtung wird als Faktor benannt"


def test_kalibrierung_innerhalb_der_spanne_verspricht_nichts():
    k = schaetzung.kalibrierung(120_000, 100_000, 150_000)
    assert k["innerhalb_der_spanne"] is True
    assert "Mehr sagt das nicht" in k["befund"], (
        "eine weite Spanne zu treffen ist keine Bestätigung"
    )


def test_ohne_vergleichswert_gibt_es_keine_kalibrierung():
    assert schaetzung.kalibrierung(None, 1, 2) is None
    assert schaetzung.kalibrierung(0, 1, 2) is None
    assert schaetzung.kalibrierung(-5, 1, 2) is None
    assert schaetzung.kalibrierung("viel", 1, 2) is None


def test_pruefstein_veraendert_das_ergebnis_nicht():
    """Er wird gegenübergestellt, nicht eingerechnet."""
    basis = dict(einwohner=10_000, wettbewerber=30, besuche_je_einwohner=60.3,
                 bon_min=7.15, bon_max=10.21)
    ohne = schaetzung.rechne(schaetzung.Eingaben(**basis))
    mit = schaetzung.rechne(schaetzung.Eingaben(
        **basis, kalibrierung_umsatz_eur=999_999, kalibrierung_bezeichnung="Test"))
    assert ohne["ergebnis"] == mit["ergebnis"]
    assert ohne["kalibrierung"] is None
    assert mit["kalibrierung"]["tatsaechlich_eur"] == 999_999
