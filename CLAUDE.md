# CLAUDE.md — GastroViewer

Lokaler Daten-Browser für offene Standortdaten (Python 3.10+, FastAPI, httpx, SQLite; Oberfläche als
ES-Module ohne Build). Hintergrund und Stand: `docs/ai/HANDOFF.md`, Anforderungen: `spec-standort-datenterminal.md`.

## Befehle
```bash
pip install -e '.[dev]'                 # Entwicklung (kein venv-Zwang, kein make, kein Docker)
python -m pytest -q                     # komplette Suite, offline, ~50 s, aktuell 1020 grün
python -m pytest tests/test_xyz.py -q   # einzelne Datei
gastroviewer serve --port 8011          # Server (127.0.0.1), Daten unter ~/.gastroviewer

# Oberfläche (CI-Stand, siehe .github/workflows/tests.yml)
npx --yes eslint@9 gastroviewer/static/js gastroviewer/static/app.js gastroviewer/static/score.js gastroviewer/static/bericht.js gastroviewer/static/duell.js
node --input-type=module --check < gastroviewer/static/js/DATEI.js     # Syntaxcheck eines Moduls
python scripts/attrappe.py --port 8041 &                               # App ohne Netz
python scripts/uitest.py http://127.0.0.1:8041 --attrappe              # Browserprüfung (braucht playwright + chromium)
```
Live-Skripte (`scripts/vollpruefung.py`, `abnahme.py`, `kontrakt_check.py`, `at_probe.py`) brauchen Netz; in
der Cloud-Umgebung meist nicht erreichbar. Kein Python-Linter, keine Typprüfung konfiguriert.

## Konventionen (weichen vom Üblichen ab)
- **Sprache:** Kommentare, Docstrings, Fehlermeldungen, Commit-Messages und Doku auf Deutsch (mit Umlauten).
- **Jede Zahl ist belegt:** Jeder Block liefert `SourceResult` mit Quelle, Stand, Lizenz. Keine Konstante, die
  wie ein Messwert aussieht. Lieber ein Feld weniger als ein geratenes.
- **Fehler konkret:** `SourceError(kind, message)` mit echter Ursache (Timeout, HTTP-Status, fehlendes Feld).
  Quellenausfall nie als „keine Treffer" werten und nie über gültigen Datenstand schreiben.
- **Tests gegen aufgezeichnete echte Antworten** (`fixtures/`, `tests/fixtures/`), nie gegen ausgedachte.
  Neue Quelle: erst Live-Probe, dann Fixture, dann Code. Nicht nur reine Funktionen testen, auch die
  Verdrahtung Loader → Service → API.
- **Ausgehender Verkehr nur über `http.py` (`Outbound`)** — mit Limiter und Protokoll (`/api/outbound`).
  `GASTROVIEWER_ERLAUBTE_HOSTS` betrifft nur den *eingehenden* Host-/Origin-Schutz (LAN-Hostnamen).
- **Event-Loop freihalten:** CPU-schwere Rechnung (Graphen, Zellen) per `asyncio.to_thread`.
- **Neue Quelle braucht:** TTL-Eintrag in der `ttl_for`-Tabelle (AST-Test), Eintrag in README-API-Tabelle
  (`test_readme_api.py`), Quelle/Lizenz-Abschnitt im README.
- **Version** nur in `gastroviewer/__init__.py` ändern.
- Oberfläche: Lader prüfen `lauf !== state.ladeLauf` (veraltete Antworten verwerfen); Namen aus anderen
  Modulen explizit importieren (ESLint `no-undef` ist in der CI scharf); Fremdtexte (OSM, GTFS) vor
  `innerHTML` maskieren.

## Stolperfallen
- `node --check datei.js` prüft ES-Module **nicht**; nur `--input-type=module` über stdin prüft wirklich.
- Nominatim braucht `GASTROVIEWER_CONTACT` (Kontaktadresse im User-Agent), sonst HTTP 403.
- Overpass: höchstens eine Abfrage gleichzeitig; `remark` im Ergebnis bedeutet Abbruch, nicht „leer".
- Zensus-100-m-Zellen anteilig nach überdeckter Fläche zählen, nicht voll bei bloßer Berührung.
- Feiertage: `regionalScope: Local` / `subdivisions` beachten (Augsburger Friedensfest ≠ Bayern).
- Landesdienste nach Bundesland-Code wählen, nie nach Rechteck (Stuttgart/Ulm liegen im Bayern-Kasten).
- GitHub schaltet `schedule`-Workflows nach 60 Tagen ohne Aktivität ab (betrifft `kontrakt-check.yml`).
- README ist von Skripten gelesener Teil der Spec (`abnahme.py`): nicht aufspalten.

Für größere Überarbeitungen arbeitet die Hauptsession nach docs/ai/WORKFLOW.md.
