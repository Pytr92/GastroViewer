# Funktionsliste und Vergleich mit kommerziellen Standortanalyse-Produkten

Stand: 02.08.2026. Die Angaben zu Fremdprodukten stammen aus deren öffentlichen
Webauftritten (Fundstellen am Ende); Preise nennen die Anbieter überwiegend nur auf
Anfrage. Screenshots des eigenen Werkzeugs entstehen aus dem laufenden Programm;
von den Bezahlprodukten können hier keine Screenshots gezeigt werden — sie liegen
hinter Login bzw. Lizenz.

---

## 1 · Funktionsliste Standort-Datenterminal

### Erkundung — WO suchen?

| Funktion | Datengrundlage |
|---|---|
| Übersichtsebene Einwohner, ganz Bayern (10-km-Gitter) und ganze Städte (1-km-Gitter), feste Farbklassen, Zellklick mit „Hier analysieren" | Zensus 2022 |
| Flächen-Scan: Einwohner je Gastronomiebetrieb im 300-m-Umfeld, je 100-m-Zelle, mit Sonderklasse „kein Betrieb im Umfeld" | Zensus 2022 + OSM |
| Grundkarten: OpenStreetMap, amtliche basemap.de (farbig/grau), in Bayern Luftbild und Flurstücke (ALKIS) | BKG, LDBV |
| Deckkraftregler für alle aufgesetzten Ebenen | — |

### Punktanalyse — WIE ist es hier? (ein Klick, 19 Blöcke)

| Block | Inhalt |
|---|---|
| Standort | Adresse, Gemeinde, AGS, Bundesland |
| Bevölkerung | Einwohner, Altersgruppen, Haushaltsgröße, Ausländeranteil — 100-m-genau |
| Wohnen | Nettokaltmiete, Leerstandsquote, Eigentümerquote, Baualter, Neubauhinweis |
| Verfügbares Einkommen (3b) | VGRdL-Kreiswert mit Land/Bund und Verlauf — die ehrliche Kaufkraft-Näherung |
| Kreisprofil (3c) | Übernachtungen je EW, **Erwerbstätige am Arbeitsort je 1.000 EW** (Tagesbevölkerung), Beschäftigten-/Arbeitslosenquote, Bevölkerungsbewegung — Regionalatlas, je eigenes Datenjahr |
| Pendler (3d) | Ein-/Auspendler, Saldo, Quoten, Binnenpendler der Gemeinde + Top-Herkünfte/-Ziele mit km (Pendlerrechnung der Länder) |
| Gastronomie | Betriebe nach Typ, Küche, Kette/Einzelbetrieb, Wettbewerbsdichte nach Entfernung (150/300/600/900 m), nächster Betrieb, **Branchenprofil** (was zählt als direkter Wettbewerb), **Öffnungszeiten-Lücken** (sonntags/nach 22 Uhr — konservativ gezählte Mindestzahlen), **Snack-Verkauf** als eigene Kategorie (Bäckerei/Confiserie/Kaffeeausschank), Nachtclubs und Saftbars |
| Erreichbarkeit zu Fuß | echtes Wegenetz statt Luftlinie: erreichbare Fläche, Erschließungsgrad, Umwegfaktor, Gehstrecke je Betrieb |
| Rad-Liefergebiet (4d) | erreichbare Einwohner in 5–15 min Radstrecke (Radprofil, 15 km/h als benannter gewählter Wert) |
| Gastro-Dynamik (4e) | Jahresreihe der Gastro-Objekte aus der OSM-Historie (ohsome): wächst die Lage oder stirbt sie? — mit benannter Kartierungs-Grenze |
| Wettbewerbs-Abgleich (4f) | Overture Places (Meta/Foursquare/Filiallisten, offene Lizenz) gegen OSM: in beiden / nur Overture / kombinierte Zahl, eigene Karten-Pins — am MIRA: OSM 3, Overture 15 |
| Systemgastronomie & Marken | Ketten je Marke mit Anzahl und Entfernung, Kettenanteil, **Gebietsschutz-Check für die eigene Marke (5/10/20 km)** |
| Umfeld | Frequenzbringer in 9 Kategorien (Einkauf, Bildung, Gesundheit, Büro, …) |
| Klima (5b) | DWD-Normalwerte 1991–2020 der nächsten Station: Sommertage (mit Monatsbalken), Heiße Tage, Sonne, Niederschlag, Temperatur — für Außengastronomie |
| Verkehr/ÖPNV | Haltestellen, Linien, GTFS-Abfahrten je Stunde eines konkreten Tages, Mittagsfenster 11–14, Abendfenster 17–22, Nachtfenster 22–1 Uhr |
| Gemessene Frequenz | Radzählstellen München (Jahressumme + **Jahresgang aus Tages-Rohdaten**: Monatsmittel, Messtage, Spitzentag), Kfz-Verkehrsstärke DTV (BAYSIS, ganz Bayern) |
| Planungsrecht | Hochwassergefahrenflächen HQhäufig/HQ100/HQextrem (Bayern), Bebauungsplan-Umgriffe (München) |
| Straßenlärm (6f) | LDEN/LNight in dB(A) am Punkt aus der EU-Umgebungslärmkartierung (LfU Bayern) — mit Kartierungsjahr und ehrlicher „nicht kartiert ≠ leise“-Grenze |
| Bodenrichtwerte | Kartenebene + Klickabfrage in 7 Bundesländern, Portallinks für alle |
| Leerstände | OSM-Leerstand als Untergrenze mit Adresse; Klick springt in der Karte zum Objekt |

### Entscheidung — WELCHER Kandidat?

| Funktion | Besonderheit |
|---|---|
| Vergleichstabelle: 54 Kennzahlen in 6 schaltbaren Gruppen | jede berechnete Spalte ist als „berechnet" beschriftet |
| Gewichtetes Ranking | Punktzahl allein aus eigenen Gewichten, jeder Beitrag offen |
| Eigene Note (1–5) und Notiz je Punkt | einzige Wertung im Werkzeug — und sie kommt vom Nutzer |
| Verlauf & „Neu prüfen" | Quellen erneut abfragen; eröffnete/verschwundene Betriebe namentlich; ab drei Ständen Verlaufslinien im Bericht |
| Pflegelauf | „alle N neu prüfen" mit Kostenansage, Zusammenfassung je Punkt |
| Standortbericht | druckbare Seite je Punkt mit Lagekarte, PDF über Browserdruck |
| **Duell-Bericht A gegen B** | zwei Kandidaten Spalte an Spalte, beide Lagekarten, Differenzspalte als Fakt statt Wertung |
| Adressliste | bis 25 Makler-Adressen auf einmal geocodieren und als Punkte merken (Nominatim-Limit gewahrt) |
| Umsatzschätzung | Spanne, offene Formel, Prüfstein gegen echten Umsatz, **Franchise-Kostenprobe** (Gebühr, Werbeabgabe, Wareneinsatz, Personal → Verbleib vor Miete), **Mietprobe** gegen das konkrete Exposé mit **Wohnmiete-Lage-Anker** (Zensus), **Sensitivität** (exakte Spannen-Zerlegung, Effekt eines übersehenen Wettbewerbers) |
| Export & Datensicherung | JSON und CSV je Punkt, CSV des Vergleichs; alle Punkte samt Verlauf als Sicherungsdatei mit Wiedereinspielen |

### Betrieb

Läuft komplett lokal (localhost, SQLite), kein Konto, keine Cloud. Cache mit
Kachel-Logik schont die freien Dienste; jeder echte Abruf steht im Protokoll.
Geprüft durch 389 automatische Tests, 53 Live-Routenprüfungen, 36 Browser-Checks
und 9 Abnahmekriterien.

---

## 2 · Gegenüberstellung mit den Premium-Produkten

Verglichen werden die vier Produktkategorien, die bei professioneller
Standortsuche in Deutschland typischerweise eingekauft werden.

| | **Standort-Datenterminal** (dieses Werkzeug) | **hystreet.com** | **GfK/NIQ RegioGraph** | **Nexiga / WIGeoGIS** (Location-Intelligence-Suiten) |
|---|---|---|---|---|
| **Kosten** | 0 € (offene Daten, lokal) | Portalzugang teils frei, **gewerbliche Nutzung nur mit kommerzieller Lizenz** (Preis auf Anfrage) | Kauf-/Jahreslizenzen im Tausender-Bereich (Listenpreise im GfK-Webshop; Zusatzdaten z. B. Länderkarten ab 5.000 €) | Projekt-/Abopreise auf Anfrage, typisch vier- bis fünfstellig pro Jahr |
| **Betrieb / Datenhoheit** | lokal auf dem eigenen Rechner, keine Cloud, kein Konto | Cloud-Portal | Desktop-Software mit Datenpaketen | Cloud/WebGIS |
| **Einwohner kleinräumig** | ✅ amtlicher Zensus 2022 im 100-m-Gitter (Stichtag 15.05.2022, ausgewiesen) | — | ✅ eigene Mikrodaten, jährlich fortgeschrieben | ✅ eigene Mikrodaten (z. T. 100-m-Raster) |
| **Kaufkraft** | ❌ kleinräumig bewusst nicht — es gibt keine seriöse freie Quelle; Ersatz: Nettokaltmiete (100 m) + verfügbares Einkommen (VGRdL, Kreis) | — | ✅ Kernprodukt (NIQ-Kaufkraft) | ✅ enthalten |
| **Tagesbevölkerung / Pendler** | ✅ amtlich: Pendlerrechnung je Gemeinde (Ein-/Auspendler, Saldo, Top-Verflechtungen) + Erwerbstätige am Arbeitsort je Kreis | — | teils (Zusatzdaten) | ✅ meist modelliert |
| **Klima (Außengastronomie)** | ✅ DWD-Normalwerte 1991–2020 der nächsten Station, mit Stationsangabe | — | — | teils |
| **Passantenfrequenz** | ❌ nicht flächig; Ersatz: GTFS-Abfahrten je Stunde, Radzählstellen, Kfz-DTV — alles gemessen; hystreet wird verlinkt, nicht abgegriffen | ✅ **gemessen** (300+ Laserscanner, 24/7) — aber nur an ausgerüsteten Einkaufsstraßen | teils als Zusatzdaten | teils, meist modelliert (Mobilfunk-/Mobilitätsdaten) |
| **Wettbewerb / POI** | ✅ OpenStreetMap **live** (tagesaktuell, als Untergrenze ausgewiesen), nach Typ/Küche/Kette | — | POI-Pakete zukaufbar | ✅ POI-Datenbanken enthalten |
| **Gehzeit statt Luftlinie** | ✅ eigenes Fußwegenetz, Erschließungsgrad, Umwegfaktor | — | eingeschränkt | ✅ Fahr-/Gehzeitzonen |
| **Franchise: Gebietsschutz-Check eigene Marke** | ✅ brand-/Namenssuche bis 20 km, Treffer auf der Karte | — | über POI-Daten möglich (Eigenarbeit) | über POI-Daten möglich (Projektleistung) |
| **Umsatzprognose** | bewusst nur **Vergleichsmaß** mit offener Formel + Prüfstein gegen echten Umsatz + Franchise-Kostenprobe | — | Potenzialrechnungen | ✅ Umsatzprognose-Modelle (Methodik proprietär) |
| **Verlauf / Monitoring** | ✅ „Neu prüfen" mit namentlicher Veränderungsliste | ✅ Zeitreihen an den Messpunkten | — | teils |
| **Bericht / Export** | ✅ Druckbericht, CSV, JSON | Portal-Exports | ✅ Karten/Berichte | ✅ Berichte |
| **Quellentransparenz** | ✅ **jede Zahl** mit Quelle, Stand, Lizenz; Protokoll aller Abrufe; bekannte Grenzen stehen in der Oberfläche | Methodik dokumentiert | Methodik teils proprietär | Methodik teils proprietär |
| **Aktualität Wettbewerb** | live bei jedem Abruf | — | Datenstand der gekauften Pakete | Datenstand der Pakete |

### Ehrliche Einordnung

Die Premium-Produkte haben drei Dinge, die es frei **nicht** gibt — und die dieses
Werkzeug deshalb bewusst nicht nachbaut, statt sie zu simulieren:

1. **Gemessene Passantenfrequenz** (hystreet) — der wichtigste fehlende Wert für
   eine 1a-Lage. Kein freier Datensatz misst das flächig.
2. **Kaufkraft** (GfK/Nexiga) — kleinräumige Kaufkraft ist ein kommerzielles
   Datenprodukt; jede „freie" Zahl dazu wäre erfunden.
3. **Modellierte Umsatzprognosen und Beratung** — mit dem Risiko, dass die
   Methodik eine Blackbox ist. Dieses Werkzeug rechnet stattdessen offen und
   verlangt einen Prüfstein.

Umgekehrt hat das Werkzeug vier Dinge, die die Suiten so nicht bieten: den
**tagesaktuellen** Wettbewerbsbestand (statt gekaufter POI-Stände), volle
**Datenhoheit** ohne Cloud und Konto, **komplette Quellentransparenz** bis zum
einzelnen Abruf — und den Preis 0 €.

### Empfehlung für die Praxis

Mit dem Datenterminal **suchen und vorauswählen** (Erkundung → Scan → Punktanalyse
→ Vergleich), und Premiumdaten **punktuell nur für die Endkandidaten** einkaufen:
eine hystreet-Auswertung, wenn ein Kandidat an einer gemessenen Straße liegt, und
Kaufkraft-/Frequenzdaten erst, wenn Bank oder Franchisegeber sie verlangen. So
zahlt man für zwei Standorte statt für eine Jahreslizenz.

---

### Fundstellen (abgerufen 02.08.2026)

- hystreet: Fallstudie railslove.com/case-studies/hystreet (300+ Laserscanner,
  Echtzeitportal), llasm.de/123d1795495; Nutzungsbedingungen des Portals
  (gewerbliche Nutzung nur mit kommerzieller Lizenz — bei Projektstart geprüft)
- GfK/NIQ RegioGraph: shop.gfk-geomarketing.de (Editionen Analysis/Planning/
  Strategy, Jahres-Abos, Zusatzdaten ab 5.000 €)
- WIGeoGIS: wigeogis.com (WebGIS-Standortanalyse, Umsatzprognosen,
  100-m-Marktraster)
- Nexiga: nexiga.com (Standortanalyse, Mobilitäts-/Frequenzdaten,
  Fahrzeit-Einzugsgebiete)
