"""API-Ebene: Cache-Wirkung, Ausfallverhalten, Export, Vergleich.

Alle Antworten stammen aus den Phase-0-Fixtures; es geht kein Aufruf ins Netz.
Der Ersatz sitzt bewusst auf ``Outbound.request``-Ebene, damit Cache-Logik,
Rate-Limiter und Fehlerpfade mitgetestet werden statt umgangen zu werden.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from gastroviewer.api import create_app, point_to_csv
from gastroviewer.sources.base import SourceError

LAT, LON, R = 48.1334, 11.5674, 600


class FakeOutbound:
    """Ersetzt nur die Netz-Ebene und zählt die Aufrufe."""

    def __init__(self, zensus, overpass, nominatim, fehler: set[str] | None = None):
        self.zensus = zensus
        self.overpass = overpass
        self.nominatim = nominatim
        self.fehler = fehler or set()
        self.calls: list[str] = []

    def _dispatch(self, url: str):
        if "arcgis" in url:
            self.calls.append("zensus")
            if "zensus" in self.fehler:
                raise SourceError("timeout", "Zeitüberschreitung — Dienst antwortet nicht.")
            return self.zensus
        if "interpreter" in url:
            self.calls.append("overpass")
            if "overpass" in self.fehler:
                raise SourceError("http_status", "HTTP 504 — der Dienst hat abgebrochen.")
            return self.overpass
        if "nominatim" in url:
            self.calls.append("nominatim")
            if "nominatim" in self.fehler:
                raise SourceError("http_status", "HTTP 403 — Zugriff abgelehnt.")
            return self.nominatim
        raise AssertionError(f"unerwartete URL: {url}")

    async def start(self):
        pass

    async def aclose(self):
        pass

    async def get_json(self, source, url, **kw):
        return self._dispatch(url)

    async def post_json(self, source, url, **kw):
        return self._dispatch(url)

    class _Lim:
        @staticmethod
        def stats():
            return {}

    limiters = _Lim()


@pytest.fixture()
def client(tmp_path, monkeypatch, zensus_600, overpass_combined, nominatim_reverse):
    from gastroviewer.config import Settings

    settings = Settings()
    settings.data_dir = tmp_path
    settings.overpass_endpoints = ("https://overpass-api.de/api/interpreter",)

    fake = FakeOutbound(zensus_600, overpass_combined, nominatim_reverse)
    app = create_app(settings)

    original_lifespan_state = {}

    def make_client(fake_outbound=fake):
        import gastroviewer.api as api_mod

        monkeypatch.setattr(api_mod, "Outbound", lambda *a, **k: fake_outbound)
        return TestClient(create_app(settings))

    original_lifespan_state["make"] = make_client
    c = make_client()
    c.fake = fake  # type: ignore[attr-defined]
    c.make = make_client  # type: ignore[attr-defined]
    c.settings = settings  # type: ignore[attr-defined]
    with c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "gastroviewer/" in body["user_agent"], "User-Agent muss identifizieren"
    assert body["gtfs"]["importiert"] is False


def test_point_liefert_zensus_und_osm(client):
    r = client.get("/api/point", params={"lat": LAT, "lon": LON, "r": R})
    assert r.status_code == 200
    d = r.json()
    assert d["bloecke"]["zensus"]["ok"] and d["bloecke"]["osm"]["ok"]
    assert d["punkt"]["ags"] == "09162000"
    assert d["punkt"]["bundesland"] == "Bayern"
    assert d["bloecke"]["zensus"]["data"]["zellen_gefunden"] == 118
    assert d["bloecke"]["osm"]["data"]["zusammenfassung"]["gastronomie"]["gesamt"] > 100


def test_jeder_block_nennt_quelle_stand_lizenz(client):
    d = client.get("/api/point", params={"lat": LAT, "lon": LON, "r": R}).json()
    for name in ("adresse", "zensus", "osm"):
        p = d["bloecke"][name]["provenance"]
        assert p and p.get("source") and p.get("license"), f"{name} ohne Quellenangabe"
    assert "ODbL" in d["bloecke"]["osm"]["provenance"]["license"]
    assert "Statistische Ämter" in d["bloecke"]["zensus"]["provenance"]["license"]
    assert "15.05.2022" in d["bloecke"]["zensus"]["provenance"]["stand"]


def test_zweiter_aufruf_erzeugt_keinen_outbound_traffic(client):
    """Abnahmekriterium §7."""
    client.get("/api/point", params={"lat": LAT, "lon": LON, "r": R})
    vorher = len(client.fake.calls)
    assert vorher == 3

    d = client.get("/api/point", params={"lat": LAT, "lon": LON, "r": R}).json()
    assert len(client.fake.calls) == vorher, "Cache hat nicht gegriffen"
    assert d["meta"]["outbound_requests"] == 0
    assert d["meta"]["aus_cache"] is True
    assert d["bloecke"]["zensus"]["provenance"]["cached"] is True


def test_refresh_umgeht_den_cache(client):
    client.get("/api/point", params={"lat": LAT, "lon": LON, "r": R})
    vorher = len(client.fake.calls)
    client.get("/api/point", params={"lat": LAT, "lon": LON, "r": R, "refresh": "true"})
    assert len(client.fake.calls) > vorher


def test_ausfall_einer_quelle_bricht_die_seite_nicht(client, tmp_path, zensus_600,
                                                    overpass_combined, nominatim_reverse):
    """Abnahmekriterium §7: die übrigen Blöcke laufen weiter."""
    kaputt = FakeOutbound(zensus_600, overpass_combined, nominatim_reverse,
                          fehler={"overpass"})
    c2 = client.make(kaputt)
    with c2:
        r = c2.get("/api/point", params={"lat": LAT, "lon": LON, "r": R})
    assert r.status_code == 200
    d = r.json()
    assert d["bloecke"]["osm"]["ok"] is False
    assert d["bloecke"]["osm"]["error"]["kind"] == "http_status"
    assert "504" in d["bloecke"]["osm"]["error"]["message"]
    # ... und die übrigen Blöcke sind trotzdem da:
    assert d["bloecke"]["zensus"]["ok"] is True
    assert d["bloecke"]["zensus"]["data"]["zellen_gefunden"] == 118
    assert d["punkt"]["gemeinde"] == "München"


def test_fehlerhafte_quelle_wird_nicht_gecacht(client, zensus_600, overpass_combined,
                                               nominatim_reverse):
    kaputt = FakeOutbound(zensus_600, overpass_combined, nominatim_reverse,
                          fehler={"overpass"})
    c2 = client.make(kaputt)
    with c2:
        c2.get("/api/point", params={"lat": LAT, "lon": LON, "r": R})
        n1 = kaputt.calls.count("overpass")
        c2.get("/api/point", params={"lat": LAT, "lon": LON, "r": R})
        assert kaputt.calls.count("overpass") > n1, "Fehler darf nicht zwischengespeichert werden"


def test_grenzen_stehen_in_der_antwort(client):
    d = client.get("/api/point", params={"lat": LAT, "lon": LON, "r": R}).json()
    text = " ".join(d["grenzen"])
    assert "Untergrenze" in text
    assert "15.05.2022" in text
    assert "Passantenströme" in text


def test_bodenrichtwerte_bayern_bekommt_suchlink_statt_geratener_url(client):
    d = client.get("/api/point", params={"lat": LAT, "lon": LON, "r": R}).json()
    b = d["bodenrichtwerte"]
    assert b["bundesland"] == "Bayern"
    assert "nicht in BORIS-D" in b["hinweis"]
    assert any("Suchlink" in link["status"] for link in b["links"])


def test_weiterfuehrende_links_sind_vorbefuellt(client):
    d = client.get("/api/point", params={"lat": LAT, "lon": LON, "r": R}).json()
    gruppen = {g["gruppe"]: g for g in d["weiterfuehrend"]}
    assert "Passantenfrequenz" in gruppen
    hystreet = gruppen["Passantenfrequenz"]["eintraege"][0]
    assert "gewerbliche Nutzung untersagt" in hystreet["warnung"]
    wettbewerb = gruppen["Wettbewerb & Frequenz vor Ort"]["eintraege"][0]
    assert wettbewerb["url"].startswith("https://overpass-turbo.eu/?Q=")


def test_koordinaten_ausserhalb_deutschlands_werden_abgelehnt(client):
    r = client.get("/api/point", params={"lat": 40.7, "lon": -74.0, "r": 600})
    assert r.status_code == 422
    assert "Deutschland" in r.json()["detail"]


def test_unsinniger_radius_wird_abgelehnt(client):
    assert client.get("/api/point", params={"lat": LAT, "lon": LON, "r": 0}).status_code == 422
    assert client.get("/api/point", params={"lat": LAT, "lon": LON, "r": 99999}).status_code == 422


def test_einzelne_quellen_endpunkte(client):
    for pfad in ("zensus", "osm", "adresse", "gtfs"):
        r = client.get(f"/api/point/{pfad}", params={"lat": LAT, "lon": LON, "r": R})
        assert r.status_code == 200, pfad
        assert r.json()["ok"] is True, pfad


def test_gtfs_ohne_import_meldet_das_und_faellt_nicht_aus(client):
    d = client.get("/api/point/gtfs", params={"lat": LAT, "lon": LON, "r": R}).json()
    assert d["ok"] is True
    assert d["data"] is None
    assert "import-gtfs" in d["warnings"][0]


# --------------------------------------------------------------- Vergleich


def test_punkt_merken_und_vergleichen(client):
    r = client.post("/api/points", json={"label": "Kandidat A", "lat": LAT, "lon": LON,
                                         "radius": R})
    assert r.status_code == 200
    r2 = client.post("/api/points", json={"label": "Kandidat B", "lat": 48.1078,
                                          "lon": 11.5470, "radius": R})
    assert r2.status_code == 200

    v = client.get("/api/points/vergleich").json()
    assert len(v["zeilen"]) == 2
    keys = {c["key"] for c in v["spalten"]}
    for pflicht in ("einwohner", "miete_qm", "gastro_gesamt", "haltestellen", "erzeugt"):
        assert pflicht in keys
    zeile = v["zeilen"][0]
    assert zeile["label"] == "Kandidat A"
    assert zeile["einwohner"] == 16370.0

    pid = r.json()["id"]
    assert client.delete(f"/api/points/{pid}").status_code == 200
    assert client.delete(f"/api/points/{pid}").status_code == 404


def test_gemerkter_punkt_speichert_keine_rohzellen(client):
    """Sonst wächst die Datei je Punkt um Hunderte Kilobyte."""
    client.post("/api/points", json={"label": "A", "lat": LAT, "lon": LON, "radius": R})
    rows = client.get("/api/points").json()["punkte"]
    z = rows[0]["payload"]["bloecke"]["zensus"]["data"]
    assert "zellen" not in z
    assert z["zellen_gefunden"] == 118, "Kennzahlen müssen erhalten bleiben"


# ------------------------------------------------------------------ Export


def test_export_json_traegt_zeitstempel_und_quellen(client):
    r = client.get("/api/export/point.json", params={"lat": LAT, "lon": LON, "r": R})
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    d = json.loads(r.text)
    assert d["meta"]["erzeugt"]
    assert d["bloecke"]["zensus"]["provenance"]["license"]


def test_export_csv_hat_je_zeile_quelle_und_stand(client):
    r = client.get("/api/export/point.csv", params={"lat": LAT, "lon": LON, "r": R})
    assert r.status_code == 200
    zeilen = r.text.strip().splitlines()
    kopf = zeilen[0].split(";")
    assert kopf == ["Block", "Kennzahl", "Wert", "Einheit", "Zellen/Basis", "Quelle",
                    "Stand", "Lizenz"]
    inhalt = r.text
    assert "Zensus 2022" in inhalt and "OpenStreetMap" in inhalt
    assert "15.05.2022" in inhalt
    assert "€/m²" in inhalt
    assert "Untergrenze" in inhalt, "Bekannte Grenzen gehören in den Export"


def test_vergleich_csv(client):
    client.post("/api/points", json={"label": "A", "lat": LAT, "lon": LON, "radius": R})
    r = client.get("/api/export/vergleich.csv")
    assert r.status_code == 200
    assert "Bezeichnung;Adresse" in r.text
    assert "16370" in r.text


def test_csv_erzeugung_ohne_daten_bricht_nicht():
    text = point_to_csv({"punkt": {}, "bloecke": {}, "meta": {}, "grenzen": []})
    assert text.startswith("Block;Kennzahl")


# ------------------------------------------------------------------- Cache


def test_cache_leeren(client):
    client.get("/api/point", params={"lat": LAT, "lon": LON, "r": R})
    st = client.get("/api/stats").json()
    assert st["total"] >= 3
    r = client.delete("/api/cache")
    assert r.json()["geloescht"] >= 3
    assert client.get("/api/stats").json()["total"] == 0


def test_outbound_log_ist_abrufbar(client):
    client.get("/api/point", params={"lat": LAT, "lon": LON, "r": R})
    d = client.get("/api/outbound").json()
    # FakeOutbound umgeht das Protokoll, deshalb nur Struktur prüfen.
    assert "anzahl" in d and "eintraege" in d


# ------------------------------------------------------- Umsatzschätzung §9


def test_schaetzung_vorgaben_kommen_aus_den_punktdaten(client):
    d = client.get("/api/schaetzung/vorgaben", params={"lat": LAT, "lon": LON, "r": R}).json()
    assert d["einwohner"] == 16370.0
    assert d["wettbewerber"] == 26
    assert "Zensus 2022" in d["einwohner_herkunft"]
    assert "Untergrenze" in d["wettbewerber_herkunft"]
    assert d["referenzwerte"] and all(r["quelle"] for r in d["referenzwerte"])
    assert len(d["formel"]) == 6


def test_schaetzung_rechnet_und_liefert_spannen(client):
    r = client.post("/api/schaetzung", json={
        "einwohner": 16370, "wettbewerber": 26, "besuche_je_einwohner": 60.3,
        "bon_min": 7.15, "bon_max": 10.21,
    })
    assert r.status_code == 200
    d = r.json()
    for feld, werte in d["ergebnis"].items():
        assert len(werte) == 2 and werte[0] <= werte[1], feld
    assert "Vergleichsmaß" in d["beschriftung"]
    assert d["ergebnis"]["bestellungen_je_oeffnungsstunde"][0] > 0


def test_schaetzung_lehnt_unsinnige_eingaben_ab(client):
    r = client.post("/api/schaetzung", json={
        "einwohner": 16370, "wettbewerber": 26, "besuche_je_einwohner": 60.3,
        "bon_min": 7.15, "bon_max": 10.21, "oeffnungstage": 0,
    })
    assert r.status_code == 422


def test_schaetzung_beruehrt_den_datenteil_nicht(client):
    """Die Schätzung ist ein getrennter Reiter — sie darf nirgends in die
    Datenblöcke einsickern (Spec §9: „eigener, klar getrennter Reiter")."""
    d = client.get("/api/point", params={"lat": LAT, "lon": LON, "r": R}).json()
    text = json.dumps(d, ensure_ascii=False).lower()
    for begriff in ("schaetzung", "schätzung", "jahresumsatz", "marktanteil",
                    "bestellungen"):
        assert begriff not in text, f"„{begriff}\" taucht im Datenteil auf"
