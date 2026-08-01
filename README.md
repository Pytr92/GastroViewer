# Standort-Datenterminal Deutschland

Punkt auf einer Deutschlandkarte anklicken → alle verfügbaren offenen Daten zu diesem
Punkt sehen. Gedacht für die Standortsuche eines Fast-Food-Betriebs: wer wohnt dort, wer
arbeitet dort, wer betreibt schon Gastronomie, wie gut ist die Anbindung.

**Das Werkzeug ist ein Daten-Browser, kein Prognose-Tool.** Jede angezeigte Zahl stammt
aus einer realen API-Antwort und trägt Quelle, Stand und Lizenz. Es gibt keine Konstante
im Code, die wie ein Messwert aussieht, und keine Umsatzschätzung.

Grundlage: [`spec-standort-datenterminal.md`](spec-standort-datenterminal.md) ·
Kontext: [`notizen-standort-flaeche.md`](notizen-standort-flaeche.md) ·
Endpunktprüfung: [`docs/endpoints-verified.md`](docs/endpoints-verified.md)

---

## Start

Läuft auf **macOS, Linux und Windows**. Voraussetzung: Python 3.10 oder neuer. Sonst
nichts — kein Docker, kein `make`, keine Datenbank zum Aufsetzen.

```bash
git clone https://github.com/Pytr92/GastroViewer.git
cd GastroViewer

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .

gastroviewer serve
```

Dann `http://127.0.0.1:8000` im Browser öffnen.

Ohne Installation geht auch `python -m gastroviewer serve` aus dem Projektverzeichnis,
sofern `fastapi`, `uvicorn` und `httpx` vorhanden sind.

### Kontaktadresse setzen (wichtig)

Nominatim verlangt einen identifizierenden `User-Agent` mit Kontaktadresse und antwortet
ohne ihn mit **HTTP 403**. Vor dem ersten ernsthaften Einsatz setzen:

```bash
export GASTROVIEWER_CONTACT="deine@mailadresse.de"     # Windows: set GASTROVIEWER_CONTACT=…
```

---

## Bedienung

| Aktion | Wirkung |
|---|---|
| Klick in die Karte | setzt den Punkt und lädt alle Blöcke |
| Marker ziehen | verschiebt den Punkt |
| Adresssuche | Nominatim, mit 1,1 s Verzögerung wegen des Limits von 1 Anfrage/s |
| Radius 300/600/900/1400 m | begrenzt alle Abfragen |
| Ebenen links oben | Zensus-Gitter, Gastronomie, Frequenzbringer, ÖPNV, Leerstände |
| Auswahl in der Legende | Zensus-Ebene: Einwohner, Anteil 18–49, Miete, Leerstand |
| Klick auf Zelle oder POI | zeigt die Rohwerte, wie sie vom Dienst kamen |
| „Punkt merken" | legt den Standort in die Vergleichstabelle (bleibt in SQLite) |
| „Vergleich" | Kandidaten nebeneinander, mit CSV-Export |
| „Neu laden" | umgeht den Cache für diesen Punkt |
| „Export JSON/CSV" | ein Punkt mit Zeitstempel und Quellenangaben je Zeile |

---

## Kommandos

```bash
gastroviewer serve                       # Server starten (Standard)
gastroviewer serve --port 8080           # anderer Port
gastroviewer status                      # Cache- und GTFS-Status
gastroviewer clear-cache                 # Cache leeren
gastroviewer clear-cache --quelle zensus # nur eine Quelle
gastroviewer import-gtfs --bbox 47.9,11.2,48.4,11.9
```

Alle Daten liegen unter `~/.gastroviewer` (überschreibbar mit `GASTROVIEWER_DATA_DIR`).
Cache leeren geht auch, indem man `~/.gastroviewer/gastroviewer.sqlite` löscht.

### GTFS-Import (ÖPNV-Abfahrten)

Der ÖPNV-Block bleibt leer, bis ein Fahrplan importiert ist. Alles andere funktioniert
auch ohne.

```bash
# Empfohlen: auf die Zielregion begrenzen (min_lat,min_lon,max_lat,max_lon)
gastroviewer import-gtfs --bbox 47.9,11.2,48.4,11.9

# Ganz Deutschland — dauert deutlich länger und braucht mehrere Gigabyte
gastroviewer import-gtfs

# Bereits geladenes ZIP verwenden
gastroviewer import-gtfs --file ~/Downloads/latest.zip --bbox 47.9,11.2,48.4,11.9
```

Quelle ist der freie Deutschland-Feed von [gtfs.de](https://gtfs.de/) (CC BY 4.0,
Datengrundlage DELFI e.V.), rund 259 MB, täglich aktualisiert, **ohne Registrierung**.
Kleinere Feeds gibt es unter `--url`:
`https://download.gtfs.de/germany/rv_free/latest.zip` (Regionalverkehr, 10 MB),
`nv_free` (Nahverkehr), `fv_free` (Fernverkehr).

Gezählt werden die Abfahrten an einem **konkreten, benannten Werktag** (dem nächsten
Dienstag im Gültigkeitszeitraum), nicht ein Durchschnitt. Verkehrstage stammen aus
`calendar.txt` einschließlich der Ausnahmen aus `calendar_dates.txt`.

Läuft der Fahrplan ab, meldet der Block das und der Import wird einfach wiederholt.

---

## Quellen und Lizenzen

| Quelle | Wofür | Lizenz | Cache-TTL |
|---|---|---|---|
| [Zensus 2022, 100-m-Gitter](https://services2.arcgis.com/jUpNdisbWqRpMo35/arcgis/rest/services/Zensus2022_grid_final/FeatureServer) | Bevölkerung, Alter, Haushalte, Miete, Leerstand, Baualter | © Statistische Ämter des Bundes und der Länder 2024 · dl-de/by-2-0 · GeoBasis-DE/BKG 2024 | 30 Tage |
| [OpenStreetMap / Overpass](https://overpass-api.de/) | Gastronomie, Frequenzbringer, ÖPNV, Leerstand, Linien | ODbL 1.0, © OpenStreetMap-Mitwirkende | 24 h |
| [Nominatim](https://nominatim.openstreetmap.org/) | Adresse, Gemeinde, Ortsteil, PLZ | ODbL 1.0, © OpenStreetMap-Mitwirkende | 30 Tage |
| [gtfs.de](https://gtfs.de/) | Abfahrten je Haltestelle und Stunde | CC BY 4.0, Datengrundlage DELFI e.V. | lokal, kein Cache |
| OSM-Kacheln | Kartenhintergrund | ODbL 1.0 | Browser |

Verlinkt, aber **nicht abgerufen**: BORIS-D und die Landesportale für Bodenrichtwerte,
hystreet, Pendleratlas, INKAR, Regionalstatistik, Zensusatlas, Leerstandsmelder,
nexxt-change, DEHOGA, ahgz immo, Brauerei-Pachtbörsen, ECE, MEC, DB InfraGO.

> **hystreet:** Im kostenfreien Modell ist die **gewerbliche Nutzung untersagt**. Für eine
> Standortentscheidung vorher den Tarif klären. hystreet ist Datenbankhersteller nach
> § 87a UrhG, Quellenangabe ist Pflicht.

### Rücksicht auf die Dienste

Overpass ist ein Spendenprojekt, Nominatim läuft auf Spendenhardware. Deshalb:

- **eine** kombinierte Overpass-Abfrage je Punkt statt einer pro Kategorie
- Mindestabstand zwischen Abfragen, serialisiert auch bei parallelen Anfragen
- Nominatim strikt auf 1 Anfrage/Sekunde gedrosselt
- jede Antwort wird zwischengespeichert; der zweite Aufruf desselben Punkts erzeugt
  **keinen** ausgehenden Verkehr (nachprüfbar unter `/api/outbound`)

---

## Was dieses Werkzeug bewusst nicht tut

- **Keine Umsatzschätzung.** Ein Vorgänger hat aus Einwohnerzahl, Wettbewerbsdichte und
  frei gewählten Distanzgewichten einen Jahresumsatz „berechnet". Die Eingangsdaten waren
  echt, die Gewichte erfunden, das Ergebnis sah präzise aus und war es nicht.
- **Keine Bewertung und keine Rangliste.** Die Vergleichstabelle hebt nur den jeweils
  höchsten Wert hervor, ohne ihn als „besser" zu bezeichnen.
- **Kein Scraping** von Immobilienportalen. ImmoScout24 und Immowelt haben aktiven
  Bot-Schutz; ihn zu umgehen ist der rechtlich kritischste Punkt beim Scraping. Der Weg
  über Suchagenten und ein Sammelpostfach steht in `notizen-standort-flaeche.md` §4.2.
- **Keine geratenen URLs.** Für Bundesländer ohne bestätigtes Bodenrichtwert-Portal wird
  ein Suchlink erzeugt, kein erfundener Link.

## Bekannte Grenzen der Daten

Diese Hinweise stehen auch in der Oberfläche, nicht nur hier:

- **OSM ist unvollständig**, besonders bei kleinen Imbissen und Neueröffnungen. Die
  angezeigte Wettbewerbsdichte ist eine **Untergrenze**.
- **Zensus-Stichtag ist der 15.05.2022.** Neubaugebiete danach fehlen. Über den Werten
  liegt zum Datenschutz eine stochastische Überlagerung (Cell-Key-Methode) — Einzelwerte
  summieren sich nicht zwingend zur Summe. Die Oberfläche weist die Abweichung aus, statt
  sie wegzurechnen. Zellen ohne Einwohner fehlen im Datensatz vollständig.
- **`opening_hours` wird nicht ausgewertet**, sondern unverändert angezeigt. Die Syntax
  kennt Feiertage, Saisons und Ausnahmen, die ein einfacher Parser falsch verstehen würde.
- **Passantenströme fehlen komplett.** Fußgängerzone und Seitenstraße sind in diesen Daten
  nicht unterscheidbar. Dafür hystreet, die GTFS-Abfahrten und eigene Zählung.
- **Die Umsatzstärke der Wettbewerber ist unbekannt.**
- **Flächen mit fernem Mittelpunkt:** Overpass prüft den Umkreis gegen die Geometrie,
  dieses Werkzeug misst zum Mittelpunkt. Ein Universitäts- oder Klinikgelände kann in den
  Umkreis hineinreichen, während sein Mittelpunkt Kilometer entfernt liegt. Solche Objekte
  sind gekennzeichnet.
- **Bodenrichtwerte werden nicht abgerufen.** BORIS-D deckt Bayern, Baden-Württemberg,
  Saarland, Schleswig-Holstein und Mecklenburg-Vorpommern aus rechtlichen Gründen nicht ab.

---

## Konfiguration

Alles über Umgebungsvariablen, alles optional:

| Variable | Vorgabe |
|---|---|
| `GASTROVIEWER_CONTACT` | Projekt-URL — **auf eine eigene Adresse setzen** |
| `GASTROVIEWER_HOST` / `GASTROVIEWER_PORT` | `127.0.0.1` / `8000` |
| `GASTROVIEWER_DATA_DIR` | `~/.gastroviewer` |
| `GASTROVIEWER_OVERPASS_ENDPOINTS` | overpass-api.de, kumi.systems, private.coffee |
| `GASTROVIEWER_NOMINATIM_MIN_INTERVAL` | `1.0` — nicht ohne Grund verringern |
| `GASTROVIEWER_OVERPASS_MIN_INTERVAL` | `1.0` |
| `GASTROVIEWER_TTL_OSM` / `_ZENSUS` / `_NOMINATIM` | 24 h / 30 d / 30 d |
| `GASTROVIEWER_ZENSUS_PAGE_SIZE` / `_MAX_PAGES` | `2000` / `10` |
| `GASTROVIEWER_GTFS_URL` | gtfs.de Komplettfeed |

---

## API

| Endpunkt | Zweck |
|---|---|
| `GET /api/point?lat=&lon=&r=` | alles auf einmal |
| `GET /api/point/{adresse\|zensus\|osm\|gtfs\|links}` | je Quelle einzeln (nutzt die Oberfläche) |
| `GET /api/geocode?q=` | Adresssuche |
| `GET /api/points` · `POST /api/points` · `DELETE /api/points/{id}` | gemerkte Punkte |
| `GET /api/points/vergleich` | Vergleichstabelle |
| `GET /api/export/point.json` · `point.csv` · `vergleich.csv` | Export |
| `GET /api/stats` · `GET /api/outbound` | Cache-Zustand, Protokoll der echten Abrufe |
| `DELETE /api/cache?quelle=` | Cache leeren |
| `GET /api/health` | Zustand, GTFS-Status |

Interaktive Doku unter `/docs`.

Jede Quellenantwort hat dieselbe Form:

```json
{
  "name": "zensus",
  "ok": true,
  "data": { "…": "…" },
  "provenance": { "source": "…", "stand": "…", "license": "…", "cached": false },
  "error": null,
  "warnings": []
}
```

Fällt eine Quelle aus, ist nur ihr `ok` gleich `false` und `error` nennt die konkrete
Ursache (Timeout, HTTP-Status, Parse-Fehler). Die übrigen Blöcke sind davon unberührt.

---

## Tests

```bash
pip install -e ".[dev]"
pytest
```

Die Tests laufen ausschließlich gegen die in Phase 0 aufgezeichneten **echten** Antworten
unter `fixtures/`, nicht gegen ausgedachte Testdaten. Sie brauchen kein Netz.

---

## Aufbau

```
gastroviewer/
  config.py          Einstellungen aus Umgebungsvariablen
  cache.py           SQLite-Cache mit TTL + Protokoll der echten Abrufe
  ratelimit.py       Mindestabstand je Dienst, serialisiert
  http.py            alle ausgehenden Aufrufe, Fehler → benennbare Ursachen
  service.py         führt die Quellen zusammen, isoliert Ausfälle
  api.py             HTTP-Schnittstelle
  __main__.py        CLI: serve, import-gtfs, clear-cache, status
  sources/
    zensus.py        100-m-Gitter, Paginierung, null-Behandlung, Aggregate
    overpass.py      eine kombinierte Abfrage, Klassifikation, Spiegel-Fallback
    nominatim.py     Geocoding und Reverse-Geocoding
    gtfs.py          Import und Abfahrtszählung
    boris.py         Bodenrichtwert-Portale je Bundesland
    links.py         Deep-Links aus Spec §4.6 und den Notizen
  static/            Oberfläche (Leaflet lokal, kein CDN)
fixtures/            echte API-Antworten aus Phase 0, Grundlage der Tests
docs/                Endpunktprüfung
```
