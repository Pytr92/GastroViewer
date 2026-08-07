"""Weiterführende Portale als kontextbezogene Deep-Links.

Spec §4.6: verlinken, nicht abrufen. Wo möglich mit Koordinaten, PLZ oder
Gemeindename vorbefüllt. Die Adressen stammen aus ``notizen-standort-flaeche.md``
(§1–§3 dort) und aus §4.6 der Spec.

Hier wird nichts abgerufen und nichts geschätzt — das ist eine Linksammlung.
Wo eine Lizenz- oder Rechtslage zu beachten ist, steht sie am Eintrag.
"""

from __future__ import annotations

from urllib.parse import quote_plus

from .overpass import build_query

# Städte, deren Zeitreihen das Statistische Bundesamt für seinen Index nutzt
# (Notizen §1). Nur zur Einordnung, ob für den Ort überhaupt Frequenzdaten
# zu erwarten sind.
HYSTREET_INDEXSTAEDTE = [
    "Köln", "Frankfurt am Main", "München", "Hamburg", "Berlin", "Stuttgart",
    "Wiesbaden", "Rostock", "Hannover", "Düsseldorf", "Mainz", "Saarbrücken",
    "Dresden", "Kiel", "Erfurt", "Bremen", "Halle (Saale)", "Leipzig",
    "Dortmund", "Essen", "Nürnberg",
]

BRAUEREI_BOERSEN = [
    ("Paulaner Gruppe", "https://www.pbg-pachtboerse.de/"),
    ("Krombacher", "https://pachtvermittlung.krombacher.de/"),
    ("Bitburger Braugruppe", "https://www.dasgastroportal.de/objektboerse"),
    ("Veltins", "https://www.veltins-gastroportal.de/"),
    ("Warsteiner", "https://www.warsteiner-gruppe.de/"),
    ("Fürstenberg", "https://www.fuerstenberg.de/service/pachtboerse"),
    ("Ayinger (Region München)", "https://www.ayinger.de/"),
    ("Kühbach (Region München)", "https://www.brauereikuehbach.de/pachtobjekte"),
]

MAKLER = [
    ("Comfort", "https://www.comfort.de/"),
    ("Lührmann", "https://www.luehrmann.de/"),
    ("Brockhoff", "https://www.brockhoff.de/"),
    ("Engel & Völkers Commercial", "https://www.engelvoelkers.com/de/commercial/"),
    ("BNP Paribas Real Estate", "https://www.realestate.bnpparibas.de/"),
    ("JLL Retail", "https://www.jll.de/"),
]


def _dd(q: str) -> str:
    return f"https://duckduckgo.com/?q={quote_plus(q)}"


def build(
    lat: float,
    lon: float,
    radius: int,
    *,
    gemeinde: str | None = None,
    plz: str | None = None,
    ags: str | None = None,
) -> list[dict]:
    ort = gemeinde or ""
    ort_q = ort or f"{lat:.4f},{lon:.4f}"
    overpass_query = build_query(lat, lon, radius, timeout=60)

    gruppen: list[dict] = []

    # ---------------------------------------------------------- Statistik
    statistik = [
        {
            "titel": "Zensusatlas 2022",
            "url": "https://atlas.zensus2022.de/",
            "beschreibung": "Gitterkarten im Browser, Schnellcheck ohne GIS.",
        },
        {
            "titel": "Pendleratlas der Bundesagentur für Arbeit",
            "url": "https://statistik.arbeitsagentur.de/DE/Navigation/Statistiken/Interaktive-Statistiken/Pendleratlas/Pendleratlas-Nav.html",
            "beschreibung": "Einpendler je Gemeinde — der Indikator fürs Mittagsgeschäft.",
        },
        {
            "titel": "Beschäftigte am Arbeitsort (BA-Statistik)",
            "url": "https://statistik.arbeitsagentur.de/DE/Navigation/Statistiken/Themen-im-Fokus/Beschaeftigung/Beschaeftigung-Nav.html",
            "beschreibung": "Bürodichte im Umfeld.",
        },
        {
            "titel": "INKAR (BBSR)",
            "url": "https://www.inkar.de/",
            "beschreibung": "Indikatoren für Raumbeobachtung, Kreis- und Gemeindeebene.",
            "warnung": (
                "Geprüft 08/2026: Der Server liefert eine unvollständige "
                "TLS-Zertifikatskette — je nach Browser/Werkzeug schlägt der "
                "Abruf fehl. Deshalb kein Datenblock, nur dieser Link."
            ),
        },
        {
            "titel": "BBSR-Bevölkerungsprognose 2045 (Dashboard)",
            "url": "https://www.bbsr.bund.de/BBSR/DE/daten-karten/"
                   "raumentwicklung/2025/rop2045-bevoelkerung.html",
            "beschreibung": (
                "Der Blick nach vorn je Kreis — Raumordnungsprognose 2045. "
                "Geprüft 08/2026: Zahlen nur im interaktiven Dashboard, keine "
                "stabilen offenen Datei-Endpunkte; deshalb Link statt Block."
            ),
        },
        {
            "titel": "Regionalstatistik der Statistischen Ämter",
            "url": "https://www.regionalstatistik.de/genesis/online",
            "beschreibung": "Amtliche Tabellen bis Gemeindeebene.",
        },
        {
            "titel": "Polizeiliche Kriminalstatistik — Kreistabellen (BKA)",
            "url": "https://www.bka.de/DE/AktuelleInformationen/"
                   "StatistikenLagebilder/PolizeilicheKriminalstatistik/"
                   "PKS2024/PKSTabellen/KreisFalltabellen/kreisfalltabellen.html",
            "beschreibung": (
                "Für Nachtgastronomie relevant. Geprüft 08/2026: nur als "
                "XLSX, kein CSV — und die Häufigkeitszahlen je Kreis sind "
                "laut BKA-Interpretationshilfe nur eingeschränkt vergleichbar "
                "(Anzeigeverhalten, Tatortprinzip). Deshalb Link statt Block."
            ),
        },
    ]
    if ags:
        statistik.append(
            {
                "titel": f"Regionalstatistik zu AGS {ags} suchen",
                "url": _dd(f"regionalstatistik Gemeinde {ags} {ort}"),
                "beschreibung": "Vorbefüllter Suchlink auf den Gemeindeschlüssel.",
            }
        )
    gruppen.append({"gruppe": "Statistik & Bevölkerung", "eintraege": statistik})

    # ------------------------------------------------- Passantenfrequenz
    hystreet_hinweis = (
        "Achtung: Im kostenfreien Modell ist die gewerbliche Nutzung untersagt. "
        "Für eine Standortentscheidung vorher Tarif klären. hystreet ist "
        "Datenbankhersteller nach § 87a UrhG, Quellenangabe Pflicht."
    )
    frequenz = [
        {
            # Reiner Absprunglink — keine API, kein Scraping. Google-Daten
            # dürfen weder gecacht noch auf unserer Karte gezeigt werden;
            # als Handkontrolle im Browser sind sie aber der Goldstandard
            # für die Vollständigkeit der Wettbewerbszählung.
            "titel": "Google Maps — Gastronomie am Punkt (Handkontrolle)",
            "url": (
                f"https://www.google.com/maps/search/Restaurants/"
                f"@{lat:.5f},{lon:.5f},17z"
            ),
            "beschreibung": (
                "Öffnet Google Maps mit Gastronomie-Suche an genau diesem "
                "Punkt. Zum Gegenzählen von Hand — OSM und Overture sind "
                "Untergrenzen, Google kennt fast alles, darf aber nicht in "
                "das Werkzeug eingebunden werden (Lizenz)."
            ),
        },
        {
            # Ebenfalls reiner Absprunglink: Mapillary (Meta) zeigt freie
            # Straßenfotos — die „Begehung vom Schreibtisch aus", bevor man
            # hinfährt. Erreichbarkeit der App-URL geprüft am 2026-08-07.
            "titel": "Mapillary — Straßenfotos am Punkt (virtuelle Begehung)",
            "url": (
                f"https://www.mapillary.com/app/"
                f"?lat={lat:.5f}&lng={lon:.5f}&z=17"
            ),
            "beschreibung": (
                "Von Freiwilligen aufgenommene Straßenfotos, ohne Konto "
                "einsehbar. Ladenfront, Leerstand und Umfeld vorab ansehen — "
                "Bildstand kann je nach Straße Monate bis Jahre alt sein."
            ),
        },
        {
            "titel": "hystreet — Passantenfrequenz",
            "url": "https://hystreet.com/",
            "beschreibung": "322 Messpunkte in 112 Städten (Stand Jahresbilanz 2024). "
            "Vollständige Liste nur über die interaktive Karte.",
            "warnung": hystreet_hinweis,
        },
        {
            "titel": "hystreet API-Doku",
            "url": "https://hystreet.com/apidocs",
            "beschreibung": "REST/JSON, Konto erforderlich, stündliche Auflösung.",
        },
    ]
    if ort:
        in_index = ort in HYSTREET_INDEXSTAEDTE
        frequenz.append(
            {
                "titel": f"Open-Data-Portal {ort} — Passantenzählung",
                "url": _dd(f"Open Data {ort} Passantenfrequenz hystreet"),
                "beschreibung": (
                    "Einzelne Städte spiegeln ihre hystreet-Daten kostenfrei im eigenen "
                    "Open-Data-Portal (z. B. Bonn, Münster, Rendsburg). Erst dort suchen. "
                    "Geprüft 08/2026: München bietet keine offene Passantenzählung; "
                    "Bonns „tagesaktuelle“ Ressource verweist nur auf hystreet.com, "
                    "die statischen Bonner Jahresdateien stammen von 2018 und tragen "
                    "keine ausgewiesene Lizenz — deshalb hier kein Datenblock."
                ),
            }
        )
        frequenz.append(
            {
                "titel": f"{ort}: {'im' if in_index else 'nicht im'} Index des Statistischen Bundesamts",
                "url": "https://www.destatis.de/",
                "beschreibung": (
                    "Diese 21 Städte haben die längsten und saubersten Zeitreihen."
                    if in_index
                    else "Für Orte außerhalb dieser 21 Städte sind Frequenzdaten dünner."
                ),
            }
        )
    gruppen.append({"gruppe": "Passantenfrequenz", "eintraege": frequenz})

    # ------------------------------------------------------ Wettbewerb
    wettbewerb = [
        {
            "titel": "Overpass Turbo mit dieser Abfrage öffnen",
            "url": "https://overpass-turbo.eu/?Q=" + quote_plus(overpass_query) + "&R",
            "beschreibung": "Dieselbe Abfrage wie im Panel, zum Nachprüfen und Anpassen.",
        },
        {
            "titel": "Google Maps — Stoßzeiten der Wettbewerber",
            "url": f"https://www.google.com/maps/search/restaurant/@{lat},{lon},16z",
            "beschreibung": "Tagesverlauf je Betrieb. Manuell je Wettbewerber ansehen.",
        },
        {
            "titel": "Lieferando im Umfeld",
            "url": f"https://www.lieferando.de/lieferservice{'/' + quote_plus(plz) if plz else ''}",
            "beschreibung": "Wer liefert schon, zu welchen Preisen.",
        },
    ]
    gruppen.append({"gruppe": "Wettbewerb & Frequenz vor Ort", "eintraege": wettbewerb})

    # --------------------------------------------------------- Leerstand
    leerstand = [
        {
            "titel": "Leerstandsmelder",
            "url": "https://www.leerstandsmelder.de/",
            "beschreibung": "Bürgerschaftlich gemeldete Leerstände.",
        },
    ]
    if ort:
        leerstand += [
            {
                "titel": f"Wirtschaftsförderung {ort}",
                "url": _dd(f"Wirtschaftsförderung {ort} Ansiedlung Leerstandskataster"),
                "beschreibung": "Leerstandskataster, Ansiedlungsförderung, LeAn-Zugang.",
            },
            {
                "titel": f"Open-Data-Portal {ort}",
                "url": _dd(f"Open Data Portal {ort}"),
                "beschreibung": "Einzelhandelsgutachten stehen oft im Ratsinformationssystem.",
            },
        ]
    gruppen.append({"gruppe": "Leerstand & Kommune", "eintraege": leerstand})

    # ------------------------------------------------ Flächen & Übernahme
    flaechen = [
        {
            "titel": "nexxt-change (Unternehmensbörse)",
            "url": "https://www.nexxt-change.org/",
            "beschreibung": "Kostenlos, rund 7.000 Inserate, eigenes Kaufgesuch möglich.",
        },
        {
            "titel": "DEHOGA „Die Gastgeber\"",
            "url": "https://www.die-gastgeber.info/",
            "beschreibung": "Objektbörse des Branchenverbands.",
        },
        {
            "titel": "ahgz immo",
            "url": "https://www.ahgzimmo.de/",
            "beschreibung": "Fachzeitung mit kostenlosem Suchagenten.",
        },
        {
            "titel": "gastro-pacht.de",
            "url": "https://www.gastro-pacht.de/",
            "beschreibung": "Pacht- und Übernahmeangebote.",
        },
        {
            "titel": "Kleinanzeigen — Ablöse/Übernahme",
            "url": "https://www.kleinanzeigen.de/s-gewerbeimmobilien/"
            + (quote_plus(ort) + "/" if ort else "")
            + "gastronomie/k0c276",
            "beschreibung": "Suchbegriffe: „Imbiss Ablöse\", „Gastro Übernahme\".",
        },
    ]
    gruppen.append({"gruppe": "Flächensuche & Übernahme", "eintraege": flaechen})

    gruppen.append(
        {
            "gruppe": "Brauerei-Pachtbörsen",
            "hinweis": (
                "Bierbezugsvertrag prüfen: Laufzeit und Mindestabnahme in hl/Jahr. "
                "Bei Fast Food ohne Bierfokus oft verhandelbar. Der Außendienst des "
                "Getränkefachgroßhandels erfährt trotzdem als Erster von freien Objekten."
            ),
            "eintraege": [
                {"titel": t, "url": u, "beschreibung": ""} for t, u in BRAUEREI_BOERSEN
            ],
        }
    )

    gruppen.append(
        {
            "gruppe": "Makler & Center",
            "hinweis": (
                "Suchprofil hinterlegen statt Exposés abwarten: Konzept, Marke, qm, "
                "Zielmiete, Wunschlagen, Bonität, Zeitpunkt, Franchisegeber als Referenz."
            ),
            "eintraege": [{"titel": t, "url": u, "beschreibung": ""} for t, u in MAKLER]
            + [
                {
                    "titel": "ECE Centermanagement (Vermietung)",
                    "url": "https://www.ece.com/",
                    "beschreibung": "leasing@ece.com · Tel. 040 60606-7000 · courtagefrei.",
                },
                {
                    "titel": "ECE Pop-up / temporäre Flächen",
                    "url": "https://mallmarketing.ece.com/",
                    "beschreibung": "1–3 Monate.",
                },
                {
                    "titel": "MEC (Fachmarktzentren)",
                    "url": "https://www.mec-cm.com/",
                    "beschreibung": "",
                },
                {
                    "titel": "DB InfraGO — Personenbahnhöfe",
                    "url": "https://www.dbinfrago.com/",
                    "beschreibung": "Feedback@bahnhof.de · rund 600 Empfangsgebäude.",
                },
            ],
        }
    )

    return gruppen
