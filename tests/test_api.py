"""API-Ebene: Cache-Wirkung, Ausfallverhalten, Export, Vergleich.

Alle Antworten stammen aus den Phase-0-Fixtures; es geht kein Aufruf ins Netz.
Der Ersatz sitzt bewusst auf ``Outbound.request``-Ebene, damit Cache-Logik,
Rate-Limiter und Fehlerpfade mitgetestet werden statt umgangen zu werden.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gastroviewer.api import create_app, point_to_csv
from gastroviewer.sources.base import SourceError

LAT, LON, R = 48.1334, 11.5674, 600


class FakeOutbound:
    """Ersetzt nur die Netz-Ebene und zählt die Aufrufe."""

    def __init__(self, zensus, overpass, nominatim, einkommen=None,
                 kreisprofil=None, dwd=None, pendler=None, ohsome=None,
                 laerm=None, fehler: set[str] | None = None):
        self.zensus = zensus
        self.overpass = overpass
        self.nominatim = nominatim
        self.einkommen = einkommen or {"features": []}
        # Fixture je Tabelle — Einkommen und Kreisprofil teilen sich Endpunkt
        # und URL, unterscheiden sich nur im layer-Parameter.
        self.kreisprofil = kreisprofil or {}
        # DWD-Textdateien, Schlüssel = Dateiname.
        self.dwd = dwd or {}
        # Pendleratlas: {"dateien": {Dateiname: CSV-Text}, "gemeinden": {...}}.
        self.pendler = pendler or {"dateien": {}, "gemeinden": {"features": []}}
        # ohsome: {"gastro": Antwort, "fast_food": Antwort}.
        self.ohsome = ohsome or {"gastro": {"result": []},
                                 "fast_food": {"result": []}}
        # Lärm-WMS: Antwort je Layername (query_layers).
        self.laerm = laerm or {}
        self.fehler = fehler or set()
        self.calls: list[str] = []

    def _dispatch(self, url: str, kw=None):
        # Vor "arcgis" prüfen: auch der Regionalatlas läuft auf einem
        # ArcGIS-Server und würde sonst die Zensus-Fixture bekommen.
        if "regionalatlas" in url:
            layer = ((kw or {}).get("data") or {}).get("layer", "")
            tabelle = next((t for t in self.kreisprofil if t in layer), None)
            if tabelle:
                self.calls.append("kreisprofil")
                if "kreisprofil" in self.fehler:
                    raise SourceError("timeout",
                                      "Zeitüberschreitung — Dienst antwortet nicht.")
                return self.kreisprofil[tabelle]
            self.calls.append("einkommen")
            if "einkommen" in self.fehler:
                raise SourceError("timeout", "Zeitüberschreitung — Dienst antwortet nicht.")
            return self.einkommen
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
        if "pendleratlas" in url:
            self.calls.append("pendler")
            name = url.rsplit("/", 1)[-1]
            if name.startswith("gemeinden_2024"):
                return self.pendler["gemeinden"]
            raise SourceError("http_status", f"HTTP 404 — {name} fehlt.")
        # Genau der Lärmdienst — auch der Hochwasser-Block (planung) läuft
        # auf lfu.bayern und soll hier weiterhin als „unerwartet" scheitern.
        if "laerm/hauptverkehrsstrassen" in url:
            self.calls.append("laerm")
            if "laerm" in self.fehler:
                raise SourceError("timeout",
                                  "Zeitüberschreitung — Dienst antwortet nicht.")
            layer = ((kw or {}).get("params") or {}).get("query_layers", "")
            if layer not in self.laerm:
                raise AssertionError(f"unerwarteter Lärm-Layer: {layer}")
            return self.laerm[layer]
        if "ohsome" in url:
            self.calls.append("dynamik")
            if "dynamik" in self.fehler:
                raise SourceError("timeout",
                                  "Zeitüberschreitung — Dienst antwortet nicht.")
            filter_ = ((kw or {}).get("data") or {}).get("filter", "")
            return self.ohsome[
                "fast_food" if filter_ == "amenity=fast_food" else "gastro"
            ]
        raise AssertionError(f"unerwartete URL: {url}")

    async def start(self):
        pass

    async def aclose(self):
        pass

    async def get_json(self, source, url, **kw):
        return self._dispatch(url, kw)

    async def post_json(self, source, url, **kw):
        return self._dispatch(url, kw)

    async def get_text(self, source, url, **kw):
        if "dwd" in url:
            self.calls.append("dwd")
            if "dwd" in self.fehler:
                raise SourceError("timeout",
                                  "Zeitüberschreitung — Dienst antwortet nicht.")
            name = url.rsplit("/", 1)[-1]
            if name not in self.dwd:
                raise SourceError("http_status", f"HTTP 404 — {name} fehlt.")
            return self.dwd[name]
        if "pendleratlas" in url:
            self.calls.append("pendler")
            if "pendler" in self.fehler:
                raise SourceError("timeout",
                                  "Zeitüberschreitung — Dienst antwortet nicht.")
            name = url.rsplit("/", 1)[-1]
            if name not in self.pendler["dateien"]:
                # Jahres-Sondierung: nicht vorhandene Jahrgänge sind ein 404.
                raise SourceError("http_status", f"HTTP 404 — {name} fehlt.")
            return self.pendler["dateien"][name]
        raise AssertionError(f"unerwartete Text-URL: {url}")

    class _Lim:
        @staticmethod
        def stats():
            return {}

    limiters = _Lim()


@pytest.fixture()
def client(tmp_path, monkeypatch, zensus_600, overpass_combined, nominatim_reverse,
           einkommen_muenchen, kreisprofil_muenchen, dwd_klima, pendler_muenchen,
           ohsome_dynamik, laerm_bayern):
    from gastroviewer.config import Settings

    settings = Settings()
    settings.data_dir = tmp_path
    settings.overpass_endpoints = ("https://overpass-api.de/api/interpreter",)

    fake = FakeOutbound(zensus_600, overpass_combined, nominatim_reverse,
                        einkommen_muenchen, kreisprofil_muenchen, dwd_klima,
                        pendler_muenchen, ohsome_dynamik, laerm_bayern)
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
    # Nominatim, Zensus, Overpass — der Regionalatlas fürs Einkommen (1) und
    # Kreisprofil (5 Tabellen) — der DWD (5 Parameter x 2 Dateien) — der
    # Pendleratlas (2 Jahres-Sondierungen mit 404, 6 Karten, Gemeindeliste,
    # Verflechtungen) — ohsome (2 Zeitreihen: Gastro gesamt, fast_food) —
    # und das Lärm-WMS (LDEN und LNight je 2022 mit NoData plus 2017 = 4).
    assert vorher == 35

    d = client.get("/api/point", params={"lat": LAT, "lon": LON, "r": R}).json()
    assert len(client.fake.calls) == vorher, "Cache hat nicht gegriffen"
    assert d["meta"]["outbound_requests"] == 0
    assert d["meta"]["aus_cache"] is True
    assert d["bloecke"]["zensus"]["provenance"]["cached"] is True


def test_point_dynamik_block_und_endpunkt(client):
    """Der Dynamik-Block hängt am Gesamtpunkt UND am eigenen Endpunkt —
    beide gegen die echte ohsome-Fixture (326 → 369 am Marienplatz)."""
    d = client.get("/api/point", params={"lat": LAT, "lon": LON, "r": R}).json()
    dy = d["bloecke"]["dynamik"]
    assert dy["ok"]
    assert dy["data"]["veraenderung"]["von"] == 326
    assert dy["data"]["veraenderung"]["bis"] == 369
    assert "ohsome" in dy["provenance"]["source"]

    e = client.get("/api/point/dynamik",
                   params={"lat": LAT, "lon": LON, "r": R}).json()
    assert e["data"]["reihe"][0] == {
        "jahr": 2019, "gastro": 326, "schnellgastronomie": 29,
    }


def test_point_laerm_block_mit_fallback_auf_2017(client):
    """München ist Ballungsraum: die 2022er-Schicht antwortet NoData, der
    Wert kommt aus der Kartierung 2017 — und das Jahr steht dabei."""
    d = client.get("/api/point", params={"lat": LAT, "lon": LON, "r": R}).json()
    la = d["bloecke"]["laerm"]
    assert la["ok"]
    assert la["data"]["lden"]["wert_db"] == 65.6
    assert la["data"]["lden"]["kartierung"] == 2017
    assert la["data"]["lnight"]["wert_db"] == 56.9
    assert "LfU" in la["provenance"]["source"]

    e = client.get("/api/point/laerm",
                   params={"lat": LAT, "lon": LON, "bundesland_code": "05"}).json()
    assert e["ok"] and e["data"] is None, "außerhalb Bayerns bleibt der Block leer"


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
    frequenz = gruppen["Passantenfrequenz"]["eintraege"]
    hystreet = next(e for e in frequenz if e["titel"].startswith("hystreet"))
    assert "gewerbliche Nutzung untersagt" in hystreet["warnung"]
    google = next(e for e in frequenz if "Google Maps" in e["titel"])
    assert google["url"].startswith("https://www.google.com/maps/search/")
    assert "nicht" in google["beschreibung"], "die Lizenzgrenze muss dabeistehen"
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


def test_verhaeltniszahlen_stehen_im_vergleich(client):
    """Zwei Kennzahlen, die der Zensus allein nicht hergibt: die Sättigung und
    ein Näherungswert für Zulauf von außerhalb."""
    client.post("/api/points", json={"label": "A", "lat": LAT, "lon": LON, "radius": R})
    v = client.get("/api/points/vergleich").json()
    keys = {c["key"] for c in v["spalten"]}
    assert "wettbewerb_je_1000" in keys and "abfahrten_je_einwohner" in keys

    titel = {c["key"]: c["titel"] for c in v["spalten"]}
    for k in ("wettbewerb_je_1000", "abfahrten_je_einwohner"):
        assert "berechnet" in titel[k], (
            "abgeleitete Zahlen dürfen nicht wie Messwerte aussehen"
        )

    z = v["zeilen"][0]
    assert z["wettbewerb_je_1000"] == pytest.approx(
        z["gastro_gesamt"] / z["einwohner"] * 1000, abs=0.05
    )


def test_verhaeltniszahl_ohne_bezugsgroesse_ist_keine_null():
    """Ohne Einwohnerdaten gibt es keine Dichte von 0 — es gibt gar keine."""
    from gastroviewer.api import je_bezugsgroesse

    assert je_bezugsgroesse(40, 10_000, 1000, 1) == 4.0
    assert je_bezugsgroesse(0, 10_000, 1000, 1) == 0.0, "keine Wettbewerber ist ein Wert"
    assert je_bezugsgroesse(40, 0, 1000, 1) is None, "Division durch null"
    assert je_bezugsgroesse(40, None, 1000, 1) is None
    assert je_bezugsgroesse(None, 10_000, 1000, 1) is None
    assert je_bezugsgroesse(40, -5, 1000, 1) is None
    assert je_bezugsgroesse(True, 10_000, 1000, 1) is None, "bool ist keine Messgröße"


def test_verhaeltniszahlen_auch_im_csv(client):
    client.post("/api/points", json={"label": "A", "lat": LAT, "lon": LON, "radius": R})
    text = client.get("/api/export/vergleich.csv").text
    assert "Wettbewerber je 1.000 Einw. (berechnet)" in text
    assert "Abfahrten je Einwohner (berechnet)" in text


def test_wettbewerb_nach_entfernung_ist_kumuliert(client):
    """Ein Betrieb in 50 m konkurriert anders als einer am Rand des Umkreises."""
    d = client.get("/api/point", params={"lat": LAT, "lon": LON, "r": R}).json()
    gas = d["bloecke"]["osm"]["data"]["zusammenfassung"]["gastronomie"]
    stufen = gas["nach_entfernung"]

    assert [s["bis_m"] for s in stufen] == [150, 300, R], "auf den Radius begrenzt"
    anzahlen = [s["anzahl"] for s in stufen]
    assert anzahlen == sorted(anzahlen), "kumuliert, also monoton steigend"
    assert anzahlen[-1] == gas["gesamt"], "die letzte Stufe ist der volle Umkreis"

    liste = d["bloecke"]["osm"]["data"]["gastronomie"]
    assert gas["naechster_m"] == min(x["distanz_m"] for x in liste)
    for s, ff in zip(stufen, gas["schnellrestaurants_nach_entfernung"]):
        assert ff["anzahl"] <= s["anzahl"], "Teilmenge aller Betriebe"


def test_entfernungsstufen_ueberschreiten_den_radius_nicht():
    from gastroviewer.sources.overpass import nach_entfernung

    objekte = [{"distanz_m": d} for d in (40, 120, 260, 280, 590)]
    assert nach_entfernung(objekte, 300) == [
        {"bis_m": 150, "anzahl": 2},
        {"bis_m": 300, "anzahl": 4},
    ]
    assert nach_entfernung([], 600) == [
        {"bis_m": 150, "anzahl": 0},
        {"bis_m": 300, "anzahl": 0},
        {"bis_m": 600, "anzahl": 0},
    ]


def test_mittagsfenster_steht_im_vergleich(client):
    """Eine Pendlerhaltestelle hat ihre Spitzen um 8 und 18 Uhr und ist mittags
    leer — die Tagessumme allein trennt die Fälle nicht."""
    v = client.get("/api/points/vergleich").json()
    keys = {c["key"] for c in v["spalten"]}
    assert {"abfahrten_mittag", "mittagsanteil"} <= keys
    assert {"gastro_bis_150", "gastro_bis_300", "naechster_wettbewerber"} <= keys
    assert {"fastfood_je_1000", "neubau_anteil"} <= keys


def test_spalten_geben_ihre_nachkommastellen_vor(client):
    """Auf eine Stelle gerundet wären 0,52 und 0,07 beide „0,5" bzw. „0,1" —
    der Unterschied, um den es geht, verschwände in der Darstellung."""
    v = client.get("/api/points/vergleich").json()
    stellen = {c["key"]: c.get("stellen") for c in v["spalten"]}
    assert stellen["abfahrten_je_einwohner"] == 2
    assert stellen["wettbewerb_je_1000"] == 1
    assert stellen["miete_qm"] == 2, "Cent-Unterschiede bei der Miete sind vergleichsrelevant"
    assert stellen["leerstandsquote"] == 2
    assert stellen["einwohner"] is None, "ganze Zahlen bekommen keine Nachkommastellen"


def test_saettigung_wird_nicht_als_hoechstwert_hervorgehoben():
    """Der Höchstwert bekommt in der Tabelle die Klasse „best". Bei der
    Wettbewerbsdichte wäre das die dichteste Konkurrenz — kein Lob."""
    js = (Path(__file__).resolve().parents[1]
          / "gastroviewer" / "static" / "app.js").read_text(encoding="utf-8")
    block = js.split("HOCH_IST_AUFFAELLIG = new Set([")[1].split("]);")[0]
    assert "abfahrten_je_einwohner" in block
    assert "wettbewerb_je_1000" not in block


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
    kopf = r.text.splitlines()[0]
    for spalte in ("Bezeichnung", "Adresse", "Einwohner"):
        assert spalte in kopf, f"{spalte} fehlt im CSV-Kopf"
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


# --------------------------------- Bodenrichtwert-Kartendienste (Phase 4)


def test_wms_register_deckt_alle_bundeslaender(client):
    d = client.get("/api/wms").json()
    codes = {x["bundesland_code"] for x in d["dienste"]} | {
        x["bundesland_code"] for x in d["ohne_dienst"]
    }
    assert len(codes) == 16
    assert d["verifiziert_am"] == "2026-08-01"


def test_wms_fuer_bayern_nennt_den_grund(client):
    d = client.get("/api/wms", params={"bundesland_code": "09"}).json()
    assert d["verfuegbar"] is False
    assert "rechtlichen Gründen" in d["grund"]


def test_wms_fuer_nrw_liefert_die_ebene(client):
    d = client.get("/api/wms", params={"bundesland_code": "05"}).json()
    assert d["verfuegbar"] is True
    assert d["url"].startswith("https://www.wms.nrw.de/")
    assert d["min_zoom"] == 14
    assert d["params"]["TIME"] == "2026-01-01"
    assert "dl-de/zero-2-0" in d["lizenz"]


def test_bodenrichtwert_ohne_dienst_bricht_nicht(client):
    d = client.get("/api/wms/bodenrichtwert",
                   params={"lat": LAT, "lon": LON, "bundesland_code": "09"}).json()
    assert d["ok"] is True
    assert d["data"] is None
    assert d["warnings"]


def test_bodenrichtwerte_im_punkt_tragen_den_kartendienst(client):
    d = client.get("/api/point", params={"lat": LAT, "lon": LON, "r": R}).json()
    k = d["bodenrichtwerte"]["kartendienst"]
    assert k["verfuegbar"] is False, "München liegt in Bayern"
    assert "keine URL geraten" in k["hinweis"]


def test_schaetzung_ohne_einwohner_rechnet_statt_abzubrechen(client):
    """Ländlicher Punkt ohne Zensuszelle: die Rechnung muss 0 liefern, nicht 422."""
    r = client.post("/api/schaetzung", json={
        "besuche_je_einwohner": 60.3, "bon_min": 7.15, "bon_max": 10.21,
    })
    assert r.status_code == 200
    assert r.json()["ergebnis"]["jahresumsatz_eur"] == [0, 0]


def test_bodenrichtwerte_ohne_bundesland_haben_dieselbe_form(client):
    """Ohne AGS fehlten früher drei Schlüssel — die Oberfläche musste überall
    auf undefined prüfen."""
    from gastroviewer.sources import boris

    ohne = boris.links_for(None)
    mit = boris.links_for("05", "Köln")
    assert set(ohne) == set(mit)
    assert ohne["kartendienst"]["verfuegbar"] is False


def test_wms_ebenen_endpunkt(client):
    d = client.get("/api/wms/ebenen", params={"bundesland_code": "09"}).json()
    assert len(d["ebenen"]) == 4
    assert {e["schluessel"] for e in d["ebenen"]} == {
        "by_dop40", "by_verkehrsmengen", "by_laerm", "by_alkis"}
    d2 = client.get("/api/wms/ebenen", params={"bundesland_code": "05"}).json()
    assert d2["ebenen"] == []


def test_radzaehlung_ist_teil_des_punktes_und_des_exports(client, monkeypatch):
    """Die gemessene Frequenz muss auch in Export und Vergleich landen — sonst
    fehlt beim Standortvergleich ausgerechnet die einzige Messgröße."""
    from gastroviewer.sources.base import Provenance, SourceResult

    async def fake_rad(self, lat, lon, radius, refresh=False):
        return SourceResult(
            name="radzaehlung", ok=True,
            data={"naechste": {"name": "Erhardtstr.", "distanz_m": 1294,
                               "je_tag_vorjahr": 3877, "summe_vorjahr": 1415000},
                  "in_reichweite": [{"name": "Erhardtstr.", "distanz_m": 1294,
                                     "je_tag_vorjahr": 3877}]},
            provenance=Provenance(source="Raddauerzählstellen München",
                                  license="dl-de/by-2-0", stand="2025"),
        )

    from gastroviewer.service import PointService
    monkeypatch.setattr(PointService, "radzaehlung", fake_rad)

    d = client.get("/api/point", params={"lat": LAT, "lon": LON, "r": R}).json()
    assert d["bloecke"]["radzaehlung"]["data"]["naechste"]["je_tag_vorjahr"] == 3877

    csv_text = client.get("/api/export/point.csv",
                          params={"lat": LAT, "lon": LON, "r": R}).text
    assert "Radverkehr" in csv_text and "3877" in csv_text

    client.post("/api/points", json={"label": "A", "lat": LAT, "lon": LON, "radius": R})
    v = client.get("/api/points/vergleich").json()
    assert "rad_je_tag" in {c["key"] for c in v["spalten"]}
    assert v["zeilen"][0]["rad_je_tag"] == 3877
    assert v["zeilen"][0]["rad_entfernung"] == 1294


def test_verkehrsmenge_ist_teil_des_punktes_und_des_exports(client, monkeypatch):
    from gastroviewer.service import PointService
    from gastroviewer.sources.base import Provenance, SourceResult

    async def fake_vm(self, lat, lon, radius, refresh=False):
        return SourceResult(
            name="verkehrsmenge", ok=True,
            data={"zaehlstellen": [{"strasse": "A 9", "zaehlstelle": "9001",
                                    "distanz_m": 701, "dtv_kfz": 111624,
                                    "schwerverkehr_anteil": 2.9, "im_radius": False}],
                  "staerkste": {"strasse": "A 9", "dtv_kfz": 111624,
                                "schwerverkehr_anteil": 2.9, "distanz_m": 701},
                  "naechste": {"strasse": "A 9", "dtv_kfz": 111624, "distanz_m": 701}},
            provenance=Provenance(source="BAYSIS", license="CC BY 4.0", stand="2021"),
        )

    monkeypatch.setattr(PointService, "verkehrsmenge", fake_vm)

    d = client.get("/api/point", params={"lat": LAT, "lon": LON, "r": R}).json()
    assert d["bloecke"]["verkehrsmenge"]["data"]["staerkste"]["dtv_kfz"] == 111624

    csv_text = client.get("/api/export/point.csv",
                          params={"lat": LAT, "lon": LON, "r": R}).text
    assert "Verkehrsmenge" in csv_text and "111624" in csv_text

    client.post("/api/points", json={"label": "A", "lat": LAT, "lon": LON, "radius": R})
    v = client.get("/api/points/vergleich").json()
    assert v["zeilen"][0]["dtv_kfz"] == 111624
    assert v["zeilen"][0]["dtv_sv_anteil"] == 2.9


# ---------------------------------------------------------------- Gehstrecke


def test_gehweg_ist_nicht_teil_des_gesamtpunkts(client):
    """Das Fußwegenetz ist die größte Overpass-Antwort des Werkzeugs und darf
    nicht bei jedem Kartenklick mitlaufen — Overpass ist ein Spendendienst."""
    d = client.get("/api/point", params={"lat": LAT, "lon": LON, "r": R}).json()
    assert "gehweg" not in d["bloecke"]


def test_gehweg_hat_lange_haltbarkeit():
    from gastroviewer.config import Settings

    s = Settings()
    assert s.ttl_for("gehweg") > s.ttl_for("overpass") * 7, (
        "ein Wegenetz ändert sich in Wochen, nicht in Stunden"
    )


def test_merken_loest_keine_gehwegabfrage_aus(client, monkeypatch):
    """Sonst kostet jedes „Punkt merken" mehrere Megabyte beim Spendendienst."""
    from gastroviewer.sources import gehweg as gehweg_mod

    async def darf_nicht(*a, **kw):
        raise AssertionError("Merken darf das Wegenetz nicht laden")

    monkeypatch.setattr(gehweg_mod, "load", darf_nicht)
    r = client.post("/api/points", json={"label": "A", "lat": LAT, "lon": LON, "radius": R})
    assert r.status_code == 200
    zeile = client.get("/api/points/vergleich").json()["zeilen"][0]
    assert zeile["einwohner_gehweg"] is None, "ohne Berechnung bleibt die Spalte leer"


def test_gehwegspalten_stehen_im_vergleich(client):
    v = client.get("/api/points/vergleich").json()
    keys = {c["key"] for c in v["spalten"]}
    assert {"einwohner_gehweg", "erschliessung_einwohner",
            "gastro_gehweg", "umwegfaktor"} <= keys


def test_deckkraftregler_ist_vorhanden_und_beruehrt_die_grundkarte_nicht():
    """Der Regler soll die aufgesetzten Ebenen zurückblenden, damit Straßen und
    Gebäude sichtbar bleiben — die Grundkarte selbst darf er nicht dimmen."""
    js = (Path(__file__).resolve().parents[1]
          / "gastroviewer" / "static" / "app.js").read_text(encoding="utf-8")
    assert "deckkraft-regler" in js and 'type="range"' in js
    assert "localStorage.setItem(DECKKRAFT_SPEICHER" in js, "Einstellung muss bleiben"
    # Grundkarten werden ohne setOpacity eingehängt.
    block = js.split("if (cfg.als_grundkarte) {")[1].split("} else {")[0]
    assert "setOpacity" not in block, "eine Grundkarte wird nicht zurückgeblendet"

    css = (Path(__file__).resolve().parents[1]
           / "gastroviewer" / "static" / "style.css").read_text(encoding="utf-8")
    assert ".deckkraft-regler" in css


# ------------------------------------------------------- Spaltengruppen


def test_jede_vergleichsspalte_gehoert_zu_einer_gruppe(client):
    """Sonst fällt sie aus der Tabelle heraus, sobald gefiltert wird."""
    from gastroviewer.api import VERGLEICH_GRUPPEN, VERGLEICH_SPALTEN

    bekannt = {g["key"] for g in VERGLEICH_GRUPPEN}
    ohne = [c["key"] for c in VERGLEICH_SPALTEN if c.get("gruppe") not in bekannt]
    assert not ohne, f"Spalten ohne gültige Gruppe: {ohne}"


def test_gruppen_kommen_mit_der_vergleichsantwort(client):
    v = client.get("/api/points/vergleich").json()
    assert v["gruppen"], "die Oberfläche braucht die Gruppen zum Schalten"
    fest = [g for g in v["gruppen"] if g.get("fest")]
    assert len(fest) == 1 and fest[0]["key"] == "standort", (
        "genau eine Gruppe muss unabschaltbar sein — ohne Bezeichnung ist die "
        "Tabelle nicht lesbar"
    )
    assert v["spalten"][0]["key"] == "label", "die feste Spalte muss vorne stehen"


def test_vorgabe_zeigt_deutlich_weniger_als_alle_spalten(client):
    from gastroviewer.api import VERGLEICH_GRUPPEN, VERGLEICH_SPALTEN

    vorgabe = {g["key"] for g in VERGLEICH_GRUPPEN if g["vorgabe"] or g.get("fest")}
    sichtbar = [c for c in VERGLEICH_SPALTEN if c["gruppe"] in vorgabe]
    assert len(sichtbar) < len(VERGLEICH_SPALTEN), "die Vorgabe muss etwas ausblenden"
    assert "erreichbarkeit" not in vorgabe, (
        "die Gehwegspalten sind meist leer und gehören nicht in die Vorgabe"
    )
    assert len(sichtbar) <= 20, (
        f"die Vorgabe ist mit {len(sichtbar)} Spalten wieder zu breit geworden — "
        "abgeleitete und Detailwerte gehören in die abschaltbare Gruppe"
    )


def test_csv_enthaelt_immer_alle_spalten(client):
    """Die Auswahl in der Oberfläche darf den Export nicht beschneiden."""
    from gastroviewer.api import VERGLEICH_SPALTEN

    client.post("/api/points", json={"label": "A", "lat": LAT, "lon": LON, "radius": R})
    kopf = client.get("/api/export/vergleich.csv").text.splitlines()[0]
    for c in VERGLEICH_SPALTEN:
        assert c["titel"] in kopf, f"{c['titel']} fehlt im CSV"


# --------------------------------------------- Eigene Notiz und Bewertung


def test_notiz_und_bewertung_lassen_sich_setzen(client):
    """Das Werkzeug bewertet nicht — der Nutzer darf und soll das aber."""
    r = client.post("/api/points", json={"label": "Kandidat", "lat": LAT, "lon": LON,
                                         "radius": R})
    pid = r.json()["id"]

    zeile = client.get("/api/points/vergleich").json()["zeilen"][0]
    assert zeile["bewertung"] is None and zeile["notiz"] is None, (
        "ohne eigene Eingabe darf dort nichts stehen"
    )

    p = client.patch(f"/api/points/{pid}",
                     json={"notiz": "Ecklage, Terrasse nach Süden", "bewertung": 4})
    assert p.status_code == 200

    zeile = client.get("/api/points/vergleich").json()["zeilen"][0]
    assert zeile["bewertung"] == 4
    assert zeile["notiz"] == "Ecklage, Terrasse nach Süden"


def test_notizspalten_sind_als_eigene_einschaetzung_beschriftet(client):
    v = client.get("/api/points/vergleich").json()
    titel = {c["key"]: c["titel"] for c in v["spalten"]}
    assert "Eigene" in titel["bewertung"] and "Eigene" in titel["notiz"], (
        "sonst sähen sie aus wie eine Bewertung des Werkzeugs"
    )
    gruppe = {c["key"]: c["gruppe"] for c in v["spalten"]}
    assert gruppe["bewertung"] == "standort", (
        "in der festen Gruppe — eine eigene Note nützt nur, wenn sie sichtbar ist"
    )


def test_bewertung_ausserhalb_der_skala_wird_abgewiesen(client):
    r = client.post("/api/points", json={"label": "A", "lat": LAT, "lon": LON, "radius": R})
    pid = r.json()["id"]
    assert client.patch(f"/api/points/{pid}", json={"bewertung": 9}).status_code == 422
    assert client.patch(f"/api/points/{pid}", json={"bewertung": 0}).status_code == 422
    assert client.patch(f"/api/points/{pid}", json={"bewertung": None}).status_code == 200


def test_notiz_fuer_unbekannten_punkt_meldet_404(client):
    assert client.patch("/api/points/9999", json={"notiz": "x"}).status_code == 404


def test_alte_datenbank_bekommt_die_neuen_spalten(tmp_path):
    """Eine Datenbank aus einer früheren Fassung soll weiterlaufen, statt den
    Nutzer seine gemerkten Punkte zu kosten."""
    import sqlite3

    pfad = tmp_path / "alt.sqlite"
    with sqlite3.connect(pfad) as conn:
        conn.execute(
            "CREATE TABLE saved_points (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " label TEXT NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL,"
            " radius INTEGER NOT NULL, created_at REAL NOT NULL, payload TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO saved_points (label, lat, lon, radius, created_at, payload)"
            " VALUES ('Bestand', 48.1, 11.5, 600, 0, '{}')"
        )

    from gastroviewer.cache import Cache

    c = Cache(pfad)
    punkte = c.list_points()
    assert len(punkte) == 1 and punkte[0]["label"] == "Bestand", "Bestand ging verloren"
    assert punkte[0]["notiz"] is None and punkte[0]["bewertung"] is None
    assert c.set_point_notiz(punkte[0]["id"], "geht", 3) is True
    assert c.list_points()[0]["bewertung"] == 3


def test_alle_python_dateien_lassen_sich_uebersetzen():
    """Zweimal in dieser Entwicklung ist ein ASCII-Anführungszeichen als
    deutsches Schlusszeichen in einen String geraten und hat die Datei
    unübersetzbar gemacht — einmal in nominatim.py, einmal in planung.py.
    Module ohne eigenen Test würden das nicht bemerken."""
    import ast

    wurzel = Path(__file__).resolve().parents[1]
    dateien = [
        f for f in wurzel.rglob("*.py")
        if not any(teil in f.parts for teil in (".venv", "venvtest", "build", ".git"))
    ]
    assert len(dateien) > 15, "die Suche hat offenbar nichts gefunden"
    kaputt = []
    for f in dateien:
        try:
            ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        except SyntaxError as e:
            kaputt.append(f"{f.relative_to(wurzel)}:{e.lineno} {e.msg}")
    assert not kaputt, "nicht übersetzbar: " + " · ".join(kaputt)


# ------------------------------------------------------- Übersichtsgitter


def test_gitter_liefert_zellen_fuer_den_ausschnitt(client):
    """Die Frage „WO ist es interessant?" braucht die Fläche, nicht den Kreis."""
    r = client.get("/api/gitter", params={
        "ebene": "1km", "west": 11.36, "sued": 48.06, "ost": 11.72, "nord": 48.25})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert d["data"]["ebene"] == "1km"
    assert len(d["data"]["zellen"]) > 50
    z = d["data"]["zellen"][0]
    assert "einwohner" in z and "miete_qm" in z and z["ring"], (
        "jede Zelle braucht Werte und Geometrie"
    )
    assert d["provenance"]["license"], "auch die Übersicht trägt die Lizenz"


def test_gitter_kachelt_den_cache(client):
    """Leichtes Schwenken darf den Dienst nicht erneut fragen."""
    p1 = {"ebene": "1km", "west": 11.41, "sued": 48.09, "ost": 11.57, "nord": 48.19}
    client.get("/api/gitter", params=p1)
    vorher = client.fake.calls.count("zensus")
    # minimal verschoben, aber innerhalb derselben 0,2°-Kachel — erst das
    # Überschreiten einer Kachelgrenze darf einen neuen Abruf auslösen
    p2 = {"ebene": "1km", "west": 11.42, "sued": 48.10, "ost": 11.58, "nord": 48.18}
    d = client.get("/api/gitter", params=p2).json()
    assert client.fake.calls.count("zensus") == vorher, "Kachel-Cache griff nicht"
    assert d["provenance"]["cached"] is True


def test_gitter_weist_unsinn_ab(client):
    fehler = [
        {"ebene": "5km", "west": 11.4, "sued": 48.1, "ost": 11.6, "nord": 48.2},
        {"ebene": "1km", "west": 11.6, "sued": 48.1, "ost": 11.4, "nord": 48.2},
        {"ebene": "1km", "west": 2.0, "sued": 48.1, "ost": 2.4, "nord": 48.2},
        # zu groß für 1 km — die Oberfläche wechselt dann aufs 10-km-Gitter
        {"ebene": "1km", "west": 9.0, "sued": 47.5, "ost": 13.5, "nord": 50.0},
    ]
    for p in fehler:
        assert client.get("/api/gitter", params=p).status_code == 422, p


def test_gitter_kachel_rundet_nach_aussen():
    from gastroviewer.sources.zensus import gitter_kachel

    w, s, o, n = gitter_kachel("1km", 11.41, 48.09, 11.59, 48.21)
    assert w <= 11.41 and s <= 48.09 and o >= 11.59 and n >= 48.21
    assert abs(w / 0.2 - round(w / 0.2)) < 1e-6, "Westrand nicht auf dem Raster"
    assert abs(o / 0.2 - round(o / 0.2)) < 1e-6, "Ostrand nicht auf dem Raster"
    # Die Gleitkomma-Falle konkret: 11,4 liegt exakt auf dem Raster und darf
    # nicht um eine ganze Kachel nach außen fallen.
    w2, _, o2, _ = gitter_kachel("1km", 11.40, 48.0, 11.60, 48.2)
    assert w2 == pytest.approx(11.4) and o2 == pytest.approx(11.6)


def test_radien_enthalten_die_grossen_stufen(client):
    d = client.get("/api/health").json()
    assert d["radien"] == [300, 600, 900, 1400, 2000, 3000]


async def test_gehweg_verweigert_uebergrosse_radien(settings):
    """Zu Fuß ist ein 3-km-Umkreis kein Einzugsgebiet, und das Wegenetz dafür
    wäre eine unverhältnismäßige Last für den Spendendienst."""
    from gastroviewer.sources import gehweg

    from gastroviewer.sources.base import SourceError

    class FakeOut:
        def __init__(self):
            self.versucht = 0

        async def post_json(self, *a, **kw):
            self.versucht += 1
            raise SourceError("connect", "vom Test unterbunden")

    out = FakeOut()
    res = await gehweg.load(out, settings, 48.1372, 11.5755, 3000)
    assert res.ok is True and res.data is None
    assert "2000 m begrenzt" in res.warnings[0]
    assert out.versucht == 0, "oberhalb der Grenze darf kein Abruf hinausgehen"
    # An der Grenze selbst wird noch gerechnet — der (unterbundene) Abruf
    # beweist, dass er versucht wurde.
    res2 = await gehweg.load(out, settings, 48.1372, 11.5755, 2000)
    assert out.versucht > 0 and res2.ok is False
    assert res2.error["kind"] == "connect"

# ---------------------------------------------------------- Flächen-Scan


def test_scan_liefert_zellen_und_betriebe(client):
    """Einwohner je Betrieb im 300-m-Umfeld, je 100-m-Zelle."""
    r = client.get("/api/scan", params={
        "west": 11.56, "sued": 48.13, "ost": 11.58, "nord": 48.145})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert d["data"]["zellen"], "keine Zellen aus dem Fixture"
    assert d["data"]["betriebe_gesamt"] > 50
    assert d["data"]["umfeld_m"] == 300
    assert d["data"]["hinweise"], "die Grenzen der Kennzahl gehören in die Antwort"
    assert "ODbL" in d["provenance"]["license"]
    assert "Statistische Ämter" in d["provenance"]["license"]


def test_scan_kachelt_den_cache(client):
    """Leichtes Schwenken innerhalb derselben 0,01°-Kachel darf weder Zensus
    noch Overpass erneut fragen."""
    p1 = {"west": 11.561, "sued": 48.121, "ost": 11.579, "nord": 48.139}
    client.get("/api/scan", params=p1)
    vorher = len(client.fake.calls)
    p2 = {"west": 11.562, "sued": 48.122, "ost": 11.578, "nord": 48.138}
    d = client.get("/api/scan", params=p2).json()
    assert len(client.fake.calls) == vorher, "Kachel-Cache griff nicht"
    assert d["provenance"]["cached"] is True


def test_scan_weist_unsinn_ab(client):
    fehler = [
        {"west": 11.6, "sued": 48.1, "ost": 11.4, "nord": 48.2},   # west>ost
        {"west": 2.0, "sued": 48.1, "ost": 2.05, "nord": 48.14},   # außerhalb
        {"west": 11.0, "sued": 48.0, "ost": 11.5, "nord": 48.05},  # zu breit
        {"west": 11.0, "sued": 48.0, "ost": 11.05, "nord": 48.5},  # zu hoch
    ]
    for p in fehler:
        r = client.get("/api/scan", params=p)
        assert r.status_code == 422, p
    zu_gross = client.get("/api/scan", params=fehler[2])
    assert "Übersichtsebene" in zu_gross.json()["detail"], (
        "die Abweisung muss auf das passende Werkzeug verweisen"
    )


# --------------------------------------------- Bericht, Verlauf, Neu prüfen


def test_bericht_seite_wird_ausgeliefert(client):
    r = client.get("/bericht", params={"punkt": 1})
    assert r.status_code == 200
    assert "Standortbericht" in r.text


def test_einzelner_punkt_liefert_zeile_und_payload(client):
    assert client.get("/api/points/9999").status_code == 404
    client.post("/api/points", json={
        "label": "Berichtstest", "lat": LAT, "lon": LON, "radius": R})
    pid = client.get("/api/points").json()["punkte"][0]["id"]
    d = client.get(f"/api/points/{pid}").json()
    assert d["label"] == "Berichtstest"
    assert d["zeile"]["gastro_gesamt"] > 100
    assert d["payload"]["bloecke"]["zensus"]["provenance"]["license"]
    # /api/points/vergleich darf nicht vom Pfadparameter abgefangen werden.
    assert client.get("/api/points/vergleich").status_code == 200


def test_pruefung_erkennt_neue_und_verschwundene_betriebe(client):
    """„Neu prüfen" muss die konkrete Veränderung benennen, nicht nur eine Zahl."""
    import copy

    from gastroviewer.sources.overpass import GASTRO_AMENITIES

    client.post("/api/points", json={
        "label": "Verlaufstest", "lat": LAT, "lon": LON, "radius": R})
    pid = client.get("/api/points").json()["punkte"][0]["id"]
    alt_gesamt = client.get(f"/api/points/{pid}").json()["zeile"]["gastro_gesamt"]

    kopie = copy.deepcopy(client.fake.overpass)
    opfer = next(
        e for e in kopie["elements"]
        if (e.get("tags") or {}).get("amenity") in GASTRO_AMENITIES
        and (e.get("tags") or {}).get("name")
    )
    kopie["elements"].remove(opfer)
    client.fake.overpass = kopie

    d = client.post(f"/api/points/{pid}/pruefung").json()
    namen = [g["name"] for g in d["verschwundene_betriebe"]]
    assert opfer["tags"]["name"] in namen
    assert d["neue_betriebe"] == []
    gesamt = next(v for v in d["veraendert"] if v["key"] == "gastro_gesamt")
    assert gesamt["alt"] == alt_gesamt and gesamt["neu"] == alt_gesamt - 1
    assert any("Begehung" in h for h in d["hinweise"]), (
        "ein verschwundener Betrieb ist zunächst nur eine OSM-Änderung"
    )

    # Der gespeicherte Punkt trägt jetzt den neuen Stand …
    zeile = client.get(f"/api/points/{pid}").json()["zeile"]
    assert zeile["gastro_gesamt"] == alt_gesamt - 1
    assert zeile["geprueft"], "das Prüfdatum gehört in die Vergleichstabelle"

    # … und der alte Stand liegt im Verlauf.
    v = client.get(f"/api/points/{pid}/verlauf").json()
    assert v["anzahl"] == 2
    assert v["staende"][0]["aktuell"] is False
    assert v["staende"][0]["zeile"]["gastro_gesamt"] == alt_gesamt
    assert v["staende"][-1]["aktuell"] is True
    assert v["staende"][-1]["zeile"]["gastro_gesamt"] == alt_gesamt - 1


def test_pruefung_fuer_unbekannten_punkt_meldet_404(client):
    assert client.post("/api/points/9999/pruefung").status_code == 404
    assert client.get("/api/points/9999/verlauf").status_code == 404


def test_loeschen_raeumt_den_verlauf_mit_auf(client):
    from gastroviewer.cache import Cache

    client.post("/api/points", json={
        "label": "Wegwerftest", "lat": LAT, "lon": LON, "radius": R})
    pid = client.get("/api/points").json()["punkte"][-1]["id"]
    client.post(f"/api/points/{pid}/pruefung")
    c = Cache(client.settings.db_path)
    assert c.list_verlauf(pid), "die Prüfung muss einen Verlaufseintrag anlegen"
    client.delete(f"/api/points/{pid}")
    assert c.list_verlauf(pid) == [], "gelöschter Punkt darf keine Verlaufsleichen lassen"

# --------------------------------------------------------- Datensicherung


def test_export_und_import_der_punkte(client):
    """Sichern und Einspielen: alles kommt wieder, Dubletten bleiben draußen."""
    client.post("/api/points", json={
        "label": "Sicherungstest", "lat": LAT, "lon": LON, "radius": R})
    pid = client.get("/api/points").json()["punkte"][-1]["id"]
    client.patch(f"/api/points/{pid}", json={"notiz": "Top-Lage", "bewertung": 2})
    client.post(f"/api/points/{pid}/pruefung")  # legt einen Verlaufseintrag an

    r = client.get("/api/points/export")
    assert r.status_code == 200
    assert "gastroviewer-punkte-" in r.headers["content-disposition"]
    sicherung = r.json()
    assert sicherung["format"] == "gastroviewer-punkte"
    p = next(x for x in sicherung["punkte"] if x["label"] == "Sicherungstest")
    assert p["notiz"] == "Top-Lage" and p["bewertung"] == 2
    assert len(p["verlauf"]) == 1

    # Einspielen in denselben Bestand: alles ist Dublette.
    d = client.post("/api/points/import", json=sicherung).json()
    assert d["neu"] == 0 and d["uebersprungen"] == len(sicherung["punkte"])

    # Punkt löschen, Sicherung einspielen: der Punkt ist wieder da — samt
    # Einschätzung und Verlauf.
    client.delete(f"/api/points/{pid}")
    d = client.post("/api/points/import", json=sicherung).json()
    assert d["neu"] == 1
    zeilen = client.get("/api/points/vergleich").json()["zeilen"]
    wieder = next(z for z in zeilen if z["label"] == "Sicherungstest")
    assert wieder["notiz"] == "Top-Lage"
    v = client.get(f"/api/points/{wieder['id']}/verlauf").json()
    assert v["anzahl"] == 2


def test_import_weist_fremde_dateien_ab(client):
    r = client.post("/api/points/import", json={"format": "irgendwas"})
    assert r.status_code == 422
    assert "keine Punkte-Sicherung" in r.json()["detail"]
    r = client.post("/api/points/import",
                    json={"format": "gastroviewer-punkte", "version": 99})
    assert r.status_code == 422


# ------------------------------------------------------- Franchise-Funktionen


def test_marke_endpunkt_liefert_treffer_und_cached(client):
    from gastroviewer.sources.overpass import GASTRO_AMENITIES

    fixture = client.fake.overpass
    gesucht = next(
        (e["tags"]["brand"] for e in fixture["elements"]
         if (e.get("tags") or {}).get("amenity") in GASTRO_AMENITIES
         and (e.get("tags") or {}).get("brand")),
        None)
    assert gesucht, "Fixture ohne Kettenbetrieb"

    r = client.get("/api/point/marke", params={
        "lat": LAT, "lon": LON, "marke": gesucht, "r": 10000})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] and d["data"]["anzahl"] > 0
    assert d["data"]["naechster_m"] is not None

    vorher = len(client.fake.calls)
    client.get("/api/point/marke", params={
        "lat": LAT, "lon": LON, "marke": gesucht, "r": 10000})
    assert len(client.fake.calls) == vorher, "Markensuche muss den Cache treffen"


def test_marke_weist_unsinn_ab(client):
    fehler = [
        {"lat": LAT, "lon": LON, "marke": "X", "r": 10000},        # zu kurz
        {"lat": LAT, "lon": LON, "marke": 'A"B', "r": 10000},      # Anführungszeichen
        {"lat": LAT, "lon": LON, "marke": "Subway", "r": 500},     # Radius zu klein
        {"lat": LAT, "lon": LON, "marke": "Subway", "r": 50000},   # Radius zu groß
    ]
    for p in fehler:
        assert client.get("/api/point/marke", params=p).status_code == 422, p


def test_kettenanteil_in_der_vergleichstabelle(client):
    client.post("/api/points", json={
        "label": "Kettentest", "lat": LAT, "lon": LON, "radius": R})
    d = client.get("/api/points/vergleich").json()
    z = next(x for x in d["zeilen"] if x["label"] == "Kettentest")
    assert isinstance(z["ketten_anteil"], float) and 0 < z["ketten_anteil"] < 100
    titel = {c["key"]: c["titel"] for c in d["spalten"]}
    assert "berechnet" in titel["ketten_anteil"], (
        "abgeleitete Werte müssen als berechnet beschriftet sein"
    )


def test_schaetzung_franchise_kostenprobe(client):
    basis = {"einwohner": 10000, "wettbewerber": 4, "besuche_je_einwohner": 60,
             "bon_min": 7, "bon_max": 10}

    # Ohne Sätze findet die Probe nicht statt.
    d = client.post("/api/schaetzung", json=basis).json()
    assert d["franchise"] is None

    # Mit Sätzen: reine Prozentrechnung, nachvollziehbar.
    d = client.post("/api/schaetzung", json={
        **basis, "franchisegebuehr_prozent": 5, "werbeabgabe_prozent": 3,
        "wareneinsatz_prozent": 30, "personalkosten_prozent": 30}).json()
    fr = d["franchise"]
    assert fr["summe_prozent"] == 68 and fr["verbleib_prozent"] == 32
    u_min, u_max = d["ergebnis"]["jahresumsatz_eur"]
    assert fr["verbleib_jahr_eur"] == [round(u_min * 0.32), round(u_max * 0.32)]
    assert fr["verbleib_monat_eur"][0] == round(u_min * 0.32 / 12)
    assert "Unternehmerlohn" in fr["hinweis"]

    # Sätze über 100 %: klare Ansage statt stiller Minuszahl.
    d = client.post("/api/schaetzung", json={
        **basis, "wareneinsatz_prozent": 60, "personalkosten_prozent": 45}).json()
    assert d["franchise"]["verbleib_prozent"] < 0
    assert any("trägt sich kein Standort" in w for w in d["franchise"]["warnungen"])

    # Negative Sätze weist die API ab.
    r = client.post("/api/schaetzung", json={**basis, "franchisegebuehr_prozent": -1})
    assert r.status_code == 422


# ------------------------------------------------ Verfügbares Einkommen


def test_einkommen_block_im_punkt_und_vergleich(client):
    d = client.get("/api/point", params={"lat": LAT, "lon": LON, "r": R}).json()
    e = d["bloecke"]["einkommen"]
    assert e["ok"] and e["data"]["kreis"]["wert_eur"] == 35467
    assert e["data"]["bund"]["wert_eur"] == 25830
    assert "Kreiswert" in e["provenance"]["note"]

    client.post("/api/points", json={
        "label": "Einkommenstest", "lat": LAT, "lon": LON, "radius": R})
    v = client.get("/api/points/vergleich").json()
    z = next(x for x in v["zeilen"] if x["label"] == "Einkommenstest")
    assert z["einkommen_kreis"] == 35467


def test_einkommen_endpunkt_und_kreiscache(client):
    r = client.get("/api/einkommen", params={"ags": "09162000"})
    assert r.status_code == 200
    assert r.json()["data"]["kreis"]["wert_eur"] == 35467
    vorher = client.fake.calls.count("einkommen")
    # Anderer Punkt, derselbe Kreis: der Wert ist identisch, der Cache
    # greift über den Kreisschlüssel, nicht über die Koordinate.
    client.get("/api/einkommen", params={"ags": "09162001"})
    assert client.fake.calls.count("einkommen") == vorher, "Kreis-Cache griff nicht"
    assert client.get("/api/einkommen", params={"ags": "9x"}).status_code == 422
    assert client.get("/api/einkommen", params={"ags": "abcde"}).status_code == 422


# ------------------------------------------------ Kreisprofil


def test_kreisprofil_block_im_punkt_und_vergleich(client):
    d = client.get("/api/point", params={"lat": LAT, "lon": LON, "r": R}).json()
    k = d["bloecke"]["kreisprofil"]
    assert k["ok"], k.get("error")
    werte = {i["schluessel"]: i for i in k["data"]["indikatoren"]}
    assert werte["uebernachtungen_je_ew"]["kreis"] == 13.2
    assert werte["et_je_1000_ew"]["kreis"] == 1159.1
    assert werte["arbeitslosenquote"]["kreis"] == 5.4
    assert werte["bev_entwicklung"]["kreis"] == 108.8
    assert k["data"]["gebiete"]["kreis"]["ags"] == "09162"
    assert "Kreiswerte" in k["provenance"]["note"]

    client.post("/api/points", json={
        "label": "Kreisprofiltest", "lat": LAT, "lon": LON, "radius": R})
    v = client.get("/api/points/vergleich").json()
    z = next(x for x in v["zeilen"] if x["label"] == "Kreisprofiltest")
    assert z["uebernachtungen_je_ew"] == 13.2
    assert z["et_je_1000_ew"] == 1159.1
    assert z["arbeitslosenquote"] == 5.4
    assert z["bev_entwicklung"] == 108.8


def test_klima_block_im_punkt_und_vergleich(client):
    d = client.get("/api/point", params={"lat": LAT, "lon": LON, "r": R}).json()
    k = d["bloecke"]["klima"]
    assert k["ok"], k.get("error")
    werte = {z["schluessel"]: z for z in k["data"]["kennzahlen"]}
    assert werte["sommertage"]["wert"] == 53.3
    assert werte["sommertage"]["station"]["name"] == "München-Stadt"
    assert werte["sonnenschein"]["wert"] == 1841.5
    assert "1991–2020" in k["provenance"]["stand"]

    client.post("/api/points", json={
        "label": "Klimatest", "lat": LAT, "lon": LON, "radius": R})
    v = client.get("/api/points/vergleich").json()
    z = next(x for x in v["zeilen"] if x["label"] == "Klimatest")
    assert z["sommertage"] == 53.3
    assert z["sonnenschein"] == 1841.5


def test_klima_dateien_cache_ist_landesweit(client):
    """Die zehn DWD-Dateien beantworten jeden Punkt in Deutschland — ein
    zweiter, ganz anderer Punkt darf keinen weiteren DWD-Abruf auslösen."""
    client.get("/api/point/klima", params={"lat": LAT, "lon": LON})
    vorher = client.fake.calls.count("dwd")
    assert vorher == 10  # 5 Parameter x (Werte + Stationsliste)
    client.get("/api/point/klima", params={"lat": 50.94, "lon": 6.96})
    assert client.fake.calls.count("dwd") == vorher, "Dateien-Cache griff nicht"


def test_pendler_block_im_punkt_und_vergleich(client):
    d = client.get("/api/point", params={"lat": LAT, "lon": LON, "r": R}).json()
    p = d["bloecke"]["pendler"]
    assert p["ok"], p.get("error")
    assert p["data"]["jahr"] == 2024
    assert p["data"]["einpendler"] == 529834
    assert p["data"]["saldo"] == 281155
    assert p["data"]["gemeinde"]["name"] == "München"
    assert len(p["data"]["verflechtung"]["herkunft"]) == 5
    assert "Gemeindewert" in p["provenance"]["note"]

    client.post("/api/points", json={
        "label": "Pendlertest", "lat": LAT, "lon": LON, "radius": R})
    v = client.get("/api/points/vergleich").json()
    z = next(x for x in v["zeilen"] if x["label"] == "Pendlertest")
    assert z["pendler_saldo"] == 281155
    assert z["einpendler_quote"] == 45.3


def test_pendler_endpunkt_und_gemeindecache(client):
    r = client.get("/api/pendler", params={"ags": "09162000"})
    assert r.status_code == 200
    assert r.json()["data"]["auspendler"] == 248679
    vorher = client.fake.calls.count("pendler")
    client.get("/api/pendler", params={"ags": "09162000"})
    assert client.fake.calls.count("pendler") == vorher, "Gemeinde-Cache griff nicht"
    assert client.get("/api/pendler", params={"ags": "0916"}).status_code == 422


def test_kreisprofil_endpunkt_und_kreiscache(client):
    r = client.get("/api/kreisprofil", params={"ags": "09162000"})
    assert r.status_code == 200
    themen = {i["thema"] for i in r.json()["data"]["indikatoren"]}
    assert {"Tourismus (Beherbergung)", "Erwerbstätige am Arbeitsort",
            "Arbeitsmarkt", "Bevölkerung"} <= themen
    vorher = client.fake.calls.count("kreisprofil")
    client.get("/api/kreisprofil", params={"ags": "09162001"})
    assert client.fake.calls.count("kreisprofil") == vorher, "Kreis-Cache griff nicht"
    assert client.get("/api/kreisprofil", params={"ags": "9x"}).status_code == 422


def test_point_overture_block_ohne_import(client):
    """Ohne lokalen Overture-Import: Block da, ehrliche Anleitung statt Zahlen."""
    d = client.get("/api/point", params={"lat": LAT, "lon": LON, "r": R}).json()
    ov = d["bloecke"]["overture"]
    assert ov["ok"] and ov["data"] == {"importiert": False}
    assert any("import-overture" in w for w in ov["warnings"])

    e = client.get("/api/point/overture",
                   params={"lat": LAT, "lon": LON, "r": R}).json()
    assert e["data"] == {"importiert": False}
