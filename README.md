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
| Radius 300–3000 m | begrenzt alle Abfragen; 2000/3000 sind große Abfragen für Umlandgemeinden |
| Ebenen links oben | Kartengrundlage (OSM, basemap.de farbig/grau, Luftbild Bayern) sowie Übersicht Einwohner (1/10 km), Zensus-Gitter, Gastronomie, Frequenzbringer, ÖPNV, Leerstände, Verkehrsmengen, Lärm, ALKIS |
| Regler „Deckkraft der Ebenen" | blendet Gitter, Marker und Rasterebenen gemeinsam zurück, damit Straßen und Gebäude der Grundkarte durchscheinen. Die Grundkarte selbst bleibt voll; die Einstellung wird gemerkt |
| Auswahl in der Legende | Zensus-Ebene: Einwohner, Anteil 18–49, Miete, Leerstand |
| Klick auf Zelle oder POI | zeigt die Rohwerte, wie sie vom Dienst kamen |
| „Punkt merken" | legt den Standort in die Vergleichstabelle (bleibt in SQLite) |
| „Vergleich" | Kandidaten nebeneinander, Spalten in sechs Gruppen zu- und abschaltbar, eigene Note und Notiz je Punkt, CSV-Export |
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
gastroviewer import-overture --region muenchen   # zweite Wettbewerbsquelle (braucht: pip install overturemaps)
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
| [Baustellen-Servicekarte München](https://opendata.muenchen.de/dataset/baustellen_4_weeks_opendata) | Baustellen/Haltverbote im Umkreis, Vier-Wochen-Vorschau | dl-de/by-2-0, © LH München, Mobilitätsreferat | 24 h |
| [Märkte der LH München](https://opendata.muenchen.de/dataset/maerkte) | Wochen-/Bauernmärkte mit Öffnungszeiten | dl-de/by-2-0, © LH München, GeodatenService | 30 Tage |
| [Indikatorenatlas München](https://opendata.muenchen.de/dataset?q=indikatorenatlas) | Stadtbezirks-Jahresreihen (Viertel-Steckbrief) | dl-de/by-2-0, © LH München, Statistisches Amt | 30 Tage |
| [Inside Airbnb](https://insideairbnb.com/get-the-data/) | Kurzzeitvermietung im Umkreis (München, Berlin) — Touristen-Nachfrage-Signal | CC BY 4.0, © Inside Airbnb | 30 Tage |
| [Regionaldatenbank Deutschland](https://www.regionalstatistik.de/) (GENESIS) | amtliche Gastro-Anker: Umsatz je USt-Pflichtigem Gastgewerbe, Gewerbean-/-abmeldungen (Kreis) — **Opt-in mit kostenloser Kennung** | dl-de/by-2-0, © Statistische Ämter des Bundes und der Länder | 30 Tage |
| [Veranstaltungen der Messe München](https://opendata.muenchen.de/dataset/veranstaltungen-der-messe-muenchen) | Messe-Kalender mit Besucherzahlen seit 2018 — planbare Frequenzspitzen | dl-de/by-2-0, © Messe München GmbH | 24 h |
| [Monatszahlen Tourismus München](https://opendata.muenchen.de/dataset/monatszahlen-tourismus) | Saisonkurve der Gäste und Übernachtungen seit 2006 (stadtweit) | dl-de/by-2-0, © Statistisches Amt München | 24 h |
| [Erhaltungssatzungen München](https://stadt.muenchen.de/infos/erhaltungssatzung.html) | liegt der Punkt im Milieuschutzgebiet (§ 172 BauGB), mit Satzungs-PDFs | Geoportal LH München (WMS-GetFeatureInfo) | 14 Tage |
| [Luftbild und ALKIS Bayern](https://geodaten.bayern.de/opengeodata/) | Kartenebenen | CC BY 4.0, © Bayerische Vermessungsverwaltung | kein Cache |
| [BAYSIS Straßenverkehrszählung](https://www.baysis.bayern.de/internet/verdat/svz/index.html) | Verkehrsmenge (DTV) je Zählstelle | CC BY 4.0, © Bayerische Straßenbauverwaltung | 24 h |
| [Hochwassergefahrenflächen LfU](https://www.lfu.bayern.de/wasser/hw_ue_gebiete/index.htm) | HQhäufig, HQ100, HQextrem am Punkt | CC BY 4.0, © Bayerisches Landesamt für Umwelt | 14 Tage |
| [Bebauungsplan-Umgriffe München](https://geoportal.muenchen.de/portal/plan) | gilt für die Fläche ein Plan, und welcher | dl-de/by-2-0, © LH München | 14 Tage |
| [Lärmkartierung LfU Bayern](https://www.lfu.bayern.de/) | Kartenebene Verkehrslärm | CC BY 4.0, © Bayerisches Landesamt für Umwelt | kein Cache |
| OSM-Kacheln | Kartenhintergrund (Vorgabe) | ODbL 1.0 | Browser |
| [basemap.de](https://basemap.de/) (BKG) | amtlicher Kartenhintergrund, umschaltbar | dl-de/by-2-0, © GeoBasis-DE / BKG | Browser |

Verlinkt, aber **nicht abgerufen**: BORIS-D und die Landesportale für Bodenrichtwerte,
hystreet, Pendleratlas, INKAR, Zensusatlas, Leerstandsmelder,
nexxt-change, DEHOGA, ahgz immo, Brauerei-Pachtbörsen, ECE, MEC, DB InfraGO —
sowie als reine Absprunglinks für die Handkontrolle: Google Maps (Gastro-Suche am
Punkt) und Mapillary (Straßenfotos, „virtuelle Begehung").

> **Konto-Prinzip:** Das Werkzeug braucht grundsätzlich **keine Konten**. Die einzige
> Ausnahme ist ein Opt-in: die Regionaldatenbank (regionalstatistik.de) verlangt für
> ihre Schnittstelle eine kostenlose Kennung. Ohne Eintrag bleibt der Block 3e leer
> und erklärt den Weg — alles andere läuft unverändert ohne Konto. Die Kennung wird
> nur lokal gespeichert (Datei `genesis-zugang.json` im Datenverzeichnis, alternativ
> `GASTROVIEWER_GENESIS_KENNUNG`/`…_PASSWORT`) und nur an regionalstatistik.de
> gesendet; das Outbound-Protokoll enthält nur URLs, nie Zugangsdaten. Der anonyme
> Werteabruf der Website wird bewusst **nicht** automatisiert — deren robots.txt
> untersagt das (`Disallow: /`), der sanktionierte Maschinenweg ist die API.

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

### Sensitivität: Woran die Spanne hängt — exakt, ohne Prüf-Störgrößen

Weil die Formel eine reine Multiplikationskette ist, braucht die Sensitivitätsanalyse
keine gewählten „±25 %"-Störgrößen — alles folgt exakt aus der Rechnung selbst:

- Die Umsatzspanne zerlegt sich **exakt** in Marktanteil-Faktor × Bon-Faktor
  (Standard: 4,0 × 1,43 = Spannenfaktor 5,7). Wer die Spanne enger haben will, weiß
  damit, an welcher Annahme das liegt — fast immer am Marktanteil.
- Ein **übersehener Wettbewerber** (OSM zählt Untergrenzen!) senkt den Umsatz um
  exakt 100/(n+2) Prozent — bei 3 gezählten Wettbewerbern sind das −20 %, bei 26
  nur −3,6 %. Je leerer das Umfeld gezählt ist, desto teurer jeder übersehene Betrieb.
- Einwohner und Besuche je Einwohner wirken 1:1; Öffnungstage und -stunden verändern
  den Jahresumsatz gar nicht, nur die Bestellungen je Tag/Stunde.

Das Ergebnis sagt damit konkret, **welche Annahme man vor Ort zuerst prüfen muss**.

### Wohnmiete als Lage-Anker der Mietprobe

Die Mietprobe (Fläche × geforderte Kaltmiete gegen die Miet-Obergrenze der Rechnung)
bekommt einen zweiten, gemessenen Bezugspunkt: die **durchschnittliche
Wohnungs-Nettokaltmiete des Umkreises aus dem Zensus-Gitter** (100-m-Zellen, Stichtag
15.05.2022), sichtbar vorbefüllt und änderbar. Sie ist ausdrücklich **keine** Ober-
oder Untergrenze für Gewerbemieten — die liegen regelmäßig darüber. Ihr Nutzen ist der
Vergleich: dieselbe geforderte Gewerbemiete ist im 8-€-Wohnviertel ein anderes Angebot
als im 16-€-Viertel, und das Verhältnis („das 2,8-Fache der örtlichen Wohnungsmiete")
macht zwei Standorte vergleichbar. In keine Umsatzrechnung geht der Wert ein.

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

Dazu der **Jahresgang aus den Tages-Rohdaten**: Die Jahressumme verdeckt, wie weit
Sommer und Winter auseinanderliegen. Die Tageswerte-Jahresdatei des Open-Data-Portals
(über die CKAN-API aufgelöst, die Dateinamen sind unregelmäßig) liefert je Zählstelle
die Monatsmittel als Balken, die Zahl der Messtage und den Spitzentag — an der
Arnulfstraße 2025 z. B. Januar Ø 645 gegen Juli Ø 1.662 Radfahrende/Tag. Teiljahre
werden ehrlich ausgewiesen (Kreuther 2025: nur 92 Messtage), Monate ohne Messung sind
Lücken, keine erfundene Flaute.

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

## Erkundung: WO ist es interessant? Ganz München, ganz Bayern

Der Umkreis beantwortet die Frage „wie ist es *hier*?" — für die Frage „*wo* soll ich
überhaupt hinsehen?" gibt es die Ebene **„Übersicht Einwohner (1/10 km)"** im
Ebenenschalter. Sie legt das Zensus-Gitter flächig über die Karte, aus derselben
verifizierten Quelle wie der 100-m-Block:

- **herangezoomt (ab Zoom 12):** 1-km-Zellen — ganz München sind 613 Zellen. Die dichteste
  Münchner Zelle hat 22.773 Einwohner bei 15,68 €/m² Miete.
- **herausgezoomt:** 10-km-Zellen — ganz Bayern sind 1.083 Zellen. Die dichteste ist mit
  659.675 Einwohnern der Münchner Kern, gefolgt von Nürnberg (458.590).

Die Farbklassen sind **fest und gewählt** (die Legende sagt das) — beim Schwenken über die
Stadt bleiben die Farben dadurch vergleichbar, anders als bei Quantilen, die sich jedem
Ausschnitt anpassen würden. Klick auf eine Zelle zeigt die Rohwerte und bietet **„Hier
analysieren"** an: das setzt den Punkt in die Zellmitte und lädt alle Blöcke. Der
Arbeitsfluss ist also: Übersicht an → interessante Gegend erkennen → hineinzoomen →
analysieren. Geladen wird je Kartenausschnitt, mit Kachel-Cache (leichtes Schwenken fragt
den Dienst nicht erneut).

### Größere Radien — möglich, aber mit Ansage

Der Analyse-Radius geht jetzt bis **2000 und 3000 m**. Das ist für Umlandgemeinden gedacht,
wo das Gemeindegebiet das Einzugsgebiet ist — nicht für die Innenstadt: am dichtesten Punkt
Münchens sind 3000 m rund **9.750 OSM-Elemente, 4,5 MB und ~2 Minuten** (gemessen am
01.08.2026), und ein Einwohner-Mittel über einen 3-km-Kreis verwischt genau die
Unterschiede, die man sucht. Die Auswahl sagt das dazu. Die Gehstreckenberechnung bleibt
bei **2000 m** gedeckelt — zu Fuß ist ein größerer Umkreis kein Einzugsgebiet, und das
Wegenetz dafür wäre eine unverhältnismäßige Last für den Spendendienst.

## Flächen-Scan: WO im Viertel teilen sich viele Anwohner wenige Betriebe?

Die Erkundungsebene zeigt, wo Menschen wohnen; der Umkreis zeigt, wie es an einem Punkt
ist. Die Ebene **„Flächen-Scan (Einwohner je Betrieb)"** beantwortet die Frage dazwischen:
*wo im Viertel* ist das Verhältnis aus Nachfrage und Angebot am günstigsten? Sie legt das
100-m-Zensusgitter über den Ausschnitt und stellt jeder Zelle die Gastronomie aus OSM
gegenüber — als **Einwohner je Gastronomiebetrieb im 300-m-Umfeld** der Zellmitte. Dunkle
Zellen heißen: viele Anwohner teilen sich wenige Betriebe. Zellen ganz ohne Betrieb im
Umfeld bekommen bewusst keinen Zahlenwert (nicht „unendlich"), sondern eine eigene Klasse.

So funktioniert er, und das kostet er:

- **Eine** Zensus- und **eine** Overpass-Abfrage für den ganzen Ausschnitt statt dutzender
  Umkreisabfragen. Gemessen am 02.08.2026 rund um den Marienplatz (~1,8 × 1,8 km):
  541 Zellen, 1.079 Betriebe, 162 kB.
- Nach dem Schwenken wird **nicht** automatisch neu gescannt — jeder Scan ist eine echte
  Overpass-Abfrage. Die Legende bietet stattdessen „Diesen Ausschnitt scannen" an.
  Gleiche Kachelrundung wie beim Übersichtsgitter: leichtes Schwenken trifft den Cache.
- Begrenzt auf rund **4 × 5 km** (ab Zoomstufe 13); für die große Fläche ist die
  Übersichtsebene da. Ist der Kartenausschnitt größer, wird das Scanfenster um die
  Kartenmitte gelegt — der gestrichelte Rahmen zeigt, was gescannt ist.
- Klick auf eine Zelle zeigt die Rohwerte und bietet **„Hier analysieren"** an.

Was die Kennzahl **nicht** kann, steht in Legende und Antwort: OSM zählt Betriebe
unvollständig, die Werte sind deshalb Obergrenzen. Und sie sieht nur die Wohnbevölkerung —
Zulauf von Büros, Passanten und Touristen fehlt. Eine dunkle Wohnlage ist ein Suchhinweis,
keine Standortentscheidung; die Innenstadt ist hier hell *und* trotzdem voller
funktionierender Betriebe.

## Planungsrecht und Hochwasser (Bayern, Bebauungspläne und Milieuschutz München)

Drei Fragen, die eine Standortentscheidung kippen können und die keine der übrigen Quellen
beantwortet. Block **6e** fragt sie am Punkt ab.

| Quelle | Befund der Prüfung (01.08. / 07.08.2026) |
|---|---|
| Hochwassergefahrenflächen, LfU Bayern | **funktioniert** — liefert Gewässer, Jährlichkeit und Ermittlungsdatum. Isarauen Thalkirchen: „Isar, HQ 100, 30.09.2016" |
| Bebauungsplan-Umgriffe, Geoportal München | **funktioniert** — liefert die Plannummer. Freiham: „A1856" |
| Erhaltungssatzungen (Milieuschutz), Geoportal München | **funktioniert** — liefert Gebietsname, Gültig-ab-Datum und die PDF-Links zu Plan und Satzungstext. Haidhausen: „Gebiet Haidhausen, gültig ab 11.03.2021"; Marienplatz korrekt: kein Gebiet |
| Flächennutzungsplan München | nur Kartenebene — `queryable` ist im Dienst nicht gesetzt, eine Punktabfrage gibt es nicht |
| Lärmwert am Punkt, LfU | **geht nicht.** Der Dienst antwortet, gibt aber über 81 Rasterpunkte quer über die Landshuter Allee durchgehend `NoData` zurück. Bleibt Kartenebene |

> **Fallstrick, der beim Bauen zweimal in die Irre führte:** beide Dienste führen `EPSG:4326`
> **nicht** in ihrer CRS-Liste. Mit 4326 antworten sie mit einer leeren Trefferliste statt mit
> einem Fehler — das sieht aus wie „nicht betroffen" und ist es nicht. Verwendet wird `CRS:84`.

Was der Block **nicht** sagt: ein Bebauungsplan-Umgriff bedeutet nur, dass es einen Plan
gibt — nicht, was er erlaubt. Und wo keiner ausgewiesen ist, heißt das nicht „alles
erlaubt": im unbeplanten Innenbereich gilt § 34 BauGB. Beide Hinweise stehen im Block.

Der Milieuschutz-Befund ist für Gastronomen konkret: in einem Erhaltungssatzungsgebiet
ist die **Umwandlung von Wohnraum in einen Gastraum praktisch ausgeschlossen** und jeder
Umbau genehmigungspflichtig — eine bestehende Gewerbefläche zu übernehmen bleibt möglich.
Was genau gilt, steht im direkt verlinkten Satzungstext. Ob ein Punkt betroffen ist, steht
zusätzlich als Ja/Nein-Spalte in der Vergleichstabelle.

## Eigene Notiz und Note je Standort

Das Werkzeug bewertet bewusst nicht und stellt keine Rangfolge auf. Der Nutzer darf und soll
das aber — dafür hat jeder gemerkte Punkt in der Vergleichstabelle eine **eigene Note von
1 bis 5** und ein **Notizfeld**. Beides ist als eigene Einschätzung beschriftet, steht in der
festen Spaltengruppe, geht in keine Rechnung ein und landet im CSV-Export.

Eine Datenbank aus einer früheren Fassung wird beim Start um die beiden Spalten ergänzt,
statt den Nutzer seine gemerkten Punkte zu kosten.

## Verfügbares Einkommen (Kreisebene) — die ehrliche Kaufkraft-Näherung

Kleinräumige Kaufkraft ist ein kommerzielles Datenprodukt; jede „freie" Zahl dazu wäre
erfunden. Was es amtlich und frei gibt: das **verfügbare Einkommen der privaten Haushalte
je Einwohner auf Kreisebene** aus den Volkswirtschaftlichen Gesamtrechnungen der Länder —
Block **3b** zeigt es für den Kreis des Punktes, daneben Land und Bund zum Einordnen, dazu
den Verlauf der letzten Jahre. Live-Gegenprobe bei der Anbindung am 02.08.2026:
Deutschland 25.830 €, Bayern 28.643 €, München (Stadt) 35.467 €, Landkreis München
35.832 € — deckungsgleich mit den VGRdL-Veröffentlichungen. Der Warnhinweis steht im
Block: es ist ein **Kreiswert**, innerhalb einer Großstadt unterscheidet er keine
Viertel; kleinräumige Anzeiger bleiben Nettokaltmiete und Eigentümerquote aus dem Zensus.

Technisch läuft die Abfrage gegen den Kartendienst des **Regionalatlas Deutschland**
(Statistische Ämter, ArcGIS-Server der IT.NRW, Tabelle `regionalatlas.ai016_1`), je Kreis
gecacht — jeder Punkt im selben Kreis kostet keinen weiteren Abruf.

**Geprüfter Irrweg, dokumentiert statt gebaut:** Die experimentellen
**Passantenfrequenzen von Destatis** (auf hystreet-Basis) wären die wertvollere Quelle
gewesen — die Prüfung ergab: zum **31.12.2025 eingestellt**, keine Datendateien mehr, nur
21 Städte mit je einer Zählstelle. Gemessene Passantenfrequenz bleibt damit die eine
Datenklasse, die es frei nicht gibt.

## Kreisprofil (Block 3c) — vier weitere amtliche Blicke auf den Kreis

Auf demselben verifizierten Regionalatlas-Dienst liest Block **3c** vier weitere
Indikatortabellen, jede mit Kreis, Land und Bund nebeneinander und mit ihrem eigenen
Datenjahr (die Jahre unterscheiden sich je Tabelle und werden nicht vermischt):

- **Gästeübernachtungen je Einwohner** und durchschnittliche Aufenthaltsdauer
  (Beherbergungsstatistik) — Touristen sind Zulauf, den der Zensus nicht sieht.
- **Erwerbstätige am Arbeitsort je 1.000 Einwohner (15–64)** — die ehrliche
  Tagesbevölkerungs-Näherung. Ein Wert über 1.000 heißt: mehr Arbeitsplätze als
  Erwerbsfähige, also Einpendler. Dazu der Anteil Handel/Verkehr/Gastgewerbe.
- **Beschäftigten- und Arbeitslosenquote** — für Gastronomie doppelt lesbar, als
  Kaufkraft-Umfeld und als Personalverfügbarkeit.
- **Bevölkerungsbewegung**: Entwicklung im Jahr und Wanderungssaldo je 10.000
  Einwohner, Bevölkerungsdichte — wächst die Region, in die ein langer Mietvertrag fällt?

Live-Gegenprobe am 03.08.2026 (München/Bayern/Bund): Übernachtungen 13,2/7,8/5,9 je EW
(2024) · Erwerbstätige 1.159/924/869 je 1.000 (2024) · Arbeitslosenquote 5,4/4,0/6,3 %
(2025) · Bevölkerungsentwicklung +108,8/+54,9/+14,5 je 10.000 EW (2024). Platzhalter-
Sperrwerte des Dienstes (2222222…) werden zu „liegt nicht vor", nie zu einer Zahl.

## Pendler (Block 3d) — wer ist tagsüber wirklich da?

Phase-0-Fund: der **Pendleratlas der Statistischen Ämter**
(`pendleratlas.statistikportal.de`) lädt seine Werte als offene CSV-Dateien
(Datenlizenz Deutschland 2.0) — Einpendler, Auspendler, Saldo, Quoten und Binnenpendler
je Gemeinde (12-stelliger Regionalschlüssel), dazu je Land eine Verflechtungsdatei mit
den wichtigsten Herkunfts- und Zielgemeinden **samt Entfernung**. Quelle ist die
Pendlerrechnung des Bundes und der Länder (Erwerbstätigen-Konzept, nicht nur
sozialversicherungspflichtig Beschäftigte). Live-Gegenprobe München 2024: 529.834
Einpendler, 248.679 Auspendler, Saldo +281.155, Einpendlerquote 45,3 %.

Der Block deutet den Saldo ehrlich („gewinnt tagsüber per Saldo X Menschen dazu") und
lässt Eigenheiten sichtbar: Berlin taucht als München-„Herkunft" auf — mit 501 km in der
km-Spalte, denn die Pendlerrechnung arbeitet mit gemeldeten Orten (Homeoffice,
Zweitwohnung). Der AGS aus dem Zensus wird über die Gemeindeliste des Atlas auf den ARS
abgebildet (Stellen 1–5 + 10–12). Grenze wie immer benannt: **Gemeindewert**, für München
die ganze Stadt.

## Klima für Außengastronomie (Block 5b, DWD)

Für Biergarten, Terrasse und Eisdiele: **Klimanormalwerte 1991–2020** der jeweils
nächsten DWD-Station vom Open-Data-Server (`opendata.dwd.de`, offene Textdateien) —
Sommertage, Heiße Tage, Sonnenscheindauer, Niederschlag, Jahresmitteltemperatur, dazu die
Monatsverteilung der Sommertage als Balken (wie lang ist die Draußen-Saison?). Jede
Kennzahl nennt **ihre** Station samt Entfernung und Stationshöhe — jeder Parameter hat
ein eigenes Stationsnetz (Sonnenschein wird an weit weniger Stationen gemessen als
Niederschlag), am Marienplatz stammen die Werte z. B. von München-Stadt,
München-Bogenhausen und St. Bonifaz. Ab 30 km Entfernung warnt der Block. Gecacht werden
die zehn Deutschland-weiten Dateien, nicht der Punkt — der zweite Punkt irgendwo in
Deutschland kostet keinen Abruf mehr.

## Gastro-Dynamik (Block 4e) — wächst die Lage oder stirbt sie?

Der OSM-Block ist eine Momentaufnahme; die **ohsome-API** (HeiGIT Heidelberg, ohne
Konto) wertet die volle OSM-Historie aus und liefert die Zahl der Gastro-Objekte im
Umkreis als Jahresreihe, jeweils zum 1. Januar der letzten sieben Jahre — mit
Schnellgastronomie-Teilreihe und demselben Gastronomiebegriff wie der OSM-Block
(Marienplatz r=600: 326 → 369 seit 2019). Die eine Grenze steht über allem und in
jedem Ergebnis: die Kurve misst die **OSM-Datenbank**, nicht direkt die Wirklichkeit.
Ein Anstieg kann Neueröffnungen zeigen — oder fleißigere Kartierer. Als
Mehrjahres-Trend brauchbar, als Absolutzahl je Jahr nicht; Schließungen erscheinen
nur, wenn jemand sie einträgt.

## Öffnungszeiten-Lücken — Sonntags- und Abendangebot, konservativ gezählt

Aus den ohnehin geladenen OSM-Daten (kein neuer Abruf): Wie viele Betriebe im Umfeld
haben sonntags geöffnet, wie viele nach 22 Uhr? Der Parser ist bewusst konservativ —
bewertet wird eine `opening_hours`-Angabe nur, wenn sie vollständig aus einfachen
Wochentag-Uhrzeit-Regeln besteht („Mo-Fr 11:00-22:00; Su off", „24/7"); Feiertags-,
Saison- und Sonderregeln zählen als **nicht auswertbar, nie als geschlossen**. Alle
Zahlen sind deshalb Mindestzahlen („mindestens X von Y auswertbaren"), und
Mitternachtsüberhang bleibt beim genannten Tag: Samstagnacht bis 4 Uhr ist nicht
„sonntags geöffnet". Ob eine Lücke Chance (niemand versorgt den Sonntag) oder
Warnzeichen (der Sonntag lohnt für niemanden) ist, entscheidet der Blick vor Ort.

## Straßenlärm (Block 6f) — Umgebungslärmkartierung, Bayern

Für Außengastronomie ist Straßenlärm eine Standorteigenschaft wie Sonne. Das
Lärm-WMS des LfU Bayern liefert per Rasterabfrage die berechneten Pegel der
EU-Umgebungslärmkartierung am Punkt: **LDEN** (Tag-Abend-Nacht) und **LNight**
(22–6 Uhr) in dB(A), samt Band der Kartierungslegende. Drei ehrliche Grenzen stehen
im Block: Kartiert sind nur **Hauptverkehrsstraßen** — „nicht kartiert" heißt „keine
kartierte Hauptverkehrsstraße am Punkt", nicht „leise" (Nebenstraßen-, Schienen-,
Flug- und Gewerbelärm fehlen). Es sind berechnete Pegel, keine Messwerte. Und
innerhalb der Ballungsräume (etwa München) ist die jüngste LfU-Fläche die Kartierung
**2017** — die 2022er-Runde deckt nur Gebiete außerhalb ab; das Kartierungsjahr steht
deshalb an jedem Wert. Außerhalb Bayerns bleibt der Block mit Begründung leer.

## Zweite Wettbewerbsquelle: Overture Places (Block 4f)

OSM zählt Betriebe unvollständig — am härtesten in Einkaufszentren. Gemessen am
04.08.2026 am MIRA (München-Nordheide): OSM kennt dort **3** Gastro-Betriebe,
Overture **15** (Hans im Glück, Thai Curry, Veneras Pizza, Van Hoa Sushi, Peking, …).
**Overture Maps** ist das offene POI-Projekt von Meta, Microsoft, Amazon und TomTom;
die Places speisen sich u. a. aus den Facebook/Instagram-Unternehmensprofilen,
Foursquare und den offiziellen Filiallisten der Ketten — Quellen, die Ladenpassagen
kennen. Lizenz CDLA-Permissive 2.0: darf (anders als Google-Daten) lokal gespeichert
und auf der eigenen Karte angezeigt werden.

Einrichtung wie beim GTFS-Fahrplan, einmalig:

```bash
pip install overturemaps
gastroviewer import-overture --region muenchen
```

Danach zeigt Block 4f je Punkt den Abgleich: OSM-Untergrenze, Overture-Treffer ab
einer benannten Verlässlichkeitsschwelle (0,5), „in beiden Quellen" (Abgleich über
Name und Nähe), „nur in Overture" mit Namen, Adresse und eigenen lila Karten-Pins —
und die **kombinierte Zahl**, die die Schätzung ausdrücklich (nie stillschweigend)
als Wettbewerberzahl anbietet. Ehrliche Grenzen im Block: maschinell zusammengeführte
Daten mit Ausreißern (auch Firmensitze ohne Ladentür), der Namensabgleich ist eine
Heuristik, und Schließungen hinken in beiden Quellen hinterher — die kombinierte Zahl
ist die bessere Näherung, die Begehung bleibt die Wahrheit.

## Gesamt-Score (Block 1b) — ein Punktwert, nichts versteckt

Ein Score ist immer eine Setzung — deshalb ist hier nichts verborgen: **acht
Kennzahlen** (Einwohner, Einkommen, ÖPNV-Abfahrten, Frequenzbringer, Marktsättigung,
Wohnmiete, Straßenlärm, Baustellen mit Gehweg-Eingriff), jede mit Quelle, jedem
Anker („ab wann 0, ab wann 100 Punkte" — gewählte Werte, an jeder Zeile sichtbar)
und einem eigenen **Gewichtsregler** (0–3, lokal gespeichert, Gewicht 0 nimmt die
Kennzahl heraus). Punkteformel: linear zwischen den Ankern, gekappt; bei Miete,
Lärm und Baustellen dreht die Ankerreihenfolge die Richtung um. Fehlende Kennzahlen
verkleinern die Gewichtssumme und werden benannt, statt still als 0 zu zählen.
Derselbe Score steht mit denselben Gewichten im druckbaren Standortbericht.
Vergleichbar sind nur Punkte mit gleichem Radius — auch das steht im Block.

## Viertel-Steckbrief (Block 2b) — die Entwicklung des Stadtbezirks

Der Zensus zeichnet das Umfeld räumlich fein (100 m), aber als Momentaufnahme 2022.
Der **Indikatorenatlas München** (Statistisches Amt, 68 offene Datensätze) ergänzt
die Entwicklung: Jahresreihen je Stadtbezirk bis 2025. Das Werkzeug zeigt sieben
Kennzahlen mit ~5-Jahres-Trend gegen den Stadtwert: **Einpersonenhaushalte**
(stadtweit 54,4 %, Altstadt-Lehel 63,7 % — Singles essen häufiger auswärts),
davon **unter 30**, Durchschnittsalter, 65+, Bevölkerungsdichte, **Wohndauer an
der Adresse** (Fluktuation: neue Kundschaft vs. Stammgäste) und Arbeitslosen-Anteil.
Die Bedeutung jeder Kennzahl ist aus den Basiswert-Spalten der Original-CSVs
belegt, nicht interpretiert. Der Stadtbezirk kommt aus der ohnehin geladenen
Nominatim-Adresse — null zusätzliche Anfragen; die CSVs werden stadtweit einmal
gecacht. Nur München; anderswo bleibt der Block mit Begründung leer.

## Baustellen (Block 6g) — der kurzfristige Ernstfall

Eine monatelange **Gehwegsperrung vor der Tür** ist einer der häufigsten
kurzfristigen Umsatzkiller im Gastgewerbe. Die Stadt München veröffentlicht ihre
Baustellen-Servicekarte als offenen WFS: alles, was läuft oder in den nächsten
vier Wochen beginnt, mit Umriss-Polygon, Zeitraum und exakter Beeinträchtigung.
Der Block zählt laufend/geplant, **Gehweg betroffen** und Sperrungen, zeichnet
die Umrisse auf die Karte (rot, wenn der Gehweg betroffen ist) und macht die
Liste springbar. Live am Marienplatz (600 m, 07.08.2026): 314 Maßnahmen, 248
laufend, 107 mit Gehweg-Eingriff. Ehrliche Grenzen im Block: Vier-Wochen-Vorschau
(eine Baustelle in drei Monaten kennt der Dienst noch nicht — vor der
Vertragsunterschrift neu prüfen), nur Stadtgebiet München, Haltverbote sind meist
Umzüge von wenigen Tagen.

## Städtische Märkte (Block 5c) — Frequenzbringer mit Terminen

54 Münchner Märkte (34 Wochenmärkte, 10 Bauernmärkte, 5 ständige, 5 Großmärkte)
aus dem Stadtdatensatz — mit **Öffnungszeiten** direkt aus der Quelle, denn ein
Wochenmarkt bringt Frequenz an seinen Markttagen, nicht täglich. Reichweite
2 km (gewählter Wert), eigene Karten-Pins, springbare Liste; Großmärkte sind an
der Rubrik erkennbar (Handelsplätze, keine Laufkundschaft).

**Dazu im Kreisprofil (3c):** die Wirtschaftskraft aus dem Regionalatlas —
BIP je Einwohner (München 97.406 € gegen Bayern 57.725 € und Bund 49.525 €),
BIP je Erwerbstätigen und die Vorjahresveränderung, Feldbedeutungen amtlich
belegt. Und in den weiterführenden Quellen: der **Mapillary-Link** — freie
Straßenfotos am Punkt, die „Begehung vom Schreibtisch aus", bevor man hinfährt
(Bildstand kann Monate bis Jahre alt sein, steht dabei).

**Geprüfte Irrwege dieser Runde, dokumentiert statt gebaut:** Bodenrichtwerte
über BORIS Bayern (Einsicht im Viewer frei, die Daten selbst in Bayern
**gebührenpflichtig** — es bleibt beim Link), die BASt-Straßenverkehrszählung
(frei, aber nur Autobahnen/Bundesstraßen — für Innenstadtlagen deckt die
Lärmkartierung den Kfz-Verkehr besser ab) und die städtische Parkhaus-Liste
(72 Standorte, aber ohne Kapazitäten — gegenüber dem OSM-Bestand kein
Mehrwert). Google Places bleibt draußen, weil die API eine Kreditkarte
voraussetzt; Google gibt es weiterhin nur als Handkontroll-Link.

## Kurzzeitvermietung (Block 5d) — wo die Gäste wirklich schlafen

Übernachtungszahlen gibt es amtlich nur je Kreis. **Inside Airbnb** (CC BY 4.0)
zeigt kleinräumig, wo Touristen unterkommen: alle Airbnb-Inserate einer Stadt
mit Zimmertyp, Preis und Bewertungszahl. Am Marienplatz sind es 127 Inserate im
600-m-Umkreis (86 ganze Unterkünfte) — Frühstücks- und Abendpublikum, das in
keiner Einwohnerzahl steckt. Der Block zählt Inserate und Zimmertypen, summiert
die Bewertungen der letzten zwölf Monate (Aktivitätsindiz, keine Buchungszahl)
und nennt den Median-Preis je Nacht samt Preisbasis. Ehrlich dazu: Airbnb
versetzt die Positionen plattformseitig um bis zu ~150 m — Zählwerte sind
Näherungen, die Pins zeigen nicht das richtige Haus. Datenstädte in
Deutschland: München und Berlin (Stand der Datenseite); überall sonst bleibt
der Block mit Begründung leer. Der stadtweite Datensatz wird einmal je 30 Tage
geladen (zwei Abrufe), danach rechnet jeder Punkt lokal.

## Amtliche Gastro-Anker (Block 3e) — Opt-in mit Regionaldatenbank-Kennung

Zwei Zahlen, die es nur in der Regionaldatenbank der Statistischen Ämter gibt
(beide Kreisebene, Tabellenstruktur und Sollwerte am 2026-08-07 verifiziert):

- **Umsatzsteuerstatistik 73311-01-02-4:** steuerbarer Umsatz und Zahl der
  Umsatzsteuerpflichtigen im Gastgewerbe (WZ-Abschnitt I), Zeitreihe ab 2009.
  Daraus der amtliche Anker „Umsatz je Steuerpflichtigem" — für München 2023:
  4.019 Pflichtige, im Schnitt 1.638.293 € (Vorsicht: Unternehmenssitz-Prinzip,
  Ketten und Hotels heben den Schnitt; nur Umsätze über 22.000 €/Jahr).
- **Gewerbeanzeigen 52311-01-04-4:** An-/Abmeldungen mit Neuerrichtungen und
  Betriebsaufgaben (alle Wirtschaftszweige — ein Branchen-Split existiert auf
  Kreisebene nicht). München 2025: 15.350 an, 10.245 ab, Saldo +5.105.

Der maschinelle Abruf verlangt eine **kostenlose Kennung** — das einzige
Konto-Opt-in des Werkzeugs (siehe Konto-Prinzip oben). Der Block bietet das
Eintragen direkt an, prüft die Kennung live beim Dienst (logincheck) und
speichert sie nur lokal.

## Messe-Kalender (Block 5e) — planbare Frequenzspitzen

Messetage sind vorhersagbare Nachfragespitzen: eine bauma bringt 605.974 Besucher
in die Stadt (2025, größte aufgezeichnete Veranstaltung). Die **Messe München
veröffentlicht ihre Veranstaltungen seit 2018 als offene CSV** — mit Terminen,
Turnus, Gelände und (für vergangene Veranstaltungen) Besucher- und
Ausstellerzahlen. Der Block filtert auf die Münchner Gelände (die Messe München
veranstaltet auch in Delhi und Shanghai), zeigt laufende und kommende Termine,
die Jahresbilanz und die größten Veranstaltungen, dazu die Entfernung zum
nächsten Gelände (Messe Riem, ICM, MOC — Koordinaten fest hinterlegt, als
gewählte Werte markiert). Ehrlich dazu: Der Datensatz wird als „bisherige
Veranstaltungen" nachlaufend gepflegt — kommende Termine können fehlen. Und die
Wirkung kommt über **Hotels und die U2** beim Standort an, nicht über
Laufkundschaft am Gelände. Jenseits von 20 km um die Gelände bleibt der Block
mit Begründung leer; einen vergleichbaren offenen Messe-Datensatz mit
Besucherzahlen gibt es für andere Messestädte nicht.

## Tourismus-Saisonalität (Block 3f) — wie tief ist der Januar

Das Kreisprofil (3c) trägt die Jahressumme der Übernachtungen für jeden Kreis in
Deutschland — was fehlt, ist der Jahresverlauf. Das **Statistische Amt München**
veröffentlicht Gäste und Übernachtungen als Monatsreihe seit 2006 (offene CSV,
stadtweit). Der Block zeigt die letzten zwölf gefüllten Monate mit Vergleich zum
Vorjahreszeitraum, den Auslandsanteil, die abgeleitete Aufenthaltsdauer und eine
**Saisonkurve** (Mittel der letzten fünf vollständigen Jahre, indexiert auf den
Jahresdurchschnitt — München: Juli 130, Januar 59). Für einen Standort, der vom
Tourismus lebt, ist das die Antwort auf die Frage, wie tief der Winter wird.
Bundesweit gibt es Monatswerte je Kreis **nicht** als offene Quelle — die
Regionaldatenbank führt nur Jahressummen, Destatis verlangt für den Abruf eine
Kennung; außerhalb Münchens verweist der Block deshalb ehrlich auf den
Jahreswert im Kreisprofil.

## Rad-Liefergebiet (Block 4d) — erreichbare Einwohner in Lieferzeit

Für Lieferkonzepte zählt nicht der Umkreis, sondern: wie viele Menschen erreicht ein
Lieferrad in 5–15 Minuten? Dasselbe Rechenwerk wie die Erreichbarkeit zu Fuß (OSM-Netz,
Dijkstra, Zensuszellen), aber mit **Radprofil** und pauschal 15 km/h — ein gewählter
Wert, der in der Ausgabe steht. Nur auf Knopfdruck (großes Wegenetz, Overpass ist ein
Spendendienst), Ergebnis 14 Tage im Cache, eigene Kartenebene mit Streckenstufen.

Lehrstück aus dem ersten Live-Test: ohne Fußwege zerfiel das Radnetz am Marienplatz in
Inseln (21.214 Knoten, 2 erreichbar) — Fußwege sind in Altstädten die Verbindungsstücke.
Sie sind deshalb im Profil (Lieferräder dürfen meist schieben), und der Hinweis nennt die
Fehlerrichtung: eher zu groß gerechnet. Gegenprobe danach: 9.350 Einwohner in 5 Minuten
ab Marienplatz.

## Werkzeuge: Datensicherung, Pflegelauf, Adressliste, Duell-Bericht

- **Datensicherung**: „Sichern (Datei)" im Standortvergleich lädt alle gemerkten Punkte
  samt Verlauf, Notizen und Bewertungen als eine JSON-Datei; „Sicherung einspielen" liest
  sie wieder ein — exakte Dubletten werden erkannt und übersprungen.
- **Pflegelauf**: „alle N neu prüfen" fragt jeden gemerkten Punkt nacheinander neu ab
  (mit Kostenansage — je Punkt eine Overpass-Abfrage) und fasst die Veränderungen
  zusammen.
- **Adressliste**: mehrere Adressen aus Makler-Exposés auf einmal — eine je Zeile,
  höchstens 25, nacheinander über Nominatim (1 Anfrage/s bleibt gewahrt) gesucht und als
  Punkte gemerkt; Zeilen ohne Treffer bleiben als Fehlerliste stehen.
- **Duell-Bericht** (`/duell?a=…&b=…`): die Endauswahl ist fast immer ein Zweikampf —
  eine Druckseite, beide Kandidaten Spalte an Spalte mit beiden Lagekarten und einer
  Differenzspalte. Bewusst ohne „Gewinner"-Markierung: die Differenz ist ein Fakt, keine
  Wertung; bei ungleichen Radien warnt die Seite.
- **Branchenprofil** im Gastronomieblock: wählbar, welche OSM-Typen als direkter
  Wettbewerb zählen (Imbiss, Restaurant, Café, Bar, Eisdiele) — reine Filterung
  vorhandener Daten; die Schätzung bietet die Profilzahl sichtbar zur Übernahme an.
- **Scan-Metriken**: der Flächen-Scan kann neben „Einwohner je Betrieb" auch
  Betriebsdichte und Einwohnerdichte einfärben — der Wechsel zeichnet nur um, ohne neue
  Abfrage.
- **Mietprobe** in der Schätzung: Fläche × geforderte Kaltmiete aus dem Exposé gegen die
  Miet-Obergrenze der Rechnung — eine Gegenprobe, kein Rechenfaktor.

**Geprüfte Irrwege dieser Runde, dokumentiert statt gebaut:** die
BBSR-Bevölkerungsprognose 2045 gibt es nur im Tableau-Dashboard ohne stabile offene
Datei-Endpunkte (und inkar.de liefert eine unvollständige TLS-Zertifikatskette); München
bietet keine offene Passantenzählung, Bonns „tagesaktuelle" Ressource verweist nur auf
hystreet.com und die statischen Jahresdateien (2018) tragen keine Lizenz; die
PKS-Kreistabellen des BKA gibt es nur als XLSX und laut BKA-Interpretationshilfe nur
eingeschränkt vergleichbar. Alle drei stehen als Links mit Begründung im Quellenblock.

## Franchise: Systemgastronomie, Gebietsschutz, Kostenprobe

Drei Ergänzungen aus der Sicht eines Franchisenehmers:

**Kandidaten auf der Karte.** Die Ebene **„Gemerkte Punkte"** zeigt alle gemerkten
Standorte mit Etikett und gestricheltem Einzugsgebietskreis; der Vergleichsdialog warnt,
wenn sich zwei Einzugsgebiete überschneiden — solche Kandidaten teilen sich dieselben
Einwohner und sind keine unabhängigen Optionen. Der Bericht enthält inzwischen auch eine
**Lagekarte** (Umkreis + Wettbewerber aus dem gespeicherten Stand), und der ÖPNV-Block
weist neben dem Mittags- auch das **Abendfenster 17–22 Uhr** aus.

**Block 4c · Systemgastronomie & Marken.** Welche Systeme sitzen schon im Umkreis — je
Marke mit Anzahl und nächster Entfernung, dazu der Kettenanteil an der Gastronomie (auch
als berechnete Spalte im Vergleich). Der Hinweis dazu ist bewusst zweischneidig:
Systemgastronomie prüft Standorte professionell, ihre Präsenz ist ein Indiz für tragfähige
Frequenz — und zugleich direkte Konkurrenz. Ihr Fehlen kann eine Lücke sein oder ein
Warnsignal; die Zahl entscheidet das nicht. Alles aus den bereits geladenen OSM-Daten,
keine zusätzliche Abfrage.

**Gebietsschutz-Check (`/api/point/marke`).** Wo ist der nächste Betrieb der *eigenen*
Marke? Gebietsschutz und Kannibalisierung werden in Kilometern gedacht, nicht in
Gehminuten — deshalb sucht der Check in einem eigenen Radius (5/10/20 km, auf Knopfdruck)
per brand- **und** Namenssuche unter gastronomisch getaggten Objekten. Treffer erscheinen
als violette Marker auf der Karte; Treffer ohne brand-Tag sind als „nur namensgleich"
markiert (vermutlich Einzelbetriebe). Drei Ehrlichkeiten stehen in der Antwort: null
Treffer sind eine Aussage über OSM, **kein Beleg für ein freies Gebiet**; die Namenssuche
kann Gleichnamige erwischen; und was der Gebietsschutz umfasst, steht im Franchisevertrag
— das hier ist die Karte, nicht der Vertrag.

Technische Ehrlichkeit dazu: der erste Entwurf filterte per regulärem Ausdruck auf dem
Overpass-Server und lief bei 10 km reproduzierbar in den Timeout (Regex ohne
Groß-/Kleinschreibung kann Overpass nicht indizieren). Deshalb lädt die erste Suche je
Punkt die **markenunabhängige Basis** — alle Gastronomie im Radius, gemessen für 10 km
Innenstadt: 4.631 Betriebe, 2,6 MB, ~30 s — und jede weitere Markensuche am selben Punkt
ist reine lokale Rechnung aus dem Cache.

**Franchise-Kostenprobe in der Schätzung.** Vier neue Eingabefelder — Franchisegebühr,
Werbeabgabe, Wareneinsatz, Personalkosten, jeweils in % vom Umsatz. Es gibt **bewusst
keine Vorgabewerte**: die Sätze stehen im Franchisevertrag und in der eigenen Kalkulation,
und jeder hier erfundene „typische" Satz würde als Branchenwert gelesen. Sind Sätze
eingetragen, zeigt das Ergebnis, was von der Umsatzspanne übrig bleibt — je Monat, vor
Miete, Abschreibung, Zinsen, Steuern und Unternehmerlohn. Summieren sich die Sätze über
100 %, sagt die Probe klar: unter diesen Annahmen trägt sich kein Standort.

## Standortbericht zum Drucken

Sobald es ernst wird — Vermieter, Bank, Partner —, braucht man das Ergebnis außerhalb des
Werkzeugs. Jeder gemerkte Punkt hat in der Vergleichstabelle den Link **„Bericht"**: eine
druckfreundliche Seite mit allen Kennzahlgruppen, der eigenen Note und Notiz (als solche
gekennzeichnet), dem Verlauf, jeder Quelle mit Stand und Lizenz und den bekannten Grenzen
der Daten. Ein PDF entsteht über die **Druckfunktion des Browsers** — bewusst ohne
zusätzliche Bibliothek. Der Bericht zeigt den gespeicherten Datenstand des Punktes und
löst selbst keinen Abruf bei einem externen Dienst aus.

## Verlauf: „Neu prüfen" je gemerktem Punkt

Standortsuche dauert Monate, und gemerkte Punkte waren bisher Momentaufnahmen. Der Knopf
**„neu prüfen"** in der Vergleichstabelle fragt dieselben Quellen erneut ab (ausdrücklich
am Cache vorbei, nach einer Rückfrage — es ist eine echte Overpass-Abfrage) und benennt
die konkrete Veränderung:

- **eröffnete und verschwundene Betriebe** mit Name, Typ und Entfernung — ein
  verschwundener Betrieb ist ein doppeltes Signal: mögliches freies Ladenlokal *und* ein
  Wettbewerber weniger. Der Hinweis dazu sagt ehrlich: es ist zunächst eine OSM-Änderung,
  erst die Begehung macht daraus ein freies Ladenlokal.
- **geänderte bewegliche Kennzahlen** (OSM, GTFS, Zählstellen) als vorher/jetzt-Tabelle.
  Zensuswerte werden bewusst nicht verglichen — ihr Stichtag bleibt der 15.05.2022, und
  Unterschiede wären nur Rauschen der stochastischen Überlagerung.

Der bisherige Stand wandert dabei in den **Verlauf** des Punktes (eigene Tabelle in der
Datenbank, wird beim Löschen des Punktes mit aufgeräumt). Der Standortbericht zeigt den
Verlauf als Zeitreihe; die Gehstrecken werden beim Prüfen nicht neu geladen — sie sind die
größte Abfrage des Werkzeugs und altern in Wochen, nicht in Tagen.

## Gewichtetes Ranking — eigene Gewichte, offene Rechnung

Das Werkzeug bewertet weiterhin nicht. Aber ab zwei gemerkten Punkten bietet der
Vergleichsdialog ein **gewichtetes Ranking** an, dessen Punktzahl allein aus den Gewichten
des Nutzers folgt: je Kennzahl ein Regler (0 bis ×3), jede Kennzahl wird über die
gemerkten Punkte auf 0–100 skaliert (bester Wert 100, schlechtester 0) und nach Gewicht
gemittelt. Die Tabelle zeigt **jeden Beitrag offen** — ohne diese Offenheit wäre es eine
Scheinnote. Drei ehrliche Eigenschaften:

- Kennzahlen, die fehlen oder bei allen Punkten gleich sind, gehen nicht ein und stehen
  als „—" da. Eine Skala aus einem einzigen Wert wäre erfunden.
- Gewicht 0 nimmt die Kennzahl sichtbar aus der Rechnung.
- Ob „weniger Wettbewerb" wirklich besser ist, entscheidet die Kennzahl nicht —
  Innenstadtlagen haben hohe Dichte *und* hohen Zulauf. Der Hinweis steht direkt dabei.

Die Gewichte bleiben lokal gespeichert (localStorage), wie die Spaltengruppenwahl.

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
| `GET /api/gitter?ebene=&west=&sued=&ost=&nord=` | Übersichtsgitter 1 km/10 km je Kartenausschnitt |
| `GET /api/scan?west=&sued=&ost=&nord=` | Flächen-Scan: Einwohner je Betrieb im 300-m-Umfeld, je 100-m-Zelle |
| `GET /api/einkommen?ags=` | verfügbares Einkommen je Einwohner (VGRdL, Kreisebene) mit Land- und Bundesvergleich |
| `GET /api/kreisprofil?ags=` | Kreisprofil: Übernachtungen, Erwerbstätige am Arbeitsort, Arbeitsmarkt, Bevölkerung |
| `GET /api/pendler?ags=` | Pendlerrechnung der Gemeinde: Ein-/Auspendler, Saldo, Top-Verflechtungen |
| `GET /api/point/klima?lat=&lon=` | DWD-Klimanormalwerte 1991–2020 der nächsten Station |
| `GET /api/point/dynamik?lat=&lon=&r=` | Gastro-Dynamik: Jahresreihe der OSM-Objekte (ohsome) |
| `GET /api/point/overture?lat=&lon=&r=` | Wettbewerbs-Abgleich OSM ↔ Overture Places (lokaler Import) |
| `GET /api/point/laerm?lat=&lon=&bundesland_code=` | Straßenlärm am Punkt (LfU Bayern, LDEN/LNight) |
| `GET /api/point/baustellen?lat=&lon=&r=` | Baustellen und Haltverbote im Umkreis (Stadt München, Vier-Wochen-Vorschau) |
| `GET /api/point/maerkte?lat=&lon=&r=` | städtische Märkte in Reichweite (München, mit Öffnungszeiten) |
| `GET /api/point/indikatoren?lat=&lon=` | Viertel-Steckbrief: Stadtbezirks-Jahresreihen (Indikatorenatlas München) |
| `GET /api/point/airbnb?lat=&lon=&r=` | Kurzzeitvermietung im Umkreis (Inside Airbnb, München/Berlin) |
| `GET /api/point/messe?lat=&lon=` | Messe-Kalender München (Termine, Besucher-Jahresbilanz, Gelände-Entfernung) |
| `GET /api/point/tourismus?lat=&lon=` | Tourismus-Saisonalität München (Monatszahlen, Saisonkurve) |
| `GET /api/genesis?ags=` | amtliche Gastro-Anker (Regionaldatenbank, Opt-in mit Kennung) |
| `GET/POST/DELETE /api/genesis/zugang` | Kennungs-Status ansehen, eintragen (mit Live-Prüfung), entfernen |
| `GET /api/point/liefergebiet?lat=&lon=&minuten=` | Rad-Liefergebiet: erreichbare Einwohner in 5–15 min — **nur auf Anforderung** |
| `GET /api/point/marke?lat=&lon=&marke=&r=` | Gebietsschutz-Check: Betriebe der eigenen Marke bis 20 km |
| `GET /api/geocode?q=` | Adresssuche |
| `GET /api/points` · `POST /api/points` · `DELETE /api/points/{id}` | gemerkte Punkte |
| `GET /api/points/{id}` · `GET /api/points/{id}/verlauf` | ein Punkt mit vollem Datenstand bzw. seine abgelegten Stände |
| `POST /api/points/{id}/pruefung` | „Neu prüfen": Quellen erneut abfragen, Unterschiede ausweisen |
| `GET /bericht?punkt={id}` | druckbarer Standortbericht (PDF über den Browserdruck) |
| `GET /duell?a={id}&b={id}` | Duell-Bericht: zwei Punkte Spalte an Spalte, beide Lagekarten |
| `GET /api/points/export` · `POST /api/points/import` | Datensicherung aller Punkte samt Verlauf als eine Datei |
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

### Vollprüfung aller Endpunkte

Die dritte Ebene: alle API-Routen (61 Prüfungen) live gegen einen laufenden Server, mit erzwungenen
Frischabrufen bei Zensus, Overpass und „Neu prüfen" und unabhängigen Erwartungswerten
(A9: 111.624 Kfz/Tag; Isarauen: HQ 100; Köln: Bodenrichtwert; Innenstadt-Scan: über
100 Betriebe). Braucht Netz und einen GTFS-Import.

```bash
python scripts/vollpruefung.py http://127.0.0.1:8011
```

### Oberflächenprüfung

`pytest` deckt ausschließlich Python ab. Alles in `app.js` — Blöcke, Reiter,
Kartenebenen, Vergleichstabelle — prüft ein eigenes Skript im echten Browser:

```bash
pip install playwright && playwright install chromium
python scripts/uitest.py http://127.0.0.1:8011
```

43 Prüfungen (dazu die Prüfung auf JavaScript-Fehler), darunter: jeder Block nennt
Quelle und Lizenz, im Datenreiter steht keine geschätzte Zahl, der Deckkraftregler wirkt
auf die Ebenen und **nicht** auf die Grundkarte, der Gehwegblock lädt nur auf Anforderung
und räumt seine Kartenebene beim Punktwechsel auf, der Flächen-Scan scannt nach dem
Schwenken erst auf Knopfdruck, der Bericht trägt Warnhinweis und Quellen, und im Ranking
nimmt Gewicht 0 die Kennzahl sichtbar heraus. Die Berichts- und Rankingprüfung legt sich
ihre Testpunkte selbst an und löscht sie wieder.

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
    planung.py       Hochwassergefahr, Bebauungsplan und Erhaltungssatzung am Punkt
    messe.py         Messe-Kalender München (Termine, Besucher-Jahresbilanz)
    tourismus.py     Tourismus-Monatszahlen München (Saisonkurve)
    links.py         Deep-Links aus Spec §4.6 und den Notizen
  static/            Oberfläche (Leaflet lokal, kein CDN)
scripts/
  abnahme.py         Abnahmekriterien aus §7 gegen einen laufenden Server
  uitest.py          Oberflächenprüfung im echten Browser
  vollpruefung.py    alle 29 API-Routen live, mit inhaltlicher Bewertung
fixtures/            echte API-Antworten aus Phase 0, Grundlage der Tests
docs/                Endpunktprüfung
```
