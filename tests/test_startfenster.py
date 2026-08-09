"""Das Startfenster — Zustandslogik und Hintergrundangaben.

Geprüft wird hier alles außer der Darstellung. Das ist Absicht und kein
Kompromiss: Ob eine Schaltfläche links oder rechts sitzt, sagt nichts über
die Richtigkeit; ob das Fenster „läuft" meldet, obwohl der Server nicht
geantwortet hat, sagt sehr viel.

Die Hintergrundangaben werden gegen die **echten** aufgezeichneten
Antworten von ``/api/health`` und ``/api/stats`` geprüft (§10) — dieselbe
Aufnahme, aus der die Browserprüfung ihre Daten bezieht.

``tkinter`` ist auf einem nackten Linux nicht dabei. Der Fensterbau wird
deshalb übersprungen statt fehlzuschlagen — und das Überspringen ist
sichtbar, nicht stillschweigend.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from gastroviewer.startfenster import (
    BESCHRIFTUNG,
    STARTFENSTER_S,
    Zustand,
    hintergrund_fakten,
    zustand,
)

AUFNAHME = (Path(__file__).resolve().parent / "fixtures" / "ui"
            / "api-antworten.json.gz")


@pytest.fixture(scope="module")
def echte_antworten():
    if not AUFNAHME.exists():
        pytest.skip("Aufzeichnung fehlt — scripts/aufzeichnen.py ausführen.")
    d = json.loads(gzip.decompress(AUFNAHME.read_bytes()))
    return d["/api/health"]["json"], d["/api/stats"]["json"]


# ------------------------------------------------------------- Zustände


def test_laeuft_verlangt_eine_antwort():
    """Der wichtigste Test: Ein laufender Faden allein ist nicht „läuft"."""
    assert zustand(faden_laeuft=True, gesund=False, fremd=False,
                   fehler=None, seit_s=1.0) == Zustand.STARTET
    assert zustand(faden_laeuft=True, gesund=True, fremd=False,
                   fehler=None, seit_s=1.0) == Zustand.LAEUFT


def test_startfenster_laeuft_ab():
    """Antwortet der Server nach der Startfrist immer noch nicht, heißt das
    nicht mehr „startet" — sonst dreht sich die Anzeige ewig."""
    assert zustand(faden_laeuft=True, gesund=False, fremd=False,
                   fehler=None, seit_s=STARTFENSTER_S + 1) == Zustand.ANTWORTET_NICHT


def test_fremdes_programm_auf_dem_port():
    assert zustand(faden_laeuft=False, gesund=False, fremd=True,
                   fehler=None, seit_s=0.0) == Zustand.FREMD


def test_fehler_schlaegt_alles():
    """Ein Startfehler darf von keinem anderen Zustand überdeckt werden."""
    assert zustand(faden_laeuft=True, gesund=True, fremd=False,
                   fehler="Adresse belegt", seit_s=0.0) == Zustand.FEHLER


def test_ohne_faden_ist_aus():
    assert zustand(faden_laeuft=False, gesund=False, fremd=False,
                   fehler=None, seit_s=0.0) == Zustand.AUS


def test_jeder_zustand_hat_text_und_farbe():
    schluessel = {v for k, v in vars(Zustand).items() if not k.startswith("_")}
    assert schluessel == set(BESCHRIFTUNG)
    for text, farbe in BESCHRIFTUNG.values():
        assert text and farbe.startswith("#")


def test_nur_laeuft_ist_gruen():
    """Kein Zustand außer „läuft" darf grün aussehen."""
    gruen = BESCHRIFTUNG[Zustand.LAEUFT][1]
    andere = [f for z, (_, f) in BESCHRIFTUNG.items() if z != Zustand.LAEUFT]
    assert gruen not in andere


# --------------------------------------------------- Hintergrundangaben


def test_fakten_aus_echten_antworten(echte_antworten):
    health, stats = echte_antworten
    zeilen = dict(hintergrund_fakten(health, stats))
    assert zeilen["Datenverzeichnis"] == health["datenverzeichnis"]
    assert "GTFS" in " ".join(zeilen)
    # Die Zahlen stammen unverändert aus der Antwort.
    assert zeilen["Abrufe (24 h)"] == str(stats["outbound_24h"])
    assert zeilen["davon Overpass"] == str(stats["overpass_24h"])


def test_fakten_ohne_antwort_bleiben_leer():
    """Ohne Antwort wird nichts behauptet."""
    assert hintergrund_fakten(None, None) == []


def test_fehlender_gtfs_import_wird_benannt():
    zeilen = dict(hintergrund_fakten({"gtfs": {"importiert": False}}, None))
    assert zeilen["ÖPNV-Fahrplan (GTFS)"] == "nicht importiert"


def test_keine_erfundenen_angaben(echte_antworten):
    """Arbeitsspeicher, Prozessorlast und pauschale Beruhigungen gehören
    nicht hierher — sie sagen nichts über die Arbeit des Werkzeugs.

    „Zwischenspeicher" ist ausdrücklich erlaubt: Das ist die gezählte Zahl
    der Cache-Einträge und damit eine belegte Angabe.
    """
    health, stats = echte_antworten
    text = " ".join(k for k, _ in hintergrund_fakten(health, stats)).lower()
    for verboten in ("cpu", "arbeitsspeicher", "prozessor", "auslastung",
                     "in ordnung", "alles gut"):
        assert verboten not in text


def test_datenverzeichnis_als_rueckfall():
    """Antwortet der Server nicht, kann das Verzeichnis trotzdem aus den
    eigenen Einstellungen kommen — das ist belegt, nicht geraten."""
    zeilen = dict(hintergrund_fakten(None, None, "/pfad/zum/ordner"))
    assert zeilen["Datenverzeichnis"] == "/pfad/zum/ordner"


# ----------------------------------------------------------- Einbindung


def test_cli_kennt_den_fenster_befehl():
    from gastroviewer.__main__ import build_parser

    args = build_parser().parse_args(["fenster", "--selbsttest"])
    assert args.func.__name__ == "cmd_fenster"
    assert args.selbsttest is True


def test_doppelklick_startet_das_fenster():
    """Im gefrorenen Paket ist das Fenster der Standard — ohne Paket bleibt
    es beim reinen Server, damit die Kommandozeile sich nicht ändert."""
    quelle = (Path(__file__).resolve().parents[1] / "gastroviewer"
              / "__main__.py").read_text(encoding="utf-8")
    assert 'standard = ["fenster"] if getattr(sys, "frozen", False)' in quelle
    assert 'else ["serve"]' in quelle


def test_fensterbau_wenn_tkinter_vorhanden():
    """Der eigentliche Fensterbau — übersprungen, wo tkinter fehlt."""
    pytest.importorskip("tkinter", reason="tkinter ist hier nicht installiert")
    import tkinter

    try:
        tkinter.Tk().destroy()
    except tkinter.TclError as err:                       # pragma: no cover
        pytest.skip(f"Keine Anzeige verfügbar: {err}")

    from gastroviewer.config import Settings
    from gastroviewer.startfenster import Serverlauf, _fenster_bauen

    lauf = Serverlauf(Settings(), "127.0.0.1", 8099)
    wurzel, aktualisieren, _ = _fenster_bauen(lauf, selbsttest=True)
    aktualisieren()
    wurzel.destroy()
