"""Pendlerrechnung: AGS→ARS-Abbildung und Auswertung der echten CSV-Auszüge.

Die Fixture ``raw_pendler_muenchen.json`` enthält unveränderte Zeilen der
Pendleratlas-Dateien vom 03.08.2026 (Berichtsjahr 2024): die drei
Kennzahlzeilen je Karte (München, Nürnberg, Garching) und die ersten acht
Verflechtungszeilen Münchens samt der dafür nötigen Gemeindenamen.
"""

from __future__ import annotations

from gastroviewer.sources.pendler import (ars_aus_ags, auswerten, parse_karte,
                                          parse_verflechtung)

MUC_ARS = "091620000000"


def test_ars_aus_ags(pendler_muenchen):
    gemeinden = pendler_muenchen["gemeinden"]["features"]
    # München: AGS 09162000 -> ARS 091620000000 (Verbandsteil 0000).
    g = ars_aus_ags("09162000", gemeinden)
    assert g and g["ars"] == MUC_ARS and g["gen"] == "München"
    # Garching: verbandsangehöriger Schlüsselaufbau.
    g2 = ars_aus_ags("09184119", gemeinden)
    assert g2 and g2["gen"] == "Garching b.München"
    assert ars_aus_ags("99999999", gemeinden) is None
    assert ars_aus_ags("0916", gemeinden) is None


def test_parse_karte(pendler_muenchen):
    text = pendler_muenchen["dateien"]["2024_EIP_Karte_L00.csv"]
    werte = parse_karte(text, "EIP")
    assert werte[MUC_ARS] == 529834
    quote = parse_karte(
        pendler_muenchen["dateien"]["2024_EIP_Quote_Karte_L00.csv"], "EIP_Quote")
    assert quote[MUC_ARS] == 45.3
    # Unbekannte Spalte: leeres Ergebnis statt Absturz.
    assert parse_karte(text, "GIBT_ES_NICHT") == {}


def test_auswerten_muenchen(pendler_muenchen):
    data = auswerten(
        "09162000", 2024,
        pendler_muenchen["gemeinden"]["features"],
        {name: text for name, text in (
            (n.split("_", 1)[1].rsplit("_L00.csv", 1)[0], t)
            for n, t in pendler_muenchen["dateien"].items()
            if n.endswith("_L00.csv"))},
        pendler_muenchen["dateien"]["2024_Verfl_L09.csv"],
    )
    assert data is not None
    assert data["gemeinde"]["name"] == "München"
    assert data["einpendler"] == 529834
    assert data["auspendler"] == 248679
    assert data["saldo"] == 281155
    assert data["einpendler_quote"] == 45.3
    assert data["binnenpendler"] == 640422

    verfl = data["verflechtung"]
    assert len(verfl["herkunft"]) == 5 and len(verfl["ziele"]) == 5
    # Bekannte Eigenheit der Pendlerrechnung: Berlin als „Herkunft" mit
    # 501,5 km — die Entfernung steht im Datensatz und wird mitgeführt,
    # damit solche Fernbeziehungen erkennbar bleiben.
    berlin = next((h for h in verfl["herkunft"] if h["name"] == "Berlin"), None)
    assert berlin and berlin["km"] == 501.5


def test_parse_verflechtung_fremde_gemeinde(pendler_muenchen):
    v = parse_verflechtung(
        pendler_muenchen["dateien"]["2024_Verfl_L09.csv"], "055150000000", {})
    assert v == {"ziele": [], "herkunft": []}
