"""Standortprofil — die K.-o.-Prüfung eigener Mindestanforderungen.

Der Kern dieser Datei ist die Unterscheidung, die das Werkzeug von einer
Ampel trennt: Ein **fehlender** Wert ist nicht „erfüllt". Wer dreißig
Adressen filtert, darf nicht deshalb zwei aussortieren, weil eine Quelle
gerade nicht antwortete — und erst recht keine behalten, weil ein
Kriterium mangels Daten stillschweigend durchgewinkt wurde.
"""

from __future__ import annotations

import pytest

# Die client-Fixture baut die ganze Anwendung mit aufgezeichneten Antworten.
from test_api import client  # noqa: F401

from gastroviewer.kriterien import (
    KEINE_KRITERIEN,
    NICHT_PRUEFBAR,
    ProfilFehler,
    moegliche_kriterien,
    pruefe_kriterium,
    pruefe_profil,
)

LAT, LON, R = 48.1372, 11.5755, 600

ZEILE = {
    "label": "Marienplatz",
    "einwohner": 4200,
    "gastro_bis_300": 61,
    "dtv_kfz": 12000,
    "miete_qm": 14.5,
    "abfahrten": None,          # Quelle lieferte nichts
}


# ------------------------------------------------------- Einzelne Kriterien


def test_mindestwert_erfuellt():
    e = pruefe_kriterium(ZEILE, {"key": "einwohner", "richtung": "min", "wert": 3000})
    assert e["stand"] == "erfuellt" and e["wert"] == 4200


def test_mindestwert_nicht_erfuellt():
    e = pruefe_kriterium(ZEILE, {"key": "einwohner", "richtung": "min", "wert": 25000})
    assert e["stand"] == "nicht_erfuellt"


def test_hoechstwert():
    """Bei Wettbewerb und Miete ist weniger besser — die Richtung wird
    ausdrücklich gewählt und nicht geraten."""
    assert pruefe_kriterium(
        ZEILE, {"key": "gastro_bis_300", "richtung": "max", "wert": 80},
    )["stand"] == "erfuellt"
    assert pruefe_kriterium(
        ZEILE, {"key": "gastro_bis_300", "richtung": "max", "wert": 20},
    )["stand"] == "nicht_erfuellt"


def test_genau_auf_der_schwelle_gilt_als_erfuellt():
    """„mindestens 4200" ist bei 4200 erfüllt — sonst wäre die Beschriftung
    falsch."""
    assert pruefe_kriterium(
        ZEILE, {"key": "einwohner", "richtung": "min", "wert": 4200},
    )["stand"] == "erfuellt"
    assert pruefe_kriterium(
        ZEILE, {"key": "gastro_bis_300", "richtung": "max", "wert": 61},
    )["stand"] == "erfuellt"


def test_fehlender_wert_ist_nicht_erfuellt_und_nicht_durchgefallen():
    """Der wichtigste Fall: kein Wert heißt „offen", nicht „bestanden"."""
    e = pruefe_kriterium(ZEILE, {"key": "abfahrten", "richtung": "min", "wert": 500})
    assert e["stand"] == "nicht_pruefbar"


def test_fehlende_spalte_ist_ebenfalls_nicht_pruefbar():
    e = pruefe_kriterium(ZEILE, {"key": "bip_je_ew", "richtung": "min", "wert": 1})
    assert e["stand"] == "nicht_pruefbar"


def test_text_und_wahrheitswerte_gelten_nicht_als_zahl():
    e = pruefe_kriterium({"einwohner": True}, {"key": "einwohner",
                                               "richtung": "min", "wert": 1})
    assert e["stand"] == "nicht_pruefbar", "True ist keine Einwohnerzahl"


def test_unbrauchbare_kriterien_werden_abgelehnt():
    for key in ("notiz", "label", "stand", "ags"):
        with pytest.raises(ProfilFehler):
            pruefe_kriterium(ZEILE, {"key": key, "richtung": "min", "wert": 1})


def test_unbekannte_richtung_wird_abgelehnt():
    with pytest.raises(ProfilFehler) as err:
        pruefe_kriterium(ZEILE, {"key": "einwohner", "richtung": "ungefaehr",
                                 "wert": 1})
    assert "min" in str(err.value) and "max" in str(err.value)


def test_fehlender_zahlenwert_wird_abgelehnt():
    with pytest.raises(ProfilFehler):
        pruefe_kriterium(ZEILE, {"key": "einwohner", "richtung": "min",
                                 "wert": "viele"})


# ------------------------------------------------------------ Ganzes Profil


def test_profil_zaehlt_alle_drei_ergebnisse():
    r = pruefe_profil(ZEILE, [
        {"key": "einwohner", "richtung": "min", "wert": 3000},
        {"key": "gastro_bis_300", "richtung": "max", "wert": 20},
        {"key": "abfahrten", "richtung": "min", "wert": 500},
    ])
    assert (r["erfuellt"], r["nicht_erfuellt"], r["nicht_pruefbar"]) == (1, 1, 1)
    assert r["gesamt"] == 3


def test_ko_kriterium_laesst_durchfallen():
    r = pruefe_profil(ZEILE, [
        {"key": "einwohner", "richtung": "min", "wert": 25000, "ko": True},
    ])
    assert r["durchgefallen"] is True


def test_offenes_ko_kriterium_laesst_nicht_durchfallen():
    """Ein K.-o.-Kriterium ohne Daten macht den Standort offen, nicht
    schlecht — sonst würde eine ausgefallene Quelle Kandidaten aussortieren."""
    r = pruefe_profil(ZEILE, [
        {"key": "abfahrten", "richtung": "min", "wert": 500, "ko": True},
    ])
    assert r["durchgefallen"] is False
    assert r["offene_ko_kriterien"] == ["abfahrten"]


def test_nicht_pruefbare_kriterien_werden_immer_mitgeliefert():
    """Ein Profil aus lauter grünen Haken verleitet zu dem Fehlschluss,
    der Standort sei geeignet. Die offenen Fragen stehen deshalb immer dabei."""
    r = pruefe_profil(ZEILE, [])
    assert r["nicht_pruefbar_grundsaetzlich"] == NICHT_PRUEFBAR
    text = " ".join(NICHT_PRUEFBAR).lower()
    for muss in ("sichtbarkeit", "miete", "verfügbarkeit", "stellplätze"):
        assert muss in text


def test_leeres_profil_faellt_nicht_durch():
    r = pruefe_profil(ZEILE, [])
    assert r["durchgefallen"] is False and r["gesamt"] == 0


# ------------------------------------------------------------- Auswahlliste


def test_auswahl_kommt_aus_den_vergleichsspalten():
    from gastroviewer.api import VERGLEICH_SPALTEN

    auswahl = moegliche_kriterien(VERGLEICH_SPALTEN)
    keys = {k["key"] for k in auswahl}
    assert "einwohner" in keys and "dtv_kfz" in keys
    assert not (keys & KEINE_KRITERIEN), "Texte und Schlüssel sind kein Kriterium"
    assert all(k["titel"] for k in auswahl)


# ------------------------------------------------------------------- Routen


def test_route_liefert_die_auswahl(client):
    d = client.get("/api/points/kriterien").json()
    keys = {k["key"] for k in d["kriterien"]}
    assert "einwohner" in keys and "notiz" not in keys


def test_route_prueft_gemerkte_punkte(client):
    client.post("/api/points",
                json={"label": "A", "lat": LAT, "lon": LON, "radius": R})
    antwort = client.post("/api/points/kriterien", json={"kriterien": [
        {"key": "einwohner", "richtung": "min", "wert": 1, "ko": True},
        {"key": "einwohner", "richtung": "min", "wert": 10_000_000},
    ]})
    assert antwort.status_code == 200, antwort.text
    d = antwort.json()
    assert d["anzahl"] == 1
    punkt = d["punkte"][0]
    assert punkt["label"] == "A"
    assert punkt["erfuellt"] == 1 and punkt["nicht_erfuellt"] == 1
    assert punkt["durchgefallen"] is False


def test_route_meldet_ein_kaputtes_kriterium(client):
    client.post("/api/points",
                json={"label": "A", "lat": LAT, "lon": LON, "radius": R})
    antwort = client.post("/api/points/kriterien", json={"kriterien": [
        {"key": "notiz", "richtung": "min", "wert": 1},
    ]})
    assert antwort.status_code == 422
    assert "notiz" in antwort.text


def test_route_lehnt_unbekannte_richtung_schon_im_modell_ab(client):
    antwort = client.post("/api/points/kriterien", json={"kriterien": [
        {"key": "einwohner", "richtung": "ungefaehr", "wert": 1},
    ]})
    assert antwort.status_code == 422


def test_leeres_profil_liefert_die_offenen_fragen(client):
    client.post("/api/points",
                json={"label": "A", "lat": LAT, "lon": LON, "radius": R})
    d = client.post("/api/points/kriterien", json={"kriterien": []}).json()
    assert d["punkte"][0]["nicht_pruefbar_grundsaetzlich"]
