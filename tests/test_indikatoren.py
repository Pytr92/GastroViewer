"""Indikatorenatlas München — gegen die echten CKAN-/CSV-Daten vom
07.08.2026 (auf die benötigten Ausprägungen und Jahre ab 2010 gekürzt,
Werte unverändert)."""

from __future__ import annotations

import pytest

from gastroviewer.sources import indikatoren
from gastroviewer.sources.base import SourceError


class FakeStadt:
    def __init__(self, data):
        self.data = data
        self.aufrufe = 0

    async def __call__(self):
        self.aufrufe += 1
        return self.data


def test_finde_csv_urls_exakte_titel(muenchen_indikatoren):
    urls, fehlend = indikatoren.finde_csv_urls(muenchen_indikatoren["suche"])
    assert sorted(urls) == sorted(indikatoren.DATEIEN)
    assert fehlend == []
    # Exakter Titelvergleich: „Durchschnittsalter Mütter" darf nicht matchen.
    assert "muetter" not in urls["durchschnittsalter"].lower()


def test_norm_bezirk_beidseitig():
    assert (
        indikatoren.norm_bezirk("01 Altstadt - Lehel")
        == indikatoren.norm_bezirk("Altstadt-Lehel")
        == "altstadtlehel"
    )
    assert indikatoren.norm_bezirk(None) == ""


def test_reduzieren_traegt_sieben_kennzahlen(muenchen_indikatoren):
    kompakt = indikatoren.reduzieren(muenchen_indikatoren["csv"])
    assert sorted(kompakt) == sorted(i["schluessel"] for i in indikatoren.INDIKATOREN)
    # Echte Werte 2025: 54,4 % Einpersonenhaushalte stadtweit, 63,7 % Altstadt.
    assert kompakt["einpersonenhaushalte"]["Stadt München"][-1] == [2025, 54.4]
    assert kompakt["einpersonenhaushalte"]["01 Altstadt - Lehel"][-1] == [2025, 63.7]
    # Arbeitslosen-Anteil reicht nur bis 2024.
    assert kompakt["arbeitslosen_anteil"]["Stadt München"][-1][0] == 2024


def test_auswerten_bezirk_und_trend(muenchen_indikatoren):
    kompakt = indikatoren.reduzieren(muenchen_indikatoren["csv"])
    data = indikatoren.auswerten(kompakt, "Altstadt-Lehel")
    assert data["bezirk"] == "01 Altstadt - Lehel"
    assert len(data["indikatoren"]) == 7
    je = {z["schluessel"]: z for z in data["indikatoren"]}
    jung = je["einpersonen_jung"]["bezirk"]
    assert jung == {"jahr": 2025, "wert": 23.4, "von_jahr": 2020,
                    "von_wert": 21.2, "delta": 2.2}
    assert je["einpersonenhaushalte"]["stadt"]["wert"] == 54.4
    assert je["arbeitslosen_anteil"]["bezirk"]["jahr"] == 2024
    assert len(je["bev_dichte"]["reihe"]) == 12
    assert je["senioren"]["einheit"] == "% der Bevölkerung"


def test_auswerten_ohne_bezirk_bleiben_stadtwerte(muenchen_indikatoren):
    kompakt = indikatoren.reduzieren(muenchen_indikatoren["csv"])
    data = indikatoren.auswerten(kompakt, "Sankt Pauli")
    assert data["bezirk"] is None
    assert all(z["bezirk"] is None for z in data["indikatoren"])
    assert all(z["stadt"] is not None for z in data["indikatoren"])


async def test_load_ausserhalb_muenchens_ohne_abruf(settings):
    stadt = FakeStadt({"kompakt": {}})
    res = await indikatoren.load(None, settings, "Hamburg", "St. Pauli", stadt)
    assert res.ok and res.data is None
    assert stadt.aufrufe == 0
    assert any("Stadt München" in w for w in res.warnings)


async def test_load_muenchen_mit_warnung_bei_fremdem_bezirk(
    settings, muenchen_indikatoren
):
    kompakt = indikatoren.reduzieren(muenchen_indikatoren["csv"])
    stadt = FakeStadt(
        {"kompakt": kompakt, "stand": "Jahresreihen bis 2025",
         "fehlend_warnungen": []}
    )
    res = await indikatoren.load(None, settings, "München", "Nirgendwo", stadt)
    assert res.ok and res.data["bezirk"] is None
    assert stadt.aufrufe == 1
    assert any("nicht eindeutig" in w for w in res.warnings)
    assert res.provenance.stand == "Jahresreihen bis 2025"


async def test_load_reicht_ausfall_weiter(settings):
    async def kaputt():
        raise SourceError("api_error", "Portal nicht erreichbar")

    res = await indikatoren.load(None, settings, "München", "Laim", kaputt)
    assert not res.ok
    assert res.error["kind"] == "api_error"


def test_trend_faellt_auf_fruehestes_jahr_zurueck():
    t = indikatoren._trend([[2023, 10.0], [2024, 11.0], [2025, 12.5]])
    assert t == {"jahr": 2025, "wert": 12.5, "von_jahr": 2023,
                 "von_wert": 10.0, "delta": 2.5}
    assert indikatoren._trend([]) is None
    einzeln = indikatoren._trend([[2025, 5.0]])
    assert einzeln["delta"] is None
