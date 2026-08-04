# Abnahmeprotokoll

Erzeugt am 2026-08-04 mit `python scripts/abnahme.py http://127.0.0.1:PORT`
gegen einen laufenden Server mit importiertem GTFS-Fahrplan.

Das Skript prüft jedes Kriterium aus §7 der Spec mit echten Aufrufen.
Kriterium §7.1 vergleicht die angezeigten Zahlen mit einem direkten,
unabhängigen Aufruf von Zensus und Overpass — kein Selbstzeugnis der Anwendung.

Antwortet eine Originalquelle gerade nicht (Overpass liefert unter Last HTTP 504),
wird das Kriterium als **nicht prüfbar** ausgewiesen und der Lauf endet mit Code 2.
Weder ein falscher Alarm noch ein falscher Freispruch.

```
Abnahmeprüfung gegen http://127.0.0.1:8011
========================================================================

Vier Lagetypen laden …
  Großstadt-Innenstadt       0.3s (aus dem Cache)
  Großstadt-Wohnviertel      0.1s (aus dem Cache)
  Kleinstadt                 0.1s (aus dem Cache)
  ländlich                   0.1s (aus dem Cache)
[OK   ] §7.1 Jede Zahl ist auf eine reale API-Antwort zurückführbar
         Zensus direkt abgefragt: 118 Zellen, Summe Einwohner 16370
           Anwendung zeigt: 118 Zellen, 16370 Einwohner
           Overpass `out count` fast_food: 26
           Anwendung zeigt Schnellrestaurants: 26
[OK   ] §7.2 Jeder Block nennt Quelle, Stand und Lizenz
         Beispiel Zensus: Zensus 2022, 100-m-Gitter (Statistische Ämter des Bundes…
           Stand: Stichtag 15.05.2022
           Lizenz: © Statistische Ämter des Bundes und der Länder 2024 · Datenl…
[OK   ] §7.3 Attribution OSM/ODbL und Zensus-Copyright sichtbar
         in der Fußzeile von index.html: OSM/ODbL=ja, Zensus=ja
[OK   ] §7.4 Nominatim ≤ 1 req/s gedrosselt, User-Agent gesetzt
         3 echte Suchen nacheinander (refresh=true): 2.09s (Untergrenze 2,0s)
           Limiter: {'min_interval_s': 1.0, 'acquisitions': 7, 'throttled': 4}
           User-Agent: gastroviewer/0.1.0 (https://github.com/Pytr92/GastroViewer)
[OK   ] §7.5 Cache greift: zweiter Aufruf ohne Outbound-Traffic
         erzwungener Abruf: Zähler 478 → 479 (+1)
           danach derselbe Aufruf: Zähler bleibt bei 479
           ganzer Punkt aus dem Cache: 258 ms, outbound_requests=0
           nachprüfbar unter http://127.0.0.1:8011/api/outbound
[OK   ] §7.6 Ausfall einer Quelle bricht die Seite nicht
         Overpass auf toten Endpunkt gezwungen: osm.ok=False
           Meldung: Verbindung nicht möglich — Dienst nicht erreichbar, DNS- oder Proxy-Pr
           Zensus lief weiter: 118 Zellen, Gemeinde München
[OK   ] §7.7 Vier Lagetypen liefern vollständige Ausgaben
         Großstadt-Innenstadt      118 Zellen   16370.0 Einw.   272 Gastro   26 Halte  München
         Großstadt-Wohnviertel      77 Zellen   13050.0 Einw.    18 Gastro    6 Halte  München
         Kleinstadt                 69 Zellen    1460.0 Einw.    13 Gastro    8 Halte  Greding
         ländlich                    3 Zellen      21.0 Einw.     0 Gastro    0 Halte  Gransee
           ländlicher Fall mit Hinweis statt Leere: ja
[OK   ] §7.8 exceededTransferLimit wird behandelt
         zensus.py prüft auf `is not True` (der Schlüssel fehlt bei false)
           und blättert über resultOffset weiter
           Gegenprobe r=3000: 2006 Zellen geliefert (Limit je Seite: 2000)
[OK   ] §7.9 README erklärt Start, GTFS-Import, Cache leeren, listet Quellen mit Lizenz
         Start=ja · GTFS-Import=ja · Cache leeren=ja · Zensus-Lizenz=ja · OSM-Lizenz=ja · GTFS-Lizenz=ja · Nominatim=ja · hystreet-Auflage=ja

========================================================================
9 von 9 Kriterien erfüllt.
Alle Abnahmekriterien aus §7 erfüllt.
```
