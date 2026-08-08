"""OffeneRegister-Import — gegen den echten Auszug des Dumps
de_companies_ocdata.jsonl.bz2 (Stand 05.02.2019, abgerufen 2026-08-08):
517 unveränderte JSONL-Zeilen, erster bz2-Strom der Originaldatei."""

from __future__ import annotations

import asyncio
import bz2

from gastroviewer.sources import register


def test_zeile_parsen_echte_erste_zeile(register_dump_pfad):
    with bz2.open(register_dump_pfad) as fh:
        satz = register.zeile_parsen(fh.readline())
    assert satz == {
        "name": "olly UG (haftungsbeschränkt)",
        "status": "currently registered",
        "plz": "22769",
        "adresse": "Waidmannstraße 1, 22769 Hamburg",
        "register": "Hamburg HRB 150148",
        "gericht": "Hamburg",
        "stand": "2018-11-09",
    }


def test_import_und_auswertung(settings, register_dump_pfad):
    stats = register.import_dump(settings, register_dump_pfad, quelle="fixture")
    assert stats["gesellschaften"] == 517
    assert stats["mit_plz"] == 359
    assert settings.register_db_path.exists()

    d = register.auswerten(settings.register_db_path, "20355")
    assert d["firmen_gesamt"] == 11
    assert d["aktiv_2019"] == 10
    assert d["gastro_gesamt"] == 1
    treffer = d["gastro_auszug"][0]
    assert treffer["name"] == "Restaurant Jungspund GmbH"
    assert treffer["register"] == "Hamburg HRB 134532"
    assert treffer["aktiv_2019"] is True


def test_gastro_muster_mit_wortgrenzen():
    assert register.GASTRO_MUSTER.search("Restaurant Jungspund GmbH")
    assert register.GASTRO_MUSTER.search("Brauerei zum Löwen KG")
    # Keine Scheintreffer: „Barbara" ist keine Bar, „Eisenwerk" keine Eisdiele.
    assert not register.GASTRO_MUSTER.search("Barbara Beteiligungen GmbH")
    assert not register.GASTRO_MUSTER.search("Eisenwerk Nord AG")


def test_load_ohne_import_zeigt_anleitung(settings):
    res = asyncio.run(register.load(settings, "80331"))
    assert res.ok
    assert res.data["importiert"] is False
    assert "import-register" in res.data["anleitung"]


def test_load_mit_datenbank(settings, register_dump_pfad):
    register.import_dump(settings, register_dump_pfad, quelle="fixture")
    res = asyncio.run(register.load(settings, "20355"))
    assert res.ok
    assert res.data["importiert"] is True
    assert res.data["firmen_gesamt"] == 11
    assert any("2019" in h for h in res.data["hinweise"])
    assert "CC BY 4.0" in res.provenance.license


def test_load_ohne_plz_warnt(settings, register_dump_pfad):
    register.import_dump(settings, register_dump_pfad, quelle="fixture")
    res = asyncio.run(register.load(settings, None))
    assert res.ok and res.data is None
    assert any("Postleitzahl" in w for w in res.warnings)
