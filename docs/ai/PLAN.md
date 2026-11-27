# PLAN — Überarbeitung nach AUDIT.md

Branch: `claude/jolly-shannon-g2l13z`. Status: **FREIGEGEBEN (27.11.2026)**, C4 und C5 eingeschlossen.
**Ziel:** Codebasis stabiler, sauberer, wartbarer; Funktionalität für Nutzer bleibt gleich.
**Grenzen:** keine neuen Features, kein Framework-Wechsel, Datenformat nur nach Rückfrage ändern; Oberfläche nur
Fehler beheben, kein Redesign. C4: Oberfläche in derselben Aufgabe mit anpassen, falls nötig.
Standard-Prüfbefehl (P): `python -m pytest -q` · Oberfläche zusätzlich (PJ):
`npx --yes eslint@9 gastroviewer/static/js gastroviewer/static/app.js gastroviewer/static/score.js gastroviewer/static/bericht.js gastroviewer/static/duell.js`
Jede Aufgabe: Test für den Fehlerfall zuerst (Sicherheitsnetz), dann Fix. Fixtures nach Projektregel (echte Antwortform).

Status: OFFEN | IN ARBEIT | FERTIG | ZURÜCKGESTELLT

## Block A — Backend: Ausfall ≠ keine Treffer
| ID | Ziel | Dateien | Akzeptanzkriterien | Prüf | Status |
|---|---|---|---|---|---|
| A1 | Client-Timeout greift wieder (H1) | `http.py`, `tests/test_http.py` | Ohne `timeout`-Argument gilt das Client-Timeout (`httpx.USE_CLIENT_DEFAULT`); explizites `timeout` wirkt weiter; Test mit MockTransport belegt beides | P | FERTIG (939 grün) |
| A2 | Helfer für FeatureCollections, angewendet in Baustellen und Märkte (M1, Teil 1) | `sources/base.py`, `baustellen.py`, `maerkte.py`, Tests | Nicht-dict oder fehlendes `features` → `SourceError("parse", …)`, `ok=False`; leere Liste `features: []` bleibt gültig „0 Treffer"; je ein Test | P | FERTIG (976 grün) |
| A3 | Helfer aus A2 in bayern, berlin (2×), hamburg, mobidata_bw (2×) (M1, Teil 2) | diese Module, Tests | wie A2, je Fundstelle ein Test | P | FERTIG (987 grün; offen, klein: Verdrahtungstest `_lage_bw`/`planung` für Ladesäulen/Milieuschutz fehlt; Hamburg-Warnung „keine Zählstelle" auch bei HVS-Ausfall) |
| A4 | Paginierung typsicher (M2) | `zensus.py`, `scan.py`, Tests | Nicht-dict-Payload → `SourceError("parse")`, kein 500; Test mit Liste als Payload je Pfad | P | FERTIG (1 Korrekturrunde; offen, klein: dict ohne `features` zählt weiter als 0, Zusammenführung mit `features_aus` möglich) |
| A5 | Nominatim-Fehlerfälle + Photon-Rückfall (M3) | `nominatim.py`, neu `tests/test_nominatim.py` | `{"error"}`/Nicht-Liste in `search` → SourceError → Photon greift; `reverse` mit Nicht-dict → SourceError; Suchpfad und Rückfall getestet | P | FERTIG (976 grün; offen, klein: Photon-Antwort ohne dict wirft weiter AttributeError, Hinweistext „nicht erreichbar" ungenau) |
| A6 | WMS-ServiceException erkennen (M4) | `wms.py`, Tests | `ServiceExceptionReport` → `SourceError("api_error")`, kein Datenfeld; Test | P | FERTIG (1 Korrekturrunde; offen, klein: `code`-Attribut im Regex-Rückfall fehlt, `planung.py` nutzt Helfer noch nicht) |

## Block B — Oberfläche
| ID | Ziel | Dateien | Akzeptanzkriterien | Prüf | Status |
|---|---|---|---|---|---|
| B1 | Nur `http(s):`-Links aus Fremddaten (M5) | `js/dom.js`, `bloecke-region.js`, `bloecke-gastro.js` | `sichereUrl()` lässt nur http/https durch, sonst kein Link (Text bleibt); alle 6 Stellen nutzen es; ESLint 0 Fehler | P + PJ | FERTIG (1 Korrekturrunde: +3 Stellen in `bloecke-laender.js`, insgesamt 9; uitest nicht gelaufen, Playwright für Python fehlt) |
| B2 | Laufprüfung Kartenebenen + Scan-`ausstehend` (M6, M7) | `bloecke-laender.js`, `scan.js` | Nach `await` wird veralteter Lauf verworfen; Code vor `await` gesetzt; `moveend` während Scan löst danach einen Scan aus | PJ + uitest (Attrappe) | FERTIG (Nachlauf über `scanNachBewegung`, d. h. nach Erfolg „veraltet"-Hinweis statt Auto-Overpass, wie beim normalen Schwenken; nach Fehler bleibt die Meldung stehen; uitest nicht gelaufen, Playwright für Python fehlt) |
| B3 | Speicher-Helfer und Fetch-Absicherung (M8) | neu `js/speicher.js` (+ score.js-Variante), betroffene Dateien | Alle `localStorage`-Zugriffe über try/catch; Sicherung-Einspielen meldet Netzfehler; ESLint 0 Fehler | PJ + uitest | FERTIG (1008 grün; Review OK, Kleinfund unlesbare Import-Antwort vom Steuernden behoben; `test_api.py` Deckkraft-Test sucht jetzt `schreibe(`; uitest nicht gelaufen) |
| B4 | Deckkraft für Fahrzeit-Ebene, tote Importe weg | `bloecke-mobilitaet.js`, `karte.js`, diverse js | Regler wirkt auf Fahrzeit; ESLint-Warnungen `no-unused-vars` für Importe = 0 | PJ + uitest | OFFEN |

## Block C — Backend-Kleinkram (niedrig)
| ID | Ziel | Dateien | Akzeptanzkriterien | Prüf | Status |
|---|---|---|---|---|---|
| C1 | Zeit/Datum in Ortszeit | `messe.py`, `dynamik.py`, `luft.py` | „heute"/Jahr/Alter in `Europe/Berlin`; Tests mit fester Uhrzeit um 00:30 MEZ | P | FERTIG (1005 grün, 1 Korrekturrunde: UBA-Stempel ganzjährig MEZ → `jetzt_mez`; neues `zeit.py` ohne neue Abhängigkeit; offen, klein: Jahrestest `test_dynamik.py:91` greift erst ab 2027; `date.today()` noch in baustellen, berlin, hamburg, gtfs, mobidata_bw, salzburg, wien) |
| C2 | Baustellen: LineString übernehmen, verworfene Features als Warnung; Tourismus-Lückenprüfung; Luft `aktiv_bis` | `baustellen.py`, `tourismus.py`, `luft.py` | je Test | P | OFFEN |
| C3 | Genesis-Zugangsdatei direkt mit 0o600; CLI-Download mit Timeout | `genesis.py`, `__main__.py` | Datei nie weltlesbar (Test prüft Modus); `urlopen(..., timeout=…)` | P | OFFEN |
| C4 ⚠ | API: PATCH ohne bekanntes Feld → 422; `/api/outbound` mit Obergrenze | `routen/punkte.py`, `cache.py`, README-Tabelle | Tests; README angepasst | P | OFFEN (API-Änderung, OK nötig) |
| C5 ⚠ | `pydantic>=2` deklarieren; CI-Matrix + 3.11 | `pyproject.toml`, `tests.yml` | Installation und Suite grün | P | OFFEN (Abhängigkeit, OK nötig) |

## Zurückgestellt (bewusst nicht im Plan, auf Wunsch nachziehbar)
Overture-EWKB, `_ring_center`, SQLite `closing()`, 500-Handler-Text, `resp.json` per Thread, Kreisprofil-Nicht-dict,
Import-Größengrenze, Actions SHA-Pinning, `aria-live`, `bloecke-region.js` aufteilen, uitest-Ausbau (Race, XSS, Sicherung, Fehlerpfade).

## Reihenfolge / Parallelität
A1 → (A2 ∥ A4 ∥ A5 ∥ A6) → A3 → (B1 ∥ C1) → B2 → B3 → B4 → C2 → C3 → C4 → C5.
Parallel nur ohne gemeinsame Dateien.
