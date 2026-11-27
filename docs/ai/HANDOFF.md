# HANDOFF — GastroViewer

Stand: 27.11.2026 · Version 0.6.1 · Branch `claude/jolly-shannon-g2l13z` · 1020 Tests grün (1 skipped), Überarbeitung nach PLAN.md abgeschlossen.

> Herkunft: Beim Anlegen lag mir nur das Repository vor, nicht der Chatverlauf der alten Session.
> Alles Folgende stammt aus Code, README, `docs/` und Git-Historie. Wer Erkenntnisse aus dem
> Chat kennt, die hier fehlen, ergänzt sie bitte unter „Offene Fragen".

## Zweck
Lokaler Daten-Browser („Standort-Datenterminal") für die Standortsuche eines Fast-Food-Franchise:
Punkt auf der Karte klicken → offene Daten (Zensus, OSM/Overpass, ÖPNV, Planungsrecht, Lärm,
Einkommen, Pendler, Klima …) für Deutschland und teils Österreich (Wien, Salzburg, Linz …).
**Kein Prognose-Tool:** Jede Zahl stammt aus einer realen API-Antwort mit Quelle, Stand, Lizenz.
Die Umsatzschätzung ist bewusst ein eigener, gekennzeichneter Reiter. Kein Deployment, nur `127.0.0.1`.
Maßgeblich: `spec-standort-datenterminal.md` (Anforderungen), `README.md` (Bedienung, Quellen, Lizenzen).

## Stand
- Funktionsumfang groß und stabil: ~55 Quellenmodule, 74+ Endpunkte, Oberfläche > 6 000 Zeilen JS.
- Zwei Prüfrunden („Bestandsaufnahme", 18.09.2026) sind komplett umgesetzt: 12 bestätigte Funde plus
  37 mittlere. Details und Commits: `docs/bestandsaufnahme.md`.
- **Einziger bekannter Rest:** 31 Funde niedriger Schwere im Anhang der Bestandsaufnahme, ungeprüft.
- Datenseitiger Ausbau DE/AT (0.5.0–0.6.1) ist gebaut. Weitere Ideen: `docs/erweiterungen*.md`.
- Laufender Betrieb ohne eigene Prüfroutine in dieser Umgebung: Live-Dienste sind hier nicht erreichbar.

## Architektur (nur, was man nicht sofort sieht)
- `gastroviewer/api.py` baut die FastAPI-App; Endpunkte liegen als Router je Thema in `routen/`.
  `service.py` (`PointService`) orchestriert alle Blöcke je Punkt; `sources/*.py` je ein Loader.
- Jeder Loader liefert ein `SourceResult` (`sources/base.py`): `ok`, `data`, `provenance`
  (Quelle/Stand/Lizenz/Endpunkt), `error` mit konkreter Ursache (`SourceError.kind`). Ein Quellenausfall
  darf die Seite nie brechen (Spec §7.6) und nie als „leer = keine Treffer" gelesen werden.
- Cache und Arbeitsstand in SQLite unter `~/.gastroviewer` (`cache.py`); TTL je Quelle über eine
  Tabelle (`ttl_for`, per AST-Test auf Vollständigkeit geprüft). Ausgehender Verkehr nur über
  `http.py` (`Outbound`) mit Rate-Limiter (`ratelimit.py`) und Kontaktadresse im User-Agent; eingehend prüft `api.py` Host/Origin (DNS-Rebinding, CSRF).
- Länder-/Orte-Registry (`laender.py`, `orte.py`) steuert, welche Quellen für welchen Punkt gelten.
- Oberfläche: `gastroviewer/static/` — ES-Module unter `js/` (Blöcke `bloecke-*.js`, Karte, State) plus
  klassische Skripte `score.js`, `bericht.js`, `duell.js`. Kein Build-Schritt.
- Drei Prüfebenen: `pytest` (offline, aufgezeichnete Fixtures), `scripts/uitest.py` (Browser gegen
  `scripts/attrappe.py`, echte App mit gesperrtem Netz), `scripts/vollpruefung.py` (Live, braucht Netz + GTFS).
  Dazu monatlich `scripts/kontrakt_check.py` (Datenverträge) als Workflow.

## Entscheidungen
- **Aufgezeichnete echte Antworten statt ausgedachter Testdaten** (Spec §10): der Vorgänger scheiterte
  an erfundenen Gewichten/Fixtures. Neue Quellen: erst Live-Probe (`scripts/at_probe.py`), dann Code
  gegen die echte Antwort, Fixture ablegen.
- **README bleibt ein Dokument:** `abnahme.py` und Spec §7.9 lesen es; `test_readme_api.py` prüft die
  API-Tabelle gegen die Routen.
- **Keine Registry für Stadtmodule, kein Umbau von `base.py`:** in der Bestandsaufnahme geprüft und als
  Umbau ohne Nutzerwert verworfen.
- **Zugehörigkeitsregeln** (Zensus-Zellen, Landesdienste) nutzen Fläche bzw. Bundesland-Code statt
  Rechtecken (Lehre aus den Runden 1–2). Zensuszellen zählen anteilig nach überdeckter Fläche.
- **Nicht signiertes Installer-Paket** (PyInstaller, `packaging/`, Workflow `installer.yml`): bewusst, kein Apple-/Windows-Zertifikat.
- Version steht an genau einer Stelle: `gastroviewer/__init__.py`.

## Bekannte Baustellen
- 31 ungeprüfte Funde niedriger Schwere (`docs/bestandsaufnahme.md`, Anhang).
- Starkregen-Hinweiskarte deckt BY/BW/HE nicht ab (ehrlich als „nicht abgedeckt" ausgewiesen).
- OffeneRegister-Handelsregister-Stand 2019 (nur freiwilliger Import).
- hystreet-Passantenfrequenz: gewerbliche Nutzung im Gratismodell untersagt (`notizen-standort-flaeche.md`).
- Recherche-Dokumente (`docs/erweiterungen-*.md`) beruhen auf Suchtreffern, nicht auf Live-Aufrufen.

## Verbesserungsideen
- Rechen-/Darstellungsfunktionen aus `docs/erweiterungen-funktionen.md` (bewusst noch außen vor).
- Weitere Länder-/Städteabdeckung nach dem Muster Wien/Salzburg (`docs/oesterreich.md`).
- Typprüfung (mypy/pyright) und Python-Linter sind nicht eingerichtet; nur ESLint für die Oberfläche.
- Verdrahtungstests (Loader → Service → API → UI) weiter ausbauen — das war das häufigste Testloch.

## Offene Fragen
- Soll das Projekt dauerhaft ohne Python-Linter/Typprüfung bleiben?
- Wer pflegt den monatlichen Kontrakt-Check, wenn GitHub `schedule` nach 60 Tagen Inaktivität abschaltet?
- Gibt es Chat-Wissen aus der alten Session, das hier fehlt? (siehe Herkunft oben)
