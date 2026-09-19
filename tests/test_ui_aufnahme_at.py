"""Wien in der Browserprüfung: Die Antworten, die die Oberfläche für den
Stephansplatz bekommt — aus der echten Anwendung über die aufgezeichneten
Live-Antworten der österreichischen Dienste (fixtures/at).

Die Attrappe (``scripts/attrappe.py``) spielt sie zusammen mit der
deutschen Aufzeichnung ab; ``scripts/uitest.py`` prüft daran, dass die
Oberfläche einen Wiener Punkt richtig zeigt. Aufgezeichnet wird nur mit
``GV_AUFNAHME_AT=1`` — ohne die Umgebungsvariable prüft der Test bloß, dass
jeder Pfad antwortet und die Aufzeichnung dem entspricht, was die Anwendung
heute liefert."""

from __future__ import annotations

import gzip
import importlib.util
import json
import os
from pathlib import Path

from tests.test_api import FakeOutbound, client  # noqa: F401 — die App-Fabrik der API-Tests

WURZEL = Path(__file__).resolve().parent.parent
ZIEL = WURZEL / "tests" / "fixtures" / "ui" / "api-antworten-at.json.gz"
WIEN = (48.2082, 16.3738)
RADIUS = 600


def _aufzeichnen_modul():
    spec = importlib.util.spec_from_file_location("gv_aufzeichnen", WURZEL / "scripts" / "aufzeichnen.py")
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def test_wiener_antworten_fuer_die_oberflaeche(client, zensus_600, overpass_combined,
                                                nominatim_reverse_wien, geosphere_at, laerminfo_at,
                                                lfrz_hochwasser_at, wien_wfs, wahl_at_dateien,
                                                statistik_at, wien_zb_csv, geodata_stephansplatz,
                                                immobilien_ods):
    az = _aufzeichnen_modul()
    fake = FakeOutbound(zensus_600, overpass_combined, nominatim_reverse_wien,
                        geosphere=geosphere_at, laerminfo=laerminfo_at,
                        lfrz=lfrz_hochwasser_at, wien=wien_wfs,
                        wahl_at=wahl_at_dateien, statistik_at=statistik_at,
                        wien_csv=wien_zb_csv, geodata=geodata_stephansplatz,
                        immobilien=immobilien_ods)
    lat, lon = WIEN
    aufnahme: dict[str, dict] = {}
    with client.make(fake) as c2:
        def merke(pfad: str, params: dict):
            r = c2.get(pfad, params={k: v for k, v in params.items() if v not in (None, "")})
            assert r.status_code == 200, (pfad, r.text[:200])
            aufnahme[az.schluessel(pfad, params)] = {"status": r.status_code, "json": r.json()}
            return r.json()

        punkt = merke("/api/point", {"lat": lat, "lon": lon, "r": RADIUS})
        assert punkt["punkt"]["land"] == "AT"
        for pfad in az.PUNKT_PFADE_MIT_RADIUS:
            merke(pfad, {"lat": lat, "lon": lon, "r": RADIUS})
        for pfad in az.PUNKT_PFADE_OHNE_RADIUS:
            merke(pfad, {"lat": lat, "lon": lon})
        merke("/api/point/laerm", {"lat": lat, "lon": lon})
        merke("/api/kalender", {"lat": lat, "lon": lon})
        merke("/api/wahl", {"lat": lat, "lon": lon})
        merke("/api/kreisprofil", {"lat": lat, "lon": lon})
        merke("/api/point/links", {"lat": lat, "lon": lon, "r": RADIUS})
        plz = (punkt["bloecke"]["adresse"].get("data") or {}).get("plz")
        merke("/api/register", {"plz": plz or ""})

    if os.environ.get("GV_AUFNAHME_AT"):
        ZIEL.parent.mkdir(parents=True, exist_ok=True)
        roh = json.dumps(aufnahme, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
        ZIEL.write_bytes(gzip.compress(roh, compresslevel=9, mtime=0))
    else:
        assert ZIEL.exists(), "Aufzeichnung fehlt — GV_AUFNAHME_AT=1 pytest tests/test_ui_aufnahme_at.py"
        alt = json.loads(gzip.decompress(ZIEL.read_bytes()))
        assert set(alt) == set(aufnahme), "Pfade der Wiener Aufzeichnung haben sich geändert"
        for k, wert in aufnahme.items():
            # Zeitstempel und Laufzeiten ändern sich, die Blockform nicht.
            assert _form(wert["json"]) == _form(alt[k]["json"]), k


def _form(o):
    if isinstance(o, dict):
        return {k: _form(v) for k, v in sorted(o.items())
                if k not in ("retrieved_at", "duration_ms", "erzeugt", "dauer_ms", "stand",
                             "outbound_requests", "generated_at")}
    if isinstance(o, list):
        return [_form(x) for x in o[:3]]
    return type(o).__name__
