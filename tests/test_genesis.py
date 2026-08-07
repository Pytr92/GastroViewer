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


def test_load_mit_kennung_roh_csv(settings, genesis_ffcsv):
    genesis.speichere_zugang(settings, "AB1234", "geheim")
    fake = FakePost({genesis.TAB_UMSATZ: genesis_ffcsv["umsatz"],
                     genesis.TAB_GEWERBE: genesis_ffcsv["gewerbe"]})
    res = asyncio.run(genesis.load(fake, settings, "09162000"))
    assert res.ok
    assert res.data["kreis"] == "München, kreisfreie Stadt"
    assert res.data["umsatz"]["aktuell"]["je_pflichtigem_eur"] == 1638293
    assert res.data["gewerbe"]["aktuell"]["saldo"] == 5105
    # Kennung wandert in Header und Body, nie in die URL.
    for a in fake.aufrufe:
        assert "AB1234" not in a["url"] and "geheim" not in a["url"]
        assert a["headers"] == {"username": "AB1234", "password": "geheim"}
        assert a["data"]["regionalkey"] == "09162"
        assert a["data"]["regionalvariable"] == "KREISE"
        assert a["data"]["format"] == "ffcsv"


def test_load_mit_json_umschlag(settings, genesis_ffcsv):
    """Die REST-Schnittstelle liefert das CSV in ``Object.Content`` — der
    Lader nimmt beide Formen an."""
    genesis.speichere_zugang(settings, "AB1234", "geheim")

    def umschlag(csv_text):
        return json.dumps({"Status": {"Code": 0, "Content": "erfolgreich"},
                           "Object": {"Content": csv_text}})

    fake = FakePost({genesis.TAB_UMSATZ: umschlag(genesis_ffcsv["umsatz"]),
                     genesis.TAB_GEWERBE: umschlag(genesis_ffcsv["gewerbe"])})
    res = asyncio.run(genesis.load(fake, settings, "09162000"))
    assert res.ok and res.data["umsatz"]["aktuell"]["pflichtige"] == 4019


def test_load_fehlerantwort_wird_benannt(settings):
    genesis.speichere_zugang(settings, "AB1234", "geheim")
    fehler = json.dumps({"Status": {"Code": 15, "Content": "Sie sind nicht berechtigt"},
                         "Object": None})
    fake = FakePost({genesis.TAB_UMSATZ: fehler, genesis.TAB_GEWERBE: fehler})
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
