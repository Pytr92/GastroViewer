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


def test_gehwegzahl_wird_angeboten_aber_nicht_gesetzt():
    """Die Gehstrecken liegen nur vor, wenn Block 4b geladen wurde. Würden sie
    stillschweigend die Vorgabe ändern, hinge das Ergebnis daran, ob jemand
    vorher einen Knopf gedrückt hat — und zwei Standorte wären nicht mehr
    vergleichbar."""
    punkt = {
        "punkt": {"radius_m": 600},
        "bloecke": {
            "zensus": {"data": {"bevoelkerung": {"einwohner": {"wert": 10002, "zellen": 110}}}},
            "osm": {"data": {"zusammenfassung": {"gastronomie": {
                "gesamt": 382, "nach_typ": {"Schnellrestaurant": 33}}}}},
            "gehweg": {"data": {
                "zensus": {"einwohner_gehweg": 3616, "erschliessungsgrad": 36.2},
                "gastronomie": {"im_gehradius": 290},
            }},
        },
    }
    v = schaetzung.vorgaben_aus_punkt(punkt)
    assert v["einwohner"] == 10002, "die Vorgabe bleibt die Luftlinienzahl"
    alt = v["gehweg_alternative"]
    assert alt["einwohner"] == 3616
    assert alt["erschliessungsgrad"] == 36.2
    assert "überschätzt" in alt["hinweis"]
    assert "gleich" in alt["warnung"], "der Vergleichsfehler muss benannt sein"


def test_ohne_geladene_gehstrecken_gibt_es_kein_angebot():
    punkt = {
        "punkt": {"radius_m": 600},
        "bloecke": {
            "zensus": {"data": {"bevoelkerung": {"einwohner": {"wert": 500, "zellen": 9}}}},
            "osm": {"data": {"zusammenfassung": {"gastronomie": {"gesamt": 3, "nach_typ": {}}}}},
        },
    }
    assert schaetzung.vorgaben_aus_punkt(punkt)["gehweg_alternative"] is None


# ------------------------------------------------------------ Mietprobe


def test_mietprobe_findet_ohne_eingaben_nicht_statt():
    assert rechne(basis())["mietprobe"] is None
    assert rechne(basis(flaeche_qm=120))["mietprobe"] is None, \
        "Fläche allein reicht nicht — es gibt keine Vorgabemiete"


def test_mietprobe_rechnet_und_ordnet_ein():
    d = rechne(basis(flaeche_qm=120, angebotsmiete_qm=25))
    mp = d["mietprobe"]
    assert mp["monatsmiete_eur"] == 3000
    assert mp["jahresmiete_eur"] == 36000
    assert mp["obergrenze_eur"] == d["ergebnis"]["monatsmiete_obergrenze_eur"]
    assert mp["lage"] in {"unter", "innerhalb", "ueber"}
    # Absurd teures Angebot liegt sicher über der Obergrenze.
    teuer = rechne(basis(flaeche_qm=1000, angebotsmiete_qm=500))["mietprobe"]
    assert teuer["lage"] == "ueber"
    assert "trägt sie sich" in teuer["befund"]


def test_mietprobe_veraendert_das_ergebnis_nicht():
    ohne = rechne(basis())
    mit = rechne(basis(flaeche_qm=120, angebotsmiete_qm=25))
    assert ohne["ergebnis"] == mit["ergebnis"], \
        "Die Mietprobe ist eine Gegenprobe, kein Rechenfaktor"


# ------------------------------------------------------- Sensitivität


def test_sensitivitaet_zerlegt_die_spanne_exakt():
    """Marktanteil-Faktor × Bon-Faktor muss exakt den Gesamtfaktor ergeben —
    die Zerlegung ist Mathematik, kein gewählter Prüfwert."""
    d = rechne(basis())
    s = d["sensitivitaet"]
    assert s is not None
    produkt = 1.0
    for t in s["treiber"]:
        produkt *= t["faktor"]
    assert produkt == pytest.approx(s["spannenfaktor_gesamt"], rel=0.02)
    u = d["ergebnis"]["jahresumsatz_eur"]
    assert s["spannenfaktor_gesamt"] == pytest.approx(u[1] / u[0], rel=0.02)


def test_sensitivitaet_default_marktanteil_dominiert():
    """Mit Unsicherheitsfaktor 2 spannt der Marktanteil Faktor 4 auf — mehr als
    der Bon (10,21/7,15 ≈ 1,43). Der Befund muss das benennen."""
    s = rechne(basis())["sensitivitaet"]
    assert s["treiber"][0]["key"] == "marktanteil"
    assert s["treiber"][0]["faktor"] == pytest.approx(4.0, rel=0.01)
    assert "Marktanteil" in s["befund"]


def test_sensitivitaet_wettbewerber_plus_eins_exakt():
    """26 Wettbewerber: ein übersehener senkt den Umsatz um 100/28 ≈ 3,6 %."""
    s = rechne(basis())["sensitivitaet"]
    w = s["wettbewerber_plus_eins"]
    assert w["wirkung_prozent"] == pytest.approx(-100.0 / 28, abs=0.05)
    # Gegenprobe mit echter Neurechnung: +1 Wettbewerber, Mitte vergleichen.
    u0 = rechne(basis())["ergebnis"]["jahresumsatz_eur"]
    u1 = rechne(basis(wettbewerber=27))["ergebnis"]["jahresumsatz_eur"]
    gemessen = (sum(u1) / sum(u0) - 1) * 100
    assert gemessen == pytest.approx(w["wirkung_prozent"], abs=0.1)


def test_sensitivitaet_bei_gesetztem_marktanteil_ohne_wettbewerbereffekt():
    """Ist der Marktanteil vom Nutzer gesetzt, hat die Wettbewerberzahl keinen
    Einfluss mehr — der +1-Effekt darf dann nicht angezeigt werden."""
    s = rechne(basis(marktanteil_min_prozent=2, marktanteil_max_prozent=5))["sensitivitaet"]
    assert s["wettbewerber_plus_eins"] is None
    assert "gesetzt" in s["treiber"][0]["erklaerung"] or "gesetzt" in s["treiber"][1]["erklaerung"]


def test_sensitivitaet_veraendert_das_ergebnis_nicht():
    mit = rechne(basis())
    assert mit["sensitivitaet"] is not None
    assert mit["ergebnis"] == rechne(basis())["ergebnis"]


# --------------------------------------------- Wohnmiete als Lage-Anker


def test_vorgaben_liefern_zensus_wohnmiete(zensus_600, overpass_combined):
    """Die Wohnmiete des Umkreises wird als Anker vorbefüllt — mit Herkunft."""
    from gastroviewer.sources import overpass, zensus

    cells = zensus.build_cells(zensus_600["features"])
    zdata = zensus.summarize(cells, 48.1334, 11.5674)
    punkt = {"punkt": {"radius_m": 600},
             "bloecke": {"zensus": {"data": zdata}}}
    v = schaetzung.vorgaben_aus_punkt(punkt)
    erwartet = zdata["wohnen"]["miete_qm"]["wert"]
    assert v["zensus_wohnmiete_qm"] == erwartet
    assert erwartet > 0
    assert "Wohnungen" in v["zensus_wohnmiete_herkunft"]
    assert "Gewerbemiete" in v["zensus_wohnmiete_herkunft"]


def test_mietprobe_ordnet_gegen_wohnmiete_ein():
    d = rechne(basis(flaeche_qm=100, angebotsmiete_qm=30, zensus_wohnmiete_qm=15))
    vgl = d["mietprobe"]["wohnmiete_vergleich"]
    assert vgl["verhaeltnis"] == 2.0
    assert vgl["wohnmiete_qm"] == 15
    assert "WOHNUNGEN" in vgl["hinweis"]


def test_wohnmiete_veraendert_keine_rechnung():
    """Der Anker ist Einordnung, kein Rechenfaktor: Umsatz, Obergrenzen und
    Mietproben-Befund bleiben mit und ohne Anker identisch."""
    ohne = rechne(basis(flaeche_qm=100, angebotsmiete_qm=30))
    mit = rechne(basis(flaeche_qm=100, angebotsmiete_qm=30, zensus_wohnmiete_qm=15))
    assert ohne["ergebnis"] == mit["ergebnis"]
    assert ohne["mietprobe"]["lage"] == mit["mietprobe"]["lage"]
    assert ohne["mietprobe"]["wohnmiete_vergleich"] is None


def test_wohnmiete_ohne_exposeeingaben_keine_probe():
    d = rechne(basis(zensus_wohnmiete_qm=15))
    assert d["mietprobe"] is None
