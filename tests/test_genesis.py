"""Regionaldatenbank (GENESIS) — gegen die am 2026-08-07 aufgezeichneten
echten ffcsv-Antworten (öffentlicher Werteabruf, identischer Generator wie
die REST-Schnittstelle). Sollwerte München 2023/2025 live gegengeprüft."""

from __future__ import annotations

import asyncio
import json

import pytest

from gastroviewer.sources import genesis
from gastroviewer.sources.base import SourceError


# ------------------------------------------------------------- Parser

def test_parse_ffcsv_lehnt_fremdes_format_ab():
    with pytest.raises(SourceError) as err:
        genesis.parse_ffcsv("Statistik_Code;Zeit;Wert\n123;2023;1")
    assert "unerwartete Spalten" in err.value.message


def test_zahl_qualitaetszeichen():
    assert genesis._zahl("4019") == 4019
    assert genesis._zahl("4,8") == 4.8
    assert genesis._zahl("-") is None
    assert genesis._zahl(".") is None
    assert genesis._zahl("x") is None
    assert genesis._zahl("") is None


def test_umsatz_muenchen_2023(genesis_ffcsv):
    u = genesis.umsatz_auswerten(genesis.parse_ffcsv(genesis_ffcsv["umsatz"]), "09162")
    assert u["kreis_name"] == "München, kreisfreie Stadt"
    assert u["aktuell"] == {
        "jahr": 2023,
        "pflichtige": 4019,
        "umsatz_tsd_eur": 6584298,
        "je_pflichtigem_eur": 1638293,
    }
    assert u["anteil_am_gesamtumsatz_prozent"] == 1.3


def test_umsatz_landkreis_getrennt_vom_stadtkreis(genesis_ffcsv):
    # 09184 (Landkreis München) liegt mit in der Fixture — der Filter darf
    # nicht die Stadtwerte erwischen.
    u = genesis.umsatz_auswerten(genesis.parse_ffcsv(genesis_ffcsv["umsatz"]), "09184")
    assert u["kreis_name"] == "München, Landkreis"
    assert u["aktuell"]["pflichtige"] == 871


def test_gewerbe_muenchen_2025(genesis_ffcsv):
    w = genesis.gewerbe_auswerten(genesis.parse_ffcsv(genesis_ffcsv["gewerbe"]), "09162")
    assert w["aktuell"]["jahr"] == 2025
    assert w["aktuell"]["anmeldungen"] == 15350
    assert w["aktuell"]["abmeldungen"] == 10245
    assert w["aktuell"]["saldo"] == 5105
    assert w["aktuell"]["neuerrichtungen"] == 13853
    assert w["aktuell"]["betriebsgruendungen"] == 3713
    assert w["aktuell"]["aufgaben"] == 8671
    assert w["aktuell"]["betriebsaufgaben"] == 1777


# ------------------------------------------- Gemeindetabellen (W1/W2)

def test_beschaeftigte_garching_gemeindeknoten(genesis_gemeinde_ffcsv):
    """Echte Gemeinde: GEMEIN-Zeilen mit AGS8. Sollwerte live vom
    Werteabruf 2026-08-07."""
    b = genesis.beschaeftigte_auswerten(
        genesis.parse_ffcsv(genesis_gemeinde_ffcsv["beschaeftigte"]),
        "09184119")
    assert b["name"] == "Garching b.München, St"
    assert b["ebene"] == "Gemeinde"
    assert b["aktuell"] == {"jahr": 2025, "beschaeftigte": 32823}
    assert [r["jahr"] for r in b["reihe"]] == [2008, 2016, 2025]
    assert b["reihe"][0]["beschaeftigte"] == 13163


def test_beschaeftigte_muenchen_kreisfrei_faellt_auf_kreiszeilen(
        genesis_gemeinde_ffcsv):
    """Kreisfreie Städte haben keinen Gemeindeknoten — die KREISE-Zeilen
    mit dem 5-stelligen Schlüssel gelten als Gemeindewert."""
    b = genesis.beschaeftigte_auswerten(
        genesis.parse_ffcsv(genesis_gemeinde_ffcsv["beschaeftigte"]),
        "09162000")
    assert b["name"] == "München, kreisfreie Stadt"
    assert b["ebene"] == "kreisfreie Stadt"
    assert b["aktuell"] == {"jahr": 2025, "beschaeftigte": 976230}


def test_beschaeftigte_erwischt_nie_den_landkreis(genesis_gemeinde_ffcsv):
    """Garchings Kreisschlüssel ist 09184 — der KREISE-Rückfall darf für
    eine echte Gemeinde nicht auf den Landkreis durchgreifen, solange
    GEMEIN-Zeilen da sind."""
    rows = genesis.parse_ffcsv(genesis_gemeinde_ffcsv["beschaeftigte"])
    b = genesis.beschaeftigte_auswerten(rows, "09184119")
    # Der Landkreiswert (falls je geliefert) wäre sechsstellig.
    assert b["aktuell"]["beschaeftigte"] == 32823


def test_tourismus_gemeinde_muenchen(genesis_gemeinde_ffcsv):
    t = genesis.tourismus_gemeinde_auswerten(
        genesis.parse_ffcsv(genesis_gemeinde_ffcsv["tourismus"]),
        "09162000")
    assert t["aktuell"]["jahr"] == 2024
    assert t["aktuell"]["uebernachtungen"] == 19712703
    assert t["aktuell"]["ankuenfte"] == 9279239
    assert t["aktuell"]["schlafgelegenheiten"] == 97552
    # 2008 fehlten die Schlafgelegenheiten („-" im ffcsv) → None, nicht 0.
    z2008 = next(r for r in t["reihe"] if r["jahr"] == 2008)
    assert z2008["schlafgelegenheiten"] is None
    assert z2008["uebernachtungen"] == 9847122


def test_arbeitslose_garching(genesis_gemeinde_ffcsv):
    a = genesis.arbeitslose_auswerten(
        genesis.parse_ffcsv(genesis_gemeinde_ffcsv["arbeitslose"]),
        "09184119")
    assert a["aktuell"] == {"jahr": 2025, "arbeitslose": 347}
    # 2001 gab es für Garching keinen Wert („-") → in der Reihe None.
    z2001 = next(r for r in a["reihe"] if r["jahr"] == 2001)
    assert z2001["arbeitslose"] is None


def test_jahr_aus_stichtag_und_jahresangabe():
    assert genesis._jahr("2025-06-30") == 2025
    assert genesis._jahr("2024") == 2024
    assert genesis._jahr("") is None


# ------------------------------------------------------------- Zugang

def test_zugang_datei_und_umgebung(settings, monkeypatch):
    monkeypatch.delenv("GASTROVIEWER_GENESIS_KENNUNG", raising=False)
    monkeypatch.delenv("GASTROVIEWER_GENESIS_PASSWORT", raising=False)
    assert genesis.lade_zugang(settings) is None

    genesis.speichere_zugang(settings, "AB1234", "geheim")
    z = genesis.lade_zugang(settings)
    assert z == {"kennung": "AB1234", "passwort": "geheim", "quelle": "datei"}

    # Umgebungsvariablen gewinnen gegen die Datei.
    monkeypatch.setenv("GASTROVIEWER_GENESIS_KENNUNG", "ENVUSER")
    monkeypatch.setenv("GASTROVIEWER_GENESIS_PASSWORT", "envpass")
    assert genesis.lade_zugang(settings)["quelle"] == "umgebung"

    monkeypatch.delenv("GASTROVIEWER_GENESIS_KENNUNG")
    monkeypatch.delenv("GASTROVIEWER_GENESIS_PASSWORT")
    assert genesis.loesche_zugang(settings) is True
    assert genesis.lade_zugang(settings) is None


# --------------------------------------------------------------- Abruf

class FakePost:
    """Nur post_text — mehr braucht das Modul nicht."""

    def __init__(self, antworten):
        self.antworten = antworten
        self.aufrufe = []

    async def post_text(self, source, url, **kw):
        self.aufrufe.append({"url": url, "headers": kw.get("headers"),
                             "data": kw.get("data")})
        name = (kw.get("data") or {}).get("name")
        if "logincheck" in url:
            return self.antworten["logincheck"]
        return self.antworten[name]


def test_load_ohne_kennung_bleibt_leer_ohne_abruf(settings, monkeypatch):
    monkeypatch.delenv("GASTROVIEWER_GENESIS_KENNUNG", raising=False)
    monkeypatch.delenv("GASTROVIEWER_GENESIS_PASSWORT", raising=False)

    class Nie:
        async def post_text(self, *a, **k):  # pragma: no cover
            raise AssertionError("Ohne Kennung darf nichts hinausgehen.")

    res = asyncio.run(genesis.load(Nie(), settings, "09162000"))
    assert res.ok and res.data is None
    assert any("Opt-in" in w for w in res.warnings)


def _alle_tabellen(genesis_ffcsv, genesis_gemeinde_ffcsv):
    return {
        genesis.TAB_UMSATZ: genesis_ffcsv["umsatz"],
        genesis.TAB_GEWERBE: genesis_ffcsv["gewerbe"],
        genesis.TAB_BESCHAEFTIGTE: genesis_gemeinde_ffcsv["beschaeftigte"],
        genesis.TAB_TOURISMUS_GEMEINDE: genesis_gemeinde_ffcsv["tourismus"],
        genesis.TAB_ARBEITSLOSE_GEMEINDE: genesis_gemeinde_ffcsv["arbeitslose"],
    }


def test_load_mit_kennung_roh_csv(settings, genesis_ffcsv,
                                  genesis_gemeinde_ffcsv):
    genesis.speichere_zugang(settings, "AB1234", "geheim")
    fake = FakePost(_alle_tabellen(genesis_ffcsv, genesis_gemeinde_ffcsv))
    res = asyncio.run(genesis.load(fake, settings, "09162000"))
    assert res.ok
    assert res.data["kreis"] == "München, kreisfreie Stadt"
    assert res.data["umsatz"]["aktuell"]["je_pflichtigem_eur"] == 1638293
    assert res.data["gewerbe"]["aktuell"]["saldo"] == 5105
    # Gemeindewerte: München ist kreisfrei → Kreiszeilen gelten.
    g = res.data["gemeinde"]
    assert g["ebene"] == "kreisfreie Stadt"
    assert g["beschaeftigte"]["aktuell"]["beschaeftigte"] == 976230
    assert g["tourismus"]["aktuell"]["uebernachtungen"] == 19712703
    # Kennung wandert in Header und Body, nie in die URL.
    for a in fake.aufrufe:
        assert "AB1234" not in a["url"] and "geheim" not in a["url"]
        assert a["headers"] == {"username": "AB1234", "password": "geheim"}
        assert a["data"]["regionalkey"] == "09162"
        assert a["data"]["regionalvariable"] == "KREISE"
        assert a["data"]["format"] == "ffcsv"


def test_load_echte_gemeinde_fragt_gemein_ab(settings, genesis_ffcsv,
                                             genesis_gemeinde_ffcsv):
    """Garching (09184119): Kreistabellen laufen über KREISE/09184, die
    Gemeindetabellen über GEMEIN/09184119 — ohne Kreis-Rückfall, weil die
    GEMEIN-Abfrage liefert."""
    genesis.speichere_zugang(settings, "AB1234", "geheim")
    fake = FakePost(_alle_tabellen(genesis_ffcsv, genesis_gemeinde_ffcsv))
    res = asyncio.run(genesis.load(fake, settings, "09184119"))
    assert res.ok
    assert res.data["kreis"] == "München, Landkreis"
    g = res.data["gemeinde"]
    assert g["ebene"] == "Gemeinde"
    assert g["name"] == "Garching b.München, St"
    assert g["beschaeftigte"]["aktuell"]["beschaeftigte"] == 32823
    assert g["arbeitslose"]["aktuell"]["arbeitslose"] == 347
    gemeinde_aufrufe = [a for a in fake.aufrufe
                        if a["data"]["name"] in (
                            genesis.TAB_BESCHAEFTIGTE,
                            genesis.TAB_TOURISMUS_GEMEINDE,
                            genesis.TAB_ARBEITSLOSE_GEMEINDE)]
    assert gemeinde_aufrufe, "Gemeindetabellen wurden nicht abgefragt"
    for a in gemeinde_aufrufe:
        assert a["data"]["regionalvariable"] == "GEMEIN"
        assert a["data"]["regionalkey"] == "09184119"


def test_load_mit_json_umschlag(settings, genesis_ffcsv,
                                genesis_gemeinde_ffcsv):
    """Die REST-Schnittstelle liefert das CSV in ``Object.Content`` — der
    Lader nimmt beide Formen an."""
    genesis.speichere_zugang(settings, "AB1234", "geheim")

    def umschlag(csv_text):
        return json.dumps({"Status": {"Code": 0, "Content": "erfolgreich"},
                           "Object": {"Content": csv_text}})

    tabellen = {name: umschlag(text) for name, text
                in _alle_tabellen(genesis_ffcsv, genesis_gemeinde_ffcsv).items()}
    fake = FakePost(tabellen)
    res = asyncio.run(genesis.load(fake, settings, "09162000"))
    assert res.ok and res.data["umsatz"]["aktuell"]["pflichtige"] == 4019
    assert res.data["gemeinde"]["arbeitslose"]["aktuell"]["jahr"] == 2025


def test_load_fehlerantwort_wird_benannt(settings):
    genesis.speichere_zugang(settings, "AB1234", "geheim")
    fehler = json.dumps({"Status": {"Code": 15, "Content": "Sie sind nicht berechtigt"},
                         "Object": None})
    fake = FakePost({t: fehler for t in (
        genesis.TAB_UMSATZ, genesis.TAB_GEWERBE, genesis.TAB_BESCHAEFTIGTE,
        genesis.TAB_TOURISMUS_GEMEINDE, genesis.TAB_ARBEITSLOSE_GEMEINDE)})
    res = asyncio.run(genesis.load(fake, settings, "09162000"))
    assert not res.ok
    assert "nicht berechtigt" in res.error["message"]


def test_logincheck_unterscheidet_gueltig_und_falsch():
    """Antworttexte am 2026-08-07 live aufgezeichnet."""
    ok_fake = FakePost({"logincheck": json.dumps({
        "Status": "Sie wurden erfolgreich an- und abgemeldet!",
        "Username": "AB1234"})})
    ok, meldung = asyncio.run(genesis.logincheck(
        ok_fake, {"kennung": "AB1234", "passwort": "x"}))
    assert ok and "erfolgreich" in meldung

    falsch_fake = FakePost({"logincheck": json.dumps({
        "Status": "Ein Fehler ist aufgetreten. (Bitte prüfen und korrigieren "
                  "Sie Ihren Nutzernamen bzw.\n das Passwort.)",
        "Username": "XX"})})
    ok, meldung = asyncio.run(genesis.logincheck(
        falsch_fake, {"kennung": "XX", "passwort": "x"}))
    assert not ok and "Fehler" in meldung
