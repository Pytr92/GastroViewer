# Erweiterungen — was das Werkzeug für Deutschland und Österreich noch sinnvoll lernen könnte

Stand: 18. September 2026, nach Version 0.4.0 (Österreich) und dem Knopf-Import.
Drei getrennte Recherchen, jede mit eigenem Dokument:

- [Deutschland: weitere offene Datenquellen](erweiterungen-deutschland.md) — 49 belegte Zeilen in sieben Tabellen, 18 Negativbefunde.
- [Österreich: weitere offene Datenquellen](erweiterungen-oesterreich.md) — fünf Tabellen, vertieft die Recherche aus `oesterreich.md`.
- [Funktionen und Methoden](erweiterungen-funktionen.md) — was Fachliteratur und kommerzielle Werkzeuge kennen und was sich davon mit offenen Daten und lokalem Rechnen nachbauen lässt.

**Eine Einschränkung vorweg, die für alle drei gilt:** Die Rechercheumgebung
erreichte keinen der Datenhosts direkt (Proxy 403 für `.gv.at`, `destatis.de`,
`daten.berlin.de`, `mobidata-bw.de` und alle anderen). Jede Angabe stammt aus
Suchtreffern und Portalseiten, kein Endpunkt wurde selbst aufgerufen. Was
nicht nachgewiesen ist, steht als „unbelegt“. Vor jeder Umsetzung gilt der
Stil des Projekts: erst die Live-Probe (wie `scripts/at_probe.py` für
Österreich), dann der Code gegen die echte Antwort.

## Was jetzt konkret umgesetzt ist

Stand 19. September 2026 (Version 0.6.0). Alles Datenseitige, was sich in
den Probe-Runden 5–7 live belegen ließ, ist gebaut, getestet und in der
Browserprüfung; die Rechen- und Darstellungsfunktionen aus
`erweiterungen-funktionen.md` bleiben bewusst außen vor.

**Deutschland:** Starkregen-Hinweiskarte des BKG im Planungsblock (13
Länder, BY/BW/HE ehrlich als nicht abgedeckt); Verkehrsmengen Berlin
(Verkehrsmodell 2023: Kfz, Lkw, Rad je Abschnitt), Hamburg (temporäre
Zählungen und Verkehrsmengenkarte) und Baden-Württemberg (SVZ 2024 mit
Landes- und Kreisstraßen); Baustellen Stuttgart (Stadt-WFS) und
Baden-Württemberg (MobiData); Radzähler Baden-Württemberg (Eco-Counter,
laufende Woche); Viertel-Steckbrief Hamburg (Regionalstatistik der
Stadtteile, 15 Kennzahlen mit Fünfjahrestrend); Lage-Block mit Hamburger
Parkhäusern (Live-Belegung) und Parkraum sowie Ladesäulen in
Baden-Württemberg (BNetzA-Register über MobiData).

**Österreich:** Gemeindeprofil aus der Gemeindetabelle von Statistik
Austria (Kreisprofil-Block), Gemeindekennziffer am Punkt über den
Gemeindegrenzen-WFS (auch für die Nationalratswahl), Immobilien-
Durchschnittspreise je Bezirk (Häuser, Eigentumswohnungen, Baugrund) als
Block 3i, Wien: Zählbezirks-Steckbrief, Lage-Block (Kurzparkzone, Fußgänger-
und Begegnungszonen, Geschäftsstraßen, Realnutzung, Gebäudeinfo),
Kfz-Dauerzählstellen im Verkehrsmengen-Block, Luftgütemessnetz im
Luft-Block; Salzburg: Bebauungspläne und Planblatt, Altstadtschutzzone,
Märkte mit Öffnungszeiten, Baustellen, Kurzparkzone.

**Nicht gebaut, weil nicht belegbar.** Probe-Runde 8 (19.09.2026) hat die
neun Nachzügler noch einmal auf anderen Wegen gefragt. Ergebnis:

| Quelle | Stand nach Runde 8 |
|---|---|
| ohsome-Qualitäts-API | endgültig nicht nutzbar: Alle drei Metadaten-Pfade liefern die HeiGIT-Webseite, kein JSON |
| Regionaldatenbank (Gastzugang) | GET wird mit 405 abgewiesen, POST mit 401 — der Gastzugang ist zu |
| Köln (CKAN), Frankfurt | Köln 404 in beiden Schreibweisen; Frankfurt hat ein falsch ausgestelltes Zertifikat |
| BNetzA-Ladesäulen direkt | CSV-Download 404, ArcGIS weiter mit Token; die Daten kommen ohnehin über MobiData BW |
| AMS, GISA | Der benutzte API-Pfad ist falsch (`/katalog/api/3/action/…` statt `/katalog/api/action/…`) — Runde 9 fragt nach |
| Straßen.NRW | **antwortet jetzt**: ohne `bbox` kommen Zählstellen als GML; die leere Antwort lag an der bbox-Syntax. Kandidat für einen eigenen Block |
| Autobahn-GmbH | Straßenliste (A1–A99) ist abrufbar, Baustellen je Autobahn auch — es fehlt weiter die Zuordnung Punkt → Autobahn |
| Wiener Radzählungen | unverändert ohne Standortdatei |

Runde 8 hat außerdem die **Nachfolger-Erkennung** für den Kontrakt-Check
belegt — und dabei gleich drei überholte Kennungen gefunden. Runde 9 hat
sie einzeln nachgefragt, bevor etwas umgestellt wurde:

| Fund | Was Runde 9 ergab | Folge |
|---|---|---|
| Wien führt `REALNUT2024OGD`, der Lage-Block nutzte `REALNUT2022OGD` | Der neue Jahrgang hat **andere Feldnamen** (`LEV1..3` statt `NUTZUNG_LEVEL1..3`, Zählgebiet statt Baublock) | umgestellt, beide Schemata werden gelesen — ein blindes Umstellen hätte den Block geleert |
| Statistik Austria führt Gemeindegrenzen bis `20260101`, benutzt wurde `20250101` | gleiche Felder `g_id`/`g_name` | umgestellt |
| Immobilien-Durchschnittspreise für 2025 sind da | — | das Modul nimmt ohnehin das jüngste Jahr; die Fixtures bleiben bei 2024 |
| Straßen.NRW liefert leer mit `bbox` in EPSG:4326 | mit `bbox` in **EPSG:25832** kommen Zählstellen | belegter Kandidat für einen NRW-Verkehrsmengen-Block, noch nicht gebaut |
| AMS und GISA über die CKAN-API | auch der Pfad ohne `3` gibt 404 | bleibt offen |

Berlin, Hamburg, MobiData BW, Salzburg, Stuttgart und der BKG führen
unverändert die Kennungen, die der Code benutzt. Genau dafür läuft der
Kontrakt-Check jetzt monatlich: Diese drei Funde wären sonst erst
aufgefallen, wenn jemand die Zahlen angezweifelt hätte.

## Reihenfolge, die ich vorschlage

Bewertet nach Nutzen für die Standortentscheidung, Aufwand und Belegbarkeit.
Die Nummern verweisen auf die Detailtabellen in den drei Dokumenten.

### Stufe 1 — kleiner Aufwand, sofort spürbar (je S bis M)

1. **Kapazitätsdeckel und Break-even in der Umsatzschätzung** (Funktionen 1): Sitzplätze × Umschlag × Bon als Obergrenze, Fixkosten ÷ Deckungsbeitrag als Mindestgäste je Tag, beides gegen die Nachfragespanne gehalten. Keine neuen Daten, nur Rechnung und Eingabefelder.
2. **Mietbelastungsquote mit Bandbreite** (Funktionen 5): 6–10 % gesund, über 12 % kritisch, „Pacht × 8“ und Umsatzmiete als sichtbare Anker in der Mietprobe.
3. **Szenarien nebeneinander und Tornado-Darstellung** (Funktionen 7): die Sensitivität ist schon exakt, es fehlt nur die Ansicht.
4. **Wiener Radzählungen und Zählbezirks-Steckbrief** (Österreich 3 und 4): Fixtures liegen, Blockformen existieren (Radzählung, Viertel-Steckbrief), es ist reine Anpassungsarbeit.
5. **Starkregen-Hinweiskarte** (Deutschland 8): BKG-WMS bundesweit als zweite Ebene im Planungsblock neben dem Flusshochwasser.
6. **Ladesäulen und Parkhausbelegung** (Deutschland 10): Ladesäulenregister der BNetzA (CC BY 4.0) und ParkAPI-Städte als Mikrolage-Hinweis.

### Stufe 2 — mittlerer Aufwand, schließt echte Lücken (je M)

7. **Gemeindeprofil Österreich** (Österreich 1 und 2): Bevölkerungsstand nach Alter je Gemeinde, Gemeindetabelle der Erwerbsstatistik, AMS-Arbeitslose monatlich — der Ersatz für die deutschen Kreisblöcke, die in Österreich leer bleiben. Größter Hebel für Österreich.
8. **Lohn- und Einkommensteuer je Gemeinde** (Deutschland 1): Kaufkraft unter Kreisebene über den vorhandenen GENESIS-Zugang; Haken: rund vier Jahre Verzug.
9. **Betriebsarten-Profile** (Funktionen 2): Café, Bar, Restaurant, Schnellrestaurant, Lieferküche als benannte Bündel von Radius, Zeitfenster, Wettbewerbsklasse und Score-Ankern.
10. **Tageszeit- und Wochenprofil** (Funktionen 4): geöffnete Wettbewerber je Stunde, GTFS je Stunde, Markt-, Messe- und Ferientage auf einer Achse — alles aus Daten, die das Werkzeug schon hat.
11. **Viertel-Steckbriefe weiterer Großstädte** (Deutschland 4): Köln, Hamburg, Frankfurt, Berlin nach dem Münchner Muster mit gemeinsamem Adapter.
12. **Verkehrsmengen und Baustellen weiterer Länder** (Deutschland 2 und 3): Berlin, NRW, Hamburg, Baden-Württemberg; Autobahn-GmbH-Schnittstelle bundesweit.
13. **Huff-Modell als zweite Marktanteil-Methode** (Funktionen 3): Gehstrecke je Wettbewerber und Zensuszellen als Nachfragepunkte — wählbar neben der bestehenden Rechnung, nicht statt ihrer.
14. **Wiener Lage-Indikatoren** (Österreich 8): Kurzparkzonen, Fußgänger- und Begegnungszonen, Geschäftsstraßen, Gebäudeinfo — je ein Layer über den vorhandenen WFS-Client.
15. **GISA-Gewerbe Österreich** (Österreich 5): monatliche CSV mit Gewerbeberechtigungen plus Adressregister — der Ersatz für das Registerumfeld.
16. **OSM-Vollständigkeitsindikator** (Funktionen 9): Sättigung und Aktualität aus der ohsome-Qualitäts-API als Konfidenzband an den Wettbewerbszahlen.
17. **GeoPackage- und GeoJSON-Export** (Funktionen 10): Umkreise, Isochronen, Wettbewerber, Scan-Zellen für QGIS; GeoPackage ist SQLite, keine neue Abhängigkeit.

### Stufe 3 — groß, aber der größte Hebel (L)

18. **XPlanung-Landesdienste im Baurecht-Block** (Deutschland 5): NRW, Baden-Württemberg, Schleswig-Holstein, Mecklenburg-Vorpommern, Brandenburg. Ob die Dienste Nutzungsart-Flächen liefern oder nur Umringe, ist unbelegt — die Live-Probe entscheidet, ob das ein Block oder nur ein Link wird.
19. **Flächenwidmung außerhalb Wiens** (Österreich 7): sieben Landesdienste mit sieben Formaten.
20. **Stadtweites Screening mit eigenem Kriterienprofil** (Funktionen 6) und **Analog-Kalibrierung mit Bestandsumsätzen** (Funktionen 8).

## Was bewusst nicht kommt

Alle drei Dokumente führen einen Abschnitt „Was bewusst nicht geht“. Die
Kurzfassung: Bewertungsportale und Google-Stoßzeiten (Lizenz, Scraping),
Mobilfunk- und Bewegungsdaten, kommerzielle Kaufkraft- und Milieudaten
(GfK, RegioData, Nexiga), Immobilienportale, aktuelles Handelsregister,
Passantenfrequenz in Österreich (nichts offen), feine Raster mit Attributen
für Österreich (kostenpflichtig), Lohnsteuer je österreichischer Gemeinde
(nur Atlas-Export), Bezirks-Kriminalstatistik Österreich, kalibrierte
Konversionsraten und Punktwert-Prognosen. Das Werkzeug bleibt bei dem, was
es belegen kann.
