"""Gemeinsame Testbasis.

Spec §10: Tests laufen gegen die in Phase 0 aufgezeichneten **echten** Antworten
(``fixtures/``), nicht gegen ausgedachte. Genau daran ist der Vorgänger gescheitert.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load_fixture(name: str):
    with open(FIXTURES / name, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="session")
def zensus_600():
    return load_fixture("raw_zensus_600.json")


@pytest.fixture(scope="session")
def zensus_meta():
    return load_fixture("raw_zensus_meta.json")


@pytest.fixture(scope="session")
def zensus_exceeded():
    return load_fixture("zensus_r3000_exceeded.json")


@pytest.fixture(scope="session")
def zensus_offset():
    return load_fixture("zensus_r3000_offset2000.json")


@pytest.fixture(scope="session")
def overpass_combined():
    return load_fixture("raw_overpass_combined.json")


@pytest.fixture(scope="session")
def overpass_routes():
    return load_fixture("raw_overpass_routes.json")


@pytest.fixture(scope="session")
def nominatim_search():
    return load_fixture("raw_nominatim_search.json")


@pytest.fixture(scope="session")
def nominatim_reverse():
    return load_fixture("raw_nominatim_reverse.json")


@pytest.fixture(scope="session")
def einkommen_muenchen():
    return load_fixture("raw_einkommen_muenchen.json")


@pytest.fixture()
def kreisprofil_muenchen():
    return load_fixture("raw_kreisprofil_muenchen.json")


@pytest.fixture()
def dwd_klima():
    return load_fixture("raw_dwd_klima.json")


@pytest.fixture()
def pendler_muenchen():
    return load_fixture("raw_pendler_muenchen.json")


@pytest.fixture()
def ohsome_dynamik():
    return load_fixture("raw_ohsome_dynamik.json")


@pytest.fixture()
def settings(tmp_path):
    from gastroviewer.config import Settings

    s = Settings()
    s.data_dir = tmp_path
    return s


@pytest.fixture()
def muenchen_rad_tage():
    return load_fixture("raw_muenchen_rad_tage.json")


@pytest.fixture()
def laerm_bayern():
    return load_fixture("raw_laerm_bayern.json")


@pytest.fixture(scope="session")
def muenchen_baustellen():
    return load_fixture("raw_muenchen_baustellen.json")


@pytest.fixture(scope="session")
def muenchen_indikatoren():
    return load_fixture("raw_muenchen_indikatoren.json")


@pytest.fixture(scope="session")
def muenchen_maerkte():
    return load_fixture("raw_muenchen_maerkte.json")


@pytest.fixture(scope="session")
def airbnb_muenchen():
    return load_fixture("raw_airbnb_muenchen.json")


@pytest.fixture(scope="session")
def genesis_ffcsv():
    return load_fixture("raw_genesis_ffcsv.json")


@pytest.fixture(scope="session")
def genesis_gemeinde_ffcsv():
    return load_fixture("raw_genesis_gemeinde_ffcsv.json")


@pytest.fixture(scope="session")
def genesis_bau_ffcsv():
    return load_fixture("raw_genesis_bau_ffcsv.json")


@pytest.fixture(scope="session")
def uba_luft_api():
    return load_fixture("raw_uba_luft_api.json")


@pytest.fixture(scope="session")
def wahl_btw25():
    return load_fixture("raw_wahl_btw25.json")


@pytest.fixture(scope="session")
def uba_laerm():
    return load_fixture("raw_uba_laerm.json")


@pytest.fixture(scope="session")
def bfg_hochwasser():
    return load_fixture("raw_bfg_hochwasser.json")


@pytest.fixture(scope="session")
def bast_jawe():
    return load_fixture("raw_bast_jawe2024.json")


@pytest.fixture(scope="session")
def hamburg_stadt():
    return load_fixture("raw_hamburg_stadt.json")


@pytest.fixture(scope="session")
def berlin_baustellen():
    return load_fixture("raw_berlin_baustellen.json")


@pytest.fixture(scope="session")
def photon():
    return load_fixture("raw_photon.json")


@pytest.fixture(scope="session")
def pks_auszug():
    """Echter Auszug der BKA-Kreistabelle 2024 (Download 2026-08-08, 2,1 MB,
    16 809 Zeilen) — reduziert auf Kopfzeilen, alle 400 Gesamtzeilen und die
    kompletten 41 Delikte für München (09162), Köln (05315) und Flensburg
    (01001). sharedStrings und Zellwerte unverändert."""
    with open(FIXTURES / "raw_pks2024_auszug.xlsx", "rb") as fh:
        return fh.read()


@pytest.fixture(scope="session")
def lsm_places():
    return load_fixture("raw_leerstandsmelder.json")


@pytest.fixture(scope="session")
def register_dump_pfad():
    """Echter Auszug des OffeneRegister-Dumps (erster bz2-Strom der Datei
    vom 05.02.2019, abgerufen 2026-08-08): 517 vollständige JSONL-Zeilen,
    unverändert, neu komprimiert."""
    return FIXTURES / "raw_offeneregister_auszug.jsonl.bz2"


@pytest.fixture(scope="session")
def overture_mira():
    return load_fixture("raw_overture_mira.geojson")


@pytest.fixture(scope="session")
def overture_marienplatz():
    return load_fixture("raw_overture_marienplatz.geojson")


@pytest.fixture(scope="session")
def messe_muenchen():
    return load_fixture("raw_muenchen_messe.json")


@pytest.fixture(scope="session")
def tourismus_muenchen():
    return load_fixture("raw_muenchen_tourismus.json")


@pytest.fixture(scope="session")
def erhaltungssatzung_haidhausen():
    return load_fixture("raw_muenchen_erhaltungssatzung.json")
