"""Vergleichsmaß Umsatz — Spec §9.

**Das ist keine Prognose.** Es ist eine Umrechnung, mit der sich zwei Standorte
unter denselben, selbst gesetzten Annahmen vergleichen lassen. Die Auflagen aus
§9 der Spec sind hier bindend:

* Alle Annahmen sind Eingabefelder. Keine versteckte Konstante im Rechenweg.
* Ausgabe als Spanne, nie als Punktwert.
* Pflichtausgabe daneben: Bestellungen pro Tag und pro Öffnungsstunde. Das ist
  die Zahl, die ein Betreiber beurteilen kann und das Modell nicht.
* Die Formel steht sichtbar in der Oberfläche, nicht nur im Code.

Warum so streng: Ein Vorgänger dieses Werkzeugs hat aus Einwohnerzahl,
Wettbewerbsdichte und frei gewählten Distanzgewichten einen Jahresumsatz
„berechnet". Die Eingangsdaten waren echt, die Gewichte erfunden, das Ergebnis
sah präzise aus und war es nicht. Deshalb gibt es hier **keine** Distanzgewichte,
keine Lagefaktoren und keine Kaufkraftindizes — nur eine Kette aus vier
Multiplikationen, die jeder nachrechnen kann.

Die einzige Größe, die die Daten nicht hergeben, ist der Anteil der Besuche, den
ein einzelner Betrieb auf sich zieht. Sie wird nicht geschätzt, sondern als
Eingabe verlangt — mit einer naiven Gleichverteilung als Startpunkt, die als
solche benannt ist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Referenzwerte
#
# Alle am 2026-08-01 selbst nachgeschlagen (Spec §9 verlangt das ausdrücklich —
# die in der Spec genannten Zahlen waren Sekundärzitate aus Presseberichten).
# Jeder Wert trägt Quelle, Stand und Fundstelle und ist in der Oberfläche
# überschreibbar.
# ---------------------------------------------------------------------------

REFERENZWERTE: list[dict[str, Any]] = [
    {
        "schluessel": "systemgastronomie_umsatz_mrd",
        "titel": "Umsatz Systemgastronomie Deutschland",
        "wert": 36.0,
        "einheit": "Mrd. €",
        "stand": "2025",
        "quelle": "Bundesverband der Systemgastronomie (BdS) mit Circana, CREST-Konsumentenpanel",
        "url": "https://www.bundesverband-systemgastronomie.de/die-systemgastronomie/branchendaten.html",
        "abgerufen": "2026-08-01",
    },
    {
        "schluessel": "systemgastronomie_bon",
        "titel": "Durchschnittsbon Systemgastronomie",
        "wert": 7.15,
        "einheit": "€ je Besuch",
        "stand": "2025",
        "quelle": "Bundesverband der Systemgastronomie (BdS) mit Circana, CREST-Konsumentenpanel",
        "url": "https://www.bundesverband-systemgastronomie.de/die-systemgastronomie/branchendaten.html",
        "abgerufen": "2026-08-01",
    },
    {
        "schluessel": "ahm_bon_gesamt",
        "titel": "Durchschnittsbon Außer-Haus-Markt insgesamt",
        "wert": 10.21,
        "einheit": "€ je Besuch",
        "stand": "2023",
        "quelle": "Studie im Auftrag der Denkfabrik Zukunft der Gastwelt (DZG)",
        "url": "https://brotundbackwaren.de/ausser-haus-markt-2023-weniger-besuche-hoherer-durchschnittsbon/",
        "abgerufen": "2026-08-01",
        "hinweis": (
            "Anderer Erhebungsumfang als der BdS-Wert und zwei Jahre älter. Der "
            "Gesamtmarkt enthält Bedien- und Hotelgastronomie mit deutlich höheren "
            "Bons. Für ein Schnellrestaurant ist der BdS-Wert der nähere."
        ),
    },
    {
        "schluessel": "bevoelkerung",
        "titel": "Bevölkerung Deutschland",
        "wert": 83.5,
        "einheit": "Mio.",
        "stand": "31.12.2025",
        "quelle": "Statistisches Bundesamt",
        "url": "https://www.destatis.de/DE/Presse/Pressemitteilungen/2026/01/PD26_032_124.html",
        "abgerufen": "2026-08-01",
    },
    {
        "schluessel": "mietanteil",
        "titel": "Miete als Anteil vom Nettoumsatz",
        "wert": "10–14",
        "einheit": "%",
        "stand": "Faustregel",
        "quelle": "notizen-standort-flaeche.md §6 (Checkliste vor Vertragsunterschrift)",
        "url": None,
        "abgerufen": None,
        "hinweis": "Branchenfaustregel aus dem Arbeitsdokument, keine erhobene Statistik.",
    },
]


def _ref(schluessel: str) -> dict[str, Any]:
    for r in REFERENZWERTE:
        if r["schluessel"] == schluessel:
            return r
    raise KeyError(schluessel)


def besuche_je_einwohner_und_jahr() -> dict[str, Any]:
    """Wird aus den Referenzwerten hergeleitet, nicht gesetzt.

    Umsatz der Systemgastronomie geteilt durch den Durchschnittsbon ergibt die
    Besuche; geteilt durch die Bevölkerung ergibt die Besuche je Kopf.
    """
    umsatz_mrd = _ref("systemgastronomie_umsatz_mrd")["wert"]
    bon = _ref("systemgastronomie_bon")["wert"]
    bev_mio = _ref("bevoelkerung")["wert"]
    besuche_mrd = umsatz_mrd / bon
    je_kopf = besuche_mrd * 1_000 / bev_mio
    return {
        "wert": round(je_kopf, 1),
        "einheit": "Besuche je Einwohner und Jahr",
        "herleitung": (
            f"{umsatz_mrd:.0f} Mrd. € ÷ {bon:.2f} € je Besuch = "
            f"{besuche_mrd:.2f} Mrd. Besuche; "
            f"÷ {bev_mio:.1f} Mio. Einwohner = {je_kopf:.1f} Besuche je Einwohner und Jahr"
        ),
        "quellen": [
            _ref("systemgastronomie_umsatz_mrd"),
            _ref("systemgastronomie_bon"),
            _ref("bevoelkerung"),
        ],
    }


FORMEL = [
    "Besuche im Einzugsgebiet je Jahr  =  Einwohner × Besuche je Einwohner und Jahr",
    "Marktanteil (naive Gleichverteilung)  =  1 ÷ (Wettbewerber + 1)",
    "Besuche des Betriebs je Jahr  =  Besuche im Einzugsgebiet × Marktanteil",
    "Jahresumsatz  =  Besuche des Betriebs × Durchschnittsbon",
    "Bestellungen je Tag  =  Besuche des Betriebs ÷ Öffnungstage",
    "Bestellungen je Öffnungsstunde  =  Bestellungen je Tag ÷ Öffnungsstunden",
]

WARNUNGEN = [
    "Das ist keine Prognose, sondern ein Vergleichsmaß zwischen Standorten unter "
    "denselben selbst gesetzten Annahmen.",
    "Die Rechnung kennt keine Distanzgewichte, keine Lagefaktoren, keine Kaufkraft "
    "und keine Passantenströme. Zwei Standorte mit gleicher Einwohnerzahl und "
    "gleicher Wettbewerbszahl bekommen dasselbe Ergebnis, auch wenn einer an der "
    "Fußgängerzone und einer an der Umgehungsstraße liegt.",
    "Der Marktanteil ist die einzige Größe, die keine Datenquelle hergibt. Er ist "
    "eine Setzung des Nutzers. Die naive Gleichverteilung unterstellt, dass alle "
    "Betriebe im Umkreis gleich stark sind — das sind sie nie.",
    "Die Wettbewerbszahl aus OpenStreetMap ist eine Untergrenze. Fehlende Betriebe "
    "lassen den Marktanteil und damit den Umsatz zu hoch erscheinen.",
    "Die Einwohnerzahl ist die Wohnbevölkerung zum Zensus-Stichtag 15.05.2022. "
    "Einpendler, Touristen und Durchgangsverkehr sind darin nicht enthalten — in "
    "Innenstadt- und Bahnhofslagen ist das der größere Teil der Kundschaft.",
]


@dataclass
class Eingaben:
    """Jedes Feld ist in der Oberfläche sichtbar und überschreibbar."""

    einwohner: float
    wettbewerber: int
    besuche_je_einwohner: float
    bon_min: float
    bon_max: float
    # Der Marktanteil wird nicht geschätzt. Vorgabe ist die naive Gleichverteilung,
    # aufgespannt mit einem sichtbaren Unsicherheitsfaktor.
    marktanteil_min_prozent: float | None = None
    marktanteil_max_prozent: float | None = None
    unsicherheitsfaktor: float = 2.0
    oeffnungstage: int = 360
    oeffnungsstunden: float = 12.0
    mietanteil_min_prozent: float = 10.0
    mietanteil_max_prozent: float = 14.0
    # Prüfstein: der tatsächliche Jahresumsatz eines Betriebs, den man kennt —
    # der eigene, ein übernommener, ein befreundeter. Damit lässt sich das
    # Modell einmal gegen die Wirklichkeit halten, statt es nur zu verfeinern.
    # Er geht in **keine** Rechnung ein, sondern wird nur gegenübergestellt.
    kalibrierung_umsatz_eur: float | None = None
    kalibrierung_bezeichnung: str | None = None
    # Franchise-Kostenprobe. Es gibt bewusst KEINE Vorgabewerte: die Sätze
    # stehen im Franchisevertrag bzw. in der eigenen Kalkulation, und jeder
    # hier erfundene "typische" Satz würde als Branchenwert gelesen. Leer
    # gelassen findet die Probe nicht statt.
    franchisegebuehr_prozent: float | None = None
    werbeabgabe_prozent: float | None = None
    wareneinsatz_prozent: float | None = None
    personalkosten_prozent: float | None = None
    # Mietprobe gegen ein konkretes Exposé: Fläche und geforderte Kaltmiete
    # je m². Beides kommt aus dem Angebot des Vermieters — auch hier gibt es
    # bewusst keine Vorgabewerte. Leer gelassen findet die Probe nicht statt.
    flaeche_qm: float | None = None
    angebotsmiete_qm: float | None = None
    # Wohnungsmiete des Umkreises aus dem Zensus-Gitter (100-m-Zellen,
    # Stichtag 15.05.2022). Wird aus den Punktdaten vorbefüllt und sichtbar
    # angezeigt. Sie ist eine WOHNungsmiete und taugt deshalb nicht als
    # Obergrenze für eine Gewerbemiete — wohl aber als Lage-Anker, der zwei
    # Standorte vergleichbar macht. Geht in keine Umsatzrechnung ein.
    zensus_wohnmiete_qm: float | None = None

    def naiver_marktanteil_prozent(self) -> float:
        return 100.0 / (max(0, int(self.wettbewerber)) + 1)


def _spanne(a: float, b: float) -> tuple[float, float]:
    return (a, b) if a <= b else (b, a)


def kalibrierung(
    tatsaechlich: float | None,
    umsatz_min: float,
    umsatz_max: float,
    bezeichnung: str | None = None,
) -> dict[str, Any] | None:
    """Hält die Rechnung gegen einen echten, bekannten Jahresumsatz.

    Das Modell rechnet mit Bundesdurchschnitten und kennt weder Lage noch
    Passantenströme. Ob das für **diesen** Betriebstyp um Faktor 1,2 oder um
    Faktor 5 danebenliegt, sagt ein einziger bekannter Umsatz mehr als jede
    weitere Verfeinerung der Formel.

    Der Wert fließt in keine Rechnung ein. Er wird gegenübergestellt, und der
    Faktor wird benannt — inklusive der Richtung.
    """
    if not isinstance(tatsaechlich, (int, float)) or tatsaechlich <= 0:
        return None
    mitte = (umsatz_min + umsatz_max) / 2
    if mitte <= 0:
        return None

    faktor = tatsaechlich / mitte
    innerhalb = umsatz_min <= tatsaechlich <= umsatz_max
    if innerhalb:
        befund = (
            "Der bekannte Umsatz liegt **innerhalb** der Spanne. Mehr sagt das "
            "nicht — die Spanne ist bewusst weit."
        )
    elif faktor > 1:
        befund = (
            f"Die Rechnung liegt um Faktor {faktor:.2f} **zu niedrig**. Für "
            "diesen Betriebstyp und diese Lage ist sie also zu vorsichtig."
        )
    else:
        befund = (
            f"Die Rechnung liegt um Faktor {1 / faktor:.2f} **zu hoch**. Sie "
            "überschätzt, was an diesem Standort zu erwarten wäre."
        )
    return {
        "bezeichnung": bezeichnung or "bekannter Betrieb",
        "tatsaechlich_eur": round(tatsaechlich),
        "gerechnet_mitte_eur": round(mitte),
        "gerechnete_spanne_eur": [round(umsatz_min), round(umsatz_max)],
        "faktor": round(faktor, 2),
        "innerhalb_der_spanne": innerhalb,
        "befund": befund,
        "hinweis": (
            "Ein einzelner Vergleichswert kalibriert nichts — er zeigt nur die "
            "Größenordnung des Fehlers. Der Wert geht in keine Rechnung ein und "
            "wird nicht gespeichert."
        ),
    }


def franchise_kostenprobe(
    e: Eingaben, umsatz_min: float, umsatz_max: float
) -> dict[str, Any] | None:
    """Was vom Umsatz nach den Franchise-Sätzen übrig bleibt — vor Miete.

    Reine Prozentrechnung auf den Eingaben des Nutzers. Die Sätze kommen aus
    dem Franchisevertrag und der eigenen Kalkulation; das Werkzeug gibt keine
    vor und bewertet sie nicht. Das Ergebnis ist das Budget für alles, was
    danach kommt: Miete, Abschreibung, Zinsen, Steuern, Unternehmerlohn.
    """
    saetze = [
        ("franchisegebuehr", "Franchisegebühr", e.franchisegebuehr_prozent),
        ("werbeabgabe", "Werbeabgabe", e.werbeabgabe_prozent),
        ("wareneinsatz", "Wareneinsatz", e.wareneinsatz_prozent),
        ("personalkosten", "Personalkosten", e.personalkosten_prozent),
    ]
    gesetzt = [(k, titel, float(v)) for k, titel, v in saetze if v is not None]
    if not gesetzt:
        return None

    summe = sum(v for _, _, v in gesetzt)
    verbleib_prozent = 100.0 - summe
    warnungen = []
    if summe >= 100:
        warnungen.append(
            f"Die eingegebenen Sätze summieren sich auf {summe:g} % — es bliebe "
            "nichts (oder weniger als nichts) für Miete, Abschreibung, Zinsen "
            "und Unternehmerlohn. Unter diesen Annahmen trägt sich kein Standort."
        )
    elif verbleib_prozent < 15:
        warnungen.append(
            f"Nach den eingegebenen Sätzen verbleiben {verbleib_prozent:g} % — "
            "davon müssen noch Miete (Faustregel 10–14 %), Abschreibung, Zinsen "
            "und Unternehmerlohn bezahlt werden. Das wird an jedem Standort eng."
        )
    return {
        "saetze": [
            {"key": k, "titel": titel, "prozent": v} for k, titel, v in gesetzt
        ],
        "summe_prozent": round(summe, 2),
        "verbleib_prozent": round(verbleib_prozent, 2),
        "verbleib_jahr_eur": [
            round(umsatz_min * verbleib_prozent / 100),
            round(umsatz_max * verbleib_prozent / 100),
        ],
        "verbleib_monat_eur": [
            round(umsatz_min * verbleib_prozent / 100 / 12),
            round(umsatz_max * verbleib_prozent / 100 / 12),
        ],
        "hinweis": (
            "Verbleib vor Miete, Abschreibung, Zinsen, Steuern und "
            "Unternehmerlohn. Alle Sätze stammen aus deinen Eingaben "
            "(Franchisevertrag, eigene Kalkulation) — das Werkzeug gibt keine "
            "vor. Brutto/Netto so behandeln wie beim Bon."
        ),
        "warnungen": warnungen,
    }


def mietprobe(
    e: Eingaben, umsatz_min: float, umsatz_max: float,
    obergrenze_min: float, obergrenze_max: float,
) -> dict[str, Any] | None:
    """Hält ein konkretes Mietangebot gegen die Miet-Obergrenze der Rechnung.

    Fläche × geforderte Kaltmiete je m² ergibt die Monatsmiete des Exposés;
    die Obergrenze kommt aus der Umsatzspanne und dem Mietanteil (Faustregel
    10–14 %, in der Oberfläche änderbar). Reine Multiplikation — und weil die
    Umsatzspanne keine Prognose ist, ist auch dieser Befund keiner: er sagt
    nur, unter welchen der selbst gesetzten Annahmen die Miete tragbar wäre.
    """
    if e.flaeche_qm is None or e.angebotsmiete_qm is None:
        return None
    if e.flaeche_qm <= 0 or e.angebotsmiete_qm < 0:
        return None
    monatsmiete = e.flaeche_qm * e.angebotsmiete_qm

    anteile = None
    if umsatz_min > 0 and umsatz_max > 0:
        anteile = [
            round(monatsmiete * 12 / umsatz_max * 100, 1),
            round(monatsmiete * 12 / umsatz_min * 100, 1),
        ]

    if monatsmiete <= obergrenze_min:
        befund = (
            "Die geforderte Miete liegt **unter der unteren Obergrenze** — "
            "selbst am unteren Rand der Umsatzspanne bliebe sie im Rahmen "
            "der Faustregel."
        )
        lage = "unter"
    elif monatsmiete <= obergrenze_max:
        befund = (
            "Die geforderte Miete liegt **innerhalb der Spanne** — sie trägt "
            "sich nur, wenn der Umsatz eher am oberen Rand der Rechnung liegt."
        )
        lage = "innerhalb"
    else:
        befund = (
            "Die geforderte Miete liegt **über der oberen Obergrenze** — "
            "unter den gesetzten Annahmen trägt sie sich an diesem Standort "
            "nicht. Verhandeln oder weiterziehen."
        )
        lage = "ueber"
    # Lage-Anker gegen die örtliche Wohnungsmiete (Zensus 2022). Kein Befund
    # im Sinne von tragbar/untragbar — Gewerbemieten liegen regelmäßig über
    # Wohnmieten. Der Wert macht zwei Standorte vergleichbar: dieselbe
    # geforderte Gewerbemiete ist in einem 8-€-Wohnviertel ein anderes
    # Angebot als in einem 16-€-Viertel.
    wohnmiete_vergleich = None
    if (
        isinstance(e.zensus_wohnmiete_qm, (int, float))
        and e.zensus_wohnmiete_qm > 0
        and e.angebotsmiete_qm > 0
    ):
        wohnmiete_vergleich = {
            "wohnmiete_qm": round(float(e.zensus_wohnmiete_qm), 2),
            "verhaeltnis": round(e.angebotsmiete_qm / e.zensus_wohnmiete_qm, 2),
            "hinweis": (
                "Die Zensus-Zahl ist die durchschnittliche Nettokaltmiete für "
                "WOHNUNGEN im Umkreis (Stichtag 15.05.2022) — keine Ober- oder "
                "Untergrenze für Gewerbemieten, die regelmäßig darüber liegen. "
                "Das Verhältnis taugt zum Vergleich zweier Standorte: dieselbe "
                "Forderung ist im teuren Wohnviertel ein anderes Angebot als "
                "im günstigen."
            ),
        }

    return {
        "flaeche_qm": e.flaeche_qm,
        "angebotsmiete_qm": e.angebotsmiete_qm,
        "wohnmiete_vergleich": wohnmiete_vergleich,
        "monatsmiete_eur": round(monatsmiete),
        "jahresmiete_eur": round(monatsmiete * 12),
        "obergrenze_eur": [round(obergrenze_min), round(obergrenze_max)],
        "anteil_am_umsatz_prozent": anteile,
        "lage": lage,
        "befund": befund,
        "hinweis": (
            "Kaltmiete gegen Faustregel-Mietanteil — Nebenkosten, Staffel- "
            "und Indexklauseln, Instandhaltungspflichten stehen im Vertrag "
            "und nicht in dieser Rechnung."
        ),
    }


def sensitivitaet(
    e: Eingaben,
    anteil_min: float,
    anteil_max: float,
    bon_min: float,
    bon_max: float,
    umsatz_min: float,
    umsatz_max: float,
    marktanteil_gesetzt: bool,
) -> dict[str, Any] | None:
    """Welche Annahme muss man vor Ort zuerst prüfen?

    Bewusst ohne gewählte Störgrößen (kein „±25 %"-Prüfwert): weil die Formel
    eine reine Multiplikationskette ist, lässt sich alles exakt herleiten.

    * Die Umsatzspanne zerlegt sich **exakt** in Marktanteil-Faktor ×
      Bon-Faktor: ``umsatz_max/umsatz_min = (anteil_max/anteil_min) ×
      (bon_max/bon_min)``. Wer die Spanne enger haben will, weiß damit, an
      welcher Annahme das liegt.
    * Einwohner und Besuche je Einwohner wirken 1:1 — 20 % Fehler in der
      Eingabe sind 20 % Fehler im Ergebnis, an beiden Rändern gleich.
    * Ein **übersehener Wettbewerber** (OSM zählt Untergrenzen!) senkt den
      naiven Marktanteil von 1/(n+1) auf 1/(n+2), also den Umsatz um exakt
      100/(n+2) Prozent. Je weniger Wettbewerber gezählt sind, desto härter
      schlägt jeder übersehene durch.
    * Öffnungstage und -stunden verändern den Jahresumsatz gar nicht, nur die
      Bestellungen je Tag/Stunde. Das übersieht man leicht.
    """
    if umsatz_min <= 0 or umsatz_max <= 0 or anteil_min <= 0 or bon_min <= 0:
        return None

    gesamt = umsatz_max / umsatz_min
    f_anteil = anteil_max / anteil_min
    f_bon = bon_max / bon_min

    treiber = [
        {
            "key": "marktanteil",
            "titel": "Marktanteil",
            "faktor": round(f_anteil, 2),
            "erklaerung": (
                "vom Nutzer gesetzte Spanne"
                if marktanteil_gesetzt
                else (
                    f"naive Gleichverteilung, mit dem Unsicherheitsfaktor "
                    f"{e.unsicherheitsfaktor:g} nach beiden Seiten aufgespannt "
                    f"(ergibt Faktor {e.unsicherheitsfaktor * e.unsicherheitsfaktor:g})"
                )
            ),
        },
        {
            "key": "bon",
            "titel": "Durchschnittsbon",
            "faktor": round(f_bon, 2),
            "erklaerung": f"Spanne {bon_min:.2f} bis {bon_max:.2f} € je Besuch",
        },
    ]
    treiber.sort(key=lambda t: -t["faktor"])

    n = max(0, int(e.wettbewerber))
    if marktanteil_gesetzt:
        wettbewerber_plus_eins = None
    else:
        wettbewerber_plus_eins = {
            "wettbewerber": n,
            "wirkung_prozent": round(-100.0 / (n + 2), 1),
            "erklaerung": (
                f"Der naive Marktanteil fällt von 1/{n + 1} auf 1/{n + 2}. "
                "OSM zählt Betriebe unvollständig — diese Zahl sagt, wie teuer "
                "jeder übersehene Wettbewerber die Rechnung macht."
            ),
        }

    groesster = treiber[0]
    befund = (
        f"Die Umsatzspanne (Faktor {gesamt:.1f}) zerlegt sich exakt in "
        f"Marktanteil (Faktor {f_anteil:.1f}) × Bon (Faktor {f_bon:.1f}). "
        f"Die größte Unsicherheit steckt im {groesster['titel']} — diese "
        "Annahme zuerst vor Ort prüfen."
    )

    return {
        "spannenfaktor_gesamt": round(gesamt, 2),
        "treiber": treiber,
        "linear": {
            "felder": ["Einwohner", "Besuche je Einwohner"],
            "erklaerung": (
                "wirken 1:1 auf beide Ränder — 20 % Eingabefehler sind 20 % "
                "Ergebnisfehler, die Spannenbreite ändert sich dadurch nicht"
            ),
        },
        "wettbewerber_plus_eins": wettbewerber_plus_eins,
        "ohne_wirkung": {
            "felder": ["Öffnungstage", "Öffnungsstunden"],
            "erklaerung": (
                "verändern den Jahresumsatz nicht, nur Bestellungen je Tag "
                "und je Stunde"
            ),
        },
        "befund": befund,
        "hinweis": (
            "Alles exakt aus der Formel hergeleitet, keine gewählten "
            "Prüf-Störgrößen. Die Zerlegung gilt, weil die Rechnung eine "
            "reine Multiplikationskette ist."
        ),
    }


def rechne(e: Eingaben) -> dict[str, Any]:
    """Reine Funktion. Gleiche Eingaben, gleiches Ergebnis, nichts Verstecktes."""
    fehler = []
    if e.einwohner < 0:
        fehler.append("Einwohnerzahl darf nicht negativ sein.")
    if e.oeffnungstage <= 0:
        fehler.append("Öffnungstage müssen größer als 0 sein.")
    if e.oeffnungsstunden <= 0:
        fehler.append("Öffnungsstunden müssen größer als 0 sein.")
    if e.unsicherheitsfaktor < 1:
        fehler.append("Der Unsicherheitsfaktor muss mindestens 1 sein.")
    if fehler:
        return {"ok": False, "fehler": fehler}

    naiv = e.naiver_marktanteil_prozent()
    if e.marktanteil_min_prozent is None or e.marktanteil_max_prozent is None:
        anteil_min = naiv / e.unsicherheitsfaktor
        anteil_max = min(100.0, naiv * e.unsicherheitsfaktor)
        anteil_herkunft = (
            f"naive Gleichverteilung {naiv:.2f} %, aufgespannt mit dem "
            f"Unsicherheitsfaktor {e.unsicherheitsfaktor:g} "
            f"(frei gewählt, keine Datengrundlage)"
        )
    else:
        anteil_min, anteil_max = _spanne(
            e.marktanteil_min_prozent, e.marktanteil_max_prozent
        )
        anteil_herkunft = "vom Nutzer gesetzt"

    bon_min, bon_max = _spanne(e.bon_min, e.bon_max)

    besuche_gebiet = e.einwohner * e.besuche_je_einwohner
    besuche_min = besuche_gebiet * anteil_min / 100.0
    besuche_max = besuche_gebiet * anteil_max / 100.0

    umsatz_min = besuche_min * bon_min
    umsatz_max = besuche_max * bon_max

    tag_min = besuche_min / e.oeffnungstage
    tag_max = besuche_max / e.oeffnungstage
    stunde_min = tag_min / e.oeffnungsstunden
    stunde_max = tag_max / e.oeffnungsstunden

    miete_min, miete_max = _spanne(e.mietanteil_min_prozent, e.mietanteil_max_prozent)

    miete_obergrenze = (
        umsatz_min / 12 * miete_min / 100,
        umsatz_max / 12 * miete_max / 100,
    )

    return {
        "kalibrierung": kalibrierung(
            e.kalibrierung_umsatz_eur, umsatz_min, umsatz_max, e.kalibrierung_bezeichnung
        ),
        "franchise": franchise_kostenprobe(e, umsatz_min, umsatz_max),
        "mietprobe": mietprobe(e, umsatz_min, umsatz_max, *miete_obergrenze),
        "sensitivitaet": sensitivitaet(
            e, anteil_min, anteil_max, bon_min, bon_max, umsatz_min, umsatz_max,
            marktanteil_gesetzt=(
                e.marktanteil_min_prozent is not None
                and e.marktanteil_max_prozent is not None
            ),
        ),
        "ok": True,
        "eingaben": {
            "einwohner": e.einwohner,
            "wettbewerber": e.wettbewerber,
            "besuche_je_einwohner": e.besuche_je_einwohner,
            "bon_min": bon_min,
            "bon_max": bon_max,
            "marktanteil_min_prozent": round(anteil_min, 3),
            "marktanteil_max_prozent": round(anteil_max, 3),
            "unsicherheitsfaktor": e.unsicherheitsfaktor,
            "oeffnungstage": e.oeffnungstage,
            "oeffnungsstunden": e.oeffnungsstunden,
            "mietanteil_min_prozent": miete_min,
            "mietanteil_max_prozent": miete_max,
        },
        "zwischenschritte": {
            "besuche_im_einzugsgebiet_je_jahr": round(besuche_gebiet),
            "naiver_marktanteil_prozent": round(naiv, 3),
            "marktanteil_herkunft": anteil_herkunft,
            "besuche_des_betriebs_je_jahr": [round(besuche_min), round(besuche_max)],
        },
        "ergebnis": {
            "jahresumsatz_eur": [round(umsatz_min), round(umsatz_max)],
            "bestellungen_je_tag": [round(tag_min, 1), round(tag_max, 1)],
            "bestellungen_je_oeffnungsstunde": [round(stunde_min, 1), round(stunde_max, 1)],
            "umsatz_je_tag_eur": [
                round(umsatz_min / e.oeffnungstage),
                round(umsatz_max / e.oeffnungstage),
            ],
            "monatsmiete_obergrenze_eur": [
                round(umsatz_min / 12 * miete_min / 100),
                round(umsatz_max / 12 * miete_max / 100),
            ],
        },
        "formel": FORMEL,
        "warnungen": WARNUNGEN,
        "referenzwerte": REFERENZWERTE,
        "besuche_herleitung": besuche_je_einwohner_und_jahr(),
        "beschriftung": (
            "Vergleichsmaß zwischen Standorten — keine Prognose, keine Zusage, "
            "keine Grundlage für einen Kreditantrag."
        ),
    }


def _gehweg_alternative(
    bloecke: dict[str, Any], einwohner_luftlinie: float | None
) -> dict[str, Any] | None:
    """Bietet die zu Fuß erreichbaren Zahlen als Alternative an — auf Knopfdruck.

    Der Umkreis ist ein Luftlinienkreis; zu Fuß ist er kleiner und an Flüssen,
    Gleisen und Schnellstraßen zerschnitten. Die Rechnung mit der vollen
    Einwohnerzahl überschätzt das Einzugsgebiet deshalb systematisch.

    Warum das trotzdem **nicht** die Vorgabe ist: die Gehstrecken liegen nur
    vor, wenn Block 4b geladen wurde. Würden sie stillschweigend die Vorgabe
    ändern, hinge das Ergebnis daran, ob jemand vorher einen Knopf gedrückt hat
    — und zwei Standorte wären nicht mehr vergleichbar. Deshalb: sichtbar
    angeboten, ausdrücklich zu übernehmen.
    """
    gw = (bloecke.get("gehweg") or {}).get("data") or {}
    zen = gw.get("zensus") or {}
    gas = gw.get("gastronomie") or {}
    einwohner = zen.get("einwohner_gehweg")
    if einwohner is None:
        return None
    return {
        "einwohner": einwohner,
        "einwohner_luftlinie": einwohner_luftlinie,
        "erschliessungsgrad": zen.get("erschliessungsgrad"),
        "wettbewerber_gastronomie": gas.get("im_gehradius"),
        "hinweis": (
            "Für diesen Punkt sind die Gehstrecken berechnet. Zu Fuß erreichbar "
            f"sind {einwohner:,.0f} Einwohner statt "
            f"{(einwohner_luftlinie or 0):,.0f} in der Luftlinie "
            f"({zen.get('erschliessungsgrad')} % erschlossen). Die Rechnung mit "
            "der Luftlinienzahl überschätzt das Einzugsgebiet."
        ).replace(",", "."),
        "warnung": (
            "Wenn du übernimmst, rechne beide Standorte gleich — sonst "
            "vergleichst du einen Fußwegradius mit einem Luftlinienradius."
        ),
    }


def vorgaben_aus_punkt(punkt: dict[str, Any]) -> dict[str, Any]:
    """Füllt die Eingabefelder aus den Daten des gewählten Punktes vor.

    Vorbefüllen heißt nicht festlegen: jeder Wert bleibt in der Oberfläche
    editierbar, und es wird ausgewiesen, woher er stammt.
    """
    bloecke = punkt.get("bloecke") or {}
    z = (bloecke.get("zensus") or {}).get("data") or {}
    o = (bloecke.get("osm") or {}).get("data") or {}
    einwohner = ((z.get("bevoelkerung") or {}).get("einwohner") or {}).get("wert")
    gastro = (o.get("zusammenfassung") or {}).get("gastronomie") or {}
    schnell = (gastro.get("nach_typ") or {}).get("Schnellrestaurant", 0)
    miete = (z.get("wohnen") or {}).get("miete_qm") or {}
    miete_wert = miete.get("wert")

    besuche = besuche_je_einwohner_und_jahr()
    return {
        # 0 statt None: An einem Punkt ohne Zensuszelle ist null Einwohner die
        # zutreffende Aussage. Ein leeres Pflichtfeld würde die Rechnung dagegen
        # mit HTTP 422 abbrechen — das sähe aus wie ein Fehler des Werkzeugs.
        "einwohner": einwohner if einwohner is not None else 0,
        "einwohner_herkunft": (
            f"Zensus 2022, Summe über {((z.get('bevoelkerung') or {}).get('einwohner') or {}).get('zellen', 0)} "
            f"Gitterzellen im Radius {punkt.get('punkt', {}).get('radius_m')} m"
            if einwohner is not None
            else "keine Zensuszelle im Umkreis"
        ),
        "wettbewerber": schnell,
        "wettbewerber_herkunft": (
            f"OpenStreetMap, amenity=fast_food im Radius "
            f"{punkt.get('punkt', {}).get('radius_m')} m — Untergrenze, "
            f"{gastro.get('gesamt', 0)} gastronomische Betriebe insgesamt"
        ),
        "wettbewerber_alternative": {
            "alle_gastronomie": gastro.get("gesamt", 0),
            "hinweis": (
                "Je nach Konzept ist die ganze Gastronomie der relevante Wettbewerb, "
                "nicht nur die Schnellrestaurants. Feld entsprechend ändern."
            ),
        },
        "gehweg_alternative": _gehweg_alternative(bloecke, einwohner),
        "zensus_wohnmiete_qm": miete_wert,
        "zensus_wohnmiete_herkunft": (
            f"Zensus 2022, Ø Nettokaltmiete für Wohnungen über {miete.get('zellen', 0)} "
            "Gitterzellen (Stichtag 15.05.2022) — Lage-Anker, keine Gewerbemiete"
            if miete_wert is not None
            else "keine Mietangabe in den Zensuszellen des Umkreises"
        ),
        "besuche_je_einwohner": besuche["wert"],
        "besuche_herleitung": besuche,
        "bon_min": _ref("systemgastronomie_bon")["wert"],
        "bon_max": _ref("ahm_bon_gesamt")["wert"],
        "unsicherheitsfaktor": 2.0,
        "oeffnungstage": 360,
        "oeffnungsstunden": 12.0,
        "mietanteil_min_prozent": 10.0,
        "mietanteil_max_prozent": 14.0,
        "referenzwerte": REFERENZWERTE,
        "formel": FORMEL,
        "warnungen": WARNUNGEN,
    }
