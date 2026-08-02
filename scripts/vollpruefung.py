"""Vollprüfung: jeder API-Endpunkt einmal live, mit inhaltlicher Bewertung.

Die dritte Prüfebene neben ``pytest`` (Rechenwege, ohne Netz) und
``scripts/uitest.py`` (Oberfläche im Browser): alle Routen der API werden
gegen einen laufenden Server aufgerufen — mit echten Abrufen bei den
Fachdiensten, zwei davon per ``refresh=true`` erzwungen, damit „live" belegt
ist und nicht nur der Cache antwortet.

Geprüft wird nicht „antwortet mit 200", sondern: kommt ein sinnvoller Wert
zurück, trägt er Quelle und Stand, und stimmt er mit einer unabhängigen
Erwartung überein (A9: 111.624 Kfz/Tag; Isarauen: HQ 100 der Isar; Köln:
Bodenrichtwert vorhanden).

Aufruf::

    gastroviewer serve --port 8011 &
    python scripts/vollpruefung.py http://127.0.0.1:8011

Braucht Netz und einen importierten GTFS-Fahrplan. Exitcode 0 = ohne Befund,
1 = Befunde.
"""

import json
import sys
import time
import urllib.parse
import urllib.request

BASIS = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
M = (48.1372, 11.5755)     # Marienplatz
ISARAUEN = (48.1050, 11.5530)
KOELN = (50.9413, 6.9583)

befunde = []
geprueft = 0


def hole(pfad, params=None, methode="GET", body=None, erwartet=200):
    url = BASIS + pfad + (("?" + urllib.parse.urlencode(params)) if params else "")
    req = urllib.request.Request(url, method=methode)
    daten = None
    if body is not None:
        daten = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, daten, timeout=300) as r:
            roh = r.read()
            code = r.status
    except urllib.error.HTTPError as e:
        roh = e.read()
        code = e.code
    dauer = time.perf_counter() - t0
    if code != erwartet:
        raise AssertionError(f"HTTP {code} statt {erwartet}: {roh[:120]}")
    try:
        return json.loads(roh), dauer, len(roh)
    except json.JSONDecodeError:
        return roh.decode("utf-8", "replace"), dauer, len(roh)


def pruefe(name, fn):
    global geprueft
    geprueft += 1
    try:
        ergebnis = fn()
        print(f"[ OK ] {name}")
        if ergebnis:
            print(f"       {ergebnis}")
    except Exception as e:  # noqa: BLE001
        befunde.append(f"{name}: {e}")
        print(f"[FAIL] {name}\n       {type(e).__name__}: {e}")


P = {"lat": M[0], "lon": M[1], "r": 600}

# ------------------------------------------------------ Basis und Betrieb

def t_health():
    d, dauer, _ = hole("/api/health")
    assert d["status"] == "ok" and "gastroviewer/" in d["user_agent"]
    assert d["gtfs"]["importiert"] is True, "GTFS-Fahrplan fehlt"
    return f"GTFS importiert, {dauer*1000:.0f} ms"

def t_stats():
    d, _, _ = hole("/api/stats")
    assert d["outbound_24h"] >= 0 and "outbound_24h_je_dienst" in d
    assert d["endpunkte"]["overpass"], "Endpunktliste leer"
    return f"{d['total']} Cacheeinträge, 24h: {d['outbound_24h']} Abrufe"

def t_outbound():
    d, _, _ = hole("/api/outbound", {"seit": time.time() - 3600})
    for e in d["eintraege"][:3]:
        assert e["url"].startswith("http") and e["source"]
    return f"{d['anzahl']} Einträge der letzten Stunde, jede mit Quelle und URL"

# ---------------------------------------------------------- Punktquellen

def t_point_gesamt():
    d, dauer, groesse = hole("/api/point", P)
    bl = d["bloecke"]
    fehlend = [n for n in ("adresse", "zensus", "osm", "gtfs", "radzaehlung",
                           "verkehrsmenge", "planung") if n not in bl]
    assert not fehlend, f"Blöcke fehlen: {fehlend}"
    kaputt = [n for n, b in bl.items() if not b.get("ok")]
    assert not kaputt, f"Blöcke gescheitert: {kaputt}"
    ohne_quelle = [n for n, b in bl.items()
                   if not ((b.get("provenance") or {}).get("source"))]
    assert not ohne_quelle, f"ohne Quellenangabe: {ohne_quelle}"
    return f"7 Blöcke ok, alle mit Quelle · {dauer:.1f} s · {groesse/1024:.0f} kB"

def t_adresse():
    d, _, _ = hole("/api/point/adresse", {"lat": M[0], "lon": M[1]})
    a = d["data"]
    assert a["gemeinde"] == "München" and a["plz"] == "80331"
    return f"{a['strasse'] or a['name']}, {a['plz']} {a['gemeinde']}"

def t_zensus_live():
    """refresh=true erzwingt den echten Abruf — Nachweis, dass live geht."""
    d, dauer, _ = hole("/api/point/zensus", {**P, "refresh": "true"})
    assert d["provenance"]["cached"] is False, "trotz refresh aus dem Cache"
    ew = d["data"]["bevoelkerung"]["einwohner"]
    assert ew["wert"] == 10002 and ew["zellen"] == 110
    assert "15.05.2022" in d["provenance"]["stand"]
    return f"live in {dauer:.1f} s: 10.002 Einwohner aus 110 Zellen, Stand ausgewiesen"

def t_osm_live():
    d, dauer, _ = hole("/api/point/osm", {**P, "refresh": "true"})
    assert d["provenance"]["cached"] is False
    stand = d["provenance"]["stand"]
    assert stand and stand.startswith("OSM-Datenstand 2026-08"), (
        f"OSM-Stand nicht von heute: {stand}"
    )
    g = d["data"]["zusammenfassung"]["gastronomie"]
    assert g["gesamt"] > 300 and g["nach_entfernung"][0]["bis_m"] == 150
    return f"live in {dauer:.1f} s: {g['gesamt']} Betriebe, Datenstand {stand[:34]}…"

def t_gtfs():
    d, _, _ = hole("/api/point/gtfs", P)
    x = d["data"]
    assert x["abfahrten_gesamt"] > 4000 and x["abfahrten_mittag"] > 500
    assert x["referenzdatum"] and x["referenz_wochentag"] == "Dienstag"
    return (f"{x['abfahrten_gesamt']} Abfahrten am {x['referenzdatum']}, "
            f"davon {x['abfahrten_mittag']} mittags — konkreter Tag, kein Mittel")

def t_radzaehlung():
    d, _, _ = hole("/api/point/radzaehlung", P)
    n = d["data"]["naechste"]
    assert n["summe_vorjahr_jahr"] == 2025, f"Vorjahr veraltet: {n['summe_vorjahr_jahr']}"
    assert n["summe_laufender_monat"] and n["summe_laufender_monat"] > 0, (
        "kein laufender Monat — dann wäre es nicht live"
    )
    return (f"{n['name']}: {n['summe_vorjahr']} Fahrten 2025, laufender Monat "
            f"{n['summe_laufender_monat']} — der Dienst liefert aktuelle Zahlen")

def t_verkehrsmenge():
    d, _, _ = hole("/api/point/verkehrsmenge",
                   {"lat": 48.2100, "lon": 11.6150, "r": 600})
    s = d["data"]["staerkste"]
    assert s["dtv_kfz"] == 111624, f"A9-Wert weicht ab: {s['dtv_kfz']}"
    assert "2021" in d["provenance"]["stand"], "der Jahrgang 2021 muss dastehen"
    return f"A9: {s['dtv_kfz']} Kfz/Tag — Stand 2021 ist ausgewiesen, nicht versteckt"

def t_gehweg():
    d, _, _ = hole("/api/point/gehweg", P)
    x = d["data"]
    assert x["knoten"] > 10000 and x["zensus"]["erschliessungsgrad"] > 0
    assert x["flaeche"], "keine Kartenpunkte"
    return (f"{x['knoten']} Knoten, Erschließung {x['zensus']['erschliessungsgrad']} %, "
            f"{len(x['flaeche'])} Kartenpunkte")

def t_planung():
    d, _, _ = hole("/api/point/planung",
                   {"lat": ISARAUEN[0], "lon": ISARAUEN[1], "r": 600})
    hw = d["data"]["hochwasser"]
    assert hw["hq_100"] is True and hw["gebiete"][0]["gewaesser"] == "Isar"
    return "Isarauen: HQ 100 der Isar — unabhängig bestätigt"

def t_links():
    d, _, _ = hole("/api/point/links", P)
    gruppen = {g["gruppe"] for g in d["weiterfuehrend"]}
    assert "Passantenfrequenz" in gruppen
    kaputte = [l["url"] for g in d["weiterfuehrend"] for l in g["eintraege"]
               if not l["url"].startswith("https://")]
    assert not kaputte, f"unsichere Links: {kaputte}"
    return f"{len(gruppen)} Linkgruppen, alle URLs https"

def t_gitter():
    d, dauer, _ = hole("/api/gitter", {"ebene": "1km", "west": 11.36, "sued": 48.06,
                                       "ost": 11.72, "nord": 48.25})
    z = d["data"]["zellen"]
    assert len(z) > 500, f"nur {len(z)} Zellen über München"
    top = max((x for x in z if x["einwohner"]), key=lambda x: x["einwohner"])
    assert top["einwohner"] > 15000, "die dichteste Münchner 1-km-Zelle fehlt"
    d2, _, _ = hole("/api/gitter", {"ebene": "10km", "west": 8.95, "sued": 47.25,
                                    "ost": 13.85, "nord": 50.55})
    assert len(d2["data"]["zellen"]) > 1000, "ganz Bayern in 10 km unvollständig"
    return (f"München {len(z)} Zellen (1 km, dichteste {top['einwohner']} Einw.), "
            f"Bayern {len(d2['data']['zellen'])} Zellen (10 km) · {dauer:.1f} s")

# --------------------------------------------------------------- Suche

def t_scan():
    d, dauer, groesse = hole("/api/scan", {
        "west": M[1] - 0.012, "sued": M[0] - 0.008,
        "ost": M[1] + 0.012, "nord": M[0] + 0.008})
    assert d["ok"], d.get("error")
    zellen = d["data"]["zellen"]
    assert len(zellen) > 100, f"nur {len(zellen)} Zellen um den Marienplatz"
    assert d["data"]["betriebe_gesamt"] > 100, "die Innenstadt hat >100 Betriebe"
    assert d["data"]["umfeld_m"] == 300
    mit_wert = [z for z in zellen if z["je_betrieb"] is not None]
    assert mit_wert, "keine Zelle mit Einwohner-je-Betrieb-Wert"
    assert "ODbL" in d["provenance"]["license"]
    hole("/api/scan", {"west": 11.0, "sued": 48.0, "ost": 11.5, "nord": 48.05},
         erwartet=422)
    return (f"{len(zellen)} Zellen, {d['data']['betriebe_gesamt']} Betriebe · "
            f"{dauer:.1f} s · {groesse/1024:.0f} kB · Übergröße → 422")

def t_geocode():
    d, _, _ = hole("/api/geocode", {"q": "Sendlinger Tor München"})
    t = d["data"][0]
    assert 48.13 < t["lat"] < 48.14 and t["display_name"]
    return f"Treffer: {t['display_name'][:60]}"

# ----------------------------------------------------------------- WMS

def t_wms_register():
    d, _, _ = hole("/api/wms")
    assert len(d["dienste"]) == 7 and len(d["ohne_dienst"]) == 9
    return "7 verifizierte Länderdienste, 9 mit benanntem Grund ohne"

def t_wms_nrw():
    d, _, _ = hole("/api/wms", {"bundesland_code": "05"})
    assert d["verfuegbar"] and d["layers"]
    return f"NRW: Layer {d['layers']}"

def t_wms_ebenen():
    d, _, _ = hole("/api/wms/ebenen", {"bundesland_code": "09"})
    s = {e["schluessel"] for e in d["ebenen"]}
    assert s == {"by_dop40", "by_verkehrsmengen", "by_laerm", "by_alkis"}
    return "Bayern: Luftbild, Verkehrsmengen, Lärm, ALKIS"

def t_brw_live():
    d, _, _ = hole("/api/wms/bodenrichtwert",
                   {"lat": KOELN[0], "lon": KOELN[1], "bundesland_code": "05"})
    felder = {f["feld"]: f["wert"] for f in (d["data"] or {}).get("felder") or []}
    assert felder.get("Bodenrichtwert"), f"kein Bodenrichtwert: {list(felder)[:6]}"
    return (f"Köln live: {felder['Bodenrichtwert']} €/m², Datensatz vom "
            f"{felder.get('Aktualität dieses Datensatzes', '?')[:10]}")

# ------------------------------------------------------------ Schätzung

def t_schaetzung_vorgaben():
    d, _, _ = hole("/api/schaetzung/vorgaben", P)
    assert d["einwohner"] == 10002 and "Zensus" in d["einwohner_herkunft"]
    assert d["gehweg_alternative"], "Gehweg-Angebot fehlt trotz Cache"
    return (f"vorbefüllt: {d['einwohner']} Einwohner, Angebot "
            f"{d['gehweg_alternative']['einwohner']} zu Fuß")

def t_schaetzung_rechnen():
    d, _, _ = hole("/api/schaetzung", methode="POST", body={
        "einwohner": 10002, "wettbewerber": 33, "besuche_je_einwohner": 60.3,
        "bon_min": 7.15, "bon_max": 10.21, "kalibrierung_umsatz_eur": 450000})
    lo, hi = d["ergebnis"]["jahresumsatz_eur"]
    assert lo < hi and d["kalibrierung"]["faktor"] > 1
    assert "keine Prognose" in d["beschriftung"]
    return f"Spanne {lo}–{hi} €, Prüfstein Faktor {d['kalibrierung']['faktor']}"

def t_schaetzung_lehnt_unsinn_ab():
    hole("/api/schaetzung", methode="POST",
         body={"einwohner": -5, "wettbewerber": 0, "besuche_je_einwohner": 60,
               "bon_min": 7, "bon_max": 10}, erwartet=422)
    return "negative Einwohner → HTTP 422"

# --------------------------------------------------- Punkte und Export

MERK_ID = {}

def t_punkt_merken():
    d, _, _ = hole("/api/points", methode="POST",
                   body={"label": "Vollprüfung", "lat": M[0], "lon": M[1], "radius": 600})
    MERK_ID["id"] = d["id"]
    return f"gemerkt als #{d['id']}"

def t_punkt_notiz():
    hole(f"/api/points/{MERK_ID['id']}", methode="PATCH",
         body={"notiz": "Prüflauf", "bewertung": 2})
    d, _, _ = hole("/api/points/vergleich")
    z = next(x for x in d["zeilen"] if x["id"] == MERK_ID["id"])
    assert z["notiz"] == "Prüflauf" and z["bewertung"] == 2
    return "Notiz und Note gespeichert und im Vergleich sichtbar"

def t_punkt_einzeln():
    d, _, _ = hole(f"/api/points/{MERK_ID['id']}")
    assert d["label"] == "Vollprüfung" and d["zeile"]["gastro_gesamt"] > 50
    assert d["payload"]["bloecke"]["zensus"]["provenance"]["license"]
    hole("/api/points/99999", erwartet=404)
    return f"Punkt #{MERK_ID['id']} mit Zeile und Payload, Unbekanntes → 404"

def t_pruefung():
    d, dauer, _ = hole(f"/api/points/{MERK_ID['id']}/pruefung", methode="POST")
    assert d["geprueft_am"] and isinstance(d["veraendert"], list)
    assert any("Begehung" in h for h in d["hinweise"])
    v, _, _ = hole(f"/api/points/{MERK_ID['id']}/verlauf")
    assert v["anzahl"] >= 2 and v["staende"][-1]["aktuell"] is True
    return (f"neu geprüft in {dauer:.1f} s, {len(d['veraendert'])} Veränderung(en), "
            f"{v['anzahl']} Stände im Verlauf")

def t_bericht():
    d, _, _ = hole("/bericht", {"punkt": MERK_ID["id"]})
    assert "Standortbericht" in d and "bericht.js" in d
    return "Berichtsseite wird ausgeliefert"

def t_vergleich():
    d, _, _ = hole("/api/points/vergleich")
    assert d["gruppen"] and d["spalten"][0]["key"] == "label"
    return f"{len(d['zeilen'])} Zeilen, {len(d['spalten'])} Spalten, {len(d['gruppen'])} Gruppen"

def t_export_json():
    d, _, _ = hole("/api/export/point.json", P)
    assert d["meta"]["erzeugt"] and d["bloecke"]["zensus"]["provenance"]["license"]
    return "Zeitstempel und Lizenzen im Export"

def t_export_csv():
    d, _, _ = hole("/api/export/point.csv", P)
    assert "Zensus 2022" in d and "€/m²" in d and "Untergrenze" in d
    return "Kennzahlen mit Quelle je Zeile, Grenzen enthalten"

def t_export_vergleich():
    d, _, _ = hole("/api/export/vergleich.csv")
    assert "Eigene Notiz" in d.splitlines()[0] and "Prüflauf" in d
    return "alle Spalten samt eigener Notiz"

def t_punkt_loeschen():
    hole(f"/api/points/{MERK_ID['id']}", methode="DELETE")
    hole(f"/api/points/{MERK_ID['id']}", methode="DELETE", erwartet=404)
    return "gelöscht, zweites Löschen sauber 404"

def t_validierung():
    hole("/api/point", {"lat": 35.0, "lon": 11.5, "r": 600}, erwartet=422)
    hole("/api/point", {**P, "r": 20}, erwartet=422)
    return "außerhalb Deutschlands und Mini-Radius → 422"

def t_cache_wirkt():
    d1, _, _ = hole("/api/point", P)
    d2, _, _ = hole("/api/point", P)
    assert d2["meta"]["outbound_requests"] == 0 and d2["meta"]["aus_cache"]
    return "zweiter Aufruf: 0 ausgehende Abrufe"


ALLE = [
    ("GET /api/health", t_health),
    ("GET /api/stats", t_stats),
    ("GET /api/outbound", t_outbound),
    ("GET /api/point (alle Quellen)", t_point_gesamt),
    ("GET /api/point/adresse", t_adresse),
    ("GET /api/point/zensus — Live-Abruf erzwungen", t_zensus_live),
    ("GET /api/point/osm — Live-Abruf erzwungen", t_osm_live),
    ("GET /api/point/gtfs", t_gtfs),
    ("GET /api/point/radzaehlung — Aktualität", t_radzaehlung),
    ("GET /api/point/verkehrsmenge", t_verkehrsmenge),
    ("GET /api/point/gehweg", t_gehweg),
    ("GET /api/point/planung", t_planung),
    ("GET /api/point/links", t_links),
    ("GET /api/gitter — Übersicht München + Bayern", t_gitter),
    ("GET /api/scan — Flächen-Scan Innenstadt, live", t_scan),
    ("GET /api/geocode", t_geocode),
    ("GET /api/wms (Register)", t_wms_register),
    ("GET /api/wms?bundesland_code=05", t_wms_nrw),
    ("GET /api/wms/ebenen (Bayern)", t_wms_ebenen),
    ("GET /api/wms/bodenrichtwert — live NRW", t_brw_live),
    ("GET /api/schaetzung/vorgaben", t_schaetzung_vorgaben),
    ("POST /api/schaetzung", t_schaetzung_rechnen),
    ("POST /api/schaetzung (Abweisung)", t_schaetzung_lehnt_unsinn_ab),
    ("POST /api/points", t_punkt_merken),
    ("PATCH /api/points/{id}", t_punkt_notiz),
    ("GET /api/points/{id}", t_punkt_einzeln),
    ("POST /api/points/{id}/pruefung — Live-Abruf erzwungen", t_pruefung),
    ("GET /bericht", t_bericht),
    ("GET /api/points/vergleich", t_vergleich),
    ("GET /api/export/point.json", t_export_json),
    ("GET /api/export/point.csv", t_export_csv),
    ("GET /api/export/vergleich.csv", t_export_vergleich),
    ("DELETE /api/points/{id}", t_punkt_loeschen),
    ("Validierung (422-Pfade)", t_validierung),
    ("Cache-Nachweis", t_cache_wirkt),
]

print(f"Vollprüfung gegen {BASIS} — {len(ALLE)} Prüfungen")
print("=" * 74)
for name, fn in ALLE:
    pruefe(name, fn)
print("=" * 74)
if befunde:
    print(f"{len(befunde)} BEFUND(E):")
    for b in befunde:
        print("  ·", b)
    sys.exit(1)
print(f"Alle {geprueft} Prüfungen ohne Befund.")
