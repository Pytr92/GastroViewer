# Standort-Datenterminal Deutschland

Punkt auf einer Deutschlandkarte anklicken → alle verfügbaren offenen Daten zu diesem
Punkt sehen. Gedacht für die Standortsuche eines Fast-Food-Betriebs: wer wohnt dort, wer
arbeitet dort, wer betreibt schon Gastronomie, wie gut ist die Anbindung.

**Das Werkzeug ist ein Daten-Browser, kein Prognose-Tool.** Jede angezeigte Zahl im
Datenreiter stammt aus einer realen API-Antwort und trägt Quelle, Stand und Lizenz. Es
gibt keine Konstante im Code, die wie ein Messwert aussieht. Die Umsatzschätzung sitzt
bewusst in einem eigenen, getrennt gekennzeichneten Reiter — siehe unten.

Grundlage: [`spec-standort-datenterminal.md`](spec-standort-datenterminal.md) ·
Kontext: [`notizen-standort-flaeche.md`](notizen-standort-flaeche.md) ·
Endpunktprüfung: [`docs/endpoints-verified.md`](docs/endpoints-verified.md)

---

## Start

Das Werkzeug ist **keine HTML-Datei zum Doppelklicken**. Es ist ein kleiner Webserver, der
auf dem eigenen Rechner läuft; die Oberfläche öffnet man danach im Browser unter
`127.0.0.1`. Der Server holt die Daten bei den Fachdiensten, hält den Cache und rechnet —
eine einzelne `index.html` direkt zu öffnen funktioniert nicht.

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
| Ebenen links oben | Kartengrundlage (OSM, basemap.de farbig/grau, Luftbild Bayern) sowie Zensus-Gitter, Gastronomie, Frequenzbringer, ÖPNV, Leerstände, Verkehrsmengen, Lärm, ALKIS |
| Regler „Deckkraft der Ebenen" | blendet Gitter, Marker und Rasterebenen gemeinsam zurück, damit Straßen und Gebäude der Grundkarte durchscheinen. Die Grundkarte selbst bleibt voll; die Einstellung wird gemerkt |
| Auswahl in der Legende | Zensus-Ebene: Einwohner, Anteil 18–49, Miete, Leerstand |
| Klick auf Zelle oder POI | zeigt die Rohwerte, wie sie vom Dienst kamen |
| „Punkt merken" | legt den Standort in die Vergleichstabelle (bleibt in SQLite) |
| „Vergleich" | Kandidaten nebeneinander, mit CSV-Export |
| „Neu laden" | umgeht den Cache für diesen Punkt |
| „Export JSON/CSV" | ein Punkt mit Zeitstempel und Quellenangaben je Zeile |
| „Gehstrecken berechnen" | Block 4b — rechnet die echte Fußwegdistanz statt der Luftlinie |
| Reiter „Umsatzschätzung" | getrennter Reiter, siehe eigener Abschnitt |

---

## Kommandos

```bash
gastroviewer serve                       # Server starten (Standard)
gastroviewer serve --port 8080           # anderer Port
gastroviewer status                      # Cache- und GTFS-Status
gastroviewer clear-cache                 # Cache leeren
gastroviewer clear-cache --quelle zensus # nur eine Quelle
gastroviewer import-gtfs --region muenchen
gastroviewer check-wms                   # Bodenrichtwert-Dienste gegenprüfen
```

Alle Daten liegen unter `~/.gastroviewer` (überschreibbar mit `GASTROVIEWER_DATA_DIR`).
Cache leeren geht auch, indem man `~/.gastroviewer/gastroviewer.sqlite` löscht.

### GTFS-Import (ÖPNV-Abfahrten)

Der ÖPNV-Block bleibt leer, bis ein Fahrplan importiert ist. Alles andere funktioniert
auch ohne.

```bash
# Empfohlen: voreingestellter Ausschnitt
gastroviewer import-gtfs --region muenchen          # Stadt und Umland
gastroviewer import-gtfs --region muenchen-region   # mit S-Bahn-Umland
gastroviewer import-gtfs --region oberbayern
gastroviewer import-gtfs --region bayern

# Oder eigene Bounding-Box (min_lat,min_lon,max_lat,max_lon)
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

## Ohne Internet arbeiten

„Lokal" und „offline" sind hier zwei verschiedene Dinge.

**Lokal ist es immer.** Kein Konto, kein Deployment, keine Cloud — der Server läuft auf dem
eigenen Rechner, die Daten liegen in `~/.gastroviewer`. Das gilt unabhängig davon, ob
gerade eine Internetverbindung besteht.

**Ohne Internetverbindung** hängt alles am Cache, denn jede Zahl kommt im Normalfall frisch
von einem Fachdienst. Gemessen am 01.08.2026:

| Lage | Verhalten |
|---|---|
| Punkt noch nie geladen, kein Netz | Server startet, Oberfläche lädt, jeder Block meldet nach ~2 s „Verbindung nicht möglich — Dienst nicht erreichbar". Kein Absturz, kein Hängen. |
| Punkt vorher **mit** Netz geladen | Vollständig da: 0 ausgehende Abrufe, Antwort in 14 ms, alle Blöcke aus dem Cache. |
| Kartenhintergrund | braucht Netz — die Kacheln kommen von OSM bzw. basemap.de. Leaflet selbst liegt lokal, Marker und Umkreis werden also weiter gezeichnet. |
| GTFS-Fahrplan | einmal importiert vollständig lokal, funktioniert offline. |

Nachgemessen am Marienplatz: nach einem Abruf mit Netz liefert derselbe Punkt offline
110 Zensuszellen, 10.002 Einwohner, 15,98 €/m² Miete, 380 Gastronomiebetriebe und die
Raddauerzählstelle Erhardtstraße — bei `outbound_requests: 0`.

Der praktische Weg ist deshalb: die Kandidaten **einmal mit Netz** durchklicken und mit
„Punkt merken" ablegen, danach offline vergleichen und exportieren.

> Der Cache hat eine Haltbarkeit: OSM 24 Stunden, Zensus und Nominatim 30 Tage. Ein
> abgelaufener Eintrag gilt als nicht vorhanden — für eine Offline-Sitzung die Punkte also
> kurz vorher laden, nicht letzte Woche.

Selbst nachstellen lässt sich das, indem man den Server mit einem toten Proxy startet:

```bash
HTTPS_PROXY=http://127.0.0.1:9 HTTP_PROXY=http://127.0.0.1:9 gastroviewer serve
```

Die Testsuite braucht ohnehin kein Netz — sie läuft gegen die aufgezeichneten echten
Antworten unter `fixtures/`.

---

## Quellen und Lizenzen

| Quelle | Wofür | Lizenz | Cache-TTL |
|---|---|---|---|
| [Zensus 2022, 100-m-Gitter](https://services2.arcgis.com/jUpNdisbWqRpMo35/arcgis/rest/services/Zensus2022_grid_final/FeatureServer) | Bevölkerung, Alter, Haushalte, Miete, Leerstand, Baualter | © Statistische Ämter des Bundes und der Länder 2024 · dl-de/by-2-0 · GeoBasis-DE/BKG 2024 | 30 Tage |
| [OpenStreetMap / Overpass](https://overpass-api.de/) | Gastronomie, Frequenzbringer, ÖPNV, Leerstand, Linien | ODbL 1.0, © OpenStreetMap-Mitwirkende | 24 h |
| ↳ Frequenzbringer | über §4.2 hinaus auch Märkte, Busbahnhöfe, Tankstellen, Apotheken, Banken, Post, Behörden, Kioske | ODbL 1.0 | 24 h |
| [Nominatim](https://nominatim.openstreetmap.org/) | Adresse, Gemeinde, Ortsteil, PLZ | ODbL 1.0, © OpenStreetMap-Mitwirkende | 30 Tage |
| [gtfs.de](https://gtfs.de/) | Abfahrten je Haltestelle und Stunde | CC BY 4.0, Datengrundlage DELFI e.V. | lokal, kein Cache |
| ↳ Fußwegenetz | Gehstrecke statt Luftlinie (nur auf Anforderung) | ODbL 1.0 | 14 Tage |
| Bodenrichtwert-WMS von 7 Ländern | Kartenebene und Wert am Punkt | je Land, siehe unten | kein Cache |
| [Raddauerzählstellen München](https://opendata.muenchen.de/dataset/daten-der-raddauerzaehlstellen-muenchen-jahreszahlen) | gemessene Radverkehrsfrequenz | dl-de/by-2-0, © LH München | 24 h |
| [Luftbild und ALKIS Bayern](https://geodaten.bayern.de/opengeodata/) | Kartenebenen | CC BY 4.0, © Bayerische Vermessungsverwaltung | kein Cache |
| [BAYSIS Straßenverkehrszählung](https://www.baysis.bayern.de/internet/verdat/svz/index.html) | Verkehrsmenge (DTV) je Zählstelle | CC BY 4.0, © Bayerische Straßenbauverwaltung | 24 h |
| [Lärmkartierung LfU Bayern](https://www.lfu.bayern.de/) | Kartenebene Verkehrslärm | CC BY 4.0, © Bayerisches Landesamt für Umwelt | kein Cache |
| OSM-Kacheln | Kartenhintergrund (Vorgabe) | ODbL 1.0 | Browser |
| [basemap.de](https://basemap.de/) (BKG) | amtlicher Kartenhintergrund, umschaltbar | dl-de/by-2-0, © GeoBasis-DE / BKG | Browser |

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

## Umsatzschätzung — eigener Reiter, bewusst zurückhaltend

Ein Vorgänger dieses Werkzeugs hat aus Einwohnerzahl, Wettbewerbsdichte und frei
gewählten Distanzgewichten einen Jahresumsatz „berechnet". Die Eingangsdaten waren echt,
die Gewichte erfunden, das Ergebnis sah präzise aus und war es nicht. Deshalb gelten hier
fünf Regeln:

1. **Eigener Reiter**, sichtbar als Schätzung markiert. Im Datenreiter taucht keine
   geschätzte Zahl auf — das ist mit einem Test festgehalten.
2. **Jede Annahme ist ein Eingabefeld.** Kein Faktor steckt versteckt im Code. Felder ohne
   Datengrundlage sind farblich markiert und mit „frei gewählt" beschriftet.
3. **Das Ergebnis ist immer eine Spanne**, nie ein Punktwert.
4. **Daneben steht die Umrechnung in Bestellungen pro Tag und pro Öffnungsstunde.** Das ist
   die Zahl, die ein Betreiber beurteilen kann und das Modell nicht.
5. **Der Rechenweg steht sichtbar in der Oberfläche.** Vier Multiplikationen, sonst nichts:

```
Besuche im Einzugsgebiet je Jahr  =  Einwohner × Besuche je Einwohner und Jahr
Marktanteil (naive Gleichverteilung)  =  1 ÷ (Wettbewerber + 1)
Besuche des Betriebs je Jahr  =  Besuche im Einzugsgebiet × Marktanteil
Jahresumsatz  =  Besuche des Betriebs × Durchschnittsbon
Bestellungen je Tag  =  Besuche des Betriebs ÷ Öffnungstage
Bestellungen je Öffnungsstunde  =  Bestellungen je Tag ÷ Öffnungsstunden
```

**Keine Distanzgewichte, keine Lagefaktoren, keine Kaufkraftindizes.** Zwei Standorte mit
gleicher Einwohner- und Wettbewerbszahl bekommen dasselbe Ergebnis, auch wenn einer an der
Fußgängerzone liegt und einer an der Umgehungsstraße. Genau deshalb ist das Ergebnis ein
**Vergleichsmaß und keine Prognose**.

### Gehstrecke in der Schätzung — angeboten, nicht gesetzt

Sind für den Punkt die Gehstrecken berechnet (Block 4b), erscheint im Schätzungsreiter ein
Angebot: die zu Fuß erreichbare Einwohnerzahl statt der Luftlinienzahl. Am Isarufer sind
das 4.853 statt 18.227 — die Rechnung mit der Luftlinienzahl überschätzt das Einzugsgebiet
also um mehr als das Dreifache.

**Vorgabe bleibt trotzdem die Luftlinienzahl.** Die Gehstrecken liegen nur vor, wenn jemand
den Block geladen hat; würden sie stillschweigend die Vorgabe ändern, hinge das Ergebnis
daran, ob vorher ein Knopf gedrückt wurde — und zwei Standorte wären nicht mehr
vergleichbar. Deshalb wird die engere Zahl sichtbar angeboten, mit einem Knopf übernommen
und mit einem zweiten zurückgesetzt. Wer übernimmt, muss beide Standorte gleich rechnen;
der Hinweis steht daneben.

### Prüfstein: gegen einen echten Betrieb halten

Die Rechnung arbeitet mit Bundesdurchschnitten und kennt weder Lage noch Passantenströme.
Ob sie für einen bestimmten Betriebstyp um Faktor 1,2 oder um Faktor 5 danebenliegt, sagt
**ein einziger bekannter Umsatz** mehr als jede weitere Verfeinerung der Formel. Dafür gibt
es im Schätzungsreiter zwei Felder: tatsächlicher Jahresumsatz eines Betriebs, den du
kennst, und wie er heißt.

Der Wert **geht in keine Rechnung ein** und wird nicht gespeichert — er wird
gegenübergestellt, und das Verhältnis wird benannt. Beispiel Marienplatz, 600 m: die
Rechnung ergibt 63.416 bis 362.227 € im Jahr; ein realer Betrieb mit 450.000 € liegt damit
um Faktor 2,11 darüber, die Rechnung ist für diesen Fall also zu vorsichtig. Dass ein Wert
*innerhalb* der Spanne liegt, bestätigt dagegen nichts — die Spanne ist bewusst weit.

Der Marktanteil ist die einzige Größe, für die es keine Datenquelle gibt. Er wird nicht
geschätzt, sondern verlangt: Vorgabe ist die naive Gleichverteilung `1/(Wettbewerber+1)`,
aufgespannt mit einem sichtbaren Unsicherheitsfaktor.

### Referenzwerte, am 01.08.2026 selbst nachgeschlagen

| Größe | Wert | Stand | Quelle |
|---|---|---|---|
| Umsatz Systemgastronomie Deutschland | 36 Mrd. € | 2025 | [BdS mit Circana, CREST-Panel](https://www.bundesverband-systemgastronomie.de/die-systemgastronomie/branchendaten.html) |
| Durchschnittsbon Systemgastronomie | 7,15 € je Besuch | 2025 | [BdS mit Circana, CREST-Panel](https://www.bundesverband-systemgastronomie.de/die-systemgastronomie/branchendaten.html) |
| Durchschnittsbon Außer-Haus-Markt gesamt | 10,21 € je Besuch | 2023 | [Studie für die Denkfabrik Zukunft der Gastwelt](https://brotundbackwaren.de/ausser-haus-markt-2023-weniger-besuche-hoherer-durchschnittsbon/) |
| Bevölkerung Deutschland | 83,5 Mio. | 31.12.2025 | [Statistisches Bundesamt](https://www.destatis.de/DE/Presse/Pressemitteilungen/2026/01/PD26_032_124.html) |
| Miete als Anteil vom Nettoumsatz | 10–14 % | Faustregel | `notizen-standort-flaeche.md` §6 |

Daraus **hergeleitet** (nicht gesetzt): 36 Mrd. € ÷ 7,15 € = 5,03 Mrd. Besuche;
÷ 83,5 Mio. Einwohner = **60,3 Besuche je Einwohner und Jahr**. Die Herleitung steht in
der Oberfläche neben dem Feld.

Die Spec nannte für 2023 einen Außer-Haus-Markt von 84,5 Mrd. € — je nach Erhebungsumfang
finden sich dafür auch 77,1 Mrd. €. Die beiden Durchschnittsbons stammen aus verschieden
abgegrenzten Erhebungen und lassen sich nicht ineinander umrechnen; sie dienen hier als
untere und obere Annahme. Alle Werte sind Eingabefelder und überschreibbar.

## Was dieses Werkzeug bewusst nicht tut

- **Keine Bewertung und keine Rangliste.** Die Vergleichstabelle hebt nur den jeweils
  höchsten Wert hervor, ohne ihn als „besser" zu bezeichnen.
- **Kein Scraping** von Immobilienportalen. ImmoScout24 und Immowelt haben aktiven
  Bot-Schutz; ihn zu umgehen ist der rechtlich kritischste Punkt beim Scraping. Der Weg
  über Suchagenten und ein Sammelpostfach steht in `notizen-standort-flaeche.md` §4.2.
- **Keine geratenen URLs.** Für Bundesländer ohne bestätigtes Bodenrichtwert-Portal wird
  ein Suchlink erzeugt, kein erfundener Link. Dasselbe gilt für die Kartendienste: nur
  eingebunden, was `GetCapabilities`, `GetMap` **und** `GetFeatureInfo` bestanden hat.

## München und Bayern

Das Werkzeug funktioniert bundesweit, hat für die Zielregion aber zwei Ergänzungen.

**Gemessene Frequenz — Raddauerzählstellen.** §8 nennt die größte Lücke des Werkzeugs:
Passantenströme fehlen, Fußgängerzone und Seitenstraße sind in offenen Daten nicht
unterscheidbar. Ganz schließen lässt sich das nicht — hystreet untersagt die gewerbliche
Nutzung im kostenfreien Modell. München betreibt aber **sechs Dauerzählstellen mit echten
Messwerten**, die frei nutzbar sind. Der Block zeigt die Zählstellen bis 3 km Entfernung
mit Jahressumme und Tagesmittel, dazu die Störungs- und Baustellenhinweise der Stadt.

Beispiel Sendlinger Tor: Erhardtstraße in 1.294 m, 1.415.000 Radfahrende 2025, also
3.877 je Tag. Die Grenzen stehen im Block: **Radfahrende, keine Fußgänger**, und sechs
Querschnitte für 1,6 Mio. Einwohner. Über 3 km bleibt der Block leer statt eine Zahl von
der anderen Stadtseite zu zeigen.

**Verkehrsmenge (DTV).** Für einen Standort an einer Ausfallstraße, mit Drive-through
oder mit Parkplatz ist die durchschnittliche tägliche Verkehrsstärke die
aussagekräftigste Frequenzgröße überhaupt — und anders als Passantenströme ist sie
amtlich gemessen und frei verfügbar. BAYSIS liefert **9.441 Zählstellen in Bayern** mit
Kfz-, Leicht- und Schwerverkehr. Beispiel A9 bei Fröttmaning: 111.624 Kfz/Tag in 701 m,
davon 5,1 % Schwerverkehr; die A99 daneben hat bei weniger Verkehr 13,6 %.

Gezählt wird nur das **klassifizierte Straßennetz** — Autobahnen, Bundes-, Staats- und
Kreisstraßen. Am Sendlinger Tor liegt deshalb keine Zählstelle, und der Block sagt das
auch so. Der Block warnt außerdem vor dem naheliegenden Fehlschluss: vorbeifahrender
Verkehr ist keine Kundschaft, und der Außengastronomie schadet er eher.

**Amtliche Kartenebenen Bayerns** (alle CC BY 4.0, kostenfrei):

| Ebene | Was sie zeigt | ab Zoom |
|---|---|---|
| Luftbild DOP 40 cm | Hof, Terrassenfläche, Stellplätze, Dachaufbauten | 8 |
| Verkehrsmengen 2021 | Bandbreitenkarte des DTV im klassifizierten Netz | 15 |
| Verkehrslärm L_den 2022 | Lärmkartierung — relevant für Außengastronomie | 0 |
| ALKIS-Parzellarkarte | Flurstücksgrenzen und Gebäudegrundrisse | 17 |

Für die Checkliste in `notizen-standort-flaeche.md` §6 — Abluft über Dach, Hoffläche,
Stellplatznachweis — ist das oft aussagekräftiger als jede Zahl.

## Zwei Verhältniszahlen im Vergleich

Die Vergleichstabelle rechnet zwei Quotienten aus Größen, die ohnehin gemessen vorliegen.
Es kommt kein gewählter Faktor hinzu — deshalb stehen sie im Datenreiter und nicht in der
Schätzung. Beschriftet sind sie trotzdem als **(berechnet)**, damit sie nicht wie ein
Messwert aussehen.

| Kennzahl | Rechnung | Wofür |
|---|---|---|
| Wettbewerber je 1.000 Einwohner | Gastronomie ÷ Einwohner × 1.000 | Sättigung |
| Schnellrestaurants je 1.000 Einwohner | Schnellrestaurants ÷ Einwohner × 1.000 | Sättigung im eigenen Segment — 30 Cafés sind für einen Imbiss kein Wettbewerb |
| Abfahrten je Einwohner | Abfahrten/Tag ÷ Einwohner | Näherung für Zulauf von außerhalb |
| Anteil Mittag | Abfahrten 11–14 Uhr ÷ Tagessumme × 100 | trennt die Pendlerhaltestelle von der ganztags belebten Lage |

Warum die zweite Zahl nötig ist, zeigt der Vergleich vier Münchner Lagen (Radius 600 m,
abgerufen am 01.08.2026):

| Lage | Einwohner | Gastro | Wettb./1.000 | Abfahrten | Abf./Einw. |
|---|---|---|---|---|---|
| Marienplatz (1a) | 10.002 | 381 | **38,1** | 5.203 | **0,52** |
| Arnulfpark (Büro) | 15.741 | 67 | 4,3 | 4.633 | 0,29 |
| Moosach (Stadtrand) | 13.713 | 32 | 2,3 | 3.985 | 0,29 |
| Giesing (Wohnviertel) | 22.805 | 31 | **1,4** | 1.548 | **0,07** |

Der Marienplatz hat die **wenigsten** Einwohner und die **meiste** Konkurrenz. Wer nur auf
die Einwohnerzahl schaut, hält Giesing für die bessere Lage — die Abfahrten je Einwohner
zeigen mit Faktor 7,4, dass am Marienplatz die Kundschaft von außerhalb kommt. Genau das
sieht der Zensus nicht.

> Diese Zahlen sind Hinweise, keine Bewertung. Eine hohe Wettbewerbsdichte kann Sättigung
> heißen oder einen funktionierenden Gastronomiestandort — deshalb wird sie in der Tabelle
> bewusst **nicht** als Höchstwert hervorgehoben. Und Abfahrten sind Fahrgäste, keine
> Passanten: eine Umsteigehaltestelle unter der Erde bringt weniger Laufkundschaft als die
> Zahl vermuten lässt.

Der **Anteil Mittag** war in der Erprobung die schwächste der vier Kennzahlen: alle fünf
geprüften Münchner Lagen liegen zwischen 13,7 % und 17,4 %. Im dichten Stadtgebiet fährt
der ÖPNV eben durchgehend. Aussagekräftig wird die Zahl erst dort, wo ein Fahrplan
wirklich auf Berufsverkehr zugeschnitten ist — die absolute Zahl der Mittagsabfahrten
(834 am Marienplatz gegen 270 in Giesing) unterscheidet deutlich besser.

## Wettbewerbsdichte nach Entfernung

Die reine Umkreiszahl verwischt, wo die Konkurrenz steht. Deshalb zählt der
Gastronomieblock kumuliert nach Entfernungsstufen und nennt den nächsten Betrieb. Es sind
Zählgrenzen, keine Gewichte — gewichtet wird nirgends.

| Lage | bis 150 m | bis 300 m | bis 600 m | nächster Betrieb |
|---|---|---|---|---|
| Marienplatz | 46 | 151 | 382 | 28 m |
| Moosach | 3 | 20 | 32 | 70 m |
| Giesing | 4 | 10 | 31 | 38 m |
| Arnulfpark | **0** | 3 | 67 | 267 m |

Der Arnulfpark zeigt, warum die Staffelung nötig ist: 67 Betriebe im Umkreis klingen nach
einem versorgten Viertel, aber im Umkreis von 150 m liegt **kein einziger**. Die
Gesamtzahl allein hätte die Lage falsch dargestellt.

## Neubauhinweis — und was er nicht kann

Der Zensus-Stichtag ist der 15.05.2022. Das Feld „2020 und später" umfasst deshalb nur gut
zwei Jahre; **Neubau nach dem Stichtag fehlt vollständig**. Der ausgewiesene Anteil ist
darum kein Maß für Neubau, sondern ein Anzeiger dafür, dass am Ort zuletzt überhaupt
gebaut wurde — und das trennt sauber (gemessen am 01.08.2026, Radius 600 m):

| Lage | Gebäude | davon ab 2020 | Anteil |
|---|---|---|---|
| Marienplatz | 767 | 0 | 0,00 % |
| Giesing | 1.063 | 0 | 0,00 % |
| Arnulfpark | 715 | 3 | 0,42 % |
| Moosach | 1.364 | 30 | 2,20 % |
| Freiham | 1.328 | 38 | 2,90 % |

Gewachsene Viertel liegen bei exakt null, wachsende darüber. Deshalb hängt der Hinweis an
„größer null" und nicht an einer gewählten Schwelle. Er sagt: hier lag die Einwohnerzahl
zum Stichtag vermutlich unter der heutigen.

## Erreichbarkeit zu Fuß — der Umkreis ist kein Kreis

Der Radius, mit dem dieses Werkzeug arbeitet, ist ein Kreis auf der Karte. Zu Fuß ist er
das nicht: Flüsse, Gleise und Schnellstraßen zerschneiden ihn, und hinüber kommt man nur,
wo eine Brücke steht. In München betrifft das die halbe Stadt.

Der Block **4b · Erreichbarkeit zu Fuß** rechnet deshalb die tatsächliche Gehstrecke. Das
Fußwegenetz kommt aus derselben Overpass-Quelle wie alles andere, wird zu einem Graphen
verknüpft, und ein Dijkstra liefert den kürzesten Weg je Knoten — für 12.000 Knoten in
**rund 5 ms**, in reinem Python. Es braucht **keinen Routing-Dienst** und keine zusätzliche
Abhängigkeit.

Gemessen am 01.08.2026, Radius 600 m:

| Lage | Umwegfaktor | Einwohner Luftlinie → Fußweg | erschlossen | Gastronomie | erschlossen |
|---|---|---|---|---|---|
| Moosach (Stadtrand) | 1,61 | 13.713 → 7.053 | **51,4 %** | 32 → 25 | 78,1 % |
| Giesing (Wohnviertel) | 1,34 | 22.805 → 10.981 | 48,2 % | 31 → 20 | 64,5 % |
| Marienplatz (1a) | 1,38 | 10.002 → 3.616 | 36,2 % | 382 → 290 | 75,9 % |
| Ostbahnhof (Gleise) | 1,34 | 13.648 → 4.254 | 31,2 % | 113 → 53 | 46,9 % |
| Isarufer (Fluss) | 1,41 | 18.227 → 4.853 | **26,6 %** | 153 → 43 | **28,1 %** |

Am Isarufer sind von 153 Gastronomiebetrieben im Umkreis nur **43 zu Fuß erreichbar** —
110 stehen auf der anderen Flussseite. Wer die Umkreiszahl liest, hält den Standort für
dreieinhalbmal so umkämpft, wie er ist.

> **Der Rückgang ist keine Fehlerkorrektur.** 600 m Fußweg und 600 m Luftlinie sind zwei
> verschiedene Gebiete: bei Umwegfaktor 1,4 entspricht ein 600-m-Fußweg einem
> Luftlinienkreis von rund 430 m, also gut der halben Fläche. Vergleichbar zwischen
> Standorten wird die Sache erst über den **Erschließungsgrad** — den Anteil des
> Luftlinienkreises, der zu Fuß tatsächlich erreichbar ist. Der trennt sauber: 51 % am
> offenen Stadtrand, 27 % am Fluss.

**Der Block lädt nicht von selbst.** Das Wegenetz ist mit 1–3 MB je Punkt die größte
Abfrage des Werkzeugs, und Overpass ist ein Spendenprojekt. Deshalb erst auf Knopfdruck —
dafür bleibt das Ergebnis 14 Tage im Cache (`GASTROVIEWER_TTL_GEHWEG`), und „Punkt merken"
löst die Abfrage nie aus. Der erste Abruf dauert je nach Lage 10–70 Sekunden, jeder weitere
4 Millisekunden.

Grenzen, die auch in der Oberfläche stehen:

- Gerechnet wird die **Weglänge**, nicht die Wegzeit: keine Ampeln, keine Wartezeiten,
  keine Steigung. Treppen zählen wie ebener Weg.
- Die Umrechnung in Minuten nutzt 80 m/min (4,8 km/h) — ein gewählter Wert, der in der
  Oberfläche mit dabeisteht.
- Wege mit `foot=no` oder `access=private` fallen heraus. Ein faktisch begehbarer, aber so
  getaggter Durchgang fehlt damit.
- Zensuszellen werden über ihren **Mittelpunkt** zugeordnet. Eine 100-m-Zelle kann teils
  erreichbar sein; die Zuordnung ist eine Näherung.

## Bodenrichtwerte als Kartenebene

Sieben Länder haben einen offenen Kartendienst, der am 01.08.2026 in allen drei Stufen
geprüft wurde. Liegt der gewählte Punkt in einem davon, erscheint die Ebene im
Ebenenschalter und der Wert lässt sich am Punkt abfragen.

| Land | Klickabfrage | Ebene ab Zoom | Lizenz |
|---|---|---|---|
| Nordrhein-Westfalen | Wert und alle Merkmale | 14 | dl-de/zero-2-0 |
| Niedersachsen | Wert und alle Merkmale | 7 | dl-de/by-2-0 |
| Sachsen-Anhalt | Wert und alle Merkmale | 7 | Kostenverordnung des Landes beachten |
| Thüringen | Wert und alle Merkmale | 13 | dl-de/by-2-0 |
| Brandenburg | Wert und alle Merkmale | 13 | dl-de/by-2-0 |
| Hamburg | nur Zone und Nutzungsart, **kein Wert** | 0 | keine Zugriffsbeschränkungen |
| Rheinland-Pfalz | keine — nur die Karte | 0 | dl-de/by-2-0 |

Für die übrigen neun Länder gibt es keine Ebene, und im Panel steht warum: Bayern,
Baden-Württemberg, Saarland, Schleswig-Holstein und Mecklenburg-Vorpommern sind aus
rechtlichen Gründen nicht in den offenen Diensten; Berlin scheitert an der
TLS-Zertifikatskette; Sachsen weist die Abrufe mit HTTP 403 zurück; für Hessen und Bremen
wurde kein offener Dienst gefunden. Dort bleibt es beim Portallink.

Die Kacheln holt der Browser direkt beim Landesdienst — Kartenbilder brauchen kein CORS,
und jede Kachel im Outbound-Protokoll zu zählen würde den Cache-Nachweis unbrauchbar
machen. Die Klickabfrage läuft über das Backend, weil sie sonst an CORS scheitert.

`gastroviewer check-wms` ruft bei allen sieben `GetCapabilities` ab und meldet, wenn eine
URL oder ein Layername nicht mehr stimmt. Das ist kein Luxus: Brandenburg hat seine
Dienst-URL 2025 umgestellt.

> Bodenrichtwerte sind Zonenwerte für ein fiktives Grundstück mit den angegebenen
> Merkmalen — nicht der Wert eines konkreten Grundstücks und kein Mietpreis.

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
| `GASTROVIEWER_TTL_GEHWEG` | 14 d — das Fußwegenetz ändert sich langsam |
| `GASTROVIEWER_ZENSUS_PAGE_SIZE` / `_MAX_PAGES` | `2000` / `10` |
| `GASTROVIEWER_GTFS_URL` | gtfs.de Komplettfeed |

---

## API

| Endpunkt | Zweck |
|---|---|
| `GET /api/point?lat=&lon=&r=` | alles auf einmal |
| `GET /api/point/{adresse\|zensus\|osm\|gtfs\|radzaehlung\|verkehrsmenge\|links}` | je Quelle einzeln (nutzt die Oberfläche) |
| `GET /api/point/gehweg?lat=&lon=&r=` | Gehstrecken statt Luftlinie — **nur auf Anforderung**, siehe eigener Abschnitt |
| `GET /api/geocode?q=` | Adresssuche |
| `GET /api/points` · `POST /api/points` · `DELETE /api/points/{id}` | gemerkte Punkte |
| `GET /api/points/vergleich` | Vergleichstabelle |
| `GET /api/export/point.json` · `point.csv` · `vergleich.csv` | Export |
| `GET /api/stats` · `GET /api/outbound` | Cache-Zustand, Protokoll der echten Abrufe |
| `DELETE /api/cache?quelle=` | Cache leeren |
| `GET /api/wms` · `?bundesland_code=` | Kartendienst-Register bzw. Ebene eines Landes |
| `GET /api/wms/ebenen?bundesland_code=` | zusätzliche amtliche Kartenebenen (Bayern: Luftbild, ALKIS) |
| `GET /api/wms/bodenrichtwert` | Wert am Punkt beim Landesdienst (GetFeatureInfo) |
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

Zusätzlich prüft ein Skript die Abnahmekriterien aus §7 der Spec gegen einen laufenden
Server — mit echten Aufrufen, inklusive eines direkten Gegenchecks der angezeigten Zahlen
bei Zensus und Overpass:

```bash
gastroviewer serve --port 8011 &
python scripts/abnahme.py http://127.0.0.1:8011
```

Das letzte Protokoll steht in [`docs/abnahme.md`](docs/abnahme.md).

### Oberflächenprüfung

`pytest` deckt ausschließlich Python ab. Alles in `app.js` — Blöcke, Reiter,
Kartenebenen, Vergleichstabelle — prüft ein eigenes Skript im echten Browser:

```bash
pip install playwright && playwright install chromium
python scripts/uitest.py http://127.0.0.1:8011
```

Elf Prüfungen, darunter: jeder Block nennt Quelle und Lizenz, im Datenreiter steht keine
geschätzte Zahl, der Deckkraftregler wirkt auf die Ebenen und **nicht** auf die Grundkarte,
der Gehwegblock lädt nur auf Anforderung und räumt seine Kartenebene beim Punktwechsel auf.

Fehlt Playwright oder Chromium, endet das Skript mit **Exitcode 3** und der Meldung
„Oberfläche NICHT geprüft" — ein übersprungener Test darf nicht wie ein bestandener
aussehen. Exitcode 2 heißt: der Server läuft nicht.

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
    gehweg.py        Fußwegenetz als Graph, Dijkstra, Gehstrecke je Objekt
    boris.py         Bodenrichtwert-Portale je Bundesland
    wms.py           verifizierte Landes-Kartendienste, Klickabfrage
    muenchen.py      Raddauerzählstellen der Landeshauptstadt München
    bayern.py        Verkehrsmengen der Straßenverkehrszählung (BAYSIS)
    links.py         Deep-Links aus Spec §4.6 und den Notizen
  static/            Oberfläche (Leaflet lokal, kein CDN)
scripts/
  abnahme.py         Abnahmekriterien aus §7 gegen einen laufenden Server
  uitest.py          Oberflächenprüfung im echten Browser
fixtures/            echte API-Antworten aus Phase 0, Grundlage der Tests
docs/                Endpunktprüfung
```
