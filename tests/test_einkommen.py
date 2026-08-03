"""Verfügbares Einkommen (Regionalatlas/VGRdL): Kreisableitung, Jahreswahl.

Die Fixture ist die echte Antwort des Regionalatlas-Servers vom 02.08.2026
für München (Kreis 09162), Bayern (09) und Deutschland (DG).
"""

from __future__ import annotations

import asyncio

from gastroviewer.sources import einkommen


def test_kreis_aus_ags():
    assert einkommen.kreis_aus_ags("09162000") == "09162"
    assert einkommen.kreis_aus_ags("09162") == "09162"
    assert einkommen.kreis_aus_ags(None) is None
    assert einkommen.kreis_aus_ags("091") is None


def test_auswerten_nimmt_das_juengste_gemeinsame_jahr(einkommen_muenchen):
    d = einkommen.auswerten(einkommen_muenchen, "09162", "09")
    assert d is not None
    assert d["jahr"] == 2022
    # Live-Gegenprobe vom 02.08.2026 — deckungsgleich mit den
    # VGRdL-Veröffentlichungen.
    assert d["kreis"]["wert_eur"] == 35467
    assert d["kreis"]["name"] == "München, kreisfreie Stadt"
    assert d["land"]["wert_eur"] == 28643
    assert d["bund"]["wert_eur"] == 25830
    assert d["verlauf_kreis"][-1] == {"jahr": 2022, "wert_eur": 35467}
    assert len(d["verlauf_kreis"]) <= 10


def test_auswerten_ohne_kreiszeile_ergibt_none(einkommen_muenchen):
    assert einkommen.auswerten(einkommen_muenchen, "05315", "05") is None


class FakeOut:
    def __init__(self, payload):
        self.payload = payload
        self.urls: list[str] = []

    async def post_json(self, source, url, *, data=None, **kw):
        self.urls.append(url)
        self.data = data
        return self.payload


def test_load_baut_die_richtige_abfrage(settings, einkommen_muenchen):
    out = FakeOut(einkommen_muenchen)
    res = asyncio.run(einkommen.load(out, settings, "09162000"))
    assert res.ok
    assert "dynamicLayer/query" in out.urls[0]
    assert "ai016_1" in out.data["layer"]
    assert "'09162','09','DG'" in out.data["where"]
    assert res.data["kreis"]["wert_eur"] == 35467
    assert "Berechnungsstand 2022" in res.provenance.stand
    assert "Datenlizenz Deutschland" in res.provenance.license
    assert "Kreiswert" in res.provenance.note, (
        "die Grenze — Kreisebene, keine Viertel — gehört in die Quellenzeile"
    )


def test_load_ohne_ags_ist_eine_ehrliche_leermeldung(settings):
    res = asyncio.run(einkommen.load(FakeOut({}), settings, ""))
    assert res.ok and res.data is None
    assert any("Gemeindeschlüssel" in w for w in res.warnings)
