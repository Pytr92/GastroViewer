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
def geosphere_at():
    """GeoSphere klima-v2-1y: Stationsausschnitt und Jahreswerte 1991–2020 Wien Innere Stadt."""
    wurzel = Path(__file__).resolve().parent.parent / "fixtures" / "at"
    return {"metadata": json.loads((wurzel / "geosphere_klima_v2_1y_metadata_kurz.json").read_text("utf-8")),
            "daten": json.loads((wurzel / "geosphere_klima_v2_1y_wien_1991_2020.json").read_text("utf-8"))}


@pytest.fixture(scope="session")
def laerminfo_at():
    """lärminfo.at OGC-Features: Straßenlärm-Zonen 2022 am Stephansplatz."""
    wurzel = Path(__file__).resolve().parent.parent / "fixtures" / "at"
    return {"lden": json.loads((wurzel / "laerminfo_r2_laerm_2022_strasse_lden_items.json").read_text("utf-8")),
            "lnight": json.loads((wurzel / "laerminfo_r2_laerm_2022_strasse_lnight_items.json").read_text("utf-8"))}


@pytest.fixture(scope="session")
def lfrz_hochwasser_at():
    """LFRZ-Hochwasser GetFeatureInfo: leere Antwort (Stephansplatz)."""
    wurzel = Path(__file__).resolve().parent.parent / "fixtures" / "at"
    return json.loads((wurzel / "hochwasser_gfi_leer.json").read_text("utf-8"))


@pytest.fixture(scope="session")
def wien_wfs():
    """Stadt Wien WFS, live 18.09.2026: Märkte stadtweit, Baustellen um den
    Stephansplatz, Schutzzonen (Ausschnitt) und generalisierte Widmung."""
    wurzel = Path(__file__).resolve().parent.parent / "fixtures" / "at"
    lies = lambda n: json.loads((wurzel / n).read_text("utf-8"))  # noqa: E731
    return {"MAERKTEOGD": lies("wien_maerkteogd.json"),
            "BAUSTELLENPKTOGD": lies("wien_baustellenpktogd.json"),
            "BAUSTELLENLINOGD": lies("wien_baustellenlinienogd.json"),
            # Punktkästen am Stephansplatz (Runde 4): Schutzzone Innere Stadt, GB5.
            "SCHUTZZONEOGD": lies("wien_r4_schutzzoneogd_stephansplatz.json"),
            "GENFLWIDMUNGOGD": lies("wien_r4_genflwidmungogd_stephansplatz.json")}


@pytest.fixture(scope="session")
def wahl_at_dateien():
    """NRW 2024 (BMI, data.gv.at), live 18.09.2026: Ergebnisdatei (cp1252)
    und GKZ-Liste (UTF-8 mit BOM) als Bytes."""
    wurzel = Path(__file__).resolve().parent.parent / "fixtures" / "at"
    return {"ergebnisse": (wurzel / "nrw2024_ergebnisse.txt").read_bytes(),
            "gkz": (wurzel / "nrw2024_gkz.txt").read_bytes()}


@pytest.fixture(scope="session")
def statistik_at():
    """Nächtigungsstatistik, live 18.09.2026: Herkunfts-Klassifikation und
    der Wien-Ausschnitt der Datendatei ab 2018."""
    wurzel = Path(__file__).resolve().parent.parent / "fixtures" / "at"
    return {"herkunft": (wurzel / "stat_OGD_touextsai_Tour_HKL_1_C-C93-2.txt").read_text("utf-8"),
            "daten": (wurzel / "stat_OGD_touextsai_Tour_HKL_1_wien_ab2018.csv").read_text("utf-8"),
            "gemeinde": (wurzel / "stat_OGDEXT_AEST_GEMTAB_1_auszug.csv").read_text("utf-8")}


@pytest.fixture(scope="session")
def nominatim_reverse_wien():
    """Stephansplatz, live am 18.09.2026 (AT-Probe): kein "state", ISO AT-9."""
    return load_fixture("raw_nominatim_reverse_wien.json")


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
def genesis_hebesatz_ffcsv():
    return load_fixture("raw_genesis_hebesatz_ffcsv.json")


@pytest.fixture(scope="session")
def overpass_gebaeude():
    return load_fixture("raw_overpass_gebaeude.json")


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


@pytest.fixture(scope="session")
def genesis_bestand_ffcsv():
    return load_fixture("raw_genesis_bestand_ffcsv.json")


@pytest.fixture(scope="session")
def frequenz_fixture():
    return load_fixture("raw_frequenz.json")


@pytest.fixture(scope="session")
def baurecht_fixture():
    return load_fixture("raw_baurecht.json")


@pytest.fixture(scope="session")
def ihk_berlin_csv():
    return load_fixture("raw_ihk_berlin.json")["csv"]


@pytest.fixture(scope="session")
def kalender_fixture():
    return load_fixture("raw_kalender.json")


@pytest.fixture(scope="session")
def overpass_auto_muenchen():
    """Echtes Autonetz um den Marienplatz (Overpass, 09.08.2026, r=2 200 m).

    Auf die Felder eingedampft, die das Modul liest — roh sind es 1,34 MB.
    """
    import gzip

    pfad = FIXTURES / "raw_overpass_auto_muenchen.json.gz"
    return json.loads(gzip.decompress(pfad.read_bytes()))


def api_routen(app):
    """Alle HTTP-Routen der App, flach — unabhängig davon, ob FastAPI
    eingebundene Router als eigene Einträge in ``app.routes`` führt
    (ab 0.141 ``_IncludedRouter`` mit ``original_router``) oder ihre
    Routen direkt einhängt (ältere Fassungen)."""
    gefunden = []

    def sammeln(routen):
        for r in routen:
            original = getattr(r, "original_router", None)
            if original is not None:
                sammeln(original.routes)
            elif hasattr(r, "endpoint") and hasattr(r, "path"):
                gefunden.append(r)

    sammeln(app.routes)
    return gefunden
