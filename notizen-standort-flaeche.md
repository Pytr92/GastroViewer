# Notizen – Standortdaten & Flächensuche

Stand: 31.07.2026. Arbeitsdokument, einfach ergänzen/streichen.

---

## 1. hystreet – Passantenfrequenz

**Abdeckung:** 322 Messpunkte in 112 Städten (Jahresbilanz für 2024). Vollständige Liste
nur über die interaktive Karte auf hystreet.com bzw. in der App – es gibt keine offizielle
PDF-Liste.

**München:** Kaufingerstraße, Neuhauser Straße (Ost + West getrennt), Schützenstraße.
Weitere Standorte ggf. dazugekommen – auf der Karte prüfen.

**Die 21 Städte, die das Statistische Bundesamt für seinen Index nutzt** (= die mit den
längsten, saubersten Zeitreihen):
Köln, Frankfurt/M., München, Hamburg, Berlin, Stuttgart, Wiesbaden, Rostock, Hannover,
Düsseldorf, Mainz, Saarbrücken, Dresden, Kiel, Erfurt, Bremen, Halle (Saale), Leipzig,
Dortmund, Essen, Nürnberg.

**WICHTIG – Lizenz:** Im kostenfreien Modell ist die **gewerbliche Nutzung untersagt**
(so die Stadt Münster in ihrem Open-Data-Portal). Für die Standortentscheidung eines
Franchise-Betriebs also vorher Tarif klären. Preise stehen nicht öffentlich → direkt
anfragen. hystreet ist Datenbankhersteller nach § 87a UrhG, Quellenangabe Pflicht.

**API:** REST, JSON. Doku unter hystreet.com/apidocs bzw. hystreet.com/developer.
Konto erforderlich. Standorte + Messwerte abrufbar, stündliche Auflösung.

**Gratis-Umweg:** Einzelne Städte spiegeln ihre hystreet-Daten in kommunalen Open-Data-
Portalen (z.B. Bonn, Münster, Rendsburg). Erst im Open-Data-Portal der Zielstadt suchen.

---

## 2. Weitere Datenquellen (alle kostenlos)

| Was | Wo | Wofür |
|---|---|---|
| Zensus 2022, 100m-Raster | zensus2022.de | Wer wohnt im Umkreis: Alter, Haushaltsgröße, Miete |
| Zensusatlas | zensusatlas im Browser | Schnellcheck ohne GIS |
| Pendleratlas | statistik.arbeitsagentur.de | Einpendler = Mittagsgeschäft |
| Beschäftigte am Arbeitsort | BA-Statistik, Gemeindedaten | Bürodichte |
| OpenStreetMap / Overpass | overpass-turbo.eu | Konkurrenzdichte |
| Google Maps Stoßzeiten | Maps, je Wettbewerber | Tagesverlauf der Konkurrenz |
| Lieferando | lieferando.de | Wer liefert schon, welche Preise |
| Kaufkraft (MB-Research) | über die IHK anfragen | IHKs geben PLZ-Auszüge oft gratis raus |
| Einzelhandelsgutachten | Ratsinformationssystem der Stadt | enthält oft gekaufte Kaufkraftdaten |

Overpass-Abfrage Konkurrenz (Koordinaten tauschen):

```
[out:json][timeout:25];
(
  nwr["amenity"~"fast_food|restaurant"](around:800,48.1374,11.5755);
);
out center;
```

---

## 3. Immobilien – wo suchen

### 3.1 Franchise zuerst

- Expansionsabteilung / Expansionsmanager des Franchisegebers kontaktieren, **bevor**
  eigene Suche startet. Die haben Standortprofil, Maklerkontakte, teils eigene Objekte.
- **Standortprofil schriftlich anfordern**: Mindestfrequenz, qm, Schaufensterbreite,
  Abluftanforderung, max. Miete, Einzugsgebiet. Ohne das sucht man ins Blaue.
- **Reservierungsvereinbarung / Gebietsschutz** vor der Suche abschließen – sonst sucht
  parallel evtl. ein anderer Interessent im selben Gebiet.
- Standort vom Franchisegeber freigeben lassen, **bevor** der Mietvertrag unterschrieben
  wird. Der endgültige Franchisevertrag wird meist erst nach Standortfestlegung geschlossen.

### 3.2 Übernahme (oft der schnellste Weg – Genehmigungen sind schon da)

- nexxt-change.org – kostenlos, ~7.000 Inserate, eigenes Kaufgesuch möglich (Chiffre)
- die-gastgeber.info – DEHOGA-Börse
- ahgzimmo.de – Fachzeitung, kostenloser Suchagent
- gastro-pacht.de, pachtgaststaette.de, pachtnetzwerk.immo
- kleinanzeigen.de – Ablösedeals, Suchbegriff „Imbiss Ablöse", „Gastro Übernahme"

### 3.3 Brauerei-Pachtbörsen

| Brauerei | Börse |
|---|---|
| Paulaner Gruppe | pbg-pachtboerse.de |
| Krombacher | pachtvermittlung.krombacher.de |
| Bitburger Braugruppe | dasgastroportal.de/objektboerse |
| Veltins | veltins-gastroportal.de |
| Warsteiner | warsteiner-gruppe.de → Gastroboerse |
| Fürstenberg | fuerstenberg.de/service/pachtboerse |
| Ayinger (Region MUC) | ayinger.de → Pachtbörse |
| Kühbach (Region MUC) | brauereikuehbach.de/pachtobjekte |
| Radeberger | keine Börse → Außendienst anrufen |

Achtung Bierbezugsvertrag: Laufzeit + Mindestabnahme in hl/Jahr prüfen. Bei Fast Food
ohne Bierfokus oft verhandelbar oder unnötig. Getränkefachgroßhandel-Außendienst weiß
trotzdem als Erster von freiwerdenden Objekten → anrufen, auch ohne Bezugsvertrag.

### 3.4 Makler (Suchprofil hinterlegen, nicht nur Exposés abwarten)

- Comfort, Lührmann, Brockhoff, Engel & Völkers Commercial, BNP Paribas RE, JLL Retail
- regionale Gastro-Spezialmakler der Zielstadt googeln
- Was ins Suchprofil gehört: Konzept, Marke, qm, Zielmiete, Wunschlagen, Bonität,
  Zeitpunkt, Franchisegeber als Referenz

### 3.5 Center & Bahnhöfe (starke Frequenz, Food-Courts)

- ECE: leasing@ece.com, Tel. 040 60606-7000 – courtagefrei, zentral für alle Center
- ECE temporär/Pop-up: mallmarketing.ece.com (1–3 Monate)
- MEC (Fachmarktzentren): mec-cm.com
- DB InfraGO, Personenbahnhöfe: Feedback@bahnhof.de – ca. 600 Empfangsgebäude

### 3.6 Kommune

- Wirtschaftsförderung der Zielstadt anrufen: Leerstandskataster? Ansiedlungsförderung?
- LeAn (Leerstand & Ansiedlung) – Matching-Tool, in vielen Städten im Einsatz
- leerstandsmelder.de

### 3.7 Direktakquise

Zielstraßen ablaufen, Leerstände fotografieren, Eigentümer über Hausverwaltungsschild
oder Nachbargeschäfte ermitteln, kurzes Anschreiben mit Konzept-Onepager + Marke.

---

## 4. Benachrichtigungen – Setup

### 4.1 Ohne Programmieren (zuerst machen, 1 Stunde Arbeit)

1. Eigene Mailadresse nur für Objekte anlegen, z.B. objekte@meinedomain.de
2. Suchagenten anlegen auf: ImmoScout24 Gewerbe, Immowelt, Kleinanzeigen, ahgzimmo,
   gastro-pacht, nexxt-change, jede relevante Brauereibörse
3. **ImmoScout24-App installieren und Push aktivieren** – Push kommt schneller als die
   E-Mail-Zusammenfassung. Der Suchauftrag muss in der App angelegt/aktiviert sein.
4. Alle Portal-Mails an diese eine Adresse, dann Filterregel → alles in einen Ordner

### 4.2 Mit Claude Code gebaut (der saubere Weg)

**Architektur: E-Mail-Relay statt Scraping.**

```
Portale (Suchagenten) → Sammel-Postfach → IMAP-Poller (alle 60s)
   → Parser (Titel, Preis, qm, Ort, Link) → SQLite (Dedup)
   → Push an Telegram / ntfy.sh
```

Warum so: Du verarbeitest Mails, die du legitim bekommst. Kein Bot-Schutz, keine
Captchas, keine AGB-Verletzung, läuft stabil. Aufwand: ein Wochenende.

Bausteine:

- `imap-tools` oder `imaplib` (Python) – Postfach auslesen
- `sqlite3` – Dedup über Objekt-ID/URL
- Telegram Bot API (BotFather) oder **ntfy.sh** (kostenlos, kein Account nötig)
- `cron` auf einem 5-€-VPS oder Docker auf dem Raspberry Pi
- optional: Overpass + Zensus-Lookup, der jedem Treffer direkt
  „X Einwohner in 500m, Y Wettbewerber in 800m" anhängt → das ist der eigentliche Mehrwert

Ergänzend problemlos abrufbar:

- Brauereibörsen / kleine Portale: HTML alle 15–30 Min. höflich pollen, robots.txt
  beachten, User-Agent setzen. Kein Captcha im Weg.
- nexxt-change: hat Suchagent, aber HTML-Poll als Backup ok

### 4.3 Was NICHT bauen

ImmoScout24 und Immowelt haben aktiven Bot-Schutz (Captcha, DataDome). Die kursierenden
GitHub-Projekte (flathunter, immopushr, diverse „Wohnungsbots") lösen das über
Captcha-Dienste wie 2captcha oder DataDome-Bypass. Das **umgeht technische
Schutzmaßnahmen** – rechtlich der kritischste Punkt beim Scraping, unabhängig davon, wie
viele Daten man zieht. Außerdem brechen die Projekte ständig. Finger weg, der
E-Mail-Weg ist schneller gebaut und läuft zuverlässiger.

(Zur Einordnung: Der BGH hat 2011 im Fall „Automobil-Onlinebörse" entschieden, dass
einzelne, eng gefasste Suchabfragen keine Übernahme „wesentlicher Teile" einer Datenbank
sind – ein Grund war aber, dass die Börse ihre Daten ungeschützt zugänglich gemacht
hatte. Sobald ein Schutzmechanismus da ist und umgangen wird, ist die Lage anders.
Keine Rechtsberatung – im Zweifel Anwalt fragen.)

### 4.4 No-Code-Alternative

n8n (self-hosted, kostenlos) oder Make.com: IMAP-Trigger → Filter → Telegram.
Gleiches Ergebnis ohne Code, wenn es schnell gehen soll.

---

## 5. Realitätscheck zur Geschwindigkeit

Der Bot bringt Minuten Vorsprung auf dem öffentlichen Markt. Die wirklich guten
Gastroflächen tauchen dort nie auf – die gehen über Makler, Brauerei-Außendienst,
Centermanagement und Mundpropaganda weg, oft Wochen vorher.

→ Verhältnis: 20 % Zeit in den Bot, 80 % in Telefonate mit Maklern, Getränkegroßhandel,
Wirtschaftsförderung und den Expansionsmanager des Franchisegebers.

---

## 6. Vor Vertragsunterschrift prüfen

- [ ] Standort vom Franchisegeber freigegeben (schriftlich)
- [ ] Bauvoranfrage: Nutzungsänderung zu Gastronomie genehmigungsfähig?
- [ ] Abluft über Dach möglich? (Vollküche zwingend, oft der Dealbreaker)
- [ ] Fettabscheider vorhanden/nachrüstbar?
- [ ] Bei Eigentumswohnanlage: Teilungserklärung – steht dort nur „Laden"?
- [ ] Stellplatznachweis / Ablösebetrag der Kommune
- [ ] Mietvertrag mit aufschiebender Bedingung „Erteilung aller Genehmigungen"
- [ ] Mietfreie Ausbauzeit verhandelt
- [ ] Konkurrenzschutzklausel
- [ ] Rückbaupflichten begrenzt
- [ ] Miete ≤ ca. 10–14 % vom realistischen Nettoumsatz

---

## 7. Offene Punkte / To-do

- [ ] hystreet: Tarif für gewerbliche Nutzung anfragen, Preis notieren
- [ ] Franchisegeber: Standortprofil + Reservierungsvereinbarung anfordern
- [ ] IHK München: Kaufkraftauszug für Ziel-PLZ anfragen
- [ ] 3 Makler kontaktieren, Suchprofil hinterlegen
- [ ] Wirtschaftsförderung anrufen
- [ ] Sammelpostfach + Suchagenten einrichten
- [ ] Eigene Zählung: Di 12h, Fr 18h, Sa 15h an den Top-2-Kandidaten
