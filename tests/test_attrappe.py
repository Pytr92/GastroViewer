"""Die Werkzeuge hinter der Browserprüfung in der CI.

Geprüft wird hier nicht die Oberfläche selbst — das tut ``scripts/uitest.py``
im Browser — sondern das Gerüst darunter: die Schlüsselbildung der
Aufzeichnung, das abgestufte Nachschlagen der Attrappe und vor allem die
**Vollständigkeit**. Der letzte Punkt ist der eigentliche Wert dieser Datei:
Wer künftig einen Block mit einem neuen Endpunkt ergänzt und das Aufzeichnen
vergisst, bekommt einen roten Test statt einer stumm übersprungenen
Browserprüfung.
"""

from __future__ import annotations

import gzip
import importlib.util
import json
import re
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
AUFNAHME_DATEI = (WURZEL / "tests" / "fixtures" / "ui"
                  / "api-antworten.json.gz")
APP_JS = WURZEL / "gastroviewer" / "static" / "app.js"

# Routen mit Zustand laufen in der Attrappe gegen die echte Anwendung und
# werden bewusst nicht aufgezeichnet.
OHNE_AUFZEICHNUNG = {
    "/api/points",          # merken, benoten, löschen, vergleichen, sichern
    "/api/schaetzung",      # POST, rechnet clientnah im Backend ohne Netz
    "/api/export",          # Downloads aus gespeicherten Punkten
}


def _lade(name: str):
    pfad = WURZEL / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"gv_{name}", pfad)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


@pytest.fixture(scope="module")
def aufzeichnen():
    return _lade("aufzeichnen")


@pytest.fixture(scope="module")
def attrappe():
    return _lade("attrappe")


@pytest.fixture(scope="module")
def aufnahme_roh():
    if not AUFNAHME_DATEI.exists():
        pytest.skip("Aufzeichnung fehlt — scripts/aufzeichnen.py ausführen.")
    return json.loads(gzip.decompress(AUFNAHME_DATEI.read_bytes()))


# ------------------------------------------------------- Schlüsselbildung


def test_schluessel_ist_reihenfolgeunabhaengig(aufzeichnen):
    a = aufzeichnen.schluessel("/api/point/sonne", {"lon": 11.5, "lat": 48.1})
    b = aufzeichnen.schluessel("/api/point/sonne", {"lat": 48.1, "lon": 11.5})
    assert a == b


def test_schluessel_ignoriert_refresh(aufzeichnen):
    """``refresh`` umgeht nur den Cache, es ändert die Antwortform nicht —
    sonst läge dieselbe Antwort zweimal in der Aufnahme."""
    ohne = aufzeichnen.schluessel("/api/point/osm", {"lat": 48.1, "r": 600})
    mit = aufzeichnen.schluessel(
        "/api/point/osm", {"lat": 48.1, "r": 600, "refresh": "true"})
    assert ohne == mit


def test_schluessel_laesst_leere_werte_weg(aufzeichnen):
    assert aufzeichnen.schluessel("/api/register", {"plz": ""}) == "/api/register"


def test_punkte_routen_werden_nicht_aufgezeichnet(aufzeichnen):
    """Zustandsbehaftete Routen dürfen nicht eingefroren werden — sonst
    prüfen Vergleich, Notiz und Löschen nichts mehr."""
    pfade = {p for p, _ in aufzeichnen.FESTE_ABRUFE}
    assert not any(p.startswith("/api/points") for p in pfade)


def test_haidhausen_ist_dabei(aufzeichnen):
    """Die Erhaltungssatzungs-Prüfung hängt an genau dieser Koordinate."""
    assert aufzeichnen.PUNKTE["haidhausen"] == (48.1289, 11.5967)


# ------------------------------------------------------ Abgestufte Suche


@pytest.fixture
def kleine_aufnahme(attrappe):
    return attrappe.Aufnahme({
        "/api/point/sonne?lat=48.1372&lon=11.5755":
            {"status": 200, "json": {"ort": "marienplatz"}},
        "/api/point/sonne?lat=50.9413&lon=6.9583":
            {"status": 200, "json": {"ort": "koeln"}},
        "/api/gitter?ebene=1km&nord=48.23&ost=11.76&sued=48.06&west=11.34":
            {"status": 200, "json": {"zellen": 1}},
    })


def test_genauer_treffer(kleine_aufnahme):
    wert, stufe = kleine_aufnahme.suche(
        "/api/point/sonne", {"lat": "48.1372", "lon": "11.5755"})
    assert stufe == "genau" and wert["json"]["ort"] == "marienplatz"


def test_refresh_stoert_den_treffer_nicht(kleine_aufnahme):
    wert, stufe = kleine_aufnahme.suche(
        "/api/point/sonne",
        {"lat": "48.1372", "lon": "11.5755", "refresh": "true"})
    assert stufe == "genau" and wert["json"]["ort"] == "marienplatz"


def test_naechste_koordinate_statt_fehlgriff(kleine_aufnahme):
    """Ein leicht verschobener Punkt darf nicht ins Leere laufen — aber die
    Stufe muss ablesbar bleiben, damit ein grober Treffer auffällt."""
    wert, stufe = kleine_aufnahme.suche(
        "/api/point/sonne", {"lat": "48.1400", "lon": "11.5700"})
    assert stufe == "naechste" and wert["json"]["ort"] == "marienplatz"
    fern, stufe_fern = kleine_aufnahme.suche(
        "/api/point/sonne", {"lat": "50.9000", "lon": "6.9000"})
    assert stufe_fern == "naechste" and fern["json"]["ort"] == "koeln"


def test_kartenausschnitt_wird_bewusst_ignoriert(kleine_aufnahme):
    """Die Bbox entsteht aus der Fenstergröße und wandert mit jeder
    Chromium-Version — darauf darf die Prüfung nicht stehen."""
    wert, stufe = kleine_aufnahme.suche(
        "/api/gitter", {"ebene": "1km", "west": "11.3", "sued": "48.0",
                        "ost": "11.8", "nord": "48.3"})
    assert wert["json"]["zellen"] == 1 and stufe in {"ort", "pfad"}


def test_unbekannter_pfad_wird_gemeldet(kleine_aufnahme):
    wert, stufe = kleine_aufnahme.suche("/api/point/erfunden", {})
    assert wert is None and stufe == "fehlt"
    assert "/api/point/erfunden" in kleine_aufnahme.fehlgriffe


def test_punkte_routen_bleiben_echt(attrappe):
    assert "/api/points".startswith(attrappe.ECHT_BELASSEN)
    assert not "/api/point/sonne".startswith(attrappe.ECHT_BELASSEN)


# --------------------------------------------------------- Vollständigkeit


def _pfade_aus_app_js() -> set[str]:
    text = APP_JS.read_text(encoding="utf-8")
    roh = set(re.findall(r"['\"`](/api/[a-zA-Z0-9/_.-]*)", text))
    pfade = set()
    for p in roh:
        # Pfadparameter wie /api/points/${id} enden im Fund als Präfix.
        pfade.add(p.rstrip("/"))
    return {p for p in pfade if p.startswith("/api/")}


def test_app_js_benutzt_nur_abgedeckte_endpunkte(aufnahme_roh):
    """Der eigentliche Wächter: Jeder Endpunkt, den die Oberfläche anspricht,
    ist entweder aufgezeichnet oder läuft in der Attrappe echt.

    Schlägt dieser Test fehl, fehlt der Browserprüfung genau der Datensatz
    für einen neuen Block — sie würde ihn sonst stillschweigend überspringen.
    """
    aufgezeichnet = {k.partition("?")[0] for k in aufnahme_roh}
    fehlend = sorted(
        p for p in _pfade_aus_app_js()
        if p not in aufgezeichnet
        and not any(p.startswith(a) for a in OHNE_AUFZEICHNUNG))
    assert not fehlend, (
        "Nicht aufgezeichnete Endpunkte: " + ", ".join(fehlend)
        + " — scripts/aufzeichnen.py ergänzen und erneut laufen lassen.")


def test_aufnahme_enthaelt_den_sammelendpunkt(aufnahme_roh):
    """Ohne ihn funktioniert „Punkt merken" in der Attrappe nicht, und damit
    fielen Vergleich, Bericht, Duell und Notizen aus."""
    assert any(k.startswith("/api/point?") for k in aufnahme_roh)


def test_aufnahme_deckt_alle_pruefkoordinaten_ab(aufnahme_roh, aufzeichnen):
    """Jede Koordinate der Browserprüfung braucht wenigstens die Adresse."""
    for name, (lat, lon) in aufzeichnen.PUNKTE.items():
        schluessel = aufzeichnen.schluessel(
            "/api/point/adresse", {"lat": lat, "lon": lon})
        assert schluessel in aufnahme_roh, f"Adresse fehlt für {name}"


def test_aufnahme_ist_echt_und_nicht_erfunden(aufnahme_roh):
    """§10: Die Aufnahme stammt aus echten Antworten des eigenen Servers.

    Ein sicheres Kennzeichen dafür sind die Herkunftsangaben, die jede
    Quelle mitliefert — erfundene Antworten hätten sie nicht.
    """
    mit_herkunft = [k for k, v in aufnahme_roh.items()
                    if isinstance(v.get("json"), dict)
                    and v["json"].get("provenance")]
    assert len(mit_herkunft) > 20
