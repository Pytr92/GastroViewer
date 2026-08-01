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

    return {
        "kalibrierung": kalibrierung(
            e.kalibrierung_umsatz_eur, umsatz_min, umsatz_max, e.kalibrierung_bezeichnung
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
