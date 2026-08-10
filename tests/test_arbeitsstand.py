"""Arbeitsstand je gemerktem Standort.

Standortsuche dauert Monate und läuft über dutzende Adressen. Die Zahlen
allein reichen dafür nicht — man muss sehen, wie weit man mit jeder Adresse
selbst ist, und bei einer abgelehnten den Grund, damit dieselbe Adresse
nicht in einem Jahr noch einmal durchgeprüft wird.

Der wichtigste Test hier ist `test_stand_aendern_loescht_die_notiz_nicht`:
Vor dieser Runde schrieb ein Aufruf immer Notiz **und** Note gemeinsam.
Sobald ein drittes Feld dazukommt, würde das Setzen des Arbeitsstands eine
mühsam eingetippte Notiz stillschweigend löschen.
"""

from __future__ import annotations

import sqlite3

# Die client-Fixture baut die ganze Anwendung mit aufgezeichneten Antworten
# auf; sie steht in test_api.py und wird hier wiederverwendet statt kopiert.
from test_api import client  # noqa: F401

from gastroviewer.cache import NACHRUESTUNG, STAENDE, STAND_SCHLUESSEL, Cache

LAT, LON, R = 48.1372, 11.5755, 600


def _merken(client, label="Kandidat"):
    antwort = client.post("/api/points",
                          json={"label": label, "lat": LAT, "lon": LON, "radius": R})
    assert antwort.status_code == 200, antwort.text
    return antwort.json()["id"]


# --------------------------------------------------------- Teilaktualisierung


def test_stand_aendern_loescht_die_notiz_nicht(client):
    pid = _merken(client)
    client.patch(f"/api/points/{pid}",
                 json={"notiz": "Ecklage, Schaufenster nach Süden", "bewertung": 2})
    client.patch(f"/api/points/{pid}", json={"stand": "besichtigt"})

    punkt = client.get(f"/api/points/{pid}").json()
    assert punkt["stand"] == "besichtigt"
    assert punkt["notiz"] == "Ecklage, Schaufenster nach Süden", (
        "das Setzen des Arbeitsstands darf die Notiz nicht löschen")
    assert punkt["bewertung"] == 2


def test_notiz_aendern_loescht_den_stand_nicht(client):
    pid = _merken(client)
    client.patch(f"/api/points/{pid}", json={"stand": "verhandlung"})
    client.patch(f"/api/points/{pid}", json={"notiz": "Vermieter meldet sich Montag"})

    punkt = client.get(f"/api/points/{pid}").json()
    assert punkt["stand"] == "verhandlung"
    assert punkt["notiz"] == "Vermieter meldet sich Montag"


def test_ausdrueckliches_leeren_bleibt_moeglich(client):
    """Ein Feld absichtlich zu leeren muss weiterhin gehen — sonst wäre der
    Arbeitsstand nach dem ersten Setzen nicht mehr zurückzunehmen."""
    pid = _merken(client)
    client.patch(f"/api/points/{pid}", json={"stand": "gesichtet"})
    client.patch(f"/api/points/{pid}", json={"stand": None})
    assert client.get(f"/api/points/{pid}").json()["stand"] is None


# ------------------------------------------------------------- Gültige Werte


def test_unbekannter_stand_wird_abgelehnt(client):
    pid = _merken(client)
    antwort = client.patch(f"/api/points/{pid}", json={"stand": "vielleicht"})
    assert antwort.status_code == 422
    assert "vielleicht" in antwort.text
    # Die Meldung nennt die möglichen Werte, statt nur „ungültig" zu sagen.
    assert "gesichtet" in antwort.text


def test_alle_staende_werden_angenommen(client):
    pid = _merken(client)
    for schluessel in STAND_SCHLUESSEL:
        antwort = client.patch(f"/api/points/{pid}", json={"stand": schluessel})
        assert antwort.status_code == 200, f"{schluessel}: {antwort.text}"


def test_ablehnungsgrund_wird_gespeichert(client):
    pid = _merken(client)
    client.patch(f"/api/points/{pid}",
                 json={"stand": "abgelehnt",
                       "stand_grund": "Vermieter will keine Gastronomie"})
    punkt = client.get(f"/api/points/{pid}").json()
    assert punkt["stand"] == "abgelehnt"
    assert "Vermieter" in punkt["stand_grund"]


# ------------------------------------------------------------- Vergleich/CSV


def test_vergleich_liefert_die_auswahl_mit(client):
    """Die Oberfläche erfindet keine Arbeitsstände — sie kommen vom Server."""
    _merken(client)
    v = client.get("/api/points/vergleich").json()
    assert [s["key"] for s in v["staende"]] == STAND_SCHLUESSEL
    assert all(s["label"] for s in v["staende"])
    assert any(c["key"] == "stand" for c in v["spalten"])


def test_stand_steht_in_der_vergleichszeile(client):
    pid = _merken(client)
    client.patch(f"/api/points/{pid}", json={"stand": "angebot"})
    zeile = client.get("/api/points/vergleich").json()["zeilen"][0]
    assert zeile["stand"] == "angebot"


def test_stand_ist_im_csv_export(client):
    pid = _merken(client)
    client.patch(f"/api/points/{pid}", json={"stand": "besichtigt"})
    csv = client.get("/api/export/vergleich.csv").text
    assert "Arbeitsstand" in csv
    assert "besichtigt" in csv


def test_stand_ist_in_der_datensicherung(client):
    pid = _merken(client)
    client.patch(f"/api/points/{pid}",
                 json={"stand": "abgelehnt", "stand_grund": "zu wenig Parkplätze"})
    sicherung = client.get("/api/points/export").json()
    punkt = sicherung["punkte"][0]
    assert punkt["stand"] == "abgelehnt"
    assert punkt["stand_grund"] == "zu wenig Parkplätze"


# ------------------------------------------------------------ Nachrüstung


def test_alte_datenbank_bekommt_die_spalten(tmp_path):
    """Wer seit Monaten Standorte pflegt, darf durch ein Update nichts
    verlieren — die Spalten werden ergänzt, die Daten bleiben."""
    pfad = tmp_path / "alt.sqlite"
    with sqlite3.connect(pfad) as conn:
        conn.execute(
            "CREATE TABLE saved_points (id INTEGER PRIMARY KEY, label TEXT,"
            " lat REAL, lon REAL, radius INTEGER, created_at REAL, payload TEXT)")
        conn.execute(
            "INSERT INTO saved_points(label, lat, lon, radius, created_at, payload)"
            " VALUES ('Altbestand', 48.1, 11.5, 600, 0, '{}')")

    Cache(pfad)          # legt an und rüstet nach
    with sqlite3.connect(pfad) as conn:
        conn.row_factory = sqlite3.Row
        spalten = {r["name"] for r in
                   conn.execute("PRAGMA table_info(saved_points)").fetchall()}
        zeilen = conn.execute("SELECT * FROM saved_points").fetchall()
    assert {"stand", "stand_grund"} <= spalten
    assert len(zeilen) == 1 and zeilen[0]["label"] == "Altbestand"


def test_nachruestung_kennt_die_neuen_spalten():
    spalten = {s for _, s, _ in NACHRUESTUNG}
    assert {"stand", "stand_grund"} <= spalten


def test_nur_eigene_felder_sind_schreibbar(tmp_path):
    """Über diesen Weg darf niemand Koordinaten oder Nutzdaten verbiegen."""
    c = Cache(tmp_path / "t.sqlite")
    pid = c.save_point("A", 48.1, 11.5, 600, {"bloecke": {}})
    assert c.set_point_felder(pid, {"lat": 0.0, "payload": "{}"}) is False
    punkt = c.get_point(pid)
    assert punkt["lat"] == 48.1


def test_staende_sind_beschriftet():
    """Jeder Schlüssel hat einen lesbaren Text — die Oberfläche zeigt nie
    einen rohen Schlüssel."""
    for schluessel, text in STAENDE:
        assert schluessel and text
        assert schluessel.islower()


# ------------------------------------------------ Standortbericht


def _bericht_js() -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parents[1] / "gastroviewer" / "static"
            / "bericht.js").read_text(encoding="utf-8")


def test_bericht_zeigt_den_arbeitsstand():
    """Wer den Bericht in die Hand bekommt, will zuerst wissen, wie weit die
    Sache ist — und bei einer Ablehnung warum."""
    js = _bericht_js()
    assert "Arbeitsstand: " in js
    assert "p.stand_grund" in js


def test_bericht_zeigt_das_standortprofil():
    js = _bericht_js()
    assert "gastroviewer.standortprofil" in js, "derselbe Speicher wie die Anwendung"
    assert "/api/points/kriterien" in js, "gerechnet wird im Backend, nicht doppelt"
    assert "nicht prüfbar" in js
    assert "nicht_pruefbar_grundsaetzlich" in js, (
        "was der Ortstermin klären muss, gehört in den Bericht")


def test_bericht_loest_keine_overpass_abfrage_aus():
    """Die Fahrzeit erscheint nur, wenn sie beim Merken schon vorlag."""
    js = _bericht_js()
    assert "payload.bloecke?.fahrzeit" in js
    assert "/api/point/fahrzeit" not in js, (
        "eine Druckansicht darf die größte Abfrage des Werkzeugs nicht starten")
