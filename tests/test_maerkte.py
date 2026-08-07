"""Städtische Märkte München — gegen die echte WFS-Antwort vom 07.08.2026
(54 Punkte, unverändert)."""

from __future__ import annotations

from gastroviewer.sources import maerkte

MARIENPLATZ = (48.1374, 11.5755)


class FakeOut:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    async def get_json(self, source, url, params=None, **kw):
        self.calls += 1
        return self.payload


def test_name_und_zeiten_trennung():
    name, zeiten = maerkte.name_und_zeiten(
        "Wochenmarkt Messestadt Riem, Öffnungszeiten: Freitag, 10:00 - 18:00"
    )
    assert name == "Wochenmarkt Messestadt Riem"
    assert zeiten == "Freitag, 10:00 - 18:00"
    # Der Viktualienmarkt hat im Datensatz keine Zeiten — dann ehrlich None.
    assert maerkte.name_und_zeiten("Viktualienmarkt") == ("Viktualienmarkt", None)
    assert maerkte.name_und_zeiten(None) == (None, None)


def test_aufbereiten_marienplatz(muenchen_maerkte):
    d = maerkte.aufbereiten(muenchen_maerkte["features"], *MARIENPLATZ, 600)
    assert d["stadtweit"] == 54
    assert len(d["in_reichweite"]) == 8
    assert d["im_radius"] == 2
    assert d["naechster"]["name"] == "Viktualienmarkt"
    assert d["naechster"]["rubrik"] == "Ständiger Markt"
    assert d["naechster"]["distanz_m"] == 265
    assert d["nach_rubrik"] == {
        "Ständiger Markt": 3, "Bauernmarkt": 3, "Wochenmarkt": 2
    }
    # Wochenmarkt-Eintrag trägt seine Zeiten aus dem Datensatz.
    au = next(m for m in d["in_reichweite"] if m["name"] == "Wochenmarkt Au")
    assert au["oeffnungszeiten"] and "07:00" in au["oeffnungszeiten"]


async def test_load_muenchen(settings, muenchen_maerkte):
    out = FakeOut(muenchen_maerkte)
    res = await maerkte.load(out, settings, *MARIENPLATZ, 600)
    assert res.ok and res.data["stadtweit"] == 54
    assert res.data["hinweise"]
    assert "GeodatenService" in res.provenance.source


async def test_load_ausserhalb_ohne_anfrage(settings, muenchen_maerkte):
    out = FakeOut(muenchen_maerkte)
    res = await maerkte.load(out, settings, 52.52, 13.40, 600)
    assert res.ok and res.data is None
    assert out.calls == 0
    assert any("Stadt München" in w for w in res.warnings)
