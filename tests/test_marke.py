"""Gebietsschutz-Check: Basisabfrage, Markenfilter, Ehrlichkeit.

Der erste Entwurf filterte per Regex auf dem Overpass-Server und lief bei
10 km um den Marienplatz in den Timeout. Deshalb: Basis ohne Markenfilter
(indizierbar, markenunabhängig cachebar), Markensuche als reine Rechnung.
"""

from __future__ import annotations

import asyncio

from gastroviewer.sources import marke

LAT, LON = 48.1334, 11.5674


def test_basisabfrage_hat_keinen_regex_auf_marke_oder_name():
    """Regex auf brand/name kann Overpass nicht indizieren — bei 10 km lief
    das in den 60-Sekunden-Timeout (gemessen 02.08.2026)."""
    q = marke.basis_query(LAT, LON, 10000)
    assert '"brand"' not in q and '"name"' not in q
    assert '"amenity"~' in q and "around:10000" in q


class FakeOut:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    async def post_json(self, source, url, **kw):
        self.calls += 1
        return self.payload


def _erste_marke(overpass_combined) -> str:
    from gastroviewer.sources.overpass import GASTRO_AMENITIES

    for el in overpass_combined["elements"]:
        tags = el.get("tags") or {}
        if tags.get("amenity") in GASTRO_AMENITIES and tags.get("brand"):
            return tags["brand"]
    raise AssertionError("Fixture ohne Kettenbetrieb — unerwartet für die Innenstadt")


def _basis(settings, payload):
    settings.overpass_endpoints = ("https://overpass-api.de/api/interpreter",)
    return asyncio.run(marke.load_basis(FakeOut(payload), settings, LAT, LON, 10000))


def test_basis_reduziert_auf_das_noetige(settings, overpass_combined):
    basis = _basis(settings, overpass_combined)
    assert basis.ok and basis.data["anzahl"] > 100
    b = basis.data["betriebe"][0]
    assert set(b) == {"name", "marke", "typ", "lat", "lon", "osm_url"}, (
        "volle Tag-Sätze wären im Cache nur Ballast"
    )
    assert "ODbL" in basis.provenance.license


def test_suche_findet_marke_und_sortiert_nach_entfernung(settings, overpass_combined):
    gesucht = _erste_marke(overpass_combined)
    basis = _basis(settings, overpass_combined)
    res = marke.suche(basis, gesucht, LAT, LON, 10000)

    assert res.ok and res.name == "marke"
    d = res.data
    assert d["anzahl"] > 0
    assert d["naechster_m"] == d["treffer"][0]["distanz_m"]
    assert d["treffer"] == sorted(d["treffer"], key=lambda t: t["distanz_m"])
    for t in d["treffer"]:
        text = f"{t.get('marke') or ''} {t.get('name') or ''}".lower()
        assert gesucht.lower() in text, f"Treffer ohne Markenbezug: {t}"
    assert any("Vertrag" in h for h in d["hinweise"]), (
        "der Hinweis fehlt, dass der Gebietsschutz im Vertrag steht, nicht auf der Karte"
    )


def test_ohne_treffer_ist_kein_beleg_fuer_freies_gebiet(settings, overpass_combined):
    basis = _basis(settings, overpass_combined)
    res = marke.suche(basis, "Xyzzy Grill", LAT, LON, 10000)
    assert res.ok
    assert res.data["anzahl"] == 0 and res.data["naechster_m"] is None
    assert any("kein Beleg" in w for w in res.warnings), (
        "null Treffer müssen als OSM-Aussage markiert sein, nicht als freies Gebiet"
    )


def test_namensgleiche_treffer_werden_markiert(settings):
    payload = {"elements": [
        {"type": "node", "id": 1, "lat": LAT + 0.001, "lon": LON,
         "tags": {"amenity": "fast_food", "name": "Adler Grill",
                  "brand": "Adler Grill"}},
        # Gleicher Name, aber kein brand-Tag — vermutlich ein Einzelbetrieb.
        {"type": "node", "id": 2, "lat": LAT + 0.002, "lon": LON,
         "tags": {"amenity": "restaurant", "name": "Gasthof Adler Grill"}},
        # Kein Gastro-Tag — gehört nicht in die Basis.
        {"type": "node", "id": 3, "lat": LAT + 0.003, "lon": LON,
         "tags": {"shop": "kiosk", "name": "Adler Grill Kiosk"}},
    ]}
    basis = _basis(settings, payload)
    assert basis.data["anzahl"] == 2
    res = marke.suche(basis, "Adler Grill", LAT, LON, 5000)
    d = res.data
    assert d["anzahl"] == 2
    je_name = {t["name"]: t for t in d["treffer"]}
    assert je_name["Adler Grill"]["nur_namensgleich"] is False
    assert je_name["Gasthof Adler Grill"]["nur_namensgleich"] is True
