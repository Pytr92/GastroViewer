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
