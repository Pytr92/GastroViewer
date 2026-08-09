# Phase 0 — Endpunkte verifiziert

Datum der Prüfung: **2026-08-01**
Umgebung: Linux-Container, ausgehender Verkehr über HTTP-Proxy (`HTTPS_PROXY`).
Alle Rohantworten liegen als Fixtures unter `fixtures/` und sind die Grundlage der Tests
(§10 der Spec: keine ausgedachten Testdaten).

Regel aus §3 der Spec: **Wo die echte Antwort von der Spec abweicht, gilt die echte Antwort.**

| # | Quelle | Status | Ergebnis |
|---|---|---|---|
| 1 | Overpass Grundabfrage | ✅ | HTTP 200, 2,0 s |
| 2 | Overpass Rekursion → Routenrelationen | ✅ | HTTP 200, funktioniert entgegen der Risikoannahme |
| 3 | Zensus 2022 Gitterabfrage | ✅ | HTTP 200, 118 Zellen bei r=600 |
| 4 | Zensus Feldliste | ✅ | 49 Felder, §4.1 vollständig bestätigt |
| 5 | Nominatim search/reverse | ✅ | HTTP 200; ohne User-Agent HTTP 403 |
| — | Overpass-Spiegel (kumi, private.coffee) | ⚠️ | in dieser Umgebung Timeout, siehe A-1 |
| — | GTFS (gtfs.de) | ✅ | Feeds live, Größen und Stand siehe unten |
| — | Bodenrichtwert-Portale | ✅ | alle 5 bestätigten URLs HTTP 200 |

---

## 1) Overpass — Grundabfrage

`POST https://overpass-api.de/api/interpreter` · **HTTP 200** · 2,04 s · 14.231 Bytes
Fixture: `fixtures/raw_overpass_fastfood.json`

```
[out:json][timeout:60];
nwr["amenity"="fast_food"](around:600,48.1334,11.5674);out center tags;
```

Antwortkopf:

```json
{
  "version": 0.6,
  "generator": "Overpass API 0.7.62.11 87bfad18",
  "osm3s": {
    "timestamp_osm_base": "2026-08-01T07:24:36Z",
    "copyright": "The data included in this document is from www.openstreetmap.org. The data is made available under ODbL."
  },
  "elements": [ … ]
}
```

Beispielelement (gekürzt):

```json
{"type":"node","id":260651990,"lat":48.1377004,"lon":11.5645217,
 "tags":{"amenity":"fast_food","brand":"Burger King","cuisine":"burger",
         "name":"Burger King","opening_hours":"Su-We 09:00-01:00; Th 09:00-04:00; …",
         "takeaway":"yes","wheelchair":"limited","addr:street":"Sonnenstraße", …}}
```

**Befund:** wie in §4.2 beschrieben. `nwr` wird akzeptiert, `out center tags` liefert bei
Ways/Relations ein `center`-Objekt statt `lat`/`lon` — der Parser muss beides behandeln.
`timestamp_osm_base` ist der brauchbare „Stand" für die UI-Fußzeile.

---

## 2) Overpass — Rekursion Haltestelle → Linienrelationen

`POST https://overpass-api.de/api/interpreter` · **HTTP 200** · 4,31 s · 70.981 Bytes
Fixture: `fixtures/raw_overpass_routes.json`

```
[out:json][timeout:60];
node["public_transport"~"^(platform|stop_position)$"](around:600,48.1334,11.5674)->.sp;
rel(bn.sp)["type"="route"]->.rt;
.rt out tags;
```

Ergebnis: **66 Relationen**, alle mit `tags.route`:

```
route:  tram 30 · bus 20 · subway 16
ref:    U1, U2, U3, U6, 16, 17, 18, 27, 28, 52, 62, 132, N17, N20, N27, N40, N41, N45 …
```

**Befund gegen die Spec:** §4.2 markiert diese Rekursion als **[U, Risiko]** und stellt den
Rückfall auf reine Haltestellenzählung in Aussicht. **Das Risiko ist nicht eingetreten** —
die Syntax wird akzeptiert und liefert `tags.route` und `tags.ref`. Das Feature
„ÖPNV-Linien" wird also voll gebaut. Nützliche Zusatzfelder in der Antwort:
`network`, `network:short`, `colour`, `from`, `to`, `gtfs:route_id` (letzteres ist später
die Brücke zum GTFS-Import aus Phase 3).

Kostenhinweis: 4,3 s gegenüber 2,0 s der Grundabfrage. Die Abfrage gehört in den Cache und
sollte nicht bei jedem Kartenklick blind mitlaufen.

---

## 3) Zensus 2022 — 100-m-Gitter im Umkreis

`POST …/Zensus2022_grid_final/FeatureServer/0/query` · **HTTP 200** · 1,31 s
Fixture: `fixtures/raw_zensus_600.json`

Parameter exakt wie in §3 der Spec. Ergebnis bei r=600:

```
exceededTransferLimit : nicht im JSON vorhanden (nur gesetzt, wenn true)
features              : 118
geometryType          : esriGeometryPolygon
spatialReference      : {"wkid":4326,"latestWkid":4326}
```

Erstes Feature:

```json
{"attributes":{"ags":"09162000","Einwohner":5,"Durchschnittsalter":31,
               "a18bis29":0,"a30bis49":0,"durchschnMieteQM":null,"Leerstandsquote":null},
 "geometry":{"rings":[[[11.5672095930734,48.133213112724],
                       [11.5672373608971,48.1341126644017], …]]}}
```

**Befunde:**

- **`inSR`/`outSR=4326` funktioniert** — die als **[U]** markierte Projektionsannahme aus
  §4.1 ist bestätigt. Der Service liegt intern in 102100/3857, gibt aber auf Wunsch
  WGS84-Ringe zurück, die Leaflet direkt zeichnen kann.
- **`null` ist ein regulärer Wert.** `durchschnMieteQM` und `Leerstandsquote` sind in dieser
  Zelle leer. Die UI muss „keine Angabe" von „0" unterscheiden — ein Nullwert darf nicht als
  Miete von 0 €/m² in einen Mittelwert einfließen.
- **Die stochastische Überlagerung ist sichtbar.** Die Beispielzelle meldet 5 Einwohner,
  Durchschnittsalter 31, aber `a18bis29 = 0` und `a30bis49 = 0`. Genau der in §4.1
  beschriebene Effekt der Cell-Key-Methode. Der Hinweis gehört wie gefordert in die UI.
- `exceededTransferLimit` fehlt im JSON, wenn es `false` wäre. Der Code muss also
  `d.get("exceededTransferLimit") is True` prüfen, nicht auf Existenz des Schlüssels.

### Grenzwerttest `exceededTransferLimit` und Paginierung

| Radius | Features | `exceededTransferLimit` | rechnerisch laut Spec |
|---|---|---|---|
| 600 m | 118 | – | ~113 |
| 1400 m | 463 | – | ~616 |
| 2500 m | 1400 | – | ~1963 |
| 3000 m | 2000 | **true** | ~2827 |

`returnCountOnly=true` bei r=3000 → `{"count":2006}`
`resultOffset=2000` bei r=3000 → 6 weitere Features, kein Limit mehr.

Fixtures: `zensus_r1400_nogeom.json`, `zensus_r2500_nogeom.json`,
`zensus_r3000_exceeded.json`, `zensus_r3000_offset2000.json`

**Befunde:**

- **Paginierung über `resultOffset` funktioniert** und wird implementiert. Kein Radius-Limit
  nötig, kein Datenverlust.
- **Die Zellzahl liegt deutlich unter der Rechnung der Spec** (463 statt ~616 bei 1400 m).
  Ursache ist die in §4.1 genannte Eigenschaft: Zellen ohne Einwohner fehlen im Datensatz
  komplett. Die Spec-Warnung „der Puffer ist dünn" ist damit entschärft — der reale Puffer
  ist größer als angenommen. Die Paginierung wird trotzdem gebaut, weil dichte Innenstädte
  näher am Limit liegen können.

---

## 4) Zensus — Feldliste

`GET …/FeatureServer/0?f=pjson` · **HTTP 200** · 0,62 s
Fixture: `fixtures/raw_zensus_meta.json`

```
name            : Zensus2022_100mGitter
geometryType    : esriGeometryPolygon
maxRecordCount  : 2000
extent SR       : {"wkid":102100,"latestWkid":3857}
```

Alle 49 Felder:

```
OBJECTID, id, GITTER_ID_100m, ags, Einwohner, AnteilAuslaender, Durchschnittsalter,
Unter18, a18bis29, a30bis49, a50bis64, a65undaelter, AnteilUnter18, AnteilUeber65,
DurchschnHHGroesse, durchschnMieteQM, durchschnFlaechejeWohn, durchschnFlaechejeBew,
Eigentuemerquote, Leerstandsquote, MALeerstQuote, Insgesamt_Energietraeger, Gas, Heizoel,
Holz_Holzpellets, Biomasse_Biogas, Solar_Geothermie_Waermepumpen, Strom, Kohle,
Fernwaerme, kein_Energietraeger, Insgesamt_Heizungsart, Fernheizung, Etagenheizung,
Blockheizung, Zentralheizung, Einzel_Mehrraumoefen, keine_Heizung, Insgesamt_Gebaeude,
Vor1919, a1919bis1948, a1949bis1978, a1979bis1990, a1991bis2000, a2001bis2010,
a2011bis2019, a2020undspaeter, Shape__Area, Shape__Length
```

**Befund:** Die Feldliste aus §4.1 stimmt **vollständig und in exakter Schreibweise**.
`maxRecordCount = 2000` bestätigt. Zusätzlich nutzbar und in der Spec nicht genannt:
`GITTER_ID_100m` (stabiler Zellschlüssel, besser als `OBJECTID` als Cache-/Dedup-Key) und
die vollständigen Energieträger-/Heizungsart-Felder.

`copyrightText` des Service ist **leer** — die in §4.1 genannte Lizenzangabe
„© Statistische Ämter des Bundes und der Länder 2024 & GeoBasis-DE/BKG 2024" kommt also
nicht aus der API und wird als Konstante in der Quellenangabe geführt. Das ist der einzige
zulässige Fall einer Konstante: eine Lizenzzeile, kein Messwert.

---

## 5) Nominatim

Fixtures: `fixtures/raw_nominatim_search.json`, `fixtures/raw_nominatim_reverse.json`

`GET /search?format=jsonv2&limit=1&countrycodes=de&addressdetails=1&q=Sendlinger+Str+10+München`
**HTTP 200** · 0,93 s

```json
[{"place_id":126946365,
  "licence":"Data © OpenStreetMap contributors, ODbL 1.0. http://osm.org/copyright",
  "lat":"48.1360641","lon":"11.5714570","name":"Cole & Porter",
  "display_name":"Cole & Porter, 10, Sendlinger Straße, Hackenviertel, Altstadt-Lehel, München, Bayern, 80331, Deutschland",
  "address":{"house_number":"10","road":"Sendlinger Straße","quarter":"Hackenviertel",
             "suburb":"Altstadt-Lehel","city":"München","state":"Bayern",
             "ISO3166-2-lvl4":"DE-BY","postcode":"80331","country_code":"de"}}]
```

`GET /reverse?format=jsonv2&lat=48.1334&lon=11.5674&addressdetails=1&zoom=18`
**HTTP 200** · 0,62 s → `Sendlinger Tor, Blumenstraße, …, München, Bayern, 80336`

**Befunde:**

- **`addressdetails=1` ist Pflicht**, sonst fehlt das `address`-Objekt und damit Gemeinde,
  Ortsteil und PLZ für die Kopfzeile. In den Spec-Beispielaufrufen fehlt der Parameter.
- **Nominatim liefert keinen Gemeindeschlüssel (AGS/ARS).** Die Kopfzeile aus §5 braucht ihn
  aber. Quelle dafür ist das Zensus-Feld `ags` — die beiden Blöcke müssen zusammengeführt
  werden. `ISO3166-2-lvl4` (`DE-BY`) liefert zusätzlich das Bundesland direkt und dient als
  Gegenprobe zur Ableitung aus `ags[0:2]` (§4.5).
- **Ohne `User-Agent` antwortet der Dienst mit HTTP 403** — geprüft. Die Nutzungsbedingung
  aus §4.3 ist serverseitig durchgesetzt, nicht bloß eine Bitte. Rate-Limiter und
  `User-Agent` sind damit Funktionsvoraussetzung, nicht Kür.
- `licence` kommt in jeder Antwort mit und wird als Quellenangabe durchgereicht statt
  hartkodiert.

---

## CORS

| Dienst | `Access-Control-Allow-Origin` |
|---|---|
| Overpass | `*` |
| Nominatim | `*` |
| Zensus/ArcGIS | `*` |

Alle drei erlauben Direktzugriff aus dem Browser. **Der Proxy bleibt trotzdem**, wie in §3
der Spec vorgesehen: er trägt Cache, Rate-Limiter und Fehlerbehandlung. Ohne ihn ließe sich
das Nominatim-Limit von 1 req/s nicht durchsetzen und jeder Reload erzeugte Outbound-Last.

---

## Abweichungen und Umgebungsbefunde

**A-1 · Overpass-Spiegel nicht erreichbar (Umgebung, kein Spec-Fehler)**
`overpass.kumi.systems` und `overpass.private.coffee` antworten auf `GET /` mit HTTP 200,
aber `/api/interpreter` läuft mit GET wie mit POST in ein Timeout (>40 s, 0 Bytes).
`overpass-api.de` funktioniert im selben Lauf zuverlässig. Das sieht nach einer Eigenheit
des ausgehenden Proxys in dieser Umgebung aus, nicht nach einem Ausfall der Spiegel.
→ Der Reihum-Fallback aus §4.2 wird **wie geplant implementiert**, mit knappem Timeout und
konfigurierbarer Reihenfolge. Auf einer normalen Internetverbindung (macOS, Linux, Windows)
sollten die Spiegel greifen. Die Konfiguration erlaubt, Spiegel abzuschalten.

**A-2 · `exceededTransferLimit` fehlt bei `false`**
Der Schlüssel erscheint nur, wenn er `true` ist. Prüfung auf Schlüsselexistenz wäre falsch.

**A-3 · Zellzahl niedriger als in der Spec gerechnet** (463 statt ~616 bei 1400 m), weil
unbewohnte Zellen fehlen. Siehe oben.

**A-4 · `addressdetails=1` fehlt in den Spec-Beispielen** für Nominatim.

**A-5 · Kein AGS aus Nominatim** — muss aus dem Zensus-Block kommen.

**A-6 · `copyrightText` des Zensus-Service ist leer** — Lizenzzeile stammt aus der Spec, nicht
aus der API.

**A-7 · Overpass-Rekursion ist kein Risiko** — §4.2 [U, Risiko] ist positiv aufgelöst.

---

## GTFS (Phase 3) — Vorabprüfung

`https://gtfs.de/de/feeds/de_full/` · HTTP 200. Angaben der Seite:
Feed „Deutschland komplett", 1,6 Mio. Trips, 632 Tsd. Stops, Datengrundlage NeTEx-Datensatz
DELFI e.V., Lizenz Creative Commons 4.0, letzte Aktualisierung **Sat Aug 1 07:56:58 CEST 2026**
(also täglich frisch, nicht nur montags wie in §4.4 vermutet).

Direkte Download-URLs, alle **HTTP 200** (nur HEAD geprüft, nichts geladen):

| Feed | URL | Größe | Last-Modified |
|---|---|---|---|
| Deutschland komplett | `https://download.gtfs.de/germany/free/latest.zip` | 259,3 MB | 2026-08-01 05:56 GMT |
| Nahverkehr | `https://download.gtfs.de/germany/nv_free/latest.zip` | 248,6 MB | 2026-08-01 05:57 GMT |
| Regionalverkehr | `https://download.gtfs.de/germany/rv_free/latest.zip` | 10,5 MB | 2026-08-01 05:57 GMT |
| Fernverkehr | `https://download.gtfs.de/germany/fv_free/latest.zip` | 0,37 MB | 2026-08-01 05:56 GMT |

**Befund:** Die Spec nennt „1-GB-Download"; real sind es 259 MB für den Komplettfeed. Der
Import bleibt trotzdem ein eigener CLI-Schritt, weil `stop_times.txt` entpackt im
Gigabyte-Bereich liegt. **Keine Registrierung nötig** — der DELFI-Weg aus §4.4 ist damit
optional, gtfs.de reicht für Phase 3.

---

## basemap.de — amtliche Kartengrundlage (§5, war **[U]**)

Nachträglich geprüft am 2026-08-01.

`GET https://sgx.geodatenzentrum.de/wmts_basemapde/1.0.0/WMTSCapabilities.xml`
**HTTP 200** · 30.712 Bytes

```
Layer            : de_basemapde_web_raster_farbe · de_basemapde_web_raster_grau
TileMatrixSets   : GLOBAL_WEBMERCATOR (20 Stufen) · DE_EPSG_3857_ADV (14) ·
                   DE_EPSG_25832_ADV (14) · DE_EPSG_25833_ADV (14)
AccessConstraints: „Es gelten keine Zugriffsbeschränkungen"
Template         : …/tile/1.0.0/{Layer}/{Style}/{TileMatrixSet}/{TileMatrix}/{TileRow}/{TileCol}.png
```

Kacheltest: `…/de_basemapde_web_raster_farbe/default/GLOBAL_WEBMERCATOR/15/11265/17445.png`
→ **HTTP 200**, 22.871 Bytes, `image/png`.

**Befunde:**

- **`GLOBAL_WEBMERCATOR` ist der Satz für Leaflet**, nicht `DE_EPSG_3857_ADV` — der
  antwortet auf denselben Kachelaufruf mit **HTTP 400**.
- **Die TileMatrix-IDs sind zweistellig** (`00`–`19`). Mit Leaflets `{z}` allein käme
  bei Zoomstufen unter 10 eine 400er-Antwort. Der Code füllt deshalb auf zwei Stellen auf.
- Reihenfolge im Pfad ist `{TileMatrix}/{TileRow}/{TileCol}`, also z/y/x — nicht z/x/y.
- Attribution: „© basemap.de / GeoBasis-DE, BKG (dl-de/by-2-0)".

basemap.de ist als umschaltbare Kartengrundlage eingebaut (farbig und grau), OSM bleibt
die Vorgabe.

> **Einschränkung dieser Umgebung:** Wie die OSM-Kacheln erreichen auch die
> basemap.de-Kacheln den Browser im Container nicht — der ausgehende Proxy beantwortet
> Kachelanfragen aus dem Browser nicht (per `curl` funktionieren dieselben URLs). Geprüft
> werden konnte daher: Erreichbarkeit und Format über `curl`, korrekte URL-Bildung und
> Umschaltung im Browser (12 Kachelanfragen mit korrekt aufgefüllter Zoomstufe). Das
> tatsächliche Kartenbild ist in dieser Umgebung nicht darstellbar.

---

## Bodenrichtwert-Portale (§4.5)

Alle fünf in der Spec als **[V]** geführten URLs geprüft, alle **HTTP 200**:

| Portal | URL |
|---|---|
| BORIS-D | `https://bodenrichtwerte-boris.de/boris-d/?lang=de` |
| Baden-Württemberg | `https://www.gutachterausschuesse-bw.de/` |
| Hessen | `https://hvbg.hessen.de/immobilienwerte/boris-hessen` |
| Berlin | `https://www.berlin.de/gutachterausschuss/marktinformationen/bodenrichtwerte/` |
| Brandenburg | `https://boris.brandenburg.de/` |

Für die übrigen Länder wird wie in §4.5 gefordert **keine URL geraten**, sondern ein
Suchlink erzeugt.

---

## Bodenrichtwert-Kartendienste der Länder (Phase 4)

Geprüft am **2026-08-01**, jeder Dienst in drei Stufen: `GetCapabilities` abgerufen,
`GetMap` mit einem Punkt im jeweiligen Land aufgerufen und geprüft, dass ein PNG **mit
Inhalt** zurückkommt, dann `GetFeatureInfo` gegen denselben Punkt.

§4.5 verlangt: **keine URL raten.** Aufgenommen ist deshalb nur, was diese drei Stufen
bestanden hat.

| Land | Dienst | WMS | GetMap | Klickabfrage | Lizenz |
|---|---|---|---|---|---|
| Nordrhein-Westfalen | `wms.nrw.de/boris/wms-t_nw_brw` | 1.3.0 | 17.017 B | ✅ voll | dl-de/zero-2-0 |
| Hamburg | `geodienste.hamburg.de/HH_WMS_Bodenrichtwerte` | 1.3.0 | 67.361 B | ⚠️ ohne Wert | keine Zugriffsbeschränkungen |
| Niedersachsen | `opendata.lgln.niedersachsen.de/…/boris_2025_wms` | 1.3.0 | 5.584 B | ✅ voll | dl-de/by-2-0 |
| Sachsen-Anhalt | `geodatenportal.sachsen-anhalt.de/ows_st_lvermgeo_brw2026` | 1.3.0 | 2.248 B | ✅ voll | Kostenverordnung genannt |
| Thüringen | `geoproxy.geoportal-th.de/geoproxy/services/boris/boris_wms` | 1.3.0 | 22.390 B | ✅ voll | dl-de/by-2-0 |
| Brandenburg | `isk.geobasis-bb.de/ows/boris_wms` | 1.3.0 | 11.087 B | ✅ voll | dl-de/by-2-0 |
| Rheinland-Pfalz | `geo5.service24.rlp.de/wms/genbori_rp.fcgi` | 1.1.1 | 3.228 B | ❌ keine Sachdaten | dl-de/by-2-0 |

Belegte Klickantworten (Auszug, unverändert):

```
Thüringen    BODENRICHTWERT=1000 · STICHTAG=2026-01-01 · ENTWICKLUNGSZUSTAND=Baureifes Land (B)
Brandenburg  Bodenrichtwert=1200 €/m² · wertrelevante Geschossflächenzahl=nicht vorhanden
Sachsen-Anh. bodenrichtwert=700 · bodenrichtwertKlassifikation=1000
Niedersachs. bodenrichtwert=10500.0 · bodenrichtwertNummer=04305001
NRW          35 Felder inkl. Bodenrichtwert, Entwicklungszustand, Bemerkung „Unter Sachsenhausen/Tunisstr."
```

**Befunde:**

- **`brw_verfuegbarkeit` (NRW) ist nur ein Sammelknoten** und zeichnet nichts. Die
  Kindebenen müssen einzeln benannt werden — sonst kommt ein leeres PNG zurück, das wie
  ein Datenfehler aussieht. Ebenso braucht NRW den Parameter `TIME`.
- **Maßstabsgrenzen** stehen als `MaxScaleDenominator` in den Capabilities und werden im
  Code in eine Mindest-Zoomstufe umgerechnet, statt sie zu schätzen: NRW ab Zoom 14,
  Thüringen und Brandenburg ab 13, Niedersachsen und Sachsen-Anhalt ab 7.
- **Hamburg:** Die gezeichnete Ebene `lgv_brw_zonen_2026` liefert per `GetFeatureInfo`
  eine leere `FeatureCollection`, unabhängig von der Boxgröße (20 m, 100 m, 300 m
  getestet). Die Ebene `v_brw_zonen_geom_flaeche_2026` antwortet, aber mit Zonennummer
  und Nutzungsarten — **ohne den €/m²-Wert**. Der steht nur als Kartenbeschriftung.
- **Rheinland-Pfalz:** Der zonale VBORIS-Dienst liegt hinter einem Mapbender-Proxy, der
  `GetMap` mit „Parameter REQUEST invalid" ablehnt. Eingebunden ist deshalb der
  generalisierte Dienst — dessen Features tragen aber keine Sachdaten, nur Geometrie.
- **Fünf Antwortformate** bei sieben Diensten: GeoJSON, `KEY=VALUE$#$`-Text, GML/XML,
  HTML-Tabellen und ein reines Ergebnisprotokoll. Statt sieben Parser gibt es vier
  allgemeine Muster; was sich nicht sicher zerlegen lässt, wird als unveränderter
  Originaltext angezeigt.

### Geprüft und **nicht** aufgenommen

| Land | Befund |
|---|---|
| Berlin | `gdi.berlin.de` und `fbinter.stadt-berlin.de` scheitern an der TLS-Zertifikatskette, auch mit dem CA-Bundle des Proxys. Ohne Beleg keine Aufnahme. |
| Sachsen | `geodienste.sachsen.de` weist die Prüfabrufe mit HTTP 403 zurück (auch der Host selbst). |
| Hessen, Bremen | Kein offener Dienst gefunden; die geprüften Kandidaten antworteten mit HTTP 404. |
| Bayern, Baden-Württemberg, Saarland, Schleswig-Holstein, Mecklenburg-Vorpommern | Aus rechtlichen Gründen nicht in den offenen Bodenrichtwert-Diensten enthalten — dieselbe Ausnahme, die §4.5 für BORIS-D nennt. |

Für diese Länder bleibt es beim Portallink bzw. beim Suchlink. `gastroviewer check-wms`
ruft bei allen sieben Diensten `GetCapabilities` ab und meldet, wenn eine URL oder ein
Layername nicht mehr stimmt — Brandenburg hat seine Dienst-URL 2025 umgestellt.

---

## München und Bayern (Recherche 2026-08-01)

Gesucht wurde gezielt nach Quellen, die das Werkzeug für die Zielregion besser machen.
Geprüft und **aufgenommen**:

| Quelle | Prüfung | Ergebnis |
|---|---|---|
| Raddauerzählstellen München, WFS `mor_wfs:raddauerzaehlstellen` | GetFeature, GeoJSON | HTTP 200, **6 Features** mit Jahres- und Monatssummen, dl-de/by-2-0 |
| Luftbild Bayern DOP 40 cm, `geoservices.bayern.de/od/wms/dop/v1/dop40` | GetCapabilities | WMS 1.3.0, Layer `by_dop40c`, EPSG:3857, **kostenfrei, CC BY 4.0** |
| ALKIS-Parzellarkarte Bayern, `…/od/wms/alkis/v1/parzellarkarte` | GetCapabilities | WMS 1.3.0, Layer `by_alkis_parzellarkarte_farbe`, max. Maßstab 1:5.000 → ab Zoom 17 |

Beispielwerte der Zählstellen (unverändert übernommen):

```
Erhardtstr. (Deutsches Museum)   1.415.000 Radfahrende 2025  →  3.877 je Tag
Rudolf-Harbig-Weg (Olympiapark)    831.000                   →  2.277 je Tag
Birketweg (Hirschgarten)           558.000                   →  1.529 je Tag
Arnulfstr. 9–11 Südseite           432.000                   →  1.184 je Tag
Margaretenstr. (Harras)         „Derzeit keine Daten"
```

**Befunde:**

- Die Felder kommen als **Zeichenketten**, teils mit HTML im Infofeld und mit
  „Derzeit keine Daten" statt eines Werts. Letzteres darf nicht zu 0 werden — eine
  gestörte Zählstelle ist etwas anderes als eine leere Straße.
- Der WFS-Typname lautet `mor_wfs:raddauerzaehlstellen`, **nicht**
  `mor_wfs:vab_raddauerzaehlstellen` wie in der Ressourcen-URL des Open-Data-Portals;
  letzterer antwortet mit `Feature type unknown`.
- `geoservices.bayern.de/od/wms/dtk` und `.../adv_dop80` antworten mit HTTP 500,
  `.../blfd/v1/denkmaldaten` und `.../dflk/v1/dflk` mit HTTP 404 — nicht aufgenommen.

### Zweite Recherchestufe 2026-08-01: Verkehr, Lärm, Statistik

| Quelle | Prüfung | Ergebnis |
|---|---|---|
| **BAYSIS Verkehrsdaten WFS**, `gisportal-stmb.bayern.de/server/services/WFS/BAYSIS_Verkehrsdaten/MapServer/WFSServer` | GetCapabilities, GetFeature GeoJSON, `resultType=hits` | WFS 2.0.0, **9.441 Zählstellen in Bayern**, Felder `DTV_Kfz`, `DTV_LV`, `DTV_SV`, CC BY 4.0 |
| **BAYSIS Verkehrsdaten WMS**, `…/WMS/BAYSIS_Verkehrsdaten/MapServer/WMSServer` | GetCapabilities | Bandbreitenkarten `svz2021_dtv_{bab,b,st,k}_25`, max. Maßstab 1:23.623 → ab Zoom 15 |
| **Lärmkartierung LfU Bayern**, `lfu.bayern.de/gdi/wms/laerm/hauptverkehrsstrassen` | GetCapabilities | WMS 1.3.0, `mroadbylden2022` (Tag-Abend-Nacht-Pegel), abfragbar, CC BY 4.0 |
| BAYSIS Straßennetz WFS | GetCapabilities | HTTP 200 — vorerst nicht eingebunden, die Straßenklasse steht schon im Zählstellenfeld |

Belegte Werte, unverändert (Zählstellen nahe Fröttmaning):

```
A 9    701 m   111.624 Kfz/Tag   davon 5.653 Schwerverkehr   ( 5,1 %)
A 9  1.251 m    95.839 Kfz/Tag   davon 4.686 Schwerverkehr   ( 4,9 %)
A 99 1.638 m    79.216 Kfz/Tag   davon 10.742 Schwerverkehr  (13,6 %)
```

**Befunde:**

- Am Sendlinger Tor liefert der Dienst **keine** Zählstelle im 2-km-Umkreis. Das ist
  richtig und wird als solches ausgewiesen: gezählt wird das klassifizierte Straßennetz —
  Autobahnen, Bundes-, Staats- und Kreisstraßen. Innerstädtische Gemeindestraßen und
  Fußgängerzonen kommen darin nicht vor.
- Der Bounding-Box-Filter braucht die CRS-Angabe im Parameter selbst
  (`bbox=…,urn:ogc:def:crs:EPSG::4326`), sonst kippt die Achsenreihenfolge.
- Der Schwerverkehrsanteil trennt Fernverkehrsachsen von Pendlerachsen deutlich:
  A 99 (Autobahnring) 13,6 %, A 9 an derselben Stelle 5,1 %.

### Geprüft und **nicht** aufgenommen

| Quelle | Grund |
|---|---|
| **GENESIS-Webservice** (Bayern und Regionalstatistik) | Konto nötig; am 01.08.2026 per POST nachgeprüft, siehe eigener Nachtrag unten. Feinste Gliederung ist ohnehin die Gemeinde — innerhalb Münchens ohne Unterscheidungskraft. |
| **Denkmalatlas Bayern (BLfD)** | Zwei plausible Dienstpfade geprüft, beide HTTP 404. Kein offener OGC-Dienst gefunden. |
| hystreet | Im kostenfreien Modell ist die gewerbliche Nutzung untersagt (Notizen §1). Bleibt Link. |
| Open-Data-Portal München, Suche „passanten", „frequenz", „einzelhandel", „kaufkraft" | jeweils **0 Treffer** — es gibt dort keine Passanten- oder Kaufkraftdaten |
| Indikatorenatlas München (68 Datensätze) | Kleinräumige Demografie je Stadtbezirksviertel. Das Zensus-100-m-Gitter ist feiner und liegt schon vor. |
| Beschäftigte am Arbeitsort (Regionalstatistik/GENESIS) | Der eigentlich fehlende Mittagsgeschäft-Indikator, aber nur mit Konto abrufbar. Bleibt Link auf den Pendleratlas. |
| Denkmalliste Bayern (BLfD) | Kein offener OGC-Dienst gefunden. |

---

## Nachtrag 2026-08-01: Frequenzbringer erweitert

Die Liste in §4.2 deckt Bildung, Gesundheit, Kultur, Einkauf, Sport, Büro und Tourismus
ab. Für einen Schnellgastronomie-Standort fehlen darin Objekte, die Laufkundschaft und
wiederkehrende Wege erzeugen. Gegenprobe mit einer eigenen Overpass-Abfrage am
Sendlinger Tor, r=600:

```
amenity: marketplace, bus_station, fuel, pharmacy, bank, post_office,
         townhall, courthouse, community_centre
shop:    kiosk, greengrocer, deli, beverages
→ 46 zusätzliche Objekte (39 Knoten, 7 Wege)
```

Aufgenommen mit einer eigenen Kategorie „Markt & Alltagsversorgung" und „Behörden".
Die kombinierte Abfrage liefert damit **843 statt 801 Elemente**, die Frequenzbringer
steigen von 354 auf 396. Das Fixture `raw_overpass_combined.json` wurde neu
aufgezeichnet (Stand 2026-08-01T09:16:36Z).

---

## Nachtrag 2026-08-01: GENESIS erneut geprüft, diesmal mit der richtigen Methode

Die erste Prüfung des GENESIS-Webservice lief per **GET** und lieferte deshalb nur
`HTTP 405 – Method Not Allowed`; der Befund „Access forbidden" war damit nicht belastbar.
Die REST-Schnittstelle 2020 verlangt **POST**. Nachgeholt:

| Aufruf (POST) | Antwort |
|---|---|
| `regionalstatistik.de/genesisws/rest/2020/helloworld/logincheck` | `{"Status":"Sie wurden erfolgreich an- und abgemeldet!","Username":"GAST"}` |
| `…/catalogue/tables` mit leeren Zugangsdaten | `Code 15 — Sie sind nicht berechtigt diesen Service aufzurufen` |
| `…/catalogue/tables` mit `GAST/GAST` | `Code 15` |
| `…/data/table?name=13111-01-03-5` mit `GAST/GAST` | `Code 15` |
| dieselben Zugangsdaten als HTTP-Header statt als Formularfeld | `Code 15` |

**Ergebnis:** Der Anmeldedienst antwortet und nennt sogar das Gastkonto, die eigentlichen
Katalog- und Datendienste weisen es aber ab. Ein (kostenfreies) registriertes Konto ist
tatsächlich nötig. Der Befund bleibt bestehen, ruht jetzt aber auf richtiger Methodik.

### Regionale Tiefe — die eigentliche Einschränkung

Feinste Gliederung der Tabelle 13111 („Sozialversicherungspflichtig Beschäftigte am
Arbeitsort") ist die **Gemeinde** (`13111-01-03-5`, regionale Tiefe: Gemeinden). Darunter
wird nichts veröffentlicht — bei Beschäftigtenzahlen wäre sonst der einzelne Betrieb
identifizierbar.

Für dieses Werkzeug heißt das: Innerhalb Münchens hätte der Wert **keinerlei
Unterscheidungskraft**, weil Marienplatz und Sendlinger Tor dieselbe Zahl für 1,6 Mio.
Einwohner bekämen. Aussagekräftig wird er erst beim Vergleich **verschiedener Gemeinden**
im Umland — Garching, Unterschleißheim, Erding, Freising —, wo das Gemeindegebiet dem
Einzugsgebiet nahekommt.

### Kleinräumige Alternative geprüft und verworfen

`opendata.muenchen.de` führt „Indikatorenatlas: Arbeitsmarkt — Sozialversicherungspflichtig
Beschäftigte" je Stadtbezirksviertel. Die Datensatzbeschreibung sagt aber wörtlich:
*„Anteil der sozialversicherungspflichtig Beschäftigten **am Wohnort** …"*. Das sind
erwerbstätige Anwohner, nicht Arbeitsplätze am Ort — für das Mittagsgeschäft der falsche
Indikator. Die übrigen sechs Treffer betreffen das Personal der Stadtverwaltung selbst.

Die Lücke „Beschäftigte am Arbeitsort, kleinräumig" bleibt damit offen; unterhalb der
Gemeindeebene gibt es sie in offenen Daten nicht.

---

## Nachtrag 2026-08-01: Verhalten ohne Internetverbindung

Nachgemessen, weil im README bisher nicht beantwortet.

| Prüfung | Ergebnis |
|---|---|
| Installation in frischem venv nach README-Anleitung | Python 3.11.15, `pip install -e .`, CLI vorhanden |
| Serverstart mit totem Proxy (`HTTPS_PROXY=http://127.0.0.1:9`) | startet, `/` liefert HTTP 200 |
| `/api/point` ohne Netz, unbekannter Punkt | 2,0 s, alle Blöcke `ok=false`, `kind=connect`, Meldung „Verbindung nicht möglich — Dienst nicht erreichbar, DNS- oder Proxy-Problem" |
| einzelne Quellen ohne Netz | 5–12 ms, `osm` 2,0 s (drei Spiegel nacheinander) |
| `/api/point` ohne Netz, **vorher mit Netz geladener** Punkt | 14 ms, `outbound_requests: 0`, `aus_cache: true`, alle sechs Blöcke `ok=true` |

Belegwerte aus der Offline-Sitzung am Marienplatz: 110 Zensuszellen, 10.002 Einwohner,
15,98 €/m² Miete (86 von 110 Zellen), 380 Gastronomiebetriebe, Raddauerzählstelle
Erhardtstraße mit 1.415.000 Fahrten 2025. `verkehrsmenge` ist leer — am Marienplatz liegt
korrekterweise keine BAYSIS-Zählstelle.

Kein Ausfall führt zu Absturz oder Hänger; jeder benennt seine Ursache.

---

## Fazit für die Umsetzung

1. Alle fünf Pflichtendpunkte funktionieren. Kein Feature muss gestrichen werden.
2. Das einzige in der Spec markierte Risiko (Overpass-Rekursion) ist entfallen.
3. Zusätzlich zu implementieren, weil real vorgefunden: `resultOffset`-Paginierung,
   `null`-Behandlung bei Zensuswerten, `center`-Fallback bei Overpass-Ways/Relations,
   `addressdetails=1`, AGS-Übernahme aus dem Zensus-Block.
4. Der Nominatim-Rate-Limiter ist Funktionsvoraussetzung (403 ohne `User-Agent`).

---

## Nachtrag 2026-08-07: Stufe-3-Quellen (Baustellen, Märkte, Indikatorenatlas, BIP)

Alle Phase-0-Prüfungen mit echten Abrufen am 07.08.2026.

| Endpunkt | Prüfung | Ergebnis |
|---|---|---|
| `geoportal.muenchen.de/geoserver/mor_wfs/ows` · `typeName=mor_wfs:baustellen_opendata` | WFS 1.1.0 GetFeature, GeoJSON, `srsName=EPSG:4326` | 5.533 Features stadtweit; bbox-Filter funktioniert nur in **lon,lat**-Reihenfolge (lat,lon → 0 Treffer); native CRS EPSG:25832; Felder: strasse_hausnr, art (Baumaßnahme/Vorübergehendes Haltverbot), beginn/ende (TT.MM.JJJJ), beeintraechtigung, betroffene_bereiche, weitere_info (HTML-Link) |
| `geoportal.muenchen.de/geoserver/gsm_wfs/ows` · `typeName=gsm_wfs:maerkte` | WFS GetFeature GeoJSON | 54 Punkte (34 Wochen-, 10 Bauern-, 5 ständige, 5 Großmärkte); Name und Öffnungszeiten gemeinsam im Feld `inhalt`, Rubrik separat; Lizenz laut CKAN `dl-by-de/2.0` |
| `opendata.muenchen.de/api/3/action/package_search?q=indikatorenatlas` | CKAN-Suche + 6 CSV-Downloads | 68 Datensätze; CSV-Spalten `Indikator, Ausprägung, Jahr, Raumbezug, Indikatorwert, Basiswert 1/2, Name Basiswert 1/2`; Raumbezug „Stadt München" + 25 Bezirke („01 Altstadt - Lehel"); Dezimalpunkt; Reihen bis 2025 (Arbeitslosen-Anteil bis 2024); Kennzahl-Bedeutungen aus den Basiswert-Spalten belegt (z. B. Einpersonenhaushalte = Privathaushalte (Einpersonen) / Privathaushalte insgesamt: Stadt 54,4 %, Bezirk 01 63,7 %) |
| Regionalatlas `regionalatlas.ai017_1` (dynamicLayer, gleicher Dienst wie Einkommen) | POST mit `ags2 IN ('09162','09','DG')` | 72 Zeilen; Feldbedeutungen amtlich belegt (Katalog AI017-1 / bundesAPI-Doku): ai1701 = BIP je Erwerbstätigen (München 122.227 €), ai1702 = Veränderung zum Vorjahr (4,8 %), ai1703 = BIP je Einwohner (97.406 € vs. Bayern 57.725 € vs. Bund 49.525 €, Jahr 2023) |
| `www.mapillary.com/app/?lat=…&lng=…&z=17` | HTTP-Erreichbarkeit ohne Konto | 200 — als reiner Absprunglink aufgenommen |

**Geprüft und verworfen:**

| Kandidat | Befund |
|---|---|
| BORIS Bayern (Bodenrichtwerte) | Viewer-Einsicht frei, Datenabgabe in Bayern **gebührenpflichtig** (Portalseite nennt Gebühren mehrfach) → bleibt Link, kein Abruf |
| BASt-Straßenverkehrszählung (Stundenwerte) | Download frei (`2023_A_S.zip` → 200), aber nur Autobahnen/Bundesstraßen — für Innenstadtlagen deckt die Lärmkartierung den Kfz-Verkehr besser ab |
| Parkhäuser München (CKAN-JSON) | 72 Standorte mit Koordinaten, aber **ohne Kapazitäten** — gegenüber dem OSM-Bestand kein Mehrwert |
| `gis-service.destatis.de` | über den Sitzungs-Proxy nicht erreichbar (502) — nicht benötigt, der Regionalatlas läuft über `gis-idmz.nrw.de` |

## Nachtrag 2026-08-07 (2. Runde): Inside Airbnb und Regionaldatenbank (GENESIS)

Alle Phase-0-Prüfungen mit echten Abrufen am 07.08.2026.

| Endpunkt | Prüfung | Ergebnis |
|---|---|---|
| `insideairbnb.com/get-the-data/` | HTML-Abruf, Link-Extraktion | Deutschland: genau zwei Städte — `germany/bv/munich/2026-06-29` und `germany/be/berlin/2026-06-26`; Lizenzangabe der Seite: CC BY 4.0 |
| `data.insideairbnb.com/germany/bv/munich/2026-06-29/visualisations/listings.csv` | CSV-Download (1,2 MB) | 6.890 Inserate; Spalten u. a. latitude/longitude, room_type (4 Werte), price (nackte Zahl, Landeswährung; 4.465 von 6.890 gefüllt), number_of_reviews_ltm (durchgängig), availability_365. Marienplatz 600 m: 127 Inserate (86 ganze Unterkünfte, 41 Privatzimmer), Median-Preis 336 € (92 mit Preis), 1.135 Bewertungen/12 M. Achtung: Positionen plattformseitig um bis zu ~150 m versetzt |
| `regionalstatistik.de/genesisws/rest/2020/helloworld/whoami` | GET | 200 — REST-2020-Schnittstelle (GENESIS V5.0.4) erreichbar |
| `…/helloworld/logincheck` | POST (Kennung als Header) | unterscheidet live: gültige Kennung → „…erfolgreich an- und abgemeldet…“, falsche → Fehlermeldung, jeweils HTTP 200. GAST/GAST besteht den logincheck, hat aber keinerlei Datenrechte |
| `…/data/table` und `…/catalogue/tables` | POST ohne/mit GAST | HTTP 401, Code 15 „Sie sind nicht berechtigt…“ — **Daten- und Katalogabruf nur mit registrierter (kostenloser) Kennung** |
| Tabelle `73311-01-02-4` (Umsatzsteuerstatistik) | öffentlicher Werteabruf der Website, einmalig manuell (Struktur + ffcsv-Format aufgezeichnet) | Zeitraum 2009–2023; Merkmale KREISE (490), WZ08RS (20 Abschnitte), Werte STR007 (Umsatzsteuerpflichtige), UMS031 (steuerbarer Umsatz, Tsd. €). München 09162, Gastgewerbe WZ08-I, 2023: 4.019 Pflichtige, 6.584.298 Tsd. € → 1.638.293 € je Pflichtigem (1,3 % des Kreisumsatzes) |
| Tabelle `52311-01-04-4` (Gewerbeanzeigen) | ebenso | Jahressumme, aktuell 2025, keine WZ-Trennung auf Kreisebene; München 2025: 15.350 Anmeldungen (13.853 Neuerrichtungen, 3.713 Betriebsgründungen), 10.245 Abmeldungen (8.671 Aufgaben, 1.777 Betriebsaufgaben), Saldo +5.105 |
| ffcsv-Format (GENESIS V5) | aus dem echten Download | englisches Langformat, eine Zeile je Wert (`statistics_code;…;time;1_variable_code;…;value;value_unit;value_variable_code;…`), ISO-8859-1; Qualitätszeichen `-`/`.`/`x` als Fehlwerte |

**Entscheidung zum Abrufweg:** Die `robots.txt` von regionalstatistik.de untersagt
automatisierte Zugriffe auf die Weboberfläche komplett (`Disallow: /`). Der anonyme
Browser-Werteabruf diente deshalb nur der einmaligen manuellen Phase-0-Verifikation
(Format, Sollwerte, Fixtures); die Anwendung selbst spricht ausschließlich die
REST-Schnittstelle an — und die verlangt eine kostenlose Kennung → **Opt-in**
(Block 3e). Der Datenpfad mit echter Kennung nutzt exakt das aufgezeichnete
ffcsv-Format desselben Software-Stands (V5.0.4); der erste echte Abruf zeigt
etwaige Abweichungen als klare Fehlermeldung im Block.

**Korrektur eigener Annahmen:** Der zunächst vermutete Tabellencode
`73111-…` ist die **Lohn- und Einkommensteuer**, nicht die Umsatzsteuer —
der öffentliche Katalog wies `73311-01-02-4` als richtige Tabelle aus.
Merkmalscode der Regionalebene (`KREISE`) aus dem öffentlich einsehbaren
Tabellenaufbau übernommen, nicht geraten.

## Nachtrag 2026-08-07 (3. Runde): Messe, Tourismus-Monatszahlen, Erhaltungssatzungen

Alle Phase-0-Prüfungen mit echten Abrufen am 07.08.2026.

| Endpunkt | Prüfung | Ergebnis |
|---|---|---|
| CKAN `veranstaltungen-der-messe-muenchen` → `veranstaltungsdaten.csv` | Download (119 kB), Struktur | Semikolon-CSV, 307 Veranstaltungen ab 2018 **weltweit** (auch Delhi, Shanghai …) → Filter `stadt = München` nötig (95 Zeilen, davon 1 mit unlesbarem Termin „Mai 2.2026“). Besucher-/Ausstellerzahlen nur für vergangene Veranstaltungen (52 von 95). Lizenz laut CKAN `dl-by-de/2.0`, Herausgeber Messe München GmbH; Ressource am Prüftag zuletzt aktualisiert. Größte Veranstaltung: bauma 2025, 605.974 Besucher |
| CKAN `monatszahlen-tourismus` → `tourismus.csv` | Download (115 kB), Struktur | Komma-CSV, `MONATSZAHL` ∈ {Gäste, Übernachtungen} × `AUSPRAEGUNG` ∈ {Ausland, Inland, insgesamt}, Monate als `JJJJMM` plus `Summe`-Jahreszeilen, Fehlwerte `NA`; Reihen ab 2006, jüngster gefüllter Monat Dez 2025 (die 2026er-Zeilen existieren schon, sind aber `NA`). Kalenderjahr 2025: 19.631.581 Übernachtungen, 9.289.657 Gäste, Auslandsanteil 44,5 % |
| `geoserver/plan/wms` · `satz_erhalt_poly` | WMS GetFeatureInfo (`CRS:84`, `info_format=application/json`) | **funktioniert** — Haidhausen (48.1289, 11.5967): `gebietname`, `gueltig_ab` 11.03.2021, PDF-Links zu Plan/Text/Info; Marienplatz korrekt: leere Trefferliste. Layer ist `queryable="1"`. Achtung: WFS ist für den `plan`-Workspace **deaktiviert** („Service WFS is disabled“), und `plan_wfs` (anderer Workspace) führt den Layer nicht — nur der WMS-Weg geht |

**Geprüft und verworfen (Deutschland-Blick):**

| Kandidat | Befund |
|---|---|
| Monatswerte Tourismus je Kreis, bundesweit | Regionaldatenbank 45412-…: alle Kreis-Tabellen sind **Jahressummen** (Titel „… - Jahressumme - regionale Tiefe: Kreise …“); die Jahressumme steckt bereits im Kreisprofil (Regionalatlas). Destatis-GENESIS (`genesis.destatis.de/genesisWS/rest/2020`): Katalog-/Datenabruf antwortet HTTP 401 Code 15 — Kennung nötig, ein **zweites** Konto-Opt-in wäre gegen das Konto-Prinzip. Saisonkurve deshalb nur für München (offene CSV) |
| Foursquare OS Places als dritte Wettbewerbsquelle | Verworfen: FSQ OS Places ist **bereits Bestandteil des Overture-Places-Imports** (Overture-Attribution nennt Foursquare ausdrücklich — steht seit dem Import in unserer Lizenzzeile von Block 4f). Ein eigener Import müsste das globale Parquet (106 Mio. POIs, viele GB, keine Regionalpartitionierung über einfaches HTTP) laden — für ein Localhost-Werkzeug unverhältnismäßig und inhaltlich doppelt |
| Bundesweiter Messe-Kalender | Kein offener Datensatz: die AUMA-Messedatenbank ist kein Open Data, andere Messegesellschaften veröffentlichen keine vergleichbare CSV mit Besucherzahlen. Bleibt ein München-Bonus wie Märkte/Baustellen |
| Erhaltungssatzungen bundesweit | Kein bundesweiter Datensatz — Milieuschutz ist kommunales Satzungsrecht, jede Stadt führt (wenn überhaupt) eigene Dienste. Eingebaut für München; anderswo sagt der Block das ehrlich |

---

## Nachtrag 2026-08-07 (4. Runde): Deutschland-Ausbau (W-Runde)

Alle Prüfungen mit echten Abrufen am 07.08.2026; Fixtures im Repo.

### Regionaldatenbank — drei Gemeindetabellen über das bestehende Opt-in

| Tabelle | Prüfung | Ergebnis |
|---|---|---|
| `13111-01-03-5` SV-Beschäftigte am **Arbeitsort**, Gemeinden, Stichtag 30.06. | öffentlicher Werteabruf (einmalig manuell), ffcsv | Zeitcode STAG (`2025-06-30`), Wertcode ERW032; München 976 230 (30.06.2025, 687 000 in 2008), Garching b.München 32 823. **Befund:** kreisfreie Städte führen im Merkmal GEMEIN keinen eigenen Knoten (Wildcard `09162*` liefert nur den Kreisknoten) — sie kommen als KREISE-Zeilen zurück; der Abruf nutzt für AGS auf `000` direkt KREISE, sonst GEMEIN mit Rückfall |
| `45412-01-03-5` Tourismus-Jahressumme, Gemeinden | ebenso | GAST01/02/04/05; München 2024: 19 712 703 Übernachtungen, 9 279 239 Ankünfte, 470 Betriebe; „-“ (2008 Schlafgelegenheiten) → None |
| `13211-01-03-5` Arbeitslose, Jahresdurchschnitt, Gemeinden | ebenso | ERWP06; Garching 2025: 347; 2001 „-“ → None; Personengruppen-Zeilen (2_variable) werden übersprungen |

### Lärm bundesweit — UBA „VeLa/LK" (datahub.uba.de)

`…/server/services/VeLa/LK/MapServer/WMSServer` · WMS 1.3.0 · „Lärmkartierung
nach der EU-Umgebungslärmrichtlinie", Stand der Daten 12/2023, Runde 2022,
Urheber UBA, AccessConstraints leer.

- Layer **35** (`LK_BLR_Abfrage`): in Ballungsräumen beantwortet **eine**
  Klickabfrage alle Quellen (`road_den`, `road_night`, `rail_*`, `air_*` als
  Pegelklassen `Lden6569` …, plus Gemeindename). Sendlinger Tor München:
  road Lden6569/Lnight5559, ein Polygon zusätzlich mit Schiene — der
  Bundesdienst deckt auch Bayern ab (Gegenprobe).
- Außerhalb der Ballungsräume: Layer **30/29** (`LK_HLQ_road_Den/Night`).
  Berlin Hermannplatz: LdenGreaterThan75 + Lden7074 bzw. Lnight6569;
  Hamburg Reeperbahn Lden7074; Köln Nord-Süd-Fahrt Lden5559; der Kölner
  Ring-Punkt traf neben das Lärmband (leer) — Punkttreffer, kein Datenloch.
- Antworten sind 5-dB-Klassen; Bayern behält deshalb den präziseren
  LfU-Rasterdienst. GetMap `layers=27,30` liefert Karteninhalt (173 kB
  Berlin) → neue Bundes-Kartenebene. Einzelne Antworten brauchten ~30 s.

### Hochwasser bundesweit — BfG INSPIRE „Natural Risk Zones DE"

`geoportal.bafg.de/arcgis1/services/INSPIRE/NZ/MapServer/WMSServer` ·
Layer `NZ.HazardArea` · GetFeatureInfo `text/xml` (ESRI-`FIELDS`) ·
„Es gelten keine Zugriffsbeschränkungen".

- Passau Rathausplatz: **drei** Treffer in einer Abfrage —
  LikelihoodOfOccurrence high/medium/low-extrem = HQhäufig/HQ100/HQextrem.
- Kölner Rheinufer: nur low/extrem (hinter der Schutzlinie plausibel);
  Kölner Ring: leer. GetMap mit Inhalt (15 kB Passau) → Bundes-Kartenebene.
- Bayern behält die LfU-Abfrage (Gewässername, Jährlichkeit, Amt — das
  führt der Bundesdienst nicht).

### Kfz-Verkehr bundesweit — BASt-Dauerzählstellen

`bast.de …/verkehrszaehlung/Daten/2024_1/Jawe2024.csv?view=renderTcDataExportCSV`
· HTTP 200 · 1,84 MB · Latin-1 · 255 Spalten · **2 127 Zählstellen** (nur
Autobahnen und Bundesstraßen) · Nutzungsbedingungen der Seite: **CC BY 4.0**.

- Felder: `DZ_Name`, `Str_Kl`/`Str_Nr`, `DTV_Kfz_MobisSo_Q`,
  `DTV_SV_MobisSo_Q`, `Koor_WGS84_N/E`; deutsches Zahlenformat; leere
  Jahreswerte („Netzmodernisierung in 2024") → None.
- Belege: Berlin Hermannplatz → Britz (A 100) 3,0 km, 128 167 Kfz/Tag,
  SV 3,5 %; Kölner Ring → nächste Zählstelle 5,8 km (Rheinbrücke
  Rodenkirchen) — außerhalb des 5-km-Radius bleibt der Block bewusst leer.
- In Bayern bleibt BAYSIS (9 441 Zählstellen im ganzen klassifizierten Netz).

### Stadt-Adapter Hamburg — Urban Data Platform (OGC API Features)

`api.hamburg.de/datasets/v1` · je Datensatz dl-de/by-2-0 · bbox-Abfragen
Ende-zu-Ende verifiziert:

| Thema | Weg | Beleg |
|---|---|---|
| Wochenmärkte | `einzelhandel` → `wochenmarkt` | 80 stadtweit, St. Pauli: 4 im Umkreis (Spielbudenplatz, Hopfenmarkt …); **keine Öffnungszeiten** im Datensatz |
| Baustellen | `baustellen` → `baustelle` | „Bauweiser“-Steckbriefe, 130 stadtweit; St. Pauli Hafenstraße/Abwasser 26.01.2026–26.01.2029; `iststoerung` heißt „verursacht Verkehrsstörung“, nicht Subtyp |
| Rad-Dauerzählstellen | `dauerzaehlstellen_rad` | Felder als „Label\|Wert“: Gurlittinsel `2025\|1926930` (5 279/Tag), Vortag `06.08.2026\|8277`, Tageslinie stündlich |
| Milieuschutz | `soz_erh_vo` → `sozerhvo_inkraft` | 16 Gebiete in Kraft; St. Georg seit 15.02.2012 mit Verordnungs-PDF (luewu.de) |

### Stadt-Adapter Berlin — VIZ-Baustellen

`api.viz.berlin.de/daten/baustellen_sperrungen_viz.json` (Ressource laut
Datenregister Berlin, `dl-de-by-2.0`) · 0,5 MB · 231 Features (144
Baustellen, 83 Sperrungen) · GeometryCollection-Geometrien ·
`validity.from/to` ISO. Beleg: Wolfensteindamm Steglitz, Baustelle in 338 m.

**Geprüft und nicht aufgenommen (Berlin/Köln):** `gdi.berlin.de` und
`fbinter.stadt-berlin.de` sind aus dieser Prüfumgebung weiterhin nicht
erreichbar (TLS-Verbindungsabbruch, nachgeprüft 07.08.2026) — Wochenmärkte,
Milieuschutz und Rad-Zählstellen Berlins bleiben deshalb draußen statt
ungeprüft verdrahtet. Für Köln fand die Prüfung keinen belegbaren offenen
Dienst zu den vier Themen (CKAN-API-Pfad `offenedaten-koeln.de/api/3/…`
antwortet 404).

### Erneut geprüft (W7)

| Dienst | Befund 07.08.2026 |
|---|---|
| INKAR (inkar.de) | **wieder erreichbar** — die frühere TLS-Störung ist behoben. Maschineller Datenweg: nur das Gesamtpaket `inkar_2025.zip` (**434 MB**, Stand 13.08.2025) — als Live-Quelle unverhältnismäßig; Kreis-/Gemeindewerte kommen aus Regionalatlas/Regionaldatenbank. Bleibt Link, Warnung aktualisiert |
| Berlin Bodenrichtwerte (gdi/fbinter) | weiterhin TLS-Abbruch aus dieser Umgebung — bleibt Portallink |
| Sachsen (geodienste.sachsen.de) | weiterhin 403/404 auf Prüfabrufe — bleibt Portallink |

---

## Nachtrag 2026-08-07 (5. Runde): Versorgungsgrad, Photon, Verwerfungen (X-Runde)

| Prüfung | Ergebnis |
|---|---|
| **Photon** (`photon.komoot.io`) | `api?q=Sendlinger+Str+10+München` → hausnummerngenau (street/housenumber/city/state/postcode), `/reverse` am Sendlinger Tor → Adresse; kein Bundesland-ISO, keine licence im JSON (ODbL-Konstante). Eingebaut als **Rückfall**, wenn Nominatim scheitert — nie stillschweigend (Warnung + eigene Quellenangabe) |
| **Versorgungsgrad** | Betriebe je 1.000 Einwohner im Umkreis, berechnet aus zwei vorhandenen Blöcken (OSM ÷ Zensus); Anker: die in der amtlichen Statistik (Statistisches Landesamt BW / DEHOGA) zitierte Schwelle „< 1 Betrieb je 1.000 EW = gastronomische Unterversorgung“. Reine Rechnung, als „berechnet“ beschriftet |
| Freischankflächen / Sperrzeiten München | CKAN-Suche `freischank`, `sperrzeit`, `sondernutzung gastronomie` → je **0 Treffer** auf opendata.muenchen.de. Kein Einbau, kein Raten |
| Gewerbeanzeigen quartalsweise / nach WZ 56 je Kreis | Katalog-Nachprüfung: es existiert nur `52311-01-04-4` (Jahressumme, ohne Branchentrennung) — der Befund der T-Runde bleibt bestehen; eine offene Quartals-/WZ-Tabelle auf Kreisebene gibt es nicht |
| Leerstandsmelder-API | `api.leerstandsmelder.de/api/v1/places` antwortet offen, liefert aber den **ungefilterten Weltbestand** (9 318 Meldungen, lat/lon-Parameter ohne Wirkung) und die Seite (SPA) nennt maschinell keine Datenlizenz → bleibt Link mit Befund |
| OffeneRegister.de | Gesamtdownload ~250 MB (eingefrorene Datenspende), Abfrage-API `db.offeneregister.de` → HTTP 502 → bleibt Link mit Befund; aktuelle Alternativen sind kommerziell |
| DEHOGA-Zahlenspiegel | Quartals-PDFs, kein stabiler Datenendpunkt → als beschriebener Link aufgenommen, bewusst kein PDF-Parser |

---

## Nachtrag 2026-08-08 (6. Runde): PKS, Leerstandsmelder, OffeneRegister (Y-Runde)

Auf Wunsch des Nutzers wurden drei früher verworfene Quellen neu bewertet:
Redundanz zählt, wenn die Quellen unabhängig sind — und zwei der drei
Ablehnungsgründe waren Form (XLSX) bzw. Aufwand, nicht die Datenlage.

| Prüfung | Ergebnis |
|---|---|
| **BKA PKS-Kreistabelle** `bka.de/SharedDocs/Downloads/…/KR-F-01-T01-Kreise-Faelle-HZ_xls.xlsx?__blob=publicationFile&v=4` | HTTP 200, 2,1 MB, ein Blatt, 16 809 Zeilen = **400 Kreise × 41 Delikte**, Daten ab Zeile 10; Spalten A Schlüssel (`------` = insgesamt), C AGS5, F Fälle, G HZ (Zensus-2022-Basis), M Aufklärungsquote. Stichprobe München 09162: 93 854 Fälle, HZ 6 304,3, AQ 63,1 % — Rang 148 von 400 (Köln: 134 209 / 13 101,1). Eingebaut als Block **3g** (Stdlib-XLSX-Parser, einmal geladen, lokal ausgewertet, Rang+Median aus derselben Datei) |
| BKA-Lizenzlage | Impressum nachgeprüft: Urheberrecht, „Kopien … nur für den privaten Bereich" — **keine offene Datenlizenz** (kein dl-de, kein CC). Steht wörtlich in Lizenzzeile und Warnung am Block; das Werkzeug lädt die veröffentlichte Tabelle direkt beim BKA und zeigt sie lokal mit Quellenangabe |
| **Leerstandsmelder** `api.leerstandsmelder.de/api/v1/places` (Endpunkt aus dem SPA-Bundle) | HTTP 200, 3,0 MB, 9 318 Meldungen weltweit, alle mit lat/lon (Strings) und `published`; Felder title/road/slug/created_at/enddate. Absprung `leerstandsmelder.de/places/<slug>` (Pfad aus dem Bundle). Gegenprobe Sendlinger Tor: 32 Meldungen < 2 km, nächste „Leerstand am Sendlinger Tor" 126 m. Eingebaut als Block **7b** auf ausdrücklichen Nutzerwunsch — Weltbestand einmal geladen, lokal gefiltert; Lizenz bleibt ungeklärt, Warnung am Block |
| **OffeneRegister** `daten.offeneregister.de/de_companies_ocdata.jsonl.bz2` | HTTP 200, 260 455 433 Bytes, `Last-Modified: 05 Feb 2019`; Startseite nennt **CC BY 4.0** (frühere Kurznotiz „keine Lizenz" damit korrigiert). Mehrstromiges bz2 (pbzip2) — Import über `bz2.open`. Schema geprüft (OpenCorporates-JSONL): name, current_status, registered_address **mit PLZ**, native_company_number, registrar. Abfrage-API `db.offeneregister.de` weiterhin HTTP 502. Eingebaut als Einmal-Import `python -m gastroviewer import-register` → lokale SQLite mit PLZ-Index, Block **7c** (klar beschriftet „Stand 2019") |
| Vollimport-Selbstprüfung | Import real ausgeführt: 260 MB geladen, Gesamtbestand in SQLite gebaut, PLZ-Abfrage am Sendlinger Tor (80331) im Browser geprüft — Zahlen siehe Abnahmeprotokoll dieser Runde |

**Bewusst weiterhin nicht eingebaut** (Frage „was ergibt keinen Sinn"):
INKAR-Gesamtpaket (434 MB für Indikatoren, die zu großen Teilen schon aus
Regionalatlas/Regionaldatenbank kommen; die INKAR-Alleinstellungen sind
Modellwerte, keine Messungen) und eine **zweite** GENESIS-Kennung bei
Destatis (gegen das Ein-Konto-Prinzip; Mehrwert wäre allein die
Monats-Saisonkurve je Kreis, deren Jahressummen bereits im Kreisprofil
stehen).

---

## Nachtrag 2026-08-08 (7. Runde): Bautätigkeit, Luftqualität, Wahl + Funktions-Ausbau (Z-Runde)

| Prüfung | Ergebnis |
|---|---|
| **Bautätigkeit je Gemeinde** `31111-01-02-5` (Baugenehmigungen) / `31121-01-02-5` (Baufertigstellungen) | Tabellencodes über die Werteabruf-Oberfläche verifiziert (`-01-01-5`/`-02-01-5` existieren nicht); ffcsv einmal manuell aufgezeichnet: je Gemeinde/Jahr Wohngebäude (BAUGEB01) mit Gebäuden (BAU015), **Wohnungen (WOHN01)** und Wohnfläche (FLC001, 1000 qm); Untergliederung WHGZHL… wird ignoriert. München 2024: **7 118 genehmigt, 5 915 fertiggestellt** (Pipeline +1 203); Garching über GEMEIN-Knoten (67/80). Läuft über die **bestehende** Regionalstatistik-Kennung — kein neues Konto |
| **UBA-Luftqualität** `luftdaten.umweltbundesamt.de/api/air-data/v3` | Offen, ohne Schlüssel (alte www-Adresse leitet weiter). `stations/json?use=airquality`: Stationen mit Koordinaten (Feldfolge aus `indices`; München 5, DEBY037 Stachus = id 471); `airquality/json`: je Stunde `[Ende, Gesamtindex, unvollständig, [Komponente, Wert, Teilindex]…]`. Skala 0-basiert belegt: NO₂ 13 µg/m³ → Teilindex 0 („sehr gut" nach UBA-Schwelle bis 20). Browser-Befund Sendlinger Tor: Index „sehr gut", NO₂ 13/PM₁₀ 16/PM₂,₅ 7, Station Stachus 472 m NW |
| **Bundestagswahl 2025** (Bundeswahlleiterin, beide dl-de/by-2-0) | `kerg2.csv` (1,8 MB, endgültig 14.03.2025, Spalte `DiffProzentPkt`) + Zuordnung `btw25_wkr_gemeinden_20241130_utf8.csv` (AGS aus RGS-Bausteinen; München = **WK 216–219**, Garching = WK 220). Mehr-Wahlkreis-Gemeinden: absolute Zweitstimmen summiert, Punktdifferenzen entfallen dann ehrlich. Browser-Befund München: CSU 29,4 %, GRÜNE 23,5 %, SPD 15,3 %, Beteiligung 84,3 % (gewichtet) — mit Struktur-Marker-Warnung am Block |
| **ÖPNV-Einzugsgebiet** (rein lokal) | Runden-Router über das importierte GTFS (RAPTOR-Idee, max. 2 Umstiege, benannte Vereinfachungen am Block). Realprobe Sendlinger Tor 30 min: **2 144 Halte, 124 Linien, fernster Halt Garching-Forschungszentrum 16,5 km (29 min — deckt sich mit der echten U6-Fahrzeit)**, Einwohner-Näherung 1,27 Mio. über das 1-km-Gitter; Laufzeit ~11 s → auf Anforderung mit Cache |
| **Autovervollständigung** | Nur über Photon — dabei Altbestand korrigiert: die frühere 1,1-s-Tippsuche ging an **Nominatim**, dessen Regeln Autocomplete ausdrücklich untersagen. Jetzt: Tippen → Photon-Vorschläge (350 ms, serverseitig gecacht), Enter → präzise Nominatim-Suche |
| **Kannibalisierungs-Check** | Realprobe Sendlinger Tor ↔ Marienplatz (600-m-Radien, 722 m Abstand): 3 629 gemeinsame Einwohner = 22,2 % von A / 36,0 % von B — über 100-m-Zensuszellen, Grenzen benannt |
| **Standort-Finder / Veränderungs-Wächter** | Finder: Top-10-Zellen des Scans nach eigenen Gewichten (Perzentilränge, Komposit offen beschriftet), Browser-Befund 875 Zellen → 10 Marker. Wächter: OSM-Gastro-Diff je gespeichertem Punkt ohne Überschreiben (Realprobe: 281 → 281, unverändert) |

---

## Nachtrag 2026-08-08 (8. Runde): CI-Testlauf + Review-Härtung

Keine neue Quelle — ein Qualitätsdurchgang: drei unabhängige Code-Reviews
(neue Quellen-Module, Service/API-Kern, komplette Oberfläche), jeder Fund
vor dem Fix einzeln verifiziert, die wichtigsten mit Regressionstests
abgesichert. Dazu ein zweiter GitHub-Actions-Workflow **„Tests"**, der bei
jedem Push die komplette pytest-Suite (offline gegen aufgezeichnete
Antworten) und den JS-Syntaxcheck auf Python 3.10 und 3.12 ausführt —
bisher lief nur der Installer-Bau mit Rauchprobe.

| Befund (verifiziert) | Fix |
|---|---|
| Wächter-Endpunkt: HTTP 500, wenn der gespeicherte Punkt bei OSM-Ausfall `data: null` trägt (`.get("data", {})` greift nur bei *fehlendem* Key) | `… or {}` wie in der Schwesterfunktion; Regressionstest |
| Cache-Stampede: gleichzeitige gleiche Anfragen (z. B. `/api/point/osm` + `/api/point/gehweg` bei kaltem Cache) lösten **zwei identische Overpass-Abfragen** aus | Laufende Abrufe je Cache-Key dedupliziert (`service._laufend`); Regressionstest: Loader läuft bei zwei gleichzeitigen Aufrufen genau 1× |
| „Kein GTFS importiert" wurde beim ÖPNV-Einzugsgebiet bis 24 h gecacht — direkt nach `import-gtfs` blieb der Block leer | Wie beim Register: ohne `gtfs.sqlite` wird nicht gecacht; Regressionstest |
| Mehrsekündige synchrone Parser (PKS-XLSX ≈ 5 s CPU, BASt, Airbnb, Wahl, Rad-Jahresdatei, Indikatoren) froren beim Cache-Füllen den ganzen Server ein | alle sechs über `asyncio.to_thread` |
| GTFS-Einzugsgebiet: `abfahrt="00:00:00"` wurde stumm als 12:00 gerechnet (`or`-Rückfall auf falsy 0) und der ausgewiesene Referenztag war der beim **Abruf** neu bestimmte Dienstag statt des gerechneten Import-Referenzdatums | expliziter `None`-Vergleich; Ergebnis meldet exakt den gerouteten Tag; zwei Regressionstests |
| Genesis: KREISE-Rückfall einer normalen Gemeinde wurde als „kreisfreie Stadt" etikettiert (Landkreiswerte als Gemeindewerte) | Ebene „Kreis (Rückfall)" + Warnung am Block + Kennzeichnung im Frontend; Regressionstest |
| Register-Import: PLZ-Regex verwarf die PLZ, sobald nach dem Ort noch eine Ziffer stand („…, Zimmer 3") | letzte fünfstellige Zahl per `findall`; Regressionstest |
| Oberfläche: ÖPNV-Einzug und Markensuche übernahmen verspätete Antworten für den inzwischen gewechselten Punkt (fehlende `ladeLauf`-Prüfung) | Lauf-Prüfung wie bei den Geschwisterfunktionen |
| Oberfläche: bei Zensus-Ausfall blieben sieben Folgeblöcke (3b–3e, 3g, 3h, 6f) für immer auf „lädt …" | Loader werden im Fehlerpfad mit leerem Schlüssel aufgerufen und sagen das ehrlich |
| Oberfläche: bei Overpass-/Zensus-Ausfall nach Punktwechsel blieben Marker und Gitter des **vorigen** Punkts auf der Karte | POI- und Zensus-Ebenen werden beim Wechsel sofort geleert |
| Oberfläche: sichtbarer Text „null" an drei Stellen (`replaceChildren` stringifiziert null — Adressliste, Mietprobe, Branchenprofil; die dritte Stelle fand erst die Browser-Selbstprüfung) | `.filter(Boolean)` wie an den dokumentierten Altstellen |
| Oberfläche: Enter innerhalb der 350-ms-Entprellung — die Nominatim-Treffer wurden von den verspäteten Photon-Vorschlägen überschrieben (`clearTimeout` zeigte auf einen nie gesetzten Alt-Timer) | Vorschlags-Timer und laufende Vorschlags-Abrufe werden bei Enter verworfen; Browser-verifiziert („3 Treffer" bleibt stehen) |
| Kleineres: ÖPNV-Einzug-Ebene ignorierte den Deckkraftregler; Vergleichs-Dialog/Notiz-Speichern/Löschen ohne Fehlerbehandlung (Notiz ging bei Serverfehler stumm verloren) | Ebene registriert, Fehler werden angezeigt |

Bewusst nicht angefasst: die `meta.outbound_requests`-Zählung je Antwort
zählt bei parallelen Requests auch fremde Abrufe mit (globaler Zähler ohne
Request-Bezug) — reine Anzeige-Ungenauigkeit, eine request-bezogene Zählung
stünde in keinem Verhältnis zum Nutzen.

Browser-Selbstprüfung nach den Fixes: kein hängender Block, Punktwechsel
leert die Marker-Ebenen sofort (281 → 0 → 384), kein „null"-Text mehr,
keine JS-Fehler. Testsuite: **549 Tests grün** (542 + 7 neue Regressionen).

---

## Nachtrag 2026-08-08 (9. Runde): Kostenfaktor, Besonnung, Frequenz, Baurecht (AA-Runde)

Sechs neue Quellen und eine gerechnete Auswertung. Die Runde ging aus einer
ergebnisoffenen Recherche über vier Richtungen hervor; die Verwerfungen unten
sind Teil des Ergebnisses.

| Prüfung | Ergebnis |
|---|---|
| **Realsteuervergleich** `71231-01-03-5` (Gemeindeebene) | ffcsv am 2026-08-08 aufgezeichnet. Wertecodes STNW07/08/09 (Hebesätze Grundsteuer A/B, Gewerbesteuer), STNW15 Steuereinnahmekraft. **München 490 % Gewerbesteuer / 535 % Grundsteuer B, Garching 330 % / 310 %** — 160 Prozentpunkte Unterschied. Der erste harte, gemeindescharfe Kostenfaktor des Werkzeugs; läuft über die bestehende Kennung |
| **Unternehmensregister** `52111-02-01-4` | `WZ08-I` = Gastgewerbe, `WZ08-B-10` = Insgesamt. München 2024: **4 705 Gastgewerbe-Niederlassungen von 94 691** (4,97 %), Zeitreihe ab 2006 (+5,7 %). Der amtliche Nenner zur OSM-Zählung. **Nicht möglich:** eine gastrospezifische Insolvenzquote — die Insolvenzstatistik (52411) führt regional keine Wirtschaftszweige |
| **Bildungstabellen** `21311-01-01-4`, `21111-01-03-4` | Studierende nach Fächergruppen (München WS 2023/24: **108 490**, davon Recht/Wirtschaft/Sozial 40 264, Ingenieure 25 618) und Schüler nach Schularten (**137 846**, Grundschulen 50 434). Filter: Geschlecht **und** Nationalität „Insgesamt", sonst Mehrfachzählung. Fernstudium-Warnung (Hagen) steht am Block |
| **Sonnenstand** (keine Quelle nötig) | Verfahren nach Astronomical Almanac, gegen die theoretischen Extremwerte geprüft: München **65,3° zur Sommer-, 18,4° zur Wintersonnenwende**, Tageslängen 16,1 h / 8,3 h. Gebäude aus Overpass (`way[building]`, `out geom`), 150-m-Umkreis, 64 KB je Abfrage |
| Höhenabdeckung in OSM | Real gemessen: Münchner Innenstadt 77 %, Altstadt 75 %, Garching 51 %, Kassel 56 %, Hamburg 57 %. Gebäude **ohne** Höhenangabe werden nicht geschätzt, sondern gezählt und ausgewiesen — das Ergebnis ist damit eine Obergrenze |
| Verschattung, Gegenprobe an zwei echten Lagen | Enge Altstadt (48,13745/11,57538): höchstes Hindernis **45,3° im Süden**, Wintersonne **0,7 h**, mittags zur Tagundnachtgleiche eine Lücke von 11:10 bis 13:00. Offener Platz (Sendlinger Tor): **6,2 h** Wintersonne durchgehend, Abendsonne im Sommer 3,3 h statt 1,5 h |
| **Passantenfrequenz** hystreet.com | API existiert (`api.hystreet.com/v2`, OpenAPI-Spec offen), aber die Datensatzbeschreibung der Stadt Münster hält wörtlich fest: im kostenfreien Modell wird „eine gewerbliche Nutzung untersagt". Für ein Standortanalyse-Werkzeug damit **unbrauchbar** |
| Passantenfrequenz über Städte | Einzelne Kommunen haben lizenziert und geben unter offener Lizenz weiter. Eingebaut: **Dortmund** (3 Zählstellen, stündlich, quasi Echtzeit, dl-de/**zero**), **Würzburg** (3, stündlich mit Wetter/Richtung/Zonen, dl-de/by, Nachlauf seit Mai 2026 gestoppt), **Augsburg** (1, Stunden-CSV, CC BY 4.0). Tagesgänge real: Dortmund Westenhellweg Ost Spitze 16 Uhr mit 2 939/h, **Abendanteil 24,4 %**; Würzburg Schönbornstraße Spitze 14 Uhr, **Abendanteil 7,4 %** |
| Bewusst nicht aufgenommen | **Oldenburg** (4 Zählstellen, gleiche Lizenz) veröffentlicht nur **Tagessummen** — ohne Stundenwerte fehlt genau der Tagesgang, um den es geht |
| **Baurecht: die Kernlücke** | GDI-DE-Katalog abgefragt: `%Bebauungsplan%` → **566 145** Datensätze, `%BP_BaugebietsTeilFlaeche%` → **15**. Die Art der baulichen Nutzung ist bundesweit fast nirgends maschinenlesbar |
| XPlanSyn-Dienste | Punktgenau geprüft: **Hamburg** (23 159 Teilflächen, dl-de/by-2-0) und **Freiburg** liefern `besondereArtDerBaulNutzungWert`; beide antworten am Testpunkt „Kerngebiet" (MK) |
| Berlin | B-Plan-Umringe mit PDF (2 844 Pläne), Sanierungsgebiete (§§ 144/145 BauGB) und Denkmalliste (9 578 Objekte), alle **dl-de/zero-2-0**. Das Feld `inhalt` ist planweiter Freitext, **nicht** flächenscharf |
| Baurecht: Absagen mit Beleg | **München** behält sich sämtliche Rechte an den Bauleitplandaten vor. **Bayerns** Landesdienst führt nur Umringe und antwortet in München, Regensburg, Augsburg, Ingolstadt und Rosenheim leer. **Sperrzeiten** gibt es maschinenlesbar nicht: GovData 0 Treffer, GDI-DE-Katalog 0 Treffer, das Bundes-Rechtsinformationsportal führt nur Bundesrecht — Sperrzeiten sind Landes- und Kommunalrecht |
| **IHK Berlin** Gewerbedaten | **CC0**, monatlich, 368 000 Zeilen mit Koordinate, PLZ, LOR-Planungsraum, Betriebsalter und Beschäftigtenklasse; 23 456 Betriebe in NACE 55/56. Git LFS: **media**.githubusercontent.com, nicht raw (dort kommt nur der Zeiger). 125 MB → auf Anforderung, danach 30 Tage Cache |
| **OpenHolidaysAPI** | ODbL, Feiertage **und** Schulferien aller 16 Länder. Gegen die amtlichen KMK-iCal-Dateien gegengeprüft (Baden-Württemberg 2026/27: identische Termine). Bewusst nur Kontextband ohne Verrechnung — Feiertage unterscheiden zwei Standorte derselben Stadt nicht |
| Kalender: Absagen | **feiertage-api.de** bezieht seine Daten laut eigener Seite aus Wikipedia und nennt keine Lizenz; **ferien-api.de** antwortet mit HTTP 429, sagt „ohne Gewähr" und liefert für 2027 stumm eine leere Liste. Die **KMK** taugt nicht als Live-Quelle (wechselnder TYPO3-Hash in der Adresse, keine Feiertage, keine Lizenzangabe) |

**Drei Implementierungsfallen, alle in Phase 0 belegt und im Code vermerkt:**

1. **WFS-Achsenreihenfolge:** `urn:ogc:def:crs:EPSG::4326` liefert bei deegree stumm **null** Treffer. Richtig ist `urn:ogc:def:crs:OGC:1.3:CRS84` in lon/lat.
2. **Ausgabeformat je Dienst:** Die XPlanSyn-Instanzen lehnen `application/json` mit **HTTP 400** ab und verlangen `application/geo+json`; Berlin umgekehrt.
3. **Bbox-Größe und Punktprüfung:** Eine sehr kleine Bbox (0,0002°) liefert bei deegree null Treffer, eine größere (0,0015°) drei. Deshalb holt die Abfrage Kandidaten in einem ~90-m-Fenster, und erst eine **Punkt-in-Polygon-Prüfung** entscheidet, welche Fläche den Standort wirklich enthält. Ohne sie stand im ersten Entwurf die Gebietsart des Nachbargrundstücks im Block — der Fehler fiel erst beim Live-Test auf.

**Nicht gebaut, mit Begründung:**

* **Handelsregister aktuell:** Auf dem OffeneRegister-Server liegt eine undokumentierte Datei `handelsregister.db` (3,72 GB, Stand 21.10.2022) — dreieinhalb Jahre frischer als der eingebaute Dump von 2019, gleiches Schema, mit PLZ. Sie trägt aber **keine Lizenzangabe**. Vor einer Nutzung müsste die Open Knowledge Foundation gefragt und die Antwort hier dokumentiert werden. `handelsregister.de` selbst (seit 2022 kostenfrei) hat keine Schnittstelle, deckelt bei 60 Abrufen je Stunde und droht in der Nutzungsordnung mit §§ 303a/b StGB; `unternehmensregister.de` sperrt die Suchpfade per robots.txt.
* **Insolvenzbekanntmachungen:** robots.txt erlaubt nur die Startseite, und die FAQ hält wörtlich fest, Sinn sei die Einzelfallprüfung und ausdrücklich **nicht**, „ohne konkreten Bezug sehen zu können, welche Insolvenzverfahren allgemein eröffnet wurden".
* **OParl** (kommunale Ratsinformationssysteme): 127 Endpunkte geprüft, 3 000 Drucksachen ausgewertet — **eine** mit Ortsangabe, **keine** mit Koordinate. Dazu 119 von 127 Systemen ohne Lizenzangabe und fünf mit ausdrücklichem Genehmigungsvorbehalt. Ohne Ortsbezug für ein Standortwerkzeug wertlos.
* **Hamburger Gewerbeanzeigen je Bezirk** (Statistikamt Nord D I 2, dl-de/by-2-0, robots erlaubt): Die Gastgewerbe-Zeilen existieren (WZ 56, Zeile 46 der Blätter `T2_1`/`T8_1`), aber die Blätter haben verschachtelte Mehrzeilen-Kopfzeilen, deren Spaltenbedeutung sich in Phase 0 nicht zweifelsfrei zuordnen ließ. Ein falsch zugeordneter Parser liefert plausibel aussehende **falsche** Zahlen — deshalb nicht gebaut. Der Weg bleibt offen, braucht aber eine saubere Kopfzeilen-Analyse.
* **Zensus-Gitter:** geprüft, ob Merkmale fehlen — das Werkzeug liest bereits alle 29 fachlichen Felder inklusive Altersklassen, Haushaltsgröße, Leerstands- und Eigentümerquote und Baujahr. Keine Lücke.
* **Gewerbemietspiegel:** Die IHKs veröffentlichen ausschließlich PDFs, kein maschinenlesbares Format — dieselbe Lage wie beim bereits verworfenen DEHOGA-Zahlenspiegel.
* **Amtliche 3D-Gebäudemodelle** (LoD1-DE): entgegen der Erwartung **nicht** in der BKG-Open-Data-Liste; offen sind nur 3D-Tiles zur Darstellung. LoD2 ist Open Data, aber ein Flickenteppich je Bundesland mit sehr großen Downloads — für die Verschattung reicht OSM mit ausgewiesener Abdeckung.

**Betriebsbefunde:** Die GENESIS-**GET**-Methode wurde am 27.11.2025 abgeschaltet (HTTP 405) — das Werkzeug ist nicht betroffen, es nutzt durchgehend POST. Der Berliner Geodienst `gdi.berlin.de` nutzt ein Wurzelzertifikat, das ältere Zertifikatsspeicher nicht kennen; das Werkzeug übersetzt den TLS-Fehler in eine verständliche Meldung mit dem Hinweis auf `pip install --upgrade certifi`. Die CKAN-Schnittstellen der Portale München, Berlin und Hamburg sind per robots.txt gesperrt (`Disallow: /api/`) — die eigentlichen Download-Adressen nicht; das Werkzeug verdrahtet sie deshalb fest, statt die API abzufragen.

Browser-Selbstprüfung: alle fünf neuen Blöcke rendern, kein hängender Block, kein „null"-Text, keine JS-Fehler. Dabei fiel auf, dass die Markdown-Betonung (`**so**`) der Quellenmodule als sichtbare Sternchen im Text stand — zentral behoben, betrifft jetzt alle 21 Hinweis-Renderings und sämtliche Warnungen. Testsuite: **613 Tests grün** (549 + 64 neue).

---

## Nachtrag 10. Runde (09.08.2026) — die Oberfläche prüft sich jetzt selbst

Diese Runde hat keine neue Datenquelle gebracht, sondern die letzte große Lücke in der Absicherung geschlossen. Die Oberfläche ist mit über 6 000 Zeilen `app.js` das größte Einzelstück des Projekts und war bis hierher nur per Syntaxprüfung abgedeckt. Die Browserprüfung `scripts/uitest.py` existierte zwar mit 43 Prüfungen, brauchte aber einen Server **mit Internetzugang** und lief deshalb nur von Hand.

**Der Aufbau.** `scripts/aufzeichnen.py` nimmt einmalig die echten `/api`-Antworten für sieben Prüfkoordinaten auf (Marienplatz, Isarufer, Isarauen, Freiham, Giesing, Haidhausen, Köln) — 224 Antworten, roh 7,8 MB, gepackt 1,32. `scripts/attrappe.py` spielt sie ab. Es ist bewusst **kein** Antwort-Abspieler, sondern die echte Anwendung mit abgeschalteter Datenschicht: Von den 44 Prüfungen brauchen sechs Zustand — merken, benoten, vergleichen, löschen. Deshalb laufen alle `/api/points`-Routen sowie Bericht und Duell echt gegen eine frische Datenbank in einem Wegwerfordner; nur die datenholenden Routen kommen aus der Aufzeichnung. Der ausgehende Verkehr ist gesperrt und meldet sich mit Klartext statt mit einem Zeitablauf.

**Drei Befunde, alle vom selben Typ.** Der erste vollständige Lauf brachte drei Fälle ans Licht — und keiner davon war ein Fehler in der Oberfläche, sondern jedes Mal eine Prüfung, die stillschweigend nichts prüfte:

* Die Prüfung „Quelle, Stand, Lizenz je Block" führte eine **handgepflegte Namensliste** der ausgenommenen Auf-Knopfdruck-Blöcke. Sie war seit Block 6h (ÖPNV-Einzug) und 4g (IHK Berlin) veraltet und meldete beide fälschlich als quellenlos. Nachverfolgt zeigte sich: `zeigeIhkBerlin` setzt die Quelle in jedem Zweig, auch im Fehler- und im Leerfall. Die Liste ist jetzt durch die Eigenschaft ersetzt, die eigentlich gemeint war — ein Block im Zustand „auf Anforderung" hat nichts zu belegen. Damit pflegt sich die Regel selbst.
* Die aufgezeichnete Markensuche war eine **echte Zeitüberschreitung** von Overpass. Ein Fehlerzustand in der Aufnahme ist grundsätzlich legitim und prüfenswert — hier hätte er aber Prüfung 18 dauerhaft stillgelegt, weil das Skript dafür einen Übersprung-Zweig hat. Der Eintrag wurde gegen den Live-Server nachgeholt (Vapiano, 361 m).
* Die Prüfung der **Vergleichstabelle** stand an Position 22 der Reihenfolge, die Testpunkte legt aber erst der Standortbericht an Position 38 an. Sie lief immer gegen eine leere Punkteliste und sprang ab; weil ein Übersprung nicht als Fehler zählt, fiel es nie auf. Sie steht jetzt zwischen Bericht und Ranking.

Dass diese drei erst jetzt auffielen, hat einen benennbaren Grund: In den beiden Runden davor lief statt `uitest.py` jeweils ein kleines Prüfskript nur für die neuen Blöcke. Der volle Lauf war länger nicht durchgezogen worden. Genau das kann jetzt nicht mehr passieren.

**Ein Fund aus der Aufzeichnung selbst.** Der Flächen-Scan antwortete auf meinen ersten Ausschnitt mit HTTP 422 — „Ausschnitt zu groß, rund 4×5 km sind das Limit". Die Oberfläche klemmt ihren Ausschnitt selbst auf `SCAN_SPANNE` (0,055° × 0,04°) um die Kartenmitte. Aufgezeichnet wird jetzt genau die Box, die sie an der Prüfkoordinate bildet. Ein ausgedachter Ausschnitt hätte hier plausibel ausgesehen und wäre falsch gewesen — dasselbe Muster wie bei den WFS-Fallen der 9. Runde.

**Stand:** Alle **44 Prüfungen ohne Befund**, nichts übersprungen. Testsuite **628 Tests grün** (613 + 15 neue). Beides läuft bei jedem Push in der CI; ein eigener Test liest die Endpunkte direkt aus `app.js` und schlägt fehl, wenn ein neuer Block weder aufgezeichnet ist noch echt läuft.
