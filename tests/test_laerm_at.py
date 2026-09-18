"""lärminfo.at-Lärmzonen gegen die Live-Antworten der AT-Probe (18.09.2026)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from gastroviewer.sources import laerm_at

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "at"
WIEN = (48.2082, 16.3738)
A23 = (48.1780, 16.4130)


def _lade(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_klassen():
    assert laerm_at.klasse("Lden5559") == {"klasse": "55–59 dB(A)", "von_db": 55, "bis_db": 59}
    assert laerm_at.klasse("LnightGreaterThan70") == {"klasse": "über 70 dB(A)", "von_db": 70, "bis_db": None}
    assert laerm_at.klasse("Lden7074")["von_db"] == 70
    assert laerm_at.klasse("unsinn") is None and laerm_at.klasse(None) is None


def test_zone_am_punkt_aus_echten_polygonen():
    a23 = _lade("laerminfo_r2_strasse_lden_a23.json")
    assert a23["numberMatched"] == 23
    zone = laerm_at.zone_am_punkt(a23["features"], *A23)
    # Fünf Polygone im Kasten, alle Lden5559 — der Punkt liegt in einem davon oder
    # in keinem; beides ist eine belegte Aussage, kein Ratewert.
    if zone is not None:
        assert zone["klasse"] == "55–59 dB(A)" and zone["quelle"] == "majorRoadsIncludingAgglomeration"
    weit_weg = laerm_at.zone_am_punkt(a23["features"], 47.0, 15.0)
    assert weit_weg is None


def test_lauteste_klasse_bei_ueberlappung():
    ring = [[16.0, 48.0], [16.1, 48.0], [16.1, 48.1], [16.0, 48.1], [16.0, 48.0]]
    fs = [{"geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": {"category": "Lden5559", "source": "x"}},
          {"geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": {"category": "Lden6569", "source": "x"}},
          {"geometry": {"type": "MultiPolygon", "coordinates": [[ring]]}, "properties": {"category": "Lden6064", "source": "x"}}]
    assert laerm_at.zone_am_punkt(fs, 48.05, 16.05)["von_db"] == 65
    loch = [[16.04, 48.04], [16.06, 48.04], [16.06, 48.06], [16.04, 48.06], [16.04, 48.04]]
    mit_loch = [{"geometry": {"type": "Polygon", "coordinates": [ring, loch]}, "properties": {"category": "Lden7074"}}]
    assert laerm_at.zone_am_punkt(mit_loch, 48.05, 16.05) is None, "im Loch ist keine Zone"


def test_load_baut_den_laermblock():
    lden = _lade("laerminfo_r2_laerm_2022_strasse_lden_items.json")
    lnight = _lade("laerminfo_r2_laerm_2022_strasse_lnight_items.json")
    gesehen = []

    class Fake:
        async def get_json(self, source, url, params=None, **kw):
            gesehen.append(url)
            if "strasse_lden" in url:
                return lden
            if "strasse_lnight" in url:
                return lnight
            return {"type": "FeatureCollection", "features": []}

    res = asyncio.run(laerm_at.load(Fake(), *WIEN))
    assert res.ok and res.name == "laerm"
    d = res.data
    assert d["dienst"] == "laerminfo" and d["lden"]["kartierung"] == 2022
    assert set(d) >= {"lden", "lnight", "weitere_quellen", "kartiert", "hinweise"}
    assert len(gesehen) == 4 and all("bbox" not in u for u in gesehen)
    assert d["lden"]["wert_db"] is None, "die Karte führt Klassen, keinen Punktwert"
    if d["kartiert"]:
        assert d["lden"]["klasse"] or d["lnight"]["klasse"]
    else:
        assert any("keine kartierte" in h for h in d["hinweise"])
    assert d["weitere_quellen"] == {}, "Schiene ohne Zone am Punkt taucht nicht auf"


def test_totalausfall_ist_ein_fehler():
    from gastroviewer.sources.base import SourceError

    class Kaputt:
        async def get_json(self, *a, **kw):
            raise SourceError("timeout", "Zeitüberschreitung")

    res = asyncio.run(laerm_at.load(Kaputt(), *WIEN))
    assert not res.ok and res.error["kind"] == "api_error"
