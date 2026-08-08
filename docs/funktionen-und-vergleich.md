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

### Punktanalyse — WIE ist es hier? (ein Klick, 27 Blöcke)

| Block | Inhalt |
|---|---|
| Standort | Adresse, Gemeinde, AGS, Bundesland |
| **Gesamt-Score (1b)** | ein Punktwert 0–100 aus 8 Kennzahlen — Anker als gewählte Werte an jeder Zeile ausgewiesen, Gewichte per Schieberegler (lokal gespeichert), fehlende Kennzahlen fallen sichtbar heraus statt still als 0 zu zählen |
| Bevölkerung | Einwohner, Altersgruppen, Haushaltsgröße, Ausländeranteil — 100-m-genau |
| **Viertel-Steckbrief (2b)** | Indikatorenatlas München: Jahresreihen des Stadtbezirks bis 2025 gegen den Stadtwert — Einpersonenhaushalte (54,4 % stadtweit!), junge Single-Haushalte, Durchschnittsalter, 65+, Dichte, Wohndauer, Arbeitslosen-Anteil, je mit ~5-Jahres-Trend |
| Wohnen | Nettokaltmiete, Leerstandsquote, Eigentümerquote, Baualter, Neubauhinweis |
| Verfügbares Einkommen (3b) | VGRdL-Kreiswert mit Land/Bund und Verlauf — die ehrliche Kaufkraft-Näherung |
| Kreisprofil (3c) | Übernachtungen je EW, **Erwerbstätige am Arbeitsort je 1.000 EW** (Tagesbevölkerung), Beschäftigten-/Arbeitslosenquote, Bevölkerungsbewegung, **Wirtschaftskraft (BIP je Einwohner/Erwerbstätigen mit Vorjahresveränderung)** — Regionalatlas, je eigenes Datenjahr |
| **Gemeindewerte (3e, bundesweit)** | über das Regionaldatenbank-Opt-in: **SV-Beschäftigte am Arbeitsort der Gemeinde** (der Mittagsgeschäft-Indikator, Stichtag 30.06., mit 5-Jahres-Trend), Gästeübernachtungen und Arbeitslose der Gemeinde — endlich feiner als der Kreis, gerade im Umland |
| Pendler (3d) | Ein-/Auspendler, Saldo, Quoten, Binnenpendler der Gemeinde + Top-Herkünfte/-Ziele mit km (Pendlerrechnung der Länder) |
| Gastronomie | Betriebe nach Typ, Küche, Kette/Einzelbetrieb, Wettbewerbsdichte nach Entfernung (150/300/600/900 m), nächster Betrieb, **Branchenprofil** (was zählt als direkter Wettbewerb), **Öffnungszeiten-Lücken** (sonntags/nach 22 Uhr — konservativ gezählte Mindestzahlen), **Snack-Verkauf** als eigene Kategorie (Bäckerei/Confiserie/Kaffeeausschank), Nachtclubs und Saftbars |
| Erreichbarkeit zu Fuß | echtes Wegenetz statt Luftlinie: erreichbare Fläche, Erschließungsgrad, Umwegfaktor, Gehstrecke je Betrieb |
| Rad-Liefergebiet (4d) | erreichbare Einwohner in 5–15 min Radstrecke (Radprofil, 15 km/h als benannter gewählter Wert) |
| Gastro-Dynamik (4e) | Jahresreihe der Gastro-Objekte aus der OSM-Historie (ohsome): wächst die Lage oder stirbt sie? — mit benannter Kartierungs-Grenze |
| Wettbewerbs-Abgleich (4f) | Overture Places (Meta/Foursquare/Filiallisten, offene Lizenz) gegen OSM: in beiden / nur Overture / kombinierte Zahl, eigene Karten-Pins — am MIRA: OSM 3, Overture 15 |
| Systemgastronomie & Marken | Ketten je Marke mit Anzahl und Entfernung, Kettenanteil, **Gebietsschutz-Check für die eigene Marke (5/10/20 km)** |
| Umfeld | Frequenzbringer in 9 Kategorien (Einkauf, Bildung, Gesundheit, Büro, …) |
| Klima (5b) | DWD-Normalwerte 1991–2020 der nächsten Station: Sommertage (mit Monatsbalken), Heiße Tage, Sonne, Niederschlag, Temperatur — für Außengastronomie |
| **Städtische Märkte (5c)** | 54 Münchner Märkte mit Rubrik und Öffnungszeiten; **80 Hamburger Wochenmärkte** (ohne Öffnungszeiten — der Datensatz führt keine, das steht dabei); Reichweite 2 km, Karten-Pins |
| **Kurzzeitvermietung (5d)** | Inside Airbnb (CC BY 4.0): Inserate im Umkreis mit Zimmertyp, Median-Preis und Bewertungs-Aktivität der letzten 12 Monate — das kleinräumige Touristen-Signal, das die amtliche Kreis-Übernachtungszahl nicht liefert; Positionsversatz (~150 m) ehrlich benannt (München, Berlin) |
| **Amtliche Gastro-Anker (3e)** | Regionaldatenbank (Opt-in, kostenlose Kennung): Umsatz je USt-Pflichtigem im Gastgewerbe des Kreises (Zeitreihe ab 2009, Prüfstein für die eigene Umsatzschätzung) und Gewerbean-/-abmeldungen mit Saldo — inkl. Unternehmenssitz-Warnung |
| **Tourismus-Saisonalität (3f)** | Monatszahlen des Statistischen Amts München seit 2006: letzte 12 Monate mit Vorjahresvergleich, Auslandsanteil, Aufenthaltsdauer und Saisonkurve (Juli 130, Januar 59 — indexiert auf den Jahresdurchschnitt); bundesweit gibt es Monatswerte je Kreis nicht offen, der Block sagt das |
| **Messe-Kalender (5e)** | Veranstaltungen der Messe München seit 2018 mit Besucherzahlen (bauma 2025: 605.974): laufende/kommende Termine, Jahresbilanz, größte Veranstaltungen, Entfernung zum nächsten Gelände — planbare Frequenzspitzen, die über Hotels und die U2 ankommen |
| **Sicherheitslage (3g, bundesweit)** | PKS-Kreistabelle des BKA: Straftaten insgesamt, Straßen-/Gewaltkriminalität, Raub gegen Geschäfte, Sachbeschädigung, Rauschgift — je mit Häufigkeitszahl, Median und **Rang unter 400 Kreisen** (München: 148., Köln: weit vorn), Aufklärungsquote; BKA-Vergleichbarkeits-Hinweis und Lizenzgrenze am Block |
| **Wahlergebnis (3h, bundesweit)** | Bundestagswahl 2025 auf Wahlkreisebene (Zweitstimmen, Beteiligung, Differenz zur Vorwahl); Großstädte über mehrere Wahlkreise werden summiert und genau so beschriftet — mit ausdrücklicher „Struktur-Marker, kein Kundenprofil"-Warnung |
| **Bau-Pipeline (3e, bundesweit)** | über das Regionaldatenbank-Opt-in: genehmigte und fertiggestellte Wohnungen je Gemeinde (München 2024: 7.118/5.915) samt berechneter Pipeline — die kommende Nachfrage, die der eingefrorene Zensus-Neubauhinweis nicht mehr sieht |
| **Luftqualität (5f, bundesweit)** | Luftqualitätsindex der nächsten Messstation (UBA/Länder, stündlich): NO₂/PM₁₀/PM₂,₅ mit Teilindex, Stationsname und Entfernung — der gemessene Begleiter zum Lärmblock für Außengastronomie |
| **ÖPNV-Einzugsgebiet (6h)** | Runden-Router über den lokal importierten GTFS-Fahrplan: erreichbare Halte in 15–45 min (max. 2 Umstiege, Referenz-Dienstag 12:00) samt Einwohner-Näherung und Karten-Ebene — am Sendlinger Tor: 2.144 Halte/1,27 Mio. EW in 30 min, fernster Halt Garching-Forschungszentrum (deckt sich mit der echten U6-Fahrzeit) |
| **Sonne auf der Terrasse (5g)** | Direkte Sonnenstunden am Punkt zu drei Stichtagen, gerechnet aus Sonnenstand (Astronomie) und OSM-Gebäudehöhen im 150-m-Umkreis — inklusive Abendsonne ab 17 Uhr und Sonnenfenstern. Die Höhenabdeckung steht dabei, weil das Ergebnis ohne sie eine Obergrenze ist. Enge Altstadtlage: 0,7 h Wintersonne gegen 6,2 h am offenen Platz. Wird sonst durch tagelanges eigenes Beobachten ermittelt |
| **Gemessene Passantenfrequenz (6i)** | Echter Tagesgang statt Näherung — wann sind die Leute wirklich da? Sieben Zählstellen in Dortmund, Würzburg und Augsburg, deren Städte die hystreet-Messung unter offener Lizenz weitergeben. Dortmund Westenhellweg: Spitze 16 Uhr mit 2.939/h, Abendanteil 24 %; Würzburg Schönbornstraße nur 7 % — die Straße leert sich abends |
| **Baurecht am Punkt (6j)** | Die Frage, die jede Umsatzprognose schlägt: Art der baulichen Nutzung nach BauNVO mit Gastronomie-Einordnung (Hamburg, Freiburg), sonst Planumring mit PDF (Berlin) oder die Aussage „kein Plan → § 34 BauGB". Dazu Sanierungsgebiete (§§ 144/145 BauGB: Nutzungsänderung genehmigungspflichtig) und Denkmalschutz |
| **Gastro-Bestand der IHK (4g)** | Für Berlin der amtliche Gegenwert zur OSM-Zählung: jeder IHK-Mitgliedsbetrieb mit Koordinate, Betriebsalter und Beschäftigtenklasse (CC0, monatlich). Zeigt zugleich, wie vollständig OpenStreetMap das Umfeld erfasst |
| **Steuerlast der Gemeinde (3e)** | Gewerbesteuer- und Grundsteuer-B-Hebesatz je Gemeinde mit Jahresreihe und Abstand zum Bundesschnitt — der erste harte Kostenfaktor, der von Gemeinde zu Gemeinde springt (München 490 %, Garching 330 %) |
| **Feiertage und Schulferien (5h)** | Kontextband ohne Verrechnung: Lage und Länge der Sommerferien neben Tourismuskurve und Studierendenzahl zeigen, ob ein Standort in den Ferien leerläuft oder aufdreht |
| Verkehr/ÖPNV | Haltestellen, Linien, GTFS-Abfahrten je Stunde eines konkreten Tages, Mittagsfenster 11–14, Abendfenster 17–22, Nachtfenster 22–1 Uhr |
| Gemessene Frequenz | Radzählstellen München (Jahressumme + **Jahresgang aus Tages-Rohdaten**) und **Hamburg** (Zählsäulen mit Jahressumme und Vortageswert), Kfz-Verkehrsstärke DTV: BAYSIS in Bayern (9.441 Zählstellen), **BASt-Dauerzählstellen im Rest Deutschlands** (Autobahnen/Bundesstraßen) |
| Planungsrecht | Hochwassergefahrenflächen HQhäufig/HQ100/HQextrem **bundesweit** (Bayern: LfU mit Gewässer/Jährlichkeit, sonst BfG/LAWA), Bebauungsplan-Umgriffe (München) und **Erhaltungssatzungen/Milieuschutz § 172 BauGB mit Satzungs-PDFs** (München und Hamburg) |
| Straßenlärm (6f) | **bundesweit**: LDEN/LNight am Punkt aus der EU-Umgebungslärmkartierung — in Bayern Rasterwerte (LfU), sonst UBA-Pegelklassen samt Schiene/Flug im Ballungsraum; mit Kartierungsjahr und ehrlicher „nicht kartiert ≠ leise“-Grenze |
| **Baustellen (6g)** | München (Servicekarte, Vier-Wochen-Vorschau mit Umrissen, Gehwegsperrungen eigens gezählt), **Hamburg** („Bauweiser“-Steckbriefe der Groß-Maßnahmen) und **Berlin** (VIZ: Baustellen und Sperrungen von verkehrlichem Interesse) |
| Bodenrichtwerte | Kartenebene + Klickabfrage in 7 Bundesländern, Portallinks für alle |
| Leerstände | OSM-Leerstand als Untergrenze mit Adresse; Klick springt in der Karte zum Objekt |
| **Leerstandsmelder (7b, bundesweit)** | zweite, unabhängige Leerstands-Untergrenze: bürgerschaftliche Meldungen (Weltbestand einmal geladen, lokal nach Entfernung gefiltert) mit Meldedatum und Absprung je Meldung — Lizenz ungeklärt, deshalb ausdrücklich nur Hinweischarakter |
| **Handelsregister-Umfeld (7c, bundesweit)** | nach freiwilligem Einmal-Import (OffeneRegister-Datenspende, CC BY 4.0, **Stand 2019**): Gesellschaften mit Sitz in der Standort-PLZ, Registernummern, Gastro-Auszug per Namensheuristik — für Ketten- und Betreiberfragen, klar als historischer Stand beschriftet |

### Entscheidung — WELCHER Kandidat?

| Funktion | Besonderheit |
|---|---|
| Vergleichstabelle: 62 Kennzahlen in 6 schaltbaren Gruppen | jede berechnete Spalte ist als „berechnet" beschriftet |
| Gesamt-Score im Punkt und im Bericht | Anker offen, Gewichte eigene Setzung, Rechnung nachvollziehbar bis zur Teilnote |
| Gewichtetes Ranking | Punktzahl allein aus eigenen Gewichten, jeder Beitrag offen |
| **Standort-Finder** | Top-10-Zellen des Flächen-Scans nach eigenen Gewichten (Chance/Dichte/Cluster als Perzentilränge), nummeriert auf der Karte mit „Hier analysieren" — ehrlich als Scan-Komposit beschriftet, kein Gesamt-Score |
| **Veränderungs-Wächter** | je gemerktem Punkt: OSM-Gastro-Diff gegen den gespeicherten Stand (neu/verschwunden), ohne den Punkt zu überschreiben — Konkurrenzbeobachtung ohne Nebenwirkungen |
| **Kannibalisierungs-Check** | gemeinsame Einwohner zweier gemerkter Punkte über das Zensusgitter, mit Anteil je Umkreis (Sendlinger Tor ↔ Marienplatz: 3.629 EW = 22 %/36 %) |
| **Adress-Autovervollständigung** | beim Tippen über Photon (Nominatim untersagt Autocomplete — die frühere Tippsuche wurde deshalb umgestellt); Enter sucht weiter präzise über Nominatim |
| Eigene Note (1–5) und Notiz je Punkt | einzige Wertung im Werkzeug — und sie kommt vom Nutzer |
| Verlauf & „Neu prüfen" | Quellen erneut abfragen; eröffnete/verschwundene Betriebe namentlich; ab drei Ständen Verlaufslinien im Bericht |
| Pflegelauf | „alle N neu prüfen" mit Kostenansage, Zusammenfassung je Punkt |
| Standortbericht | druckbare Seite je Punkt mit Lagekarte, PDF über Browserdruck |
| **Duell-Bericht A gegen B** | zwei Kandidaten Spalte an Spalte, beide Lagekarten, Differenzspalte als Fakt statt Wertung |
| Adressliste | bis 25 Makler-Adressen auf einmal geocodieren und als Punkte merken (Nominatim-Limit gewahrt) |
| Umsatzschätzung | Spanne, offene Formel, Prüfstein gegen echten Umsatz, **Franchise-Kostenprobe** (Gebühr, Werbeabgabe, Wareneinsatz, Personal → Verbleib vor Miete), **Mietprobe** gegen das konkrete Exposé mit **Wohnmiete-Lage-Anker** (Zensus), **Sensitivität** (exakte Spannen-Zerlegung, Effekt eines übersehenen Wettbewerbers) |
| Export & Datensicherung | JSON und CSV je Punkt, CSV des Vergleichs; alle Punkte samt Verlauf als Sicherungsdatei mit Wiedereinspielen |

### Betrieb

Läuft komplett lokal (localhost, SQLite), kein Konto (einzige Ausnahme: das
freiwillige Regionaldatenbank-Opt-in für Block 3e), keine Cloud. Cache mit
Kachel-Logik schont die freien Dienste; jeder echte Abruf steht im Protokoll.
Geprüft durch 456 automatische Tests, 61 Live-Routenprüfungen, 44 Browser-Checks
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
