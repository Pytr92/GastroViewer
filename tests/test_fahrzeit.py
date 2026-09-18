"""Fahrzeit-Einzugsgebiet mit dem Auto.

Geprüft wird gegen das am 09.08.2026 aufgezeichnete **echte** Autonetz um
den Marienplatz (Overpass, 2 200 m Umkreis, 1 338 Wege).

Der lehrreichste Test ist `test_fussgaengerzone_ist_ein_befund`: Am
Marienplatz liegt keine Hauptstraße in unmittelbarer Nähe. Das ist keine
Panne der Rechnung, sondern für Autokundschaft *die* Aussage — und muss
als solche herauskommen, nicht als leeres Ergebnis.
"""

from __future__ import annotations

import pytest

from gastroviewer.sources import fahrzeit
from gastroviewer.sources.base import SourceError

MARIENPLATZ = (48.1372, 11.5755)
WOHNLAGE = (48.1200, 11.5900)


@pytest.fixture(scope="module")
def netz(overpass_auto_muenchen):
    return fahrzeit.baue_autonetz(overpass_auto_muenchen["elements"])


# ------------------------------------------------------------ Tempolimits


def test_maxspeed_schlaegt_die_klassenannahme():
    assert fahrzeit._tempo_kmh({"maxspeed": "30", "highway": "secondary"}) == (30.0, True)
    # Ohne Angabe greift die Annahme je Klasse — und wird als solche gemeldet.
    kmh, aus_osm = fahrzeit._tempo_kmh({"highway": "motorway"})
    assert kmh == 120 and aus_osm is False


def test_meilen_werden_umgerechnet():
    kmh, aus_osm = fahrzeit._tempo_kmh({"maxspeed": "30 mph", "highway": "primary"})
    assert 47 < kmh < 49 and aus_osm is True


def test_unbrauchbare_angaben_fallen_auf_die_klasse_zurueck():
    """„none" (Autobahn ohne Limit) und „signals" sind keine Zahlen."""
    for roh in ("none", "signals", "variable", "DE:urban"):
        kmh, aus_osm = fahrzeit._tempo_kmh({"maxspeed": roh, "highway": "motorway"})
        assert aus_osm is False and kmh == 120


def test_schrittgeschwindigkeit():
    assert fahrzeit._tempo_kmh({"maxspeed": "walk", "highway": "tertiary"}) == (7.0, True)


def test_gesperrte_wege_zaehlen_nicht_als_befahrbar():
    assert fahrzeit._befahrbar({"motor_vehicle": "no"}) is False
    assert fahrzeit._befahrbar({"access": "private"}) is False
    assert fahrzeit._befahrbar({"access": "private", "motor_vehicle": "yes"}) is True
    assert fahrzeit._befahrbar({}) is True


# ------------------------------------------------------------------- Netz


def test_netz_aus_echten_daten(netz):
    n, z = netz
    assert z["wege"] == 1338
    assert len(n) > 4000, "das Netz muss Tausende Knoten haben"
    # Phase 0: In München sind fast alle Wege mit Tempolimit erfasst.
    anteil = 100 * z["mit_tempolimit"] / (z["mit_tempolimit"] + z["ohne_tempolimit"])
    assert anteil > 95


def test_schnelle_strasse_kostet_weniger_zeit():
    """Der Kern der Rechnung: Das Kantengewicht ist Zeit, nicht Länge."""
    weg = {"type": "way", "geometry": [{"lat": 48.10, "lon": 11.50},
                                       {"lat": 48.11, "lon": 11.50}]}
    langsam, _ = fahrzeit.baue_autonetz([{**weg, "tags": {"highway": "tertiary",
                                                          "maxspeed": "30"}}])
    schnell, _ = fahrzeit.baue_autonetz([{**weg, "tags": {"highway": "primary",
                                                          "maxspeed": "100"}}])
    a = next(iter(langsam.kanten.values()))[0][1]
    b = next(iter(schnell.kanten.values()))[0][1]
    assert a > b * 3, "dieselbe Strecke muss bei 30 km/h deutlich länger dauern"


# -------------------------------------------------------------- Auswertung


def test_fussgaengerzone_zeigt_sich_am_anfahrtsweg(netz):
    """Der Marienplatz ist eine Fußgängerzone: Die nächste Hauptstraße liegt
    rund 280 m entfernt — für Autokundschaft die entscheidende Zahl.

    Sie wird ausgewiesen, statt stillschweigend in der Fahrzeit zu
    verschwinden. Zum Vergleich: In der Wohnlage ist der Weg kürzer.
    """
    n, z = netz
    innenstadt = fahrzeit.auswerten(n, z, *MARIENPLATZ, 5, False)
    assert innenstadt["anbindung_m"] > 200
    assert innenstadt["anbindung_s"] > 30
    wohnlage = fahrzeit.auswerten(n, z, *WOHNLAGE, 5, False)
    assert wohnlage["anbindung_m"] < innenstadt["anbindung_m"]


def test_abseits_des_netzes_ist_ein_befund(netz):
    """Liegt gar keine Hauptstraße in Reichweite, ist das keine Panne der
    Rechnung, sondern die Antwort — und die Meldung sagt das."""
    n, z = netz
    with pytest.raises(SourceError) as err:
        fahrzeit.auswerten(n, z, 48.30, 11.90, 5, False)   # außerhalb der Aufnahme
    text = err.value.message
    assert "Fußgängerzone" in text
    assert "Panne" in text, "die Meldung muss den Befund als Befund benennen"


def test_wohnlage_liefert_ein_gebiet(netz):
    n, z = netz
    r = fahrzeit.auswerten(n, z, *WOHNLAGE, 5, False)
    assert r["minuten"] == 5
    assert 0 < r["anbindung_m"] <= fahrzeit.ANBINDUNG_MAX_M
    assert r["erreichte_knoten"] > 100
    assert r["flaeche"], "die erreichbare Fläche darf nicht leer sein"


def test_mehr_zeit_erreicht_mehr(netz):
    n, z = netz
    fuenf = fahrzeit.auswerten(n, z, *WOHNLAGE, 5, False)
    zehn = fahrzeit.auswerten(n, z, *WOHNLAGE, 10, False)
    assert zehn["erreichte_knoten"] > fuenf["erreichte_knoten"]
    assert len(zehn["flaeche"]) > len(fuenf["flaeche"])


def test_annahmen_stehen_in_der_ausgabe(netz):
    """Gewählte Werte gehören in die Antwort, nicht nur in den Quelltext."""
    n, z = netz
    r = fahrzeit.auswerten(n, z, *WOHNLAGE, 5, False)
    assert r["annahmen"]["zuegigkeit"] == fahrzeit.ZUEGIGKEIT
    assert r["annahmen"]["tempo_je_klasse"]["motorway"] == 120
    assert r["netz"]["tempolimit_anteil"] > 95


def test_freifluss_wird_ausdruecklich_gesagt(netz):
    n, z = netz
    r = fahrzeit.auswerten(n, z, *WOHNLAGE, 5, False)
    text = " ".join(r["hinweise"]).lower()
    assert "freifluss" in text and "stau" in text
    assert "hauptstraßennetz" in text
    assert "einbahn" in text


def test_deckel_wird_ausgewiesen(netz):
    """Ein gedeckelter Umkreis darf nicht als vollständiges Gebiet gelten."""
    n, z = netz
    ohne = fahrzeit.auswerten(n, z, *WOHNLAGE, 5, False)
    mit = fahrzeit.auswerten(n, z, *WOHNLAGE, 5, True)
    assert len(mit["hinweise"]) == len(ohne["hinweise"]) + 1
    assert any("Autobahn" in h for h in mit["hinweise"])
    assert mit["netz"]["gedeckelt"] is True


# ----------------------------------------------------------- Abfrage/Grenzen


def test_umkreis_wird_gedeckelt():
    klein, gedeckelt_klein = fahrzeit.umkreis_m(5)
    gross, gedeckelt_gross = fahrzeit.umkreis_m(10)
    assert klein < gross <= fahrzeit.MAX_UMKREIS_M
    assert gedeckelt_klein is False
    # Bei zehn Minuten greift der Deckel — Phase 0 hat 9 km nicht mehr geliefert.
    assert gedeckelt_gross is True


def test_abfrage_holt_nur_das_hauptnetz():
    q = fahrzeit.build_query(48.1, 11.5, 5)
    assert "motorway" in q and "tertiary" in q
    assert "residential" not in q, "Wohnstraßen vervierfachen die Datenmenge"
    assert "out geom" in q


def test_minuten_werden_begrenzt():
    """Größere Werte als geprüft werden nicht angeboten."""
    assert fahrzeit.MIN_MINUTEN == 5 and fahrzeit.MAX_MINUTEN == 10


def test_fahrzeit_wandert_nur_aus_dem_cache_in_den_punkt():
    """Merken darf die größte Abfrage des Werkzeugs nicht auslösen — es wird
    nur nachgesehen, nie geladen."""
    from pathlib import Path

    quelle = (Path(__file__).resolve().parents[1] / "gastroviewer"
              / "service.py").read_text(encoding="utf-8")
    block = quelle.split("async def fahrzeit_aus_cache")[1].split("async def ")[0]
    assert "self.cache.get" in block
    assert "fz_mod.load" not in block, "hier darf nichts geladen werden"


# ------------------------------------------------- Verdrahtung bis zum Service
#
# Die Tests oben prüfen reine Funktionen. Der Block war trotzdem von seiner
# Einführung an tot: Der Service übergab ein Attribut, das es nicht gibt, und
# load() las das run_query-Tupel wie ein dict. 711 grüne Tests sahen das nicht,
# weil der Service jede Ausnahme in einen Fehlerblock verpackt. Diese beiden
# Tests rufen deshalb genau den Pfad, der beim Nutzer läuft.


class _StubOut:
    """Nur die Netz-Ebene: liefert das aufgezeichnete Autonetz."""

    def __init__(self, antwort, fehler: SourceError | None = None):
        self.antwort = antwort
        self.fehler = fehler
        self.aufrufe = 0

    async def post_json(self, source, url, **kw):
        self.aufrufe += 1
        if self.fehler:
            raise self.fehler
        return self.antwort


def test_load_rechnet_aus_der_echten_antwort(overpass_auto_muenchen):
    import asyncio

    from gastroviewer.config import Settings

    out = _StubOut(overpass_auto_muenchen)
    r = asyncio.run(fahrzeit.load(out, Settings(), *MARIENPLATZ, 10))
    assert r.ok, r.error
    assert out.aufrufe == 1
    assert r.data["erreichte_knoten"] > 100
    assert r.data["flaeche"]
    assert r.provenance.endpoint, "der benutzte Spiegel gehört in die Quellenangabe"


def test_load_meldet_ausfall_als_fehlerart(overpass_auto_muenchen):
    """Alle Spiegel weg: ein Fehlerblock mit erkennbarer Art, kein „unknown"."""
    import asyncio

    from gastroviewer.config import Settings

    out = _StubOut(None, SourceError("http_status", "HTTP 504 — abgebrochen."))
    r = asyncio.run(fahrzeit.load(out, Settings(), *MARIENPLATZ, 10))
    assert not r.ok
    assert r.error["kind"] != "unknown"


def test_service_reicht_seinen_outbound_durch(monkeypatch):
    """Der Service muss das Attribut übergeben, das er wirklich besitzt."""
    import asyncio
    from unittest.mock import AsyncMock

    from gastroviewer.config import Settings
    from gastroviewer.service import PointService
    from gastroviewer.sources.base import SourceResult

    class _StubCache:
        async def get(self, key):
            return None

        async def set(self, *a, **kw):
            pass

    out = object()
    svc = PointService(Settings(), _StubCache(), out)
    ergebnis = SourceResult(name="fahrzeit", ok=True, data={"flaeche": []})
    laden = AsyncMock(return_value=ergebnis)
    monkeypatch.setattr(fahrzeit, "load", laden)
    r = asyncio.run(svc.fahrzeit(*MARIENPLATZ, 10))
    assert r.ok, r.error
    assert laden.await_count == 1
    assert laden.await_args.args[0] is out
