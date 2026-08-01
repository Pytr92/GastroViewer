# SPEC — Standort-Datenterminal Deutschland

Build-Auftrag für eine Claude-Code-Session.
Begleitdatei: `notizen-standort-flaeche.md` (Kontext, keine Anforderungen).

---

## 1. Ziel

Ein lokal laufendes Werkzeug: **Punkt auf einer Deutschlandkarte anklicken → alle
verfügbaren offenen Daten zu diesem Punkt sehen.**

Anwendungsfall: Standortsuche für einen Fast-Food-Betrieb (Franchise). Der Nutzer
vergleicht mehrere Kandidatenadressen und will je Punkt wissen, wer dort wohnt, wer
dort arbeitet, wer schon Gastronomie betreibt, wie gut die Anbindung ist und was das
Umfeld an Frequenz erzeugt.

### Das Produkt ist ein Daten-Browser, kein Prognose-Tool.

Erste Priorität ist, dass jede angezeigte Zahl **echt, aktuell und nachvollziehbar
zitiert** ist. Jeder Wert bekommt sichtbar Quelle und Stand. Lieber ein Feld weniger
als ein Feld, das geraten ist.

### Nicht-Ziele (bewusst)

- **Kein Umsatzmodell in Phase 1–3.** Ein Vorgänger dieses Tools hat aus Einwohnerzahl,
  Wettbewerbsdichte und Distanzgewichten einen Jahresumsatz „berechnet". Die Eingangsdaten
  waren echt, die Gewichte frei erfunden. Das Ergebnis sah präzise aus und war es nicht.
  Falls später gewünscht: separater, klar als Schätzung markierter Reiter — siehe §9.
- Keine Nutzerkonten, kein Deployment, keine Cloud. Läuft auf `localhost`.
- Kein Scraping von Immobilienportalen (Bot-Schutz, AGB — siehe Notizen-Datei).

---

## 2. Architektur

**Frontend allein reicht nicht.** Ein reiner Browser-Client scheitert an CORS, an
Rate-Limits und daran, dass GTFS ein 1-GB-Download ist. Deshalb:

```
Browser (Leaflet-Karte)
        │  fetch /api/point?lat=..&lon=..&r=..
        ▼
Lokaler Backend-Server  ──────► externe APIs
   · Proxy (löst CORS)
   · Cache (SQLite, TTL)         ── schont die freien Dienste
   · Rate-Limiter                ── Nominatim max. 1 req/s
   · GTFS-Index                  ── einmal importiert, dann lokal
```

- **Backend:** Python + FastAPI **oder** Node + Fastify. Freie Wahl, eine Sprache
  durchziehen. `httpx`/`undici` für Outbound.
- **Cache:** SQLite, Key = `quelle|lat|lon|radius` gerundet auf 4 Nachkommastellen.
  TTL: OSM 24 h, Zensus 30 Tage (Stichtag 2022, ändert sich nicht), Nominatim 30 Tage.
- **Frontend:** Leaflet + Vanilla JS oder React. Keine schwere UI-Bibliothek.
- Ein `docker-compose.yml` ist nett, aber `make dev` bzw. `npm run dev` muss reichen.

---

## 3. PHASE 0 — Endpunkte verifizieren (zwingend zuerst)

**Bevor eine Zeile Anwendungscode entsteht:** jeden Endpunkt aus §4 einzeln mit `curl`
aufrufen, echte Antwort ansehen, Feldnamen gegen §4 prüfen, Ergebnis in
`docs/endpoints-verified.md` dokumentieren (Datum, Statuscode, Beispielantwort gekürzt,
Abweichungen).

Wo eine Abweichung auftritt, gilt **die echte Antwort**, nicht diese Spec.

```bash
# 1) Overpass — Grundabfrage
curl -s -X POST https://overpass-api.de/api/interpreter \
  --data-urlencode 'data=[out:json][timeout:60];
nwr["amenity"="fast_food"](around:600,48.1334,11.5674);out center tags;' | head -c 1500

# 2) Overpass — Rekursion Haltestelle → Linienrelationen  (RISIKO, siehe §4.2)
curl -s -X POST https://overpass-api.de/api/interpreter \
  --data-urlencode 'data=[out:json][timeout:60];
node["public_transport"~"^(platform|stop_position)$"](around:600,48.1334,11.5674)->.sp;
rel(bn.sp)["type"="route"]->.rt;
.rt out tags;' | head -c 1500

# 3) Zensus 2022 — 100-m-Gitter im Umkreis
curl -s -X POST "https://services2.arcgis.com/jUpNdisbWqRpMo35/arcgis/rest/services/Zensus2022_grid_final/FeatureServer/0/query" \
  --data-urlencode 'f=json' \
  --data-urlencode 'where=1=1' \
  --data-urlencode 'geometry={"x":11.5674,"y":48.1334,"spatialReference":{"wkid":4326}}' \
  --data-urlencode 'geometryType=esriGeometryPoint' \
  --data-urlencode 'distance=600' \
  --data-urlencode 'units=esriSRUnit_Meter' \
  --data-urlencode 'inSR=4326' --data-urlencode 'outSR=4326' \
  --data-urlencode 'spatialRel=esriSpatialRelIntersects' \
  --data-urlencode 'outFields=ags,Einwohner,Durchschnittsalter,a18bis29,a30bis49,durchschnMieteQM,Leerstandsquote' \
  --data-urlencode 'returnGeometry=true' \
  --data-urlencode 'resultRecordCount=2000' | head -c 2000

# 4) Zensus — Feldliste gegenprüfen
curl -s "https://services2.arcgis.com/jUpNdisbWqRpMo35/arcgis/rest/services/Zensus2022_grid_final/FeatureServer/0?f=pjson" \
  | python3 -c 'import sys,json; print([f["name"] for f in json.load(sys.stdin)["fields"]])'

# 5) Nominatim
curl -s -H 'User-Agent: standort-tool/0.1 (kontakt@example.de)' \
  'https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&countrycodes=de&q=Sendlinger+Str+10+M%C3%BCnchen'
```

**Prüfpunkte:**

- Bei (3): Feld `exceededTransferLimit` im JSON. Wenn `true`, greift das 2000-Satz-Limit
  → paginieren via `resultOffset`, oder Radius begrenzen. Für 1400 m Radius sind es
  rechnerisch ~616 Zellen, für 2500 m ~1963 — der Puffer ist dünn.
- Bei (2): Liefert die Antwort Relationen mit `tags.route`? Falls die Rekursionssyntax
  abgelehnt wird, ist das kein Beinbruch — Feature „ÖPNV-Linien" auf Haltestellenzählung
  reduzieren und weitergehen.
- Bei allen: `Access-Control-Allow-Origin` im Response-Header prüfen (`curl -I`). Wenn
  vorhanden, könnte der Client direkt zugreifen — der Proxy bleibt trotzdem, wegen Cache.

---

## 4. Datenquellen

Statusspalte: **[V]** = von mir während der Recherche direkt abgerufen und bestätigt ·
**[U]** = ungeprüfte Annahme, in Phase 0 verifizieren.

### 4.1 Zensus 2022, 100-Meter-Gitter — Kerndatensatz

| | |
|---|---|
| Endpunkt | `https://services2.arcgis.com/jUpNdisbWqRpMo35/arcgis/rest/services/Zensus2022_grid_final/FeatureServer/0/query` **[V]** |
| Layer | `0` = 100 m · `1` = 1 km · `2` = 10 km **[V]** |
| Max Record Count | 2000 **[V]** |
| Projektion | Service in 102100 (3857); `inSR`/`outSR=4326` mitgeben **[U]** |
| Stichtag | 15.05.2022 |
| Lizenz | © Statistische Ämter des Bundes und der Länder 2024 & GeoBasis-DE/BKG 2024 **[V]** |

Feldnamen **[V]** (exakt so, Groß-/Kleinschreibung beachten — sie ist inkonsistent):

```
ags                     Gemeindeschlüssel (ARS). Stellen 1–2 = Bundesland
Einwohner               Anzahl
Durchschnittsalter      Jahre
Unter18 · a18bis29 · a30bis49 · a50bis64 · a65undaelter     absolute Zahlen
AnteilUnter18 · AnteilUeber65 · AnteilAuslaender             Prozent
DurchschnHHGroesse      Personen je Haushalt
durchschnMieteQM        Nettokaltmiete €/m²      ← Kaufkraft-Indiz
durchschnFlaechejeWohn · durchschnFlaechejeBew                m²
Eigentuemerquote · Leerstandsquote · MALeerstQuote            Prozent
Insgesamt_Gebaeude · Vor1919 · a1919bis1948 · a1949bis1978
  · a1979bis1990 · a1991bis2000 · a2001bis2010 · a2011bis2019 · a2020undspaeter
Heizungsart / Energieträger: Fernwaerme, Gas, Strom, Zentralheizung, …
```

Wichtig für die Darstellung: Zum Datenschutz läuft über die Werte eine stochastische
Überlagerung (Cell-Key-Methode) — **Einzelwerte summieren sich nicht zwingend zur
ausgewiesenen Summe**. Das gehört als Hinweis in die UI. Zellen ohne Einwohner fehlen
im Datensatz komplett.

### 4.2 OpenStreetMap / Overpass

Endpunkte mit Reihum-Fallback **[U]**:
`overpass-api.de/api/interpreter` · `overpass.kumi.systems/api/interpreter` ·
`overpass.private.coffee/api/interpreter`

Abzufragen im Umkreis:

- **Gastronomie:** `amenity` in fast_food, restaurant, cafe, bar, pub, ice_cream,
  biergarten, food_court. Tags mitnehmen: `name, cuisine, brand, operator,
  opening_hours, takeaway, delivery, outdoor_seating, drive_through, wheelchair`
- **Frequenzbringer:** `amenity` (school, university, college, kindergarten, hospital,
  clinic, doctors, cinema, theatre, library, parking) · `shop` (supermarket, mall,
  department_store, convenience, bakery, butcher) · `leisure` (fitness_centre,
  sports_centre, stadium, swimming_pool) · `office=*` · `building=office` ·
  `tourism` (hotel, hostel, museum, attraction)
- **ÖPNV:** `highway=bus_stop`, `railway` (station, tram_stop), `public_transport=station`
- **Leerstand:** `disused:shop=*`, `shop=vacant`, `disused:amenity=*`
- **Linienzahl:** Rekursion Haltestellen → Routenrelationen **[U, Risiko]**

Nutzungsregeln: `nwr` statt separater node/way/relation-Blöcke, `[timeout:]` setzen,
Ergebnisse cachen, keine Abfrage-Schleifen. Overpass ist ein Spendenprojekt.
Lizenz ODbL, Namensnennung „© OpenStreetMap-Mitwirkende" ist Pflicht.

### 4.3 Nominatim (Geocoding)

`https://nominatim.openstreetmap.org/search` und `/reverse` **[U]**

Nutzungsbedingungen: **max. 1 Anfrage/Sekunde**, identifizierender `User-Agent` mit
Kontaktadresse zwingend, Ergebnisse cachen. Der Backend-Rate-Limiter muss das
durchsetzen — das ist keine Empfehlung, sondern Bedingung für die Nutzung.

Reverse-Geocoding liefert Gemeinde und Ortsteil für die Kopfzeile und für ortsbezogene
Links.

### 4.4 GTFS — ÖPNV-Bedienungsqualität (Phase 3)

Der stärkste freie Frequenz-Ersatz: **Abfahrten je Haltestelle und Stunde**.

- DELFI OpenData, deutschlandweit, montags aktualisiert, Registrierung nötig:
  `https://www.opendata-oepnv.de/ht/de/organisation/delfi/startseite` **[V]**
- Alternativ frei ohne Registrierung, Basisversion mit begrenzter Fahrplangültigkeit:
  `https://gtfs.de/` **[V]**

Ablauf: ZIP einmalig laden → `stops.txt`, `stop_times.txt`, `trips.txt`, `calendar.txt`
in SQLite importieren → Index auf `stop_id` + Koordinaten (R-Tree) → Query liefert
Abfahrten je Stunde im Umkreis. Als CLI-Kommando `import-gtfs`, nicht beim Start.

Kennzahl für die UI: Abfahrten pro Werktag im Radius, und die Verteilung über den Tag
(Balken 6–24 Uhr). Das trennt eine Hauptumsteigestelle von einer Nebenlinie.

### 4.5 Bodenrichtwerte

BORIS-D deckt **nicht alle Länder** ab — Bayern, Baden-Württemberg, Saarland,
Schleswig-Holstein und Mecklenburg-Vorpommern fehlen aus rechtlichen Gründen **[V]**.
Deshalb: Bundesland aus `ags[0:2]` ableiten und auf das jeweilige Landesportal
verlinken statt auf einen Wert zu hoffen.

Bestätigte Portale **[V]**: BORIS-D `bodenrichtwerte-boris.de/boris-d/?lang=de` ·
BW `gutachterausschuesse-bw.de` · Hessen `hvbg.hessen.de/immobilienwerte/boris-hessen` ·
Berlin `berlin.de/gutachterausschuss/marktinformationen/bodenrichtwerte/` ·
Brandenburg `boris.brandenburg.de`

Übrige Länder: **keine URL raten** — Suchlink erzeugen. Falls ein WMS/WFS des Landes
gefunden wird, gern als Kartenebene nachrüsten.

### 4.6 Weiterführende Portale (verlinken, nicht abrufen)

Als kontextbezogene Deep-Links im UI-Panel, wo möglich mit Koordinaten oder Gemeindename
vorbefüllt: hystreet (Passantenfrequenz — **Achtung: im kostenfreien Modell ist die
gewerbliche Nutzung untersagt** **[V]**, API-Doku unter `hystreet.com/apidocs` **[U]**) ·
Pendleratlas der Bundesagentur · INKAR/BBSR · Regionalstatistik · Zensus-Atlas ·
Overpass Turbo mit vorbefüllter Query · Google Maps (Stoßzeiten der Wettbewerber) ·
Leerstandsmelder · Open-Data-Portal und Wirtschaftsförderung der Gemeinde ·
nexxt-change · DEHOGA „Die Gastgeber" · ahgzimmo. Adressen stehen in
`notizen-standort-flaeche.md`.

---

## 5. UI

Zweispaltig: Karte links (dominant), Datenpanel rechts, scrollbar. Unter 900 px
gestapelt, Karte oben.

**Karte**

- Basis: OSM-Tiles (`tile.openstreetmap.org`), Attribution Pflicht.
  Optional prüfen: `basemap.de` als amtliche Alternative **[U]**
- Klick setzt den Punkt, Marker ist ziehbar, Radius als Kreis (300/600/900/1400 m)
- Adresssuche mit Debounce ≥ 1 s (Nominatim-Limit)
- Umschaltbare Ebenen: Zensus-Choroplethen (Einwohner, Anteil 18–49, Miete,
  Leerstand) · Gastronomie · Frequenzbringer · ÖPNV · Leerstände
- Jede Zensuszelle und jeder POI ist anklickbar und zeigt seine Rohwerte
- Legende mit Farbskala und Einheit

**Panel** — je Block eine Fußzeile „Quelle · Stand · Lizenz":

1. Kopf: Adresse, Gemeinde, Gemeindeschlüssel, Bundesland, Koordinaten
2. Bevölkerung: Einwohner, Altersaufbau, Haushaltsgröße, Ausländeranteil
3. Wohnen: Nettokaltmiete, Eigentümerquote, Leerstandsquote, Baualtersklassen
4. Gastronomie: Liste nach Distanz mit Küche, Marke, Öffnungszeiten, Service-Tags;
   Aufteilung nach Typ; Küchenverteilung; Ketten vs. Einzelbetriebe
5. Umfeld: Frequenzbringer nach Kategorie mit Distanz
6. Verkehr: Haltestellen, Linien, ab Phase 3 Abfahrten je Stunde
7. Leerstände aus OSM
8. Weiterführende Quellen (§4.6)

**Zustände:** Ladefortschritt je Quelle einzeln anzeigen. Fällt eine Quelle aus,
laufen die übrigen weiter und der Block zeigt „nicht erreichbar" statt zu verschwinden.
Fehlermeldungen benennen die Ursache konkret — nicht „Dienst überlastet" schreiben,
wenn in Wahrheit CORS blockiert oder ein Feld fehlt.

**Standortvergleich:** „Punkt merken" legt den Datensatz in eine Vergleichstabelle
(persistiert in SQLite). Mehrere Kandidaten nebeneinander ist der eigentliche
Nutzen — die Rangfolge ist belastbarer als jeder Einzelwert.

**Export:** JSON und CSV je Punkt, inklusive Zeitstempel und Quellenangaben.

---

## 6. Phasenplan

| Phase | Inhalt | Fertig, wenn |
|---|---|---|
| 0 | Endpunkte verifizieren (§3) | `docs/endpoints-verified.md` existiert, jede Quelle mit echter Antwort belegt |
| 1 | Backend-Grundgerüst: Proxy, Cache, Rate-Limit, `/api/point` | `curl localhost:PORT/api/point?lat=48.1334&lon=11.5674&r=600` liefert Zensus + OSM |
| 2 | Karte + Panel + Ebenen + Vergleich + Export | Ein Punkt in München und einer in einem 5.000-Einwohner-Ort liefern beide plausible, vollständige Ausgaben |
| 3 | GTFS-Import und Abfahrtskennzahl | `import-gtfs` läuft durch, Abfahrten je Stunde erscheinen im Panel |
| 4 | Optional: Bodenrichtwert-WMS, weitere Landesdienste | — |

---

## 7. Abnahmekriterien

- [ ] Jede angezeigte Zahl ist auf eine reale API-Antwort zurückführbar. Keine Konstante
      im Code, die wie Messwert aussieht.
- [ ] Jeder Block nennt Quelle, Stand und Lizenz.
- [ ] Attribution OSM/ODbL und Zensus-Copyright sichtbar.
- [ ] Nominatim wird nachweislich auf ≤ 1 req/s gedrosselt; `User-Agent` gesetzt.
- [ ] Cache greift: zweiter Aufruf desselben Punkts erzeugt keinen Outbound-Traffic
      (im Log prüfbar).
- [ ] Ausfall einer Quelle bricht die Seite nicht.
- [ ] Getestet an mindestens vier Punkten: Großstadt-Innenstadt, Großstadt-Wohnviertel,
      Kleinstadt, ländlich. Erwartetes Verhalten im ländlichen Fall: wenige oder keine
      OSM-Objekte, dünne Zensuszellen — die UI muss das sauber darstellen, nicht leer bleiben.
- [ ] `exceededTransferLimit` wird behandelt, nicht ignoriert.
- [ ] README erklärt Start, GTFS-Import, Cache leeren, und listet alle Quellen mit Lizenz.

---

## 8. Bekannte Grenzen — gehören in die UI, nicht ins Kleingedruckte

- OSM ist unvollständig, besonders bei kleinen Imbissen und Neueröffnungen. Die
  angezeigte Wettbewerbsdichte ist eine **Untergrenze**.
- Zensus-Stichtag ist der 15.05.2022 mit stochastischer Überlagerung. Neubaugebiete
  nach 2022 fehlen.
- `opening_hours` in OSM hat eine reichhaltige Syntax (Feiertage, Saison, Ausnahmen).
  Ein einfacher Parser deckt sie nicht ab — entweder eine erprobte Bibliothek nutzen
  oder das Feature als „grobe Auswertung" kennzeichnen.
- Passantenströme fehlen komplett. Fußgängerzone und Seitenstraße sind in diesen Daten
  nicht unterscheidbar. Dafür hystreet, GTFS-Abfahrten und eigene Zählung.
- Umsatzstärke der Wettbewerber ist unbekannt.

---

## 9. Umsatzschätzung — falls später gewünscht

Nur als **eigener, klar getrennter Reiter**, und nur mit diesen Auflagen:

- Alle Annahmen sind Eingabefelder, keine versteckten Konstanten.
- Ausgabe als Spanne, nie als Punktwert.
- Pflichtausgabe daneben: die **Umrechnung in Bestellungen pro Tag und pro
  Öffnungsstunde**. Das ist die Zahl, die der Nutzer beurteilen kann und das Modell nicht.
- Die Formel steht sichtbar in der UI, nicht nur im Code.
- Beschriftung: Vergleichsmaß zwischen Standorten, keine Prognose.

Brauchbare Ausgangsgrößen aus der Recherche: Schnellgastronomie-Umsatz Deutschland 2023
rund 32,7 Mrd. € (Circana), Außer-Haus-Markt gesamt 84,5 Mrd. €, Durchschnittsbon
10,21 € je Besuch. Diese Werte sind Sekundärquellen aus Presseberichten — vor
Verwendung selbst nachschlagen und mit Stand versehen.

---

## 10. Arbeitsweise

- Nach Phase 0 kurz zurückmelden, was nicht so funktioniert wie hier beschrieben.
  Diese Spec ist ohne Netzzugang zu den Zieldiensten entstanden; §4.1 ist gegen die
  Dienstbeschreibung geprüft, alles mit **[U]** ist Annahme.
- Kleine Commits je Quelle.
- Tests gegen aufgezeichnete echte Antworten (Fixtures aus Phase 0), nicht gegen
  ausgedachte. Genau daran ist der Vorgänger gescheitert.
- Bei Zweifel an einer Kennzahl: weglassen und im README notieren, statt schätzen.
