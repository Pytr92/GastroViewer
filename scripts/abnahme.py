#!/usr/bin/env python3
"""Abnahmeprüfung gegen die Kriterien aus §7 der Spec.

Läuft gegen einen **laufenden** Server und prüft jedes Kriterium mit echten
Aufrufen, nicht mit Behauptungen.

    python -m gastroviewer serve --port 8011 &
    python scripts/abnahme.py http://127.0.0.1:8011

Beim ersten Lauf gehen echte Anfragen an Overpass, Zensus und Nominatim. Das
dauert ein bis zwei Minuten und ist beabsichtigt — geprüft wird das reale
Verhalten, nicht ein Ersatz.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
WURZEL = Path(__file__).resolve().parents[1]

# Vier Lagetypen laut §7.
PUNKTE = [
    ("Großstadt-Innenstadt", 48.1334, 11.5674, 600),
    ("Großstadt-Wohnviertel", 48.1078, 11.5470, 600),
    ("Kleinstadt", 49.0447, 11.3547, 600),
    ("ländlich", 53.0210, 13.2100, 900),
]

ergebnisse: list[tuple[str, bool, str]] = []


def hole(pfad: str, timeout: float = 180) -> dict:
    req = urllib.request.Request(BASE + pfad, headers={"Accept": "application/json"})
    # Kein Proxy: der Server läuft lokal.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def hole_text(pfad: str, timeout: float = 180) -> str:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(BASE + pfad, timeout=timeout) as r:
        return r.read().decode("utf-8")


def pruefe(nr: str, titel: str, bedingung: bool | None, beleg: str) -> None:
    """``bedingung=None`` bedeutet „nicht prüfbar" — etwa weil eine externe
    Quelle gerade nicht antwortet. Das ist weder bestanden noch durchgefallen
    und muss unterscheidbar bleiben, sonst führt ein Dienstausfall entweder zu
    einem falschen Alarm oder zu einem falschen Freispruch."""
    # Auf bool zwingen: manche Bedingungen sind Ausdrücke wie ``ok and warnungen``
    # und liefern eine Liste. Die wäre wahrheitswertig wahr, aber nicht ``is True``
    # — die Anzeige und die Zählung würden auseinanderlaufen.
    ergebnisse.append((f"{nr} {titel}", None if bedingung is None else bool(bedingung), beleg))
    zeichen = "OFFEN" if bedingung is None else ("OK   " if bedingung else "FEHLT")
    print(f"[{zeichen}] {nr} {titel}")
    for zeile in beleg.splitlines():
        print(f"         {zeile}")


def direkt(beschreibung: str, aufruf, versuche: int = 3):
    """Direktabruf einer Originalquelle mit Wiederholung.

    Overpass antwortet unter Last mit HTTP 504. Das ist kein Mangel der
    Anwendung — die Prüfung darf daran nicht abstürzen.
    """
    letzter = None
    for i in range(versuche):
        try:
            return aufruf(), None
        except Exception as exc:  # noqa: BLE001 — Ursache wird ausgegeben
            letzter = f"{type(exc).__name__}: {exc}"
            if i < versuche - 1:
                time.sleep(5 * (i + 1))
    return None, f"{beschreibung} nicht erreichbar ({letzter})"


print(f"Abnahmeprüfung gegen {BASE}\n" + "=" * 72)

# ---------------------------------------------------------------- Vorlauf
# Bewusst ohne refresh: Overpass ist ein Spendenprojekt (Spec §4.2 „keine
# Abfrage-Schleifen"). Beim ersten Lauf holt der Cache die Daten ohnehin echt;
# bei jedem weiteren waere ein erzwungener Neuabruf reine Last ohne Erkenntnis.
# Den einen echten Abruf, den §7.5 braucht, holt der Test unten gezielt nach.
daten: dict[str, dict] = {}
print("\nVier Lagetypen laden …")
for name, lat, lon, r in PUNKTE:
    t0 = time.perf_counter()
    daten[name] = hole(f"/api/point?lat={lat}&lon={lon}&r={r}")
    aus_cache = daten[name]["meta"]["aus_cache"]
    print(
        f"  {name:24} {time.perf_counter() - t0:5.1f}s "
        f"({'aus dem Cache' if aus_cache else 'echt abgerufen'})"
    )

# ------------------------------------------------------------------- §7.1
# Herkunftsnachweis: die angezeigten Zahlen werden gegen einen direkten,
# unabhaengigen Aufruf der Originalquellen gehalten. Eine Heuristik ueber
# Zahlenkonstanten im Code wuerde HTTP-Codes und Puffergroessen falsch anschlagen;
# hier wird stattdessen geprueft, was zaehlt: stimmt die Zahl mit der Quelle ueberein.
import urllib.parse

d = daten["Großstadt-Innenstadt"]
lat0, lon0, r0 = PUNKTE[0][1], PUNKTE[0][2], PUNKTE[0][3]
opener = urllib.request.build_opener()
# Overpass und ArcGIS lehnen Anfragen ohne User-Agent ab (Overpass mit HTTP 406).
# Dieselbe Identifikation wie die Anwendung verwenden.
KOPFZEILEN = {"User-Agent": "gastroviewer-abnahme/0.1 (Abnahmepruefung)"}

zensus_form = urllib.parse.urlencode({
    "f": "json", "where": "1=1",
    "geometry": json.dumps({"x": lon0, "y": lat0, "spatialReference": {"wkid": 4326}}),
    "geometryType": "esriGeometryPoint", "distance": str(r0),
    "units": "esriSRUnit_Meter", "inSR": "4326", "outSR": "4326",
    "spatialRel": "esriSpatialRelIntersects", "outFields": "Einwohner",
    "returnGeometry": "false", "resultRecordCount": "2000",
}).encode()
roh, zensus_problem = direkt(
    "Zensus-Dienst",
    lambda: json.loads(
        opener.open(urllib.request.Request(
            "https://services2.arcgis.com/jUpNdisbWqRpMo35/arcgis/rest/services"
            "/Zensus2022_grid_final/FeatureServer/0/query",
            data=zensus_form, headers=KOPFZEILEN), timeout=90
        ).read().decode()
    ),
)
angezeigt = d["bloecke"]["zensus"]["data"]["bevoelkerung"]["einwohner"]
if roh is None:
    quelle_summe = quelle_zellen = None
    zensus_passt = None
else:
    quelle_summe = sum(
        f["attributes"]["Einwohner"] for f in roh["features"]
        if f["attributes"].get("Einwohner") is not None
    )
    quelle_zellen = len(roh["features"])
    zensus_passt = (
        angezeigt["wert"] == quelle_summe and angezeigt["zellen"] == quelle_zellen
    )

abfrage = (
    f'[out:json][timeout:60];nwr["amenity"="fast_food"](around:{r0},{lat0},{lon0});'
    "out count;"
)
roh_osm, osm_problem = direkt(
    "Overpass",
    lambda: json.loads(
        opener.open(urllib.request.Request(
            "https://overpass-api.de/api/interpreter",
            data=urllib.parse.urlencode({"data": abfrage}).encode(),
            headers=KOPFZEILEN), timeout=90
        ).read().decode()
    ),
)
angezeigt_ff = (
    d["bloecke"]["osm"]["data"]["zusammenfassung"]["gastronomie"]["nach_typ"]
    .get("Schnellrestaurant", 0)
)
if roh_osm is None:
    quelle_ff = None
    osm_passt = None
else:
    quelle_ff = int(roh_osm["elements"][0]["tags"]["total"])
    osm_passt = angezeigt_ff == quelle_ff

if zensus_passt is None and osm_passt is None:
    urteil = None
elif zensus_passt is False or osm_passt is False:
    urteil = False
else:
    urteil = True
pruefe(
    "§7.1",
    "Jede Zahl ist auf eine reale API-Antwort zurückführbar",
    urteil,
    (
        f"Zensus direkt abgefragt: {quelle_zellen} Zellen, Summe Einwohner {quelle_summe:.0f}"
        if roh is not None
        else f"Zensus: {zensus_problem}"
    )
    + f"\n  Anwendung zeigt: {angezeigt['zellen']} Zellen, {angezeigt['wert']:.0f} Einwohner\n"
    + (
        f"  Overpass `out count` fast_food: {quelle_ff}"
        if roh_osm is not None
        else f"  Overpass: {osm_problem}"
    )
    + f"\n  Anwendung zeigt Schnellrestaurants: {angezeigt_ff}",
)

# ------------------------------------------------------------------- §7.2
fehlend = []
for name, d in daten.items():
    for block, inhalt in d["bloecke"].items():
        p = inhalt.get("provenance")
        # Blöcke, die begründet leer bleiben dürfen, tragen dann keine Quelle:
        # GTFS ohne importierten Fahrplan, Lärm außerhalb Bayerns, Overture
        # ohne lokalen Import, die München-Quellen (Baustellen, Märkte,
        # Indikatorenatlas) außerhalb des Stadtgebiets. Alle nennen den
        # Grund in ihren warnings.
        if (block in ("gtfs", "laerm", "baustellen", "maerkte", "indikatoren")
                and inhalt.get("data") is None):
            continue
        if block == "overture" and not (inhalt.get("data") or {}).get("importiert"):
            continue
        if not p or not p.get("source") or not p.get("license"):
            fehlend.append(f"{name}/{block}")
        elif block in ("zensus", "osm", "gtfs") and not p.get("stand"):
            fehlend.append(f"{name}/{block}: kein Stand")
beispiel = daten["Großstadt-Innenstadt"]["bloecke"]["zensus"]["provenance"]
pruefe(
    "§7.2",
    "Jeder Block nennt Quelle, Stand und Lizenz",
    not fehlend,
    f"Beispiel Zensus: {beispiel['source'][:56]}…\n"
    f"  Stand: {beispiel['stand']}\n"
    f"  Lizenz: {beispiel['license'][:60]}…"
    + ("\n  fehlend: " + ", ".join(fehlend) if fehlend else ""),
)

# ------------------------------------------------------------------- §7.3
html = hole_text("/")
osm_sichtbar = "OpenStreetMap-Mitwirkende" in html and "ODbL" in html
zensus_sichtbar = "Statistische Ämter des Bundes und der Länder" in html
pruefe(
    "§7.3",
    "Attribution OSM/ODbL und Zensus-Copyright sichtbar",
    osm_sichtbar and zensus_sichtbar,
    "in der Fußzeile von index.html: "
    f"OSM/ODbL={'ja' if osm_sichtbar else 'nein'}, "
    f"Zensus={'ja' if zensus_sichtbar else 'nein'}",
)

# ------------------------------------------------------------------- §7.4
gesundheit = hole("/api/health")
ua = gesundheit["user_agent"]
# refresh=true erzwingt echte Abrufe. Ohne das antwortet der Cache und es geht
# gar nichts hinaus — dann misst der Test den Cache statt den Rate-Limiter.
t0 = time.perf_counter()
for begriff in ("Augsburg Rathaus", "Regensburg Dom", "Ingolstadt Rathaus"):
    hole(f"/api/geocode?q={begriff.replace(' ', '+')}&refresh=true")
dauer = time.perf_counter() - t0
stats = hole("/api/stats")
lim = stats["rate_limiter"].get("nominatim", {})
pruefe(
    "§7.4",
    "Nominatim ≤ 1 req/s gedrosselt, User-Agent gesetzt",
    dauer >= 2.0 and lim.get("min_interval_s") == 1.0 and "gastroviewer/" in ua,
    f"3 echte Suchen nacheinander (refresh=true): {dauer:.2f}s (Untergrenze 2,0s)\n"
    f"  Limiter: {lim}\n"
    f"  User-Agent: {ua}",
)

# ------------------------------------------------------------------- §7.5
# Ein erzwungener Abruf, danach ein normaler: der Zaehler darf sich beim zweiten
# nicht bewegen. Nur die Zensus-Quelle wird erneuert - das genuegt als Beweis und
# belastet Overpass nicht.
lat, lon, r = PUNKTE[0][1], PUNKTE[0][2], PUNKTE[0][3]
vor_kalt = hole("/api/stats")["outbound_requests_total"]
hole(f"/api/point/zensus?lat={lat}&lon={lon}&r={r}&refresh=true")
nach_kalt = hole("/api/stats")["outbound_requests_total"]
hole(f"/api/point/zensus?lat={lat}&lon={lon}&r={r}")
nach_warm = hole("/api/stats")["outbound_requests_total"]
ganzer = hole(f"/api/point?lat={lat}&lon={lon}&r={r}")
nach_punkt = hole("/api/stats")["outbound_requests_total"]
pruefe(
    "§7.5",
    "Cache greift: zweiter Aufruf ohne Outbound-Traffic",
    nach_kalt > vor_kalt
    and nach_warm == nach_kalt
    and nach_punkt == nach_warm
    and ganzer["meta"]["outbound_requests"] == 0,
    f"erzwungener Abruf: Zähler {vor_kalt} → {nach_kalt} (+{nach_kalt - vor_kalt})\n"
    f"  danach derselbe Aufruf: Zähler bleibt bei {nach_warm}\n"
    f"  ganzer Punkt aus dem Cache: {ganzer['meta']['dauer_ms']} ms, "
    f"outbound_requests={ganzer['meta']['outbound_requests']}\n"
    f"  nachprüfbar unter {BASE}/api/outbound",
)

# ------------------------------------------------------------------- §7.6
# Erzwungener Ausfall: unerreichbarer Overpass-Endpunkt in einem eigenen Prozess.
proc = subprocess.run(
    [sys.executable, str(WURZEL / "scripts" / "_ausfalltest.py")],
    capture_output=True,
    text=True,
    cwd=WURZEL,
    timeout=180,
)
try:
    ausfall = json.loads(proc.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    ausfall = {"fehler": (proc.stderr or proc.stdout)[-400:]}
pruefe(
    "§7.6",
    "Ausfall einer Quelle bricht die Seite nicht",
    ausfall.get("osm_ok") is False
    and ausfall.get("zensus_ok") is True
    and bool(ausfall.get("gemeinde")),
    f"Overpass auf toten Endpunkt gezwungen: osm.ok={ausfall.get('osm_ok')}\n"
    f"  Meldung: {str(ausfall.get('osm_fehler'))[:70]}\n"
    f"  Zensus lief weiter: {ausfall.get('zellen')} Zellen, "
    f"Gemeinde {ausfall.get('gemeinde')}"
    + (f"\n  Fehler im Unterprozess: {ausfall['fehler']}" if "fehler" in ausfall else ""),
)

# ------------------------------------------------------------------- §7.7
zeilen = []
alle_ok = True
for name, _lat, _lon, _r in PUNKTE:
    d = daten[name]
    z = d["bloecke"]["zensus"]["data"] or {}
    o = d["bloecke"]["osm"]["data"] or {}
    zus = o.get("zusammenfassung", {})
    ew = ((z.get("bevoelkerung") or {}).get("einwohner") or {}).get("wert")
    zeilen.append(
        f"{name:24} {z.get('zellen_gefunden', 0):>4} Zellen  "
        f"{str(ew):>8} Einw.  {zus.get('gastronomie', {}).get('gesamt', 0):>4} Gastro  "
        f"{zus.get('oepnv', {}).get('haltestellen', 0):>3} Halte  "
        f"{d['punkt'].get('gemeinde') or '—'}"
    )
    if not d["bloecke"]["zensus"]["ok"] or not d["bloecke"]["osm"]["ok"]:
        alle_ok = False
        zeilen.append(
            "    ↳ Quelle ausgefallen: "
            + "; ".join(
                f"{k}: {(v['error'] or {}).get('message')}"
                for k, v in d["bloecke"].items()
                if not v["ok"]
            )
            + "  (Dienst gerade nicht verfügbar — Prüfung später wiederholen)"
        )
laendlich = daten["ländlich"]
laendlich_sauber = (
    laendlich["bloecke"]["osm"]["ok"]
    and (laendlich["bloecke"]["osm"]["warnings"] or laendlich["bloecke"]["zensus"]["warnings"])
)
pruefe(
    "§7.7",
    "Vier Lagetypen liefern vollständige Ausgaben",
    alle_ok and laendlich_sauber,
    "\n".join(zeilen)
    + f"\n  ländlicher Fall mit Hinweis statt Leere: {'ja' if laendlich_sauber else 'nein'}",
)

# ------------------------------------------------------------------- §7.8
quelle = (WURZEL / "gastroviewer" / "sources" / "zensus.py").read_text(encoding="utf-8")
behandelt = 'exceededTransferLimit") is not True' in quelle and "resultOffset" in quelle
gross = hole(f"/api/point/zensus?lat=48.1334&lon=11.5674&r=3000")
n = (gross.get("data") or {}).get("zellen_gefunden", 0)
pruefe(
    "§7.8",
    "exceededTransferLimit wird behandelt",
    behandelt and n > 2000,
    "zensus.py prüft auf `is not True` (der Schlüssel fehlt bei false)\n"
    f"  und blättert über resultOffset weiter\n"
    f"  Gegenprobe r=3000: {n} Zellen geliefert (Limit je Seite: 2000)",
)

# ------------------------------------------------------------------- §7.9
readme = (WURZEL / "README.md").read_text(encoding="utf-8")
pflicht = {
    "Start": "gastroviewer serve" in readme,
    "GTFS-Import": "import-gtfs" in readme,
    "Cache leeren": "clear-cache" in readme,
    "Zensus-Lizenz": "Statistische Ämter" in readme,
    "OSM-Lizenz": "ODbL" in readme,
    "GTFS-Lizenz": "CC BY 4.0" in readme,
    "Nominatim": "Nominatim" in readme,
    "hystreet-Auflage": "gewerbliche Nutzung untersagt" in readme,
}
pruefe(
    "§7.9",
    "README erklärt Start, GTFS-Import, Cache leeren, listet Quellen mit Lizenz",
    all(pflicht.values()),
    " · ".join(f"{k}={'ja' if v else 'NEIN'}" for k, v in pflicht.items()),
)

# --------------------------------------------------------------- Ergebnis
print("\n" + "=" * 72)
erfuellt = [t for t, ok, _ in ergebnisse if ok is True]
gescheitert = [t for t, ok, _ in ergebnisse if ok is False]
ungeprueft = [t for t, ok, _ in ergebnisse if ok is None]
print(f"{len(erfuellt)} von {len(ergebnisse)} Kriterien erfüllt.")
if ungeprueft:
    print("Nicht prüfbar (externe Quelle antwortet gerade nicht):")
    for t in ungeprueft:
        print(f"  ? {t}")
if gescheitert:
    print("Nicht erfüllt:")
    for t in gescheitert:
        print(f"  - {t}")
    sys.exit(1)
if ungeprueft:
    print("Kein Kriterium verletzt; die offenen Punkte später wiederholen.")
    sys.exit(2)
print("Alle Abnahmekriterien aus §7 erfüllt.")
