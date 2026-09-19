"""Der Kontrakt-Check selbst: die Nachfolger-Erkennung und die Vollzähligkeit
der geprüften Verträge.

Das Skript läuft monatlich mit Netz (``.github/workflows/kontrakt-check.yml``)
und ist deshalb nicht Teil der Suite. Was hier geprüft wird, ist seine
Logik — und vor allem, dass jede Quelle, die im Betrieb eine feste Kennung
beim Anbieter annimmt, auch wirklich gegengeprüft wird. Eine neue Quelle
ohne Vertrag fällt hier auf, nicht erst, wenn ihr Block leer bleibt.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent


def _modul():
    spec = importlib.util.spec_from_file_location("kontrakt_check", WURZEL / "scripts" / "kontrakt_check.py")
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


@pytest.fixture(scope="module")
def kc():
    return _modul()


def test_jahr_aus_kennung(kc):
    assert kc._jahr("verkehrsmengen_dtv_hvs_2019") == 2019
    assert kc._jahr("REALNUT2022OGD") == 2022
    assert kc._jahr("SVZ-Zaehlstellen_2026-06-26_augmented_SVZ2024.csv") == 2026
    assert kc._jahr("charge_points") is None
    # Vierstellige Zahlen, die kein Jahr sind, bleiben außen vor.
    assert kc._jahr("Zaehlstellen2019HR") == 2019 and kc._jahr("abc12345") is None


def test_neuere_fassung_nur_bei_gleichem_rumpf(kc):
    vorhanden = ["verkehrsmengen_dtv_hvs_2019", "verkehrsmengen_dtv_hvs_2023",
                 "verkehrsmengen_dtv_bab_2021", "verkehrsmengen_dtvw_hvs_2014"]
    assert kc._neuere_fassung(vorhanden, "verkehrsmengen_dtv_hvs_2019") == "verkehrsmengen_dtv_hvs_2023"
    # Ein anderer Datensatz mit jüngerem Jahr ist kein Nachfolger.
    assert kc._neuere_fassung(["verkehrsmengen_dtv_bab_2021"], "verkehrsmengen_dtv_hvs_2019") is None
    # Ohne Jahr in der eigenen Kennung gibt es nichts zu vergleichen.
    assert kc._neuere_fassung(["charge_points_2030"], "charge_points") is None
    # Das jüngste gewinnt, nicht das erste.
    assert kc._neuere_fassung(["REALNUT2022OGD", "REALNUT2024OGD", "REALNUT2023OGD"],
                              "REALNUT2022OGD") == "REALNUT2024OGD"


def test_fehlend_meldet_verschwundenes_und_ueberholtes(kc):
    befunde = kc._fehlend("Test", ["a_2019", "a_2023", "b"], {"a_2019": "modul.fn", "c": "modul.fn2"})
    assert len(befunde) == 2
    assert any("überholt" in b and "a_2023" in b for b in befunde)
    assert any("nicht mehr im Dienst" in b and "'c'" in b for b in befunde)
    assert not kc._fehlend("Test", ["b"], {"b": "modul.fn"})


def test_jede_feste_fremdkennung_hat_einen_vertrag(kc):
    """Der eigentliche Wächter: Für jede Quelle mit fester Kennung beim
    Anbieter muss eine Prüfung existieren. Neue Quellen ohne Vertrag fallen
    hier auf."""
    namen = " ".join(name for name, _ in kc.PRUEFUNGEN)
    for pflicht in ("Zensus", "Wien", "Salzburg", "Berlin", "Hamburg", "MobiData",
                    "Stuttgart", "Starkregen", "Statistik Austria", "DWD", "München"):
        assert pflicht in namen, f"kein Vertrag geprüft für {pflicht}"
    assert len(kc.PRUEFUNGEN) >= 12
    assert all(callable(fn) for _, fn in kc.PRUEFUNGEN)


def test_geprueft_werden_die_kennungen_aus_den_modulen(kc):
    """Die Prüfungen lesen die Kennungen aus den Quellmodulen, nicht aus
    einer zweiten Liste — sonst laufen beide auseinander."""
    quelle = (WURZEL / "scripts" / "kontrakt_check.py").read_text("utf-8")
    for ausdruck in ("berlin.VM_WFS_URL", "berlin.VM_JAHR", "hamburg.OAF_BASE",
                     "mobidata_bw.SVZ_URL", "mobidata_bw.ECO_URL", "mobidata_bw.STUTTGART_TYP",
                     "wien.WFS_URL", "wien_verkehr.KFZ_CSV_URL", "wien_profil.ZB_CSV_URL",
                     "salzburg.WFS_URL", "starkregen.SZENARIEN", "gemeinde_at.GEODATA_GEM_TYP",
                     "immobilien_at.JAHRE", "immobilien_at.DATEIEN"):
        assert ausdruck in quelle, f"{ausdruck} wird nicht aus dem Modul gelesen"
