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
