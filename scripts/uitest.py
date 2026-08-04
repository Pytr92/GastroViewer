#!/usr/bin/env python3
"""Browserprüfungen der Oberfläche.

Die Testsuite unter ``tests/`` prüft ausschließlich Python. Alles, was in
``app.js`` passiert — Blöcke, Reiter, Kartenebenen, Vergleichstabelle — war
bisher ungesichert; jede Änderung dort fiel nur auf, wenn jemand hinsah. Dieses
Skript schließt die Lücke.

Aufruf::

    gastroviewer serve --port 8011 &
    python scripts/uitest.py http://127.0.0.1:8011

Voraussetzung ist Playwright mit Chromium::

    pip install playwright && playwright install chromium

Fehlt beides, endet das Skript mit **Exitcode 3** und einer Erklärung — es ist
kein Fehlschlag, sondern eine nicht durchgeführte Prüfung. Das ist bewusst so:
ein übersprungener Test darf nicht wie ein bestandener aussehen.

Exitcodes: 0 = alles in Ordnung · 1 = Befunde · 2 = Server nicht erreichbar ·
3 = Playwright oder Chromium fehlen.
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Punkte, die für einzelne Prüfungen gebraucht werden.
MARIENPLATZ = (48.1372, 11.5755)
ISARUFER = (48.1297, 11.5822)   # Fluss als Barriere
ISARAUEN = (48.1050, 11.5530)   # liegt im Hochwassergebiet HQ 100
FREIHAM = (48.1450, 11.4200)    # dort gilt ein Bebauungsplan
GIESING = (48.1114, 11.5859)
KOELN = (50.9413, 6.9583)       # Nordrhein-Westfalen: Bodenrichtwert-Ebene

# Playwright bringt Chromium normalerweise selbst mit; in vorbereiteten
# Umgebungen liegt es an einem festen Pfad.
CHROMIUM_PFADE = [
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    "/opt/pw-browsers/chromium/chrome-linux/chrome",
]


class Befund(Exception):
    """Ein konkreter Mangel in der Oberfläche."""


# --------------------------------------------------------------- Helfer


def warte_geladen(page, sekunden: int = 120) -> None:
    """Wartet, bis kein Block mehr im Ladezustand ist."""
    for _ in range(sekunden * 2):
        if page.eval_on_selector_all(".status.laedt", "e=>e.length") == 0:
            return
        page.wait_for_timeout(500)
    raise Befund("Blöcke bleiben im Ladezustand hängen")


def setze_punkt(page, lat: float, lon: float) -> None:
    page.evaluate(f"() => setzePunkt({lat}, {lon}, true)")
    page.wait_for_timeout(1200)
    warte_geladen(page)
    page.wait_for_timeout(1200)


def text(page, sel: str) -> str:
    return page.eval_on_selector(sel, "e=>e.innerText")


def status(page, block: str) -> str:
    return page.eval_on_selector(f"#status-{block}", "e=>e.textContent").strip()


def fordere(bedingung: bool, meldung: str) -> None:
    if not bedingung:
        raise Befund(meldung)


# --------------------------------------------------------------- Prüfungen


def pruefe_grundgeruest(page) -> str:
    setze_punkt(page, *MARIENPLATZ)
    bloecke = page.eval_on_selector_all(
        ".block", "e=>e.map(x=>x.id.replace('block-',''))")
    for pflicht in ("kopf", "bevoelkerung", "wohnen", "gastronomie", "gehweg",
                    "dynamik", "laerm", "overture",
                    "umfeld", "verkehr", "gtfs", "leerstand", "quellen", "grenzen"):
        fordere(pflicht in bloecke, f"Block fehlt: {pflicht}")

    for block in ("kopf", "bevoelkerung", "wohnen", "gastronomie"):
        st = status(page, block)
        fordere(st not in ("lädt …", ""), f"Block {block} ohne Status: {st!r}")

    kopf = text(page, "#inhalt-kopf")
    fordere("München" in kopf, "Gemeinde fehlt im Kopf")
    fordere("09162000" in kopf, "Gemeindeschlüssel fehlt")
    return f"{len(bloecke)} Blöcke, Kopf mit Gemeinde und AGS"


def pruefe_quellenangaben(page) -> str:
    """Spec §5: jeder Block nennt Quelle, Stand und Lizenz."""
    ohne = page.eval_on_selector_all(
        ".block",
        """e => e.filter(b => {
            const id = b.id.replace('block-', '');
            if (['grenzen', 'gehweg', 'liefergebiet', 'bodenrichtwert'].includes(id)) return false;
            return !b.querySelector('.quelle');
        }).map(b => b.id)""")
    fordere(not ohne, f"Blöcke ohne Quellenangabe: {ohne}")
    q = text(page, "#block-gastronomie .quelle")
    fordere("ODbL" in q, "Lizenz fehlt bei der Gastronomie")
    fordere("OpenStreetMap" in q, "Quelle fehlt bei der Gastronomie")
    return "alle Blöcke mit Quelle, Stand und Lizenz"


def pruefe_wettbewerb_nach_entfernung(page) -> str:
    t = text(page, "#inhalt-gastronomie")
    for pflicht in ("Wettbewerbsdichte nach Entfernung", "150 m", "300 m",
                    "nächster Betrieb"):
        fordere(pflicht in t, f"Gastronomieblock, fehlt: {pflicht}")
    return "Entfernungsstaffelung vorhanden"


def pruefe_franchise(page) -> str:
    """Systemgastronomie-Block und Gebietsschutz-Suche (Franchise-Sicht)."""
    t = text(page, "#inhalt-franchise")
    fordere("Kettenanteil" in t, "Kettenanteil fehlt im Franchiseblock")
    fordere("Gebietsschutz" in t, "der Gebietsschutz-Abschnitt fehlt")
    fordere("Konkurrenz" in t, "der Doppelcharakter (Frequenzindiz UND Konkurrenz) fehlt")
    zeilen = page.eval_on_selector_all("#inhalt-franchise table tr", "e=>e.length")
    fordere(zeilen > 3, f"Markentabelle am Marienplatz zu klein: {zeilen} Zeilen")

    page.evaluate("""() => {
        document.getElementById('marke-name').value = "McDonald's";
        document.getElementById('marke-radius').value = '5000';
    }""")
    page.click("#btn-marke")
    for _ in range(120):
        e = text(page, "#marke-ergebnis")
        if "Nächster" in e or "Nicht erreichbar" in e or "gefunden" in e:
            break
        page.wait_for_timeout(500)
    e = text(page, "#marke-ergebnis")
    if "Nicht erreichbar" in e:
        return "übersprungen — Overpass für die Markensuche nicht erreichbar"
    fordere("Nächster eigener Betrieb" in e, f"Markensuche ohne Ergebnis: {e[:80]}")
    fordere("Vertrag" in e, "der Hinweis „Karte, nicht Vertrag“ fehlt")
    n = page.evaluate("() => state.ebenen.marke.getLayers().length")
    fordere(n > 0, "die Treffer fehlen als Marker auf der Karte")
    return f"Markentabelle mit {zeilen} Zeilen, Markensuche {n} Treffer auf der Karte"


def pruefe_gtfs_mittagsfenster(page) -> str:
    t = text(page, "#inhalt-gtfs")
    if "Kein GTFS-Fahrplan importiert" in t:
        return "übersprungen — kein Fahrplan importiert"
    fordere("11–14 Uhr" in t, "Mittagsfenster fehlt im ÖPNV-Block")
    fordere("17–22 Uhr" in t, "Abendfenster fehlt im ÖPNV-Block")
    return "Mittags- und Abendfenster ausgewiesen"


def pruefe_einkommen(page) -> str:
    """Verfügbares Einkommen (Kreisebene) — die ehrliche Kaufkraft-Näherung."""
    st = status(page, "einkommen")
    if st not in ("geladen", "ok"):
        return f"übersprungen — Regionalatlas nicht erreichbar ({st})"
    t = text(page, "#inhalt-einkommen")
    fordere("€/Einw." in t, "Einkommenswerte fehlen")
    fordere("Deutschland" in t, "der Bundesvergleich fehlt")
    fordere("Kreiswert" in t, "die Grenze (Kreisebene, keine Viertel) fehlt")
    q = text(page, "#block-einkommen .quelle")
    fordere("VGRdL" in q or "Gesamtrechnungen" in q, "Quellenangabe fehlt")
    return "Kreis-, Landes- und Bundeswert mit Kreisebenen-Hinweis"


def pruefe_kreisprofil(page) -> str:
    """Block 3c: vier Themen aus dem Regionalatlas, Kreis/Land/Bund je Zeile,
    und der Einpendler-Deutungssatz für München (ET > 1.000 je 1.000)."""
    fordere(status(page, "kreisprofil") == "geladen",
            f"Kreisprofil-Status: {status(page, 'kreisprofil')!r}")
    # innerText liefert die GERENDERTE Schrift — die Themenzeilen sind per
    # CSS in Großbuchstaben gesetzt, deshalb wird kleingeschrieben verglichen.
    inhalt = text(page, "#inhalt-kreisprofil")
    klein = inhalt.lower()
    for begriff in ("tourismus", "erwerbstätige am arbeitsort", "arbeitsmarkt",
                    "bevölkerung", "arbeitslosenquote"):
        fordere(begriff in klein, f"Kreisprofil ohne {begriff!r}")
    fordere("Einpendler" in inhalt,
            "Für München muss der Einpendler-Deutungssatz erscheinen")
    fordere("eigenes Datenjahr" in inhalt, "Datenjahr-Warnung fehlt")
    zeilen = page.eval_on_selector_all(
        "#inhalt-kreisprofil table.daten tr", "e=>e.length")
    fordere(zeilen >= 9, f"nur {zeilen} Tabellenzeilen im Kreisprofil")
    return f"{zeilen} Zeilen, Deutungssatz und Datenjahr-Hinweis vorhanden"


def pruefe_pendler(page) -> str:
    """Block 3d: Gemeinde-Pendlerzahlen samt Top-Verflechtungen mit km."""
    fordere(status(page, "pendler") == "geladen",
            f"Pendler-Status: {status(page, 'pendler')!r}")
    inhalt = text(page, "#inhalt-pendler")
    for begriff in ("Einpendler", "Auspendler", "Pendlersaldo",
                    "Wichtigste Herkünfte", "Wichtigste Ziele", "km"):
        fordere(begriff in inhalt, f"Pendlerblock ohne {begriff!r}")
    fordere("gewinnt tagsüber" in inhalt,
            "München hat Einpendlerüberschuss — der Deutungssatz muss das sagen")
    fordere("Gemeindewert" in inhalt, "Gemeindewert-Warnung fehlt")
    return "Kennzahlen, Verflechtungen und Deutungssatz vorhanden"


def pruefe_klima(page) -> str:
    """Block 5b: fünf DWD-Kennzahlen, jede mit Station und Entfernung,
    dazu die Monatsbalken der Sommertage."""
    fordere(status(page, "klima") == "geladen",
            f"Klima-Status: {status(page, 'klima')!r}")
    inhalt = text(page, "#inhalt-klima")
    for begriff in ("Sommertage", "Sonnenscheindauer", "Niederschlag",
                    "1991–2020", "km"):
        fordere(begriff in inhalt, f"Klimablock ohne {begriff!r}")
    fordere("München" in inhalt, "Stationsname fehlt")
    balken = page.eval_on_selector_all(
        "#inhalt-klima div[title*='Tage']", "e=>e.length")
    fordere(balken == 12, f"{balken} statt 12 Monatsbalken")
    return "5 Kennzahlen mit Station, 12 Monatsbalken"


def pruefe_dynamik(page) -> str:
    """Block 4e: Jahresreihe der Gastro-Objekte mit Balken, Tabelle und der
    zentralen Kartierer-Warnung."""
    fordere(status(page, "dynamik") != "", "Dynamik-Block ohne Status")
    inhalt = text(page, "#inhalt-dynamik")
    for begriff in ("Gastro-Objekte", "Veränderung", "Kartierer"):
        fordere(begriff in inhalt, f"Dynamikblock ohne {begriff!r}")
    balken = page.eval_on_selector_all(
        "#dynamik-balken div", "e=>e.length")
    fordere(balken >= 5, f"nur {balken} Jahresbalken")
    zeilen = page.eval_on_selector_all(
        "#inhalt-dynamik table.daten tr", "e=>e.length")
    fordere(zeilen >= 6, f"nur {zeilen} Tabellenzeilen")
    return f"{balken} Jahresbalken, {zeilen - 1} Jahre in der Tabelle, Warnung vorhanden"


def pruefe_laerm(page) -> str:
    """Block 6f: am Marienplatz (keine Hauptverkehrsstraße) ist „nicht
    kartiert" das erwartete, ehrlich beschriftete Ergebnis."""
    st = status(page, "laerm")
    fordere(st in ("geladen", "nicht kartiert"), f"Lärm-Status: {st!r}")
    inhalt = text(page, "#inhalt-laerm")
    fordere("Hauptverkehrsstraße" in inhalt or "Hauptverkehrsstraßen" in inhalt,
            "Lärmblock ohne Hauptverkehrsstraßen-Einordnung")
    if st == "geladen":
        fordere("dB(A)" in inhalt and "Kartierung" in inhalt,
                "Wert ohne Einheit oder Kartierungsjahr")
        return "Pegel mit Kartierungsjahr angezeigt"
    fordere("keine kartierte" in inhalt, "„nicht kartiert“ ohne Erklärung")
    return "nicht kartiert — mit ehrlicher Erklärung"


def pruefe_oeffnungsluecken(page) -> str:
    """Sonntags- und Abendlücke im Gastronomieblock — als Mindestzahlen."""
    inhalt = text(page, "#inhalt-gastronomie")
    fordere("Öffnungszeiten-Lücken" in inhalt, "Lücken-Abschnitt fehlt")
    fordere("Mindestzahlen" in inhalt, "Mindestzahlen-Beschriftung fehlt")
    kacheln = page.eval_on_selector_all(
        "#oeffnungsluecken .kennzahl", "e=>e.length")
    fordere(kacheln == 4, f"{kacheln} statt 4 Kennzahlen")
    fordere("Sonntags geöffnet" in inhalt and "auswertbaren" in inhalt,
            "Sonntagszahl ohne Bezugsgröße")
    return "4 Mindestzahlen mit Bezugsgröße und Hinweis"


def pruefe_kundenprofil(page) -> str:
    """Deskriptiver Kundenprofil-Satz im Bevölkerungsblock."""
    fordere(page.query_selector("#kundenprofil") is not None,
            "Kundenprofil-Satz fehlt")
    t = text(page, "#kundenprofil")
    fordere("Größte Altersgruppe" in t and "%" in t, "Satz ohne Altersgruppe")
    fordere("Einpendler" in t or "wohnt" in t,
            "Die Grenze (Wohnbevölkerung ≠ Kundschaft) fehlt")
    return "Größte Altersgruppe samt Grenze benannt"


def pruefe_rad_jahresgang(page) -> str:
    """Jahresgang der nächsten Zählstelle aus den Tages-Rohdaten."""
    st = status(page, "radzaehlung")
    if st != "geladen":
        return f"übersprungen — keine Zählstelle in Reichweite ({st})"
    if not page.query_selector("#rad-jahresgang"):
        raise Befund("Zählstelle geladen, aber kein Jahresgang")
    t = text(page, "#rad-jahresgang")
    fordere("Jahresgang" in t and "Messtage" in t, "Jahresgang ohne Messtage")
    balken = page.eval_on_selector_all(
        "#rad-jahresgang div[title]", "e=>e.length")
    fordere(balken == 12, f"{balken} statt 12 Monatsbalken")
    return f"12 Monatsbalken, {t.split('Messtage')[0].split()[-1]} Messtage"


def pruefe_sensitivitaet(page) -> str:
    """Sensitivität im Schätzungsreiter: Treiber-Tabelle mit Balken und der
    +1-Wettbewerber-Warnung."""
    page.eval_on_selector("#reiter button[data-reiter='schaetzung']", "e=>e.click()")
    page.wait_for_timeout(2500)
    t = text(page, "#panel-schaetzung")
    fordere("Woran die Spanne hängt" in t, "Sensitivitäts-Abschnitt fehlt")
    fordere("Marktanteil" in t and "Durchschnittsbon" in t, "Treiber fehlen")
    fordere("übersehener Wettbewerber" in t, "+1-Wettbewerber-Effekt fehlt")
    balken = page.eval_on_selector_all(".sens-balken", "e=>e.length")
    fordere(balken == 2, f"{balken} statt 2 Treiber-Balken")
    fordere("Wohnungsmiete im Umkreis" in t, "Wohnmiete-Anker-Feld fehlt")
    page.eval_on_selector("#reiter button[data-reiter='daten']", "e=>e.click()")
    page.wait_for_timeout(300)
    return "Treiber-Balken, +1-Effekt und Wohnmiete-Anker vorhanden"


def pruefe_overture(page) -> str:
    """Block 4f: mit Import Kennzahlen + Nur-Overture-Liste, ohne Import die
    Einrichtungs-Anleitung. Beides ist ein gültiger, ehrlicher Zustand."""
    for _ in range(40):
        st = status(page, "overture")
        if st not in ("lädt …", ""):
            break
        page.wait_for_timeout(500)
    inhalt = text(page, "#inhalt-overture")
    if st == "kein Import":
        fordere("import-overture" in inhalt, "Anleitung fehlt im Leerzustand")
        return "übersprungen — kein Overture-Import auf dieser Maschine"
    fordere(st == "geladen", f"Overture-Status: {st!r}")
    for begriff in ("OSM (Untergrenze)", "nur in Overture", "kombiniert",
                    "Verlässlichkeit"):
        fordere(begriff in inhalt, f"Overture-Block ohne {begriff!r}")
    eintraege = page.eval_on_selector_all(
        "#inhalt-overture .liste li.springbar", "e=>e.length")
    fordere(eintraege > 0, "keine ansteuerbaren Nur-Overture-Einträge")
    # Schätzungsreiter: die kombinierte Zahl wird angeboten, nie gesetzt.
    page.eval_on_selector("#reiter button[data-reiter='schaetzung']", "e=>e.click()")
    page.wait_for_timeout(2000)
    fordere(page.query_selector("#overture-angebot") is not None,
            "kombinierte Wettbewerberzahl wird nicht angeboten")
    page.eval_on_selector("#reiter button[data-reiter='daten']", "e=>e.click()")
    page.wait_for_timeout(300)
    return f"Kennzahlen, {eintraege} ansteuerbare Einträge, Schätzungs-Angebot"


def pruefe_snack_verkauf(page) -> str:
    inhalt = text(page, "#inhalt-gastronomie")
    fordere("Snack-Verkauf" in inhalt, "Snack-Verkauf-Abschnitt fehlt")
    fordere("Ladengeschäfte" in inhalt and "Gastro-Gesamtzahl" in inhalt,
            "Die Abgrenzung (Läden, nicht in der Gesamtzahl) fehlt")
    return "eigene Kategorie mit ehrlicher Abgrenzung"


def pruefe_leerstand_sprung(page) -> str:
    """Klick auf einen Leerstand-Eintrag: Karte springt hin, Ring erscheint."""
    if not page.query_selector("#inhalt-leerstand .liste li.springbar"):
        return "übersprungen — keine Leerstände am Testpunkt"
    ziel = page.eval_on_selector(
        "#inhalt-leerstand .liste li.springbar", "e => { e.click(); return e.innerText; }")
    page.wait_for_timeout(600)
    zoom = page.evaluate("() => karte.getZoom()")
    fordere(zoom >= 18, f"Karte zoomt nicht heran (Zoom {zoom})")
    ring = page.evaluate("() => !!sprungRing")
    fordere(ring, "Hervorhebungsring fehlt nach dem Klick")
    inhalt = text(page, "#inhalt-leerstand")
    fordere("Klick auf einen Eintrag" in inhalt, "Bedienhinweis fehlt")
    return f"Sprung mit Ring und Zoom {zoom} — Eintrag: {ziel.splitlines()[0][:40]}"


def pruefe_branchenprofil(page) -> str:
    """Das Profil filtert die vorhandenen OSM-Daten um — ohne neue Abfrage."""
    alle = page.evaluate("""() => {
        const s = document.querySelector('#inhalt-gastronomie .branche select');
        s.value = 'alle'; s.dispatchEvent(new Event('change'));
        return document.querySelector('#inhalt-gastronomie .branche .kennzahlen')
            .innerText;
    }""")
    bar = page.evaluate("""() => {
        const s = document.querySelector('#inhalt-gastronomie .branche select');
        s.value = 'bar'; s.dispatchEvent(new Event('change'));
        return document.querySelector('#inhalt-gastronomie .branche .kennzahlen')
            .innerText;
    }""")
    fordere("Direkter Wettbewerb" in bar, "Profil-Kennzahlen fehlen")
    fordere(alle != bar, "Profilwechsel muss die Zählung ändern")
    hinweis = text(page, "#inhalt-gastronomie .branche")
    fordere("cuisine" in hinweis, "Der Freitext-Hinweis zu cuisine muss stehen")
    page.evaluate("""() => {
        const s = document.querySelector('#inhalt-gastronomie .branche select');
        s.value = 'alle'; s.dispatchEvent(new Event('change'));
    }""")
    return "Profilwechsel ändert die Zählung, cuisine-Hinweis steht"


def pruefe_duell(page) -> str:
    """Duell-Bericht: zwei Punkte Spalte an Spalte, beide Lagekarten."""
    ids = []
    for label, (lat, lon) in (("TESTPUNKT Duell A", MARIENPLATZ),
                              ("TESTPUNKT Duell B", GIESING)):
        pid = page.evaluate("""async ([label, lat, lon]) => {
            const r = await fetch('/api/points', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ label, lat, lon, radius: 600 }) });
            return (await r.json()).id;
        }""", [label, lat, lon])
        ids.append(pid)
    seite = page.context.browser.new_page(viewport={"width": 1200, "height": 1400})
    fehler: list[str] = []
    seite.on("pageerror", lambda e: fehler.append(str(e)))
    try:
        seite.goto(f"{page.url.split('/#')[0].rstrip('/')}/duell?a={ids[0]}&b={ids[1]}",
                   wait_until="domcontentloaded")
        seite.wait_for_timeout(4000)
        inhalt = seite.eval_on_selector("#duell", "e=>e.innerText")
        fordere("Duell" in inhalt and "Differenz" in inhalt,
                "Duell-Kopf oder Differenzspalte fehlt")
        karten = seite.eval_on_selector_all(
            ".duell-karte.leaflet-container", "e=>e.length")
        fordere(karten == 2, f"{karten} statt 2 Lagekarten")
        fordere("keine Wertung" in inhalt, "Der Fakt-nicht-Wertung-Hinweis fehlt")
        fordere(not fehler, f"JS-Fehler auf der Duellseite: {fehler}")
    finally:
        seite.close()
        for pid in ids:
            page.evaluate(
                "async (pid) => { await fetch(`/api/points/${pid}`, { method: 'DELETE' }); }",
                pid)
    return "2 Lagekarten, Differenzspalte, Hinweis — ohne JS-Fehler"


def pruefe_punkte_ebene(page) -> str:
    """Gemerkte Punkte als Kartenebene, Überlappungsrechnung."""
    # Reine Geometrie der Überlappungsfunktion — 200 m Abstand bei 600-m-Radien
    # überlappen, 3 km nicht.
    befund = page.evaluate("""() => {
        const eng = ueberlappungen([
            { label: 'A', lat: 48.10, lon: 11.50, radius: 600 },
            { label: 'B', lat: 48.1018, lon: 11.50, radius: 600 }]);
        const weit = ueberlappungen([
            { label: 'A', lat: 48.10, lon: 11.50, radius: 600 },
            { label: 'C', lat: 48.127, lon: 11.50, radius: 600 }]);
        return { eng: eng.length, weit: weit.length, um: eng[0]?.um_m };
    }""")
    fordere(befund["eng"] == 1 and befund["weit"] == 0,
            f"Überlappungsrechnung falsch: {befund}")
    fordere(900 < befund["um"] < 1100, f"Überlappungsmaß unplausibel: {befund['um']}")

    page.evaluate("""() => {
        state.ebenen.punkte.addTo(karte);
        karte.fire('overlayadd', { layer: state.ebenen.punkte });
    }""")
    page.wait_for_timeout(1500)
    n = page.evaluate("() => state.ebenen.punkte.getLayers().length")
    fordere(n >= 4, f"zu wenige Ebenenobjekte für die Testpunkte: {n}")
    etiketten = page.eval_on_selector_all(
        ".punkt-etikett", "e=>e.map(x=>x.textContent)")
    fordere(any("UI-Testpunkt" in e for e in etiketten),
            f"Punktetiketten fehlen auf der Karte: {etiketten}")
    page.evaluate("""() => {
        karte.removeLayer(state.ebenen.punkte);
        karte.fire('overlayremove', { layer: state.ebenen.punkte });
    }""")
    page.wait_for_timeout(400)
    fordere(page.evaluate("() => state.ebenen.punkte.getLayers().length") == 0,
            "Abschalten leert die Punktebene nicht")
    return f"{n} Objekte (Kreise + Etiketten), Überlappung um {befund['um']} m erkannt"


def pruefe_schaetzung_getrennt(page) -> str:
    """Spec §9: keine geschätzte Zahl im Datenreiter."""
    daten = text(page, "#panel")
    for verboten in ("Jahresumsatz", "Bestellungen je"):
        fordere(verboten not in daten,
                f"Schätzgröße „{verboten}“ steht im Datenreiter")

    page.click("#reiter button[data-reiter=schaetzung]")
    page.wait_for_timeout(2000)
    s = text(page, "#panel-schaetzung")
    fordere("keine Prognose" in s, "Schätzungsreiter ohne Warnhinweis")
    fordere("bis" in s, "Ergebnis ist kein Spannenwert")
    fordere("frei gewählt" in s, "Annahmen ohne Datengrundlage nicht markiert")

    # Prüfstein: ein bekannter Umsatz muss gegenübergestellt werden, ohne in
    # die Rechnung einzugehen.
    fordere(page.query_selector("#sf-kalib-umsatz") is not None,
            "Prüfstein-Feld fehlt im Schätzungsreiter")
    vorher = text(page, "#schaetz-ergebnis")
    page.eval_on_selector("#sf-kalib-umsatz", """e => {
        e.value = 450000; e.dispatchEvent(new Event('input', { bubbles: true }));
    }""")
    page.wait_for_timeout(1500)
    k = text(page, "#kalib-ergebnis")
    fordere("Verhältnis" in k, f"Prüfstein rechnet nicht: {k[:70]}")
    fordere(text(page, "#schaetz-ergebnis") == vorher,
            "der Prüfstein darf das Ergebnis nicht verändern")

    page.click("#reiter button[data-reiter=daten]")
    page.wait_for_timeout(600)
    return "Schätzung getrennt, Spanne, Prüfstein wirkt ohne einzugreifen"


def pruefe_deckkraftregler(page) -> str:
    fordere(page.query_selector("#deckkraft") is not None, "Deckkraftregler fehlt")

    def gitter():
        return page.evaluate("""() => {
            const ps = [...document.querySelectorAll('#karte path[stroke-width="0.6"]')];
            return ps.length ? Number(ps[0].getAttribute('fill-opacity')) : null;
        }""")

    voll = gitter()
    fordere(voll is not None, "keine Zensuszellen auf der Karte")
    page.eval_on_selector("#deckkraft", """e => {
        e.value = 40; e.dispatchEvent(new Event('input', { bubbles: true }));
    }""")
    page.wait_for_timeout(600)
    schwach = gitter()
    fordere(abs(schwach - voll * 0.4) < 0.02,
            f"Regler wirkt nicht: {voll} -> {schwach}")

    grund = page.evaluate("() => osmKarte.options.opacity")
    fordere(grund in (None, 1),
            "die Grundkarte darf der Regler nicht zurückblenden")

    page.eval_on_selector("#deckkraft", """e => {
        e.value = 100; e.dispatchEvent(new Event('input', { bubbles: true }));
    }""")
    page.wait_for_timeout(400)
    return f"Gitter {voll} → {schwach} bei 40 %, Grundkarte unberührt"


def pruefe_gehweg(page) -> str:
    """Block 4b lädt nur auf Anforderung und zeichnet die erreichbare Fläche."""
    setze_punkt(page, *ISARUFER)
    fordere("anforder" in status(page, "gehweg").lower(),
            "Gehwegblock lädt ungefragt — das Wegenetz ist die größte Abfrage")
    fordere(page.evaluate("() => state.ebenen.gehflaeche.getLayers().length") == 0,
            "Fläche liegt schon vor der Berechnung auf der Karte")

    page.click("#btn-gehweg")
    for _ in range(240):
        if status(page, "gehweg") != "lädt …":
            break
        page.wait_for_timeout(500)
    st = status(page, "gehweg")
    if st != "geladen":
        return f"übersprungen — Dienst nicht verfügbar ({st})"

    t = text(page, "#inhalt-gehweg")
    for pflicht in ("Erschließungsgrad", "Umwegfaktor", "nicht dasselbe Gebiet",
                    "Auf der Karte"):
        fordere(pflicht in t, f"Gehwegblock, fehlt: {pflicht}")

    n = page.evaluate("() => state.ebenen.gehflaeche.getLayers().length")
    fordere(n > 50, f"zu wenige Punkte in der erreichbaren Fläche: {n}")
    zu_weit = page.evaluate("""() => {
        let n = 0;
        state.ebenen.gehflaeche.eachLayer(l => {
            if (L.latLng(state.lat, state.lon).distanceTo(l.getLatLng())
                > state.radius + 5) n++;
        });
        return n;
    }""")
    fordere(zu_weit == 0,
            f"{zu_weit} erreichbare Punkte liegen außerhalb des Radius")

    # Punktwechsel muss die Fläche löschen, sonst behauptet sie etwas Falsches.
    setze_punkt(page, *GIESING)
    rest = page.evaluate("() => state.ebenen.gehflaeche.getLayers().length")
    fordere(rest == 0, f"alte Gehfläche bleibt liegen: {rest} Punkte")
    return f"{n} Punkte gezeichnet, beim Punktwechsel geleert"


def pruefe_gehwegangebot_in_der_schaetzung(page) -> str:
    """Die engere Zahl wird angeboten, aber nicht stillschweigend gesetzt."""
    setze_punkt(page, *ISARUFER)
    page.click("#reiter button[data-reiter=schaetzung]")
    page.wait_for_timeout(2500)
    if not page.query_selector("#gehweg-angebot"):
        page.click("#reiter button[data-reiter=daten]")
        page.wait_for_timeout(600)
        return "übersprungen — für diesen Punkt sind keine Gehstrecken berechnet"

    vorgabe = page.eval_on_selector("#sf-einwohner", "e=>Number(e.value)")
    t = text(page, "#gehweg-angebot")
    fordere("überschätzt" in t, "das Angebot benennt den Fehler nicht")
    page.click("#btn-gehweg-uebernehmen")
    page.wait_for_timeout(1200)
    danach = page.eval_on_selector("#sf-einwohner", "e=>Number(e.value)")
    fordere(danach < vorgabe,
            f"Übernehmen ändert die Einwohnerzahl nicht: {vorgabe} -> {danach}")
    page.click("#reiter button[data-reiter=daten]")
    page.wait_for_timeout(600)
    return f"angeboten und übernommen: {vorgabe} → {danach} Einwohner"


def pruefe_vergleich(page) -> str:
    page.click("#btn-vergleich")
    page.wait_for_timeout(1500)
    leer = "Noch kein Punkt gemerkt" in text(page, "#vergleich-inhalt")
    if leer:
        page.eval_on_selector("#vergleich-zu", "e=>e.click()")
        return "übersprungen — keine gemerkten Punkte vorhanden"

    def spalten():
        return page.eval_on_selector_all(
            "#vergleich-inhalt tr:nth-child(2) th",
            "e=>e.map(x=>x.innerText.trim()).filter(Boolean)")

    vorher = len(spalten())
    gruppen = page.eval_on_selector_all(".gruppenwahl label", "e=>e.length")
    fordere(gruppen >= 5, f"nur {gruppen} Spaltengruppen")
    fordere(page.eval_on_selector("#gruppe-standort", "e=>e.disabled"),
            "die Standortgruppe muss unabschaltbar sein")
    fordere(page.eval_on_selector("#vergleich-inhalt td:first-child",
                                  "e=>getComputedStyle(e).position") == "sticky",
            "die Bezeichnungsspalte bleibt beim Scrollen nicht stehen")

    page.click("#gruppe-erreichbarkeit")
    page.wait_for_timeout(900)
    nachher = len(spalten())
    fordere(nachher != vorher, "Gruppenschalter ändert die Tabelle nicht")
    page.click("#gruppe-erreichbarkeit")
    page.wait_for_timeout(700)

    page.eval_on_selector("#vergleich-zu", "e=>e.click()")
    return f"{vorher} Spalten in der Vorgabe, {gruppen} Gruppen schaltbar"


def pruefe_muenchen_erweiterungen(page) -> str:
    setze_punkt(page, *MARIENPLATZ)
    rad = status(page, "radzaehlung")
    vm = status(page, "verkehrsmenge")
    fordere(rad not in ("lädt …", ""), f"Radzählung ohne Status: {rad!r}")
    fordere(vm not in ("lädt …", ""), f"Verkehrsmenge ohne Status: {vm!r}")
    t = text(page, "#inhalt-verkehrsmenge")
    if "klassifizierte" not in t and "Keine Zählstelle" not in t:
        fordere("Schwerverkehr" in t, "Verkehrsmengenblock ohne Inhalt")
    return f"Radzählung {rad}, Verkehrsmenge {vm}"


def pruefe_verkehrszaehler(page) -> str:
    """Overpass und Nominatim sind Spendenprojekte — die Last muss sichtbar sein."""
    t = text(page, "#fuss-stats")
    fordere("Cache:" in t, "Cachestand fehlt in der Fußzeile")
    fordere("24 h" in t, "Die Last der letzten 24 Stunden fehlt in der Fußzeile")
    titel = page.eval_on_selector_all(
        "#fuss-stats span", "e=>e.map(x=>x.title).filter(Boolean)")
    fordere(any("Letzte 24 h" in x for x in titel),
            "keine Aufschlüsselung je Dienst im Tooltip")
    fordere("null" not in t, f"ein null-Argument wurde als Text gerendert: {t[-40:]}")
    return t.replace("\n", " ")[:90]


def pruefe_planung_und_hochwasser(page) -> str:
    """Zwei Fragen, die eine Standortentscheidung kippen können."""
    setze_punkt(page, *ISARAUEN)
    st = status(page, "planung")
    if st not in ("geladen", "ok"):
        return f"übersprungen — Dienst nicht verfügbar ({st})"
    t = text(page, "#inhalt-planung")
    fordere("Hochwassergefahrengebiet" in t,
            f"Hochwasserbefund fehlt in den Isarauen: {t[:80]}")
    fordere("HQ 100" in t, "die Jährlichkeit wird nicht ausgewiesen")
    fordere("§ 34 BauGB" in t,
            "der Hinweis fehlt, dass „kein Plan“ nicht „alles erlaubt“ heißt")

    setze_punkt(page, *FREIHAM)
    if status(page, "planung") == "geladen":
        f = text(page, "#inhalt-planung")
        fordere("A1856" in f, f"Bebauungsplan-Nummer fehlt in Freiham: {f[:90]}")
        fordere("Kein Hochwassergefahrengebiet" in f,
                "Freiham liegt nicht im Hochwassergebiet — das muss dastehen")
    return "Hochwasser HQ 100 in den Isarauen, B-Plan A1856 in Freiham"


def pruefe_eigene_notiz(page) -> str:
    """Das Werkzeug bewertet nicht — der Nutzer darf und soll das aber."""
    page.click("#btn-vergleich")
    page.wait_for_timeout(1500)
    if "Noch kein Punkt gemerkt" in text(page, "#vergleich-inhalt"):
        page.eval_on_selector("#vergleich-zu", "e=>e.click()")
        return "übersprungen — keine gemerkten Punkte vorhanden"

    fordere(page.query_selector("#vergleich-inhalt td.eigen select") is not None,
            "keine Notenauswahl in der Vergleichstabelle")
    fordere(page.query_selector("#vergleich-inhalt td.eigen input") is not None,
            "kein Notizfeld in der Vergleichstabelle")

    page.eval_on_selector("#vergleich-inhalt td.eigen input", """e => {
        e.value = 'Prüfnotiz aus dem Oberflächentest';
        e.dispatchEvent(new Event('change', { bubbles: true }));
    }""")
    page.wait_for_timeout(1200)
    page.eval_on_selector("#vergleich-zu", "e=>e.click()")
    page.wait_for_timeout(600)
    page.click("#btn-vergleich")
    page.wait_for_timeout(1500)
    wert = page.eval_on_selector("#vergleich-inhalt td.eigen input", "e=>e.value")
    page.eval_on_selector("#vergleich-zu", "e=>e.click()")
    fordere("Prüfnotiz" in wert, f"die Notiz wurde nicht gespeichert: {wert!r}")
    return "Note und Notiz vorhanden, Notiz übersteht das Neuöffnen"


def pruefe_uebersichtsgitter(page) -> str:
    """Die Erkundungsebene: ganz Bayern in 10-km-, eine Stadt in 1-km-Zellen."""
    page.evaluate("() => { karte.setView([48.95, 11.4], 8); }")
    page.evaluate("() => { state.ebenen.uebersicht.addTo(karte); }")
    page.evaluate("() => { karte.fire('overlayadd', { layer: state.ebenen.uebersicht }); }")
    for _ in range(120):
        if page.evaluate("() => state.ebenen.uebersicht.getLayers().length") > 0:
            break
        page.wait_for_timeout(500)
    page.wait_for_timeout(1500)
    n10 = page.evaluate("() => state.ebenen.uebersicht.getLayers().length")
    fordere(n10 > 800, f"zu wenige 10-km-Zellen über Bayern: {n10}")
    leg = text(page, "#uebersicht-legende")
    fordere("10-km-Zelle" in leg, f"Legende falsch: {leg[:50]}")
    fordere("feste, gewählte Klassen" in leg,
            "die Legende muss sagen, dass die Klassen gewählt sind")

    page.evaluate("() => { karte.setView([48.145, 11.55], 12); }")
    for _ in range(120):
        if "1-km-Zelle" in text(page, "#uebersicht-legende"):
            break
        page.wait_for_timeout(500)
    page.wait_for_timeout(1500)
    n1 = page.evaluate("() => state.ebenen.uebersicht.getLayers().length")
    fordere(n1 > 300, f"zu wenige 1-km-Zellen über München: {n1}")

    page.evaluate("""() => {
        karte.removeLayer(state.ebenen.uebersicht);
        karte.fire('overlayremove', { layer: state.ebenen.uebersicht });
    }""")
    page.wait_for_timeout(600)
    fordere(page.evaluate("() => state.ebenen.uebersicht.getLayers().length") == 0,
            "Abschalten leert die Ebene nicht")
    return f"Bayern {n10} Zellen (10 km), München {n1} Zellen (1 km)"


def pruefe_flaechenscan(page) -> str:
    """Die feine Erkundungsstufe: Einwohner je Betrieb im 300-m-Umfeld."""
    page.evaluate("() => { karte.setView([48.137, 11.575], 14); }")
    page.wait_for_timeout(400)
    page.evaluate("""() => {
        state.ebenen.scan.addTo(karte);
        karte.fire('overlayadd', { layer: state.ebenen.scan });
    }""")
    for _ in range(180):
        if page.evaluate("() => state.ebenen.scan.getLayers().length") > 1:
            break
        page.wait_for_timeout(500)
    n = page.evaluate("() => state.ebenen.scan.getLayers().length")
    leg = text(page, "#scan-legende") if page.query_selector("#scan-legende") else ""
    if n <= 1:
        page.evaluate("""() => {
            karte.removeLayer(state.ebenen.scan);
            karte.fire('overlayremove', { layer: state.ebenen.scan });
        }""")
        if "nicht möglich" in leg:
            return f"übersprungen — {leg.splitlines()[-1][:70]}"
        raise Befund(f"keine Scanzellen gezeichnet: {leg[:90]}")

    fordere("Einwohner je Gastronomiebetrieb" in leg, "Scanlegende fehlt")
    fordere("Obergrenzen" in leg,
            "die Legende muss benennen, dass OSM eine Untergrenze zählt")
    fordere("kein Betrieb im Umfeld" in leg,
            "die Sonderklasse „kein Betrieb im Umfeld“ fehlt in der Legende")

    # Schwenken darf NICHT ungefragt neu scannen (jeder Scan ist eine echte
    # Overpass-Abfrage) — stattdessen bietet die Legende den Knopf an.
    page.evaluate("() => { karte.panBy([1200, 0], { animate: false }); }")
    page.wait_for_timeout(1500)
    fordere(page.query_selector("#scan-legende .scan-knopf") is not None,
            "nach dem Schwenken fehlt der Knopf „Diesen Ausschnitt scannen“")
    danach = page.evaluate("() => state.ebenen.scan.getLayers().length")
    fordere(danach == n, f"Schwenken hat ungefragt neu gescannt: {n} -> {danach}")

    page.evaluate("""() => {
        karte.removeLayer(state.ebenen.scan);
        karte.fire('overlayremove', { layer: state.ebenen.scan });
    }""")
    page.wait_for_timeout(600)
    fordere(page.evaluate("() => state.ebenen.scan.getLayers().length") == 0,
            "Abschalten leert die Scanebene nicht")
    fordere(page.query_selector("#scan-legende") is None,
            "die Scanlegende bleibt nach dem Abschalten stehen")
    return f"{n - 1} Zellen plus Scanrahmen, Schwenken fragt statt zu laden"


# Punkte, die die Berichts- und Rankingprüfung selbst anlegen — sie werden am
# Ende wieder gelöscht, damit die Prüfung keine Daten hinterlässt.
TESTPUNKTE: list[int] = []


def pruefe_bericht(page) -> str:
    """Der druckbare Standortbericht zu einem gemerkten Punkt."""
    for label, (lat, lon) in (("UI-Testpunkt Marienplatz", MARIENPLATZ),
                              ("UI-Testpunkt Giesing", GIESING)):
        pid = page.evaluate("""async ([label, lat, lon]) => {
            const r = await fetch('/api/points', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ label, lat, lon, radius: 600 }),
            });
            return (await r.json()).id;
        }""", [label, lat, lon])
        fordere(isinstance(pid, int), f"Punkt {label} ließ sich nicht merken: {pid}")
        TESTPUNKTE.append(pid)

    basis = page.evaluate("() => location.origin")
    # Nicht page.context.new_page(): den von new_page() implizit angelegten
    # Kontext lässt Playwright keine zweite Seite öffnen.
    bericht = page.context.browser.new_page()
    try:
        bericht.goto(f"{basis}/bericht?punkt={TESTPUNKTE[0]}",
                     wait_until="domcontentloaded")
        bericht.wait_for_timeout(2500)
        t = bericht.eval_on_selector("#bericht", "e=>e.innerText")
        fordere("UI-Testpunkt Marienplatz" in t, "der Bericht nennt den Punkt nicht")
        fordere("keine Prognose" in t, "der Warnhinweis fehlt im Bericht")
        fordere("Quellen, Stände, Lizenzen" in t, "die Quellentabelle fehlt")
        fordere("Bekannte Grenzen" in t, "die Grenzen der Daten fehlen im Bericht")
        fordere("ODbL" in t, "die OSM-Lizenz fehlt im Bericht")
        fordere(bericht.query_selector("#bericht button") is not None,
                "der Druckknopf fehlt")
        fordere(bericht.query_selector("#bericht-karte.leaflet-container") is not None,
                "die Lagekarte fehlt im Bericht")
        marker = bericht.eval_on_selector_all(
            "#bericht-karte path", "e=>e.length")
        fordere(marker > 10, f"zu wenige Wettbewerber auf der Berichtskarte: {marker}")
    finally:
        bericht.close()

    # Der Weg dorthin: die Vergleichstabelle verlinkt je Zeile den Bericht.
    page.click("#btn-vergleich")
    page.wait_for_timeout(1500)
    links = page.eval_on_selector_all(
        "#vergleich-inhalt td.aktionen a", "e=>e.map(x=>x.getAttribute('href'))")
    fordere(any(h and h.startswith("/bericht?punkt=") for h in links),
            f"kein Berichtslink in der Vergleichstabelle: {links}")
    page.eval_on_selector("#vergleich-zu", "e=>e.click()")
    return "Bericht mit Punkt, Warnhinweis, Quellen und Grenzen; Link in der Tabelle"


def pruefe_ranking(page) -> str:
    """Gewichtetes Ranking: Punktzahl nur aus Nutzergewichten, offen ausgewiesen."""
    page.click("#btn-vergleich")
    page.wait_for_timeout(1500)
    try:
        fordere(page.query_selector("details.ranking") is not None,
                "der Rankingbereich fehlt im Vergleichsdialog")
        page.eval_on_selector("details.ranking", "e => { e.open = true; }")
        page.wait_for_timeout(400)
        t = text(page, "details.ranking")
        fordere("keine Empfehlung" in t,
                "das Ranking muss sagen, dass die Punktzahl keine Empfehlung ist")
        zeilen = page.eval_on_selector_all(
            "#ranking-ausgabe table tr", "e=>e.length")
        fordere(zeilen >= 3, f"Rankingtabelle zu klein: {zeilen} Zeilen")

        spalten_vorher = page.eval_on_selector_all(
            "#ranking-ausgabe table tr:first-child th", "e=>e.length")
        # Gewicht der ersten Kennzahl auf 0 — ihre Spalte muss verschwinden.
        page.eval_on_selector(".ranking-gewichte input", """e => {
            e.value = 0; e.dispatchEvent(new Event('input', { bubbles: true }));
        }""")
        page.wait_for_timeout(500)
        spalten_nachher = page.eval_on_selector_all(
            "#ranking-ausgabe table tr:first-child th", "e=>e.length")
        fordere(spalten_nachher == spalten_vorher - 1,
                f"Gewicht 0 nimmt die Kennzahl nicht heraus: "
                f"{spalten_vorher} -> {spalten_nachher}")
        page.eval_on_selector(".ranking-gewichte input", """e => {
            e.value = 1; e.dispatchEvent(new Event('input', { bubbles: true }));
        }""")
        page.wait_for_timeout(300)
    finally:
        page.eval_on_selector("#vergleich-zu", "e=>e.click()")
        # Aufräumen: die von der Prüfung angelegten Punkte wieder löschen.
        for pid in TESTPUNKTE:
            page.evaluate(
                "async (pid) => { await fetch(`/api/points/${pid}`,"
                " { method: 'DELETE' }); }", pid)
        TESTPUNKTE.clear()
    return "Punktzahl offen hergeleitet, Gewicht 0 blendet die Kennzahl aus"


def pruefe_bodenrichtwert_ebene(page) -> str:
    """In Nordrhein-Westfalen gibt es einen abfragbaren Landesdienst."""
    setze_punkt(page, *KOELN)
    page.wait_for_timeout(2500)
    over = page.eval_on_selector_all(
        ".leaflet-control-layers-overlays label span span",
        "e=>e.map(x=>x.textContent.trim())")
    treffer = [o for o in over if "Bodenrichtwert" in o]
    fordere(treffer, f"keine Bodenrichtwert-Ebene in NRW: {over}")
    return f"Ebene vorhanden: {treffer[0]}"


PRUEFUNGEN = [
    ("Grundgerüst und Blöcke", pruefe_grundgeruest),
    ("Quelle, Stand, Lizenz je Block", pruefe_quellenangaben),
    ("Wettbewerb nach Entfernung", pruefe_wettbewerb_nach_entfernung),
    ("Verfügbares Einkommen (Kreis)", pruefe_einkommen),
    ("Kreisprofil (Regionalatlas)", pruefe_kreisprofil),
    ("Pendler (Gemeinde)", pruefe_pendler),
    ("Klima für Außengastronomie (DWD)", pruefe_klima),
    ("Gastro-Dynamik (OSM-Historie)", pruefe_dynamik),
    ("Straßenlärm (LfU Bayern)", pruefe_laerm),
    ("Öffnungszeiten-Lücken", pruefe_oeffnungsluecken),
    ("Kundenprofil-Satz", pruefe_kundenprofil),
    ("Radzählstellen-Jahresgang", pruefe_rad_jahresgang),
    ("Leerstand: Adresse und Kartensprung", pruefe_leerstand_sprung),
    ("Wettbewerbs-Abgleich (Overture)", pruefe_overture),
    ("Snack-Verkauf (Ladengeschäfte)", pruefe_snack_verkauf),
    ("Sensitivität und Wohnmiete-Anker", pruefe_sensitivitaet),
    ("Branchenprofil im Gastronomieblock", pruefe_branchenprofil),
    ("Systemgastronomie & Gebietsschutz", pruefe_franchise),
    ("ÖPNV-Mittags- und Abendfenster", pruefe_gtfs_mittagsfenster),
    ("Schätzung im eigenen Reiter", pruefe_schaetzung_getrennt),
    ("Deckkraftregler", pruefe_deckkraftregler),
    ("Vergleichstabelle", pruefe_vergleich),
    ("München-Erweiterungen", pruefe_muenchen_erweiterungen),
    ("Verkehrszähler in der Fußzeile", pruefe_verkehrszaehler),
    ("Erreichbarkeit zu Fuß", pruefe_gehweg),
    ("Gehwegzahl in der Schätzung", pruefe_gehwegangebot_in_der_schaetzung),
    ("Übersichtsgitter (Erkundung)", pruefe_uebersichtsgitter),
    ("Flächen-Scan (Einwohner je Betrieb)", pruefe_flaechenscan),
    ("Planung und Hochwasser", pruefe_planung_und_hochwasser),
    ("Standortbericht", pruefe_bericht),
    ("Duell-Bericht A gegen B", pruefe_duell),
    ("Gemerkte Punkte auf der Karte", pruefe_punkte_ebene),
    ("Eigene Notiz und Note", pruefe_eigene_notiz),
    ("Gewichtetes Ranking", pruefe_ranking),
    ("Bodenrichtwert-Ebene (NRW)", pruefe_bodenrichtwert_ebene),
]


# ------------------------------------------------------------------ Lauf


def chromium_pfad() -> str | None:
    for p in CHROMIUM_PFADE:
        if Path(p).exists():
            return p
    return None


def main(argv: list[str]) -> int:
    basis = argv[1] if len(argv) > 1 else "http://127.0.0.1:8000"
    basis = basis.rstrip("/")

    try:
        with urllib.request.urlopen(f"{basis}/api/health", timeout=10):
            pass
    except (urllib.error.URLError, OSError) as exc:
        print(f"Server unter {basis} nicht erreichbar: {exc}")
        print("Erst starten:  gastroviewer serve --port 8011 &")
        return 2

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright fehlt — Oberfläche NICHT geprüft.")
        print("  pip install playwright && playwright install chromium")
        return 3

    startargs: dict = {"args": ["--no-sandbox"]}
    pfad = chromium_pfad()
    if pfad:
        startargs["executable_path"] = pfad
    proxy = os.environ.get("HTTPS_PROXY")
    if proxy:
        # Der lokale Server darf nicht über den Proxy laufen.
        startargs["proxy"] = {"server": proxy, "bypass": "127.0.0.1,localhost"}

    print(f"Oberflächenprüfung gegen {basis}")
    print("=" * 72)

    befunde: list[str] = []
    uebersprungen = 0

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(**startargs)
        except Exception as exc:  # noqa: BLE001
            print(f"Chromium lässt sich nicht starten — Oberfläche NICHT geprüft: {exc}")
            print("  playwright install chromium")
            return 3

        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        js_fehler: list[str] = []
        page.on("pageerror", lambda e: js_fehler.append(str(e)))
        page.goto(basis, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        for name, fn in PRUEFUNGEN:
            try:
                ergebnis = fn(page)
                if ergebnis.startswith("übersprungen"):
                    uebersprungen += 1
                    print(f"[ -- ] {name}\n       {ergebnis}")
                else:
                    print(f"[ OK ] {name}\n       {ergebnis}")
            except Befund as b:
                befunde.append(f"{name}: {b}")
                print(f"[FAIL] {name}\n       {b}")
            except Exception as exc:  # noqa: BLE001
                befunde.append(f"{name}: {type(exc).__name__}: {exc}")
                print(f"[FAIL] {name}\n       {type(exc).__name__}: {exc}")

        if js_fehler:
            befunde.append(f"JavaScript-Fehler: {js_fehler}")
            print(f"[FAIL] Fehlerfreies JavaScript\n       {js_fehler}")
        else:
            print("[ OK ] Fehlerfreies JavaScript\n       keine Ausnahme im Browser")

        browser.close()

    print("=" * 72)
    gesamt = len(PRUEFUNGEN) + 1
    if befunde:
        print(f"{len(befunde)} Befund(e) von {gesamt} Prüfungen:")
        for b in befunde:
            print(f"  · {b}")
        return 1
    if uebersprungen:
        print(f"{gesamt - uebersprungen} von {gesamt} Prüfungen ohne Befund, "
              f"{uebersprungen} übersprungen (Daten oder Dienst fehlten).")
    else:
        print(f"Alle {gesamt} Prüfungen ohne Befund.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
