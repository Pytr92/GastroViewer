# AUDIT — Phase 1 (27.11.2026)

Vier Researcher, je ein Bereich: Backend-Kern + CI/Abhängigkeiten · Quellen DE Teil 1 · Quellen Teil 2 + Österreich ·
Oberfläche. Ausgangslage: 937 Tests grün, ESLint 0 Fehler / 49 Warnungen. Die zwei umgesetzten Runden aus
`docs/bestandsaufnahme.md` sind nicht erneut gemeldet; deren Anhang (31 niedrige Funde) wurde mitgeprüft.

**Ergebnis:** keine kritischen Funde. 1 hoch, 8 mittel, Rest niedrig. Grundsatzverletzung, die sich wiederholt:
*„Antwort ohne erwartete Struktur → leere Daten statt Fehler"* (Ausfall ≠ keine Treffer).

## Hoch
| # | Fund | Stelle | Aufwand |
|---|---|---|---|
| H1 | `timeout=None` wird ausdrücklich an `client.request` gereicht → httpx schaltet **alle** Timeouts ab; das Client-Timeout (30 s) greift nie. ~82 von 89 Aufrufern übergeben kein `timeout`. Hängender Dienst blockiert unbegrenzt, beim Overpass-Slot (`max_concurrent=1`) alle folgenden Abfragen. *Vom Steuernden am Code bestätigt.* | `http.py:97,118` | S |

## Mittel
| # | Fund | Stelle | Aufwand |
|---|---|---|---|
| M1 | JSON ohne `features` / Nicht-dict → `ok=True`, „0 Treffer" (HTML fängt `get_json` ab, ein JSON-Fehlerobjekt nicht) | `baustellen.py:269`, `bayern.py:177`, `berlin.py:187,232`, `hamburg.py:85`, `maerkte.py:148`, `mobidata_bw.py:255,432` | S–M |
| M2 | Paginierung liest `payload.get(...)` ohne Typprüfung → Nicht-dict = ungefangene 500 statt `SourceError` | `zensus.py:361,429`, `scan.py:120-122` | S |
| M3 | Nominatim: Nicht-Liste / `{"error"}` → „keine Treffer", **kein Photon-Rückfall**; `reverse` mit Liste → AttributeError. Kein `test_nominatim.py` | `nominatim.py:175-188,223-230` | S |
| M4 | WMS GetFeatureInfo erkennt `ServiceExceptionReport` nicht → Fehlertext erscheint als Datenfeld (Bodenrichtwert) | `wms.py:~440-470` (Muster: `planung.py:219`) | S |
| M5 | Fremd-URLs als `href` ohne Schema-Prüfung (`esc()` lässt `javascript:` durch) | `bloecke-region.js:476,507,525,1032,2180`, `bloecke-gastro.js:504` | S |
| M6 | Kartenebenen-Lader ohne Laufprüfung: Ebene des alten Bundeslands / doppelt | `bloecke-laender.js:41-72,175-212` | S |
| M7 | Flächenscan verwirft `moveend` während laufendem Scan (kein `ausstehend`-Flag wie beim Gitter) | `scan.js:~437` | S |
| M8 | `localStorage.getItem/setItem` ungeschützt → Aufbau bricht in Privatmodus/Quota ab; Sicherung-Einspielen ohne `fetch`-Fehlerbehandlung | `bloecke-gastro.js:253`, `schaetzung.js:94`, `scan.js:204,255`, `karte.js:148,176`, `vergleich.js:86,354,755`, `score.js:115` | S |

## Niedrig (Auswahl, bestätigt)
- Backend: PATCH ohne bekanntes Feld → 404 statt 422 (`routen/punkte.py:69-87`); `outbound_since` ohne LIMIT (`cache.py:254`);
  CLI-Download ohne Timeout (`__main__.py:98`), Import ohne Größengrenze (`importe.py:63`); 500-Handler gibt Ausnahmetext aus
  (`api.py:182`); `resp.json()` großer Antworten im Event-Loop (`http.py:185`); SQLite-Verbindungen nie geschlossen (`cache.py:124`);
  toter Code `config.set_settings`, `muenchen.MONATE_KURZ`.
- Quellen: Baustellen verwerfen LineString still (`baustellen.py:75-87,139`); Messe „heute" aus UTC (`messe.py:239`), ebenso
  `dynamik.py:110`; Luft: Zeitzonenmix (`luft.py:148`), stillgelegte Stationen (`luft.py:68`); Genesis-Zugangsdatei kurz
  weltlesbar (`genesis.py:145`); Tourismus „12 Monate" ohne Lückenprüfung (`tourismus.py:108`); Overture EWKB/SRID
  (`overture.py:171`); `_ring_center` mit Schlusspunkt (~14 m, `zensus.py:129`); Kreisprofil Nicht-dict → `{}` (`kreisprofil.py:235`).
- Oberfläche: Deckkraftregler ohne Fahrzeit-Ebene (`bloecke-mobilitaet.js:~368`, `karte.js:158`); 49 tote Importe;
  `aria-live` auf ganzem Panel; `bloecke-region.js` 2262 Zeilen.
- Abhängigkeiten/CI: `pydantic` direkt importiert, nicht deklariert (`routen/modelle.py:10`); keine Obergrenzen, Untergrenzen
  ungetestet; Matrix 3.10/3.12, Installer baut mit 3.11; Actions nicht SHA-gepinnt. Leaflet 1.9.4 = aktuell.

## Testlücken
Kein `test_nominatim.py`, `test_links.py`; keine Tests für Nicht-dict-Payloads (M1/M2), WMS-Exception (M4), Timeout-Default (H1).
Browserprüfung (`uitest.py`) ohne: schnellen Punktwechsel, XSS-Nutzlast, Sicherung export/import, „Neu prüfen", Fehlerpfade (500/ok=False),
`console.error`/`requestfailed`-Hooks.

## Widerlegt / bereits behoben (aus dem Anhang)
Overpass-`remark` & Parallelität, BfG-Exception, Limiter, Validierungsfehler, Import-Validierung, Cache-Aufräumung, Redirect-Sperre,
GTFS-Atomartausch, Dynamik-Januar, Luft-Fenster, Indikatoren-Warnungen, IHK-Bytes, Genesis-Redirect, Graph-Rechnung per `to_thread`,
Query-Injection (nur validierte Zahlen/Ziffern), Zip-Slip (keine `extract`-Aufrufe), XML ohne externe Entitäten.

## Nicht geprüft
`scripts/*.py` im Detail; Österreich-Module nur per Grep (Injection/Zip/Loop), nicht zeilenweise; Leaflet nicht gegen CVE-Datenbank.
