"""Vergleichstabelle: Spaltendefinitionen, Zeilen aus gespeicherten Punkten,
Verlaufskennzahlen, kompakte Ablage und CSV-Export.

Aus api.py herausgelöst — die Routen (routen/punkte.py) und die Tests
importieren von hier; api.py reicht die öffentlichen Namen weiter."""

from __future__ import annotations

import csv
import io
import time
from typing import Any


def _wert(node: Any) -> Any:
    """Aggregate liegen als {"wert": …, "zellen": …} vor."""
    if isinstance(node, dict) and "wert" in node:
        return node["wert"]
    return node


def je_bezugsgroesse(
    zaehler: Any, nenner: Any, faktor: float = 1.0, stellen: int = 1
) -> float | None:
    """Verhältniszahl aus zwei gemessenen Größen.

    Beide Bestandteile stammen aus echten Antworten; hier wird nur geteilt, es
    kommt kein gewählter Faktor hinzu. Fehlt eine Seite oder ist der Nenner 0,
    ist das Ergebnis ``None`` und nicht 0 — eine Lage ohne Einwohnerdaten hat
    keine Wettbewerbsdichte von null, sie hat gar keine.
    """
    if not isinstance(zaehler, (int, float)) or not isinstance(nenner, (int, float)):
        return None
    if isinstance(zaehler, bool) or isinstance(nenner, bool) or nenner <= 0:
        return None
    return round(zaehler / nenner * faktor, stellen)


# Kennzahlen, die „Neu prüfen" zwischen altem und neuem Stand vergleicht.
# Bewusst nur die beweglichen Größen — Zensuswerte haben einen festen Stichtag
# und würden hier nur Rauschen aus der stochastischen Überlagerung melden.
VERLAUF_KENNZAHLEN = [
    ("gastro_gesamt", "Gastronomie gesamt"),
    ("fast_food", "davon Schnellrestaurants"),
    ("gastro_bis_300", "Gastronomie bis 300 m"),
    ("naechster_wettbewerber", "Nächster Betrieb (m)"),
    ("ketten", "davon Ketten"),
    ("leerstand_osm", "Leerstände (OSM)"),
    ("frequenzbringer", "Frequenzbringer"),
    ("haltestellen", "Haltestellen"),
    ("abfahrten", "Abfahrten/Tag (GTFS)"),
    ("abfahrten_mittag", "Abfahrten 11–14 Uhr"),
    ("dtv_kfz", "Kfz/Tag stärkste Zählstelle"),
    ("rad_je_tag", "Radfahrende/Tag (Messung)"),
]


# Spaltengruppen. Die Tabelle ist über die Ausbaustufen auf 37 Spalten
# gewachsen; ohne Gruppierung scrollt man an der Bezeichnung vorbei und findet
# nichts wieder. "vorgabe" bestimmt, welche Gruppen beim Öffnen sichtbar sind —
# ausgeschaltet werden nur Gruppen, nie einzelne Spalten, damit die Tabelle
# nicht in beliebig viele Zustände zerfällt.
VERGLEICH_GRUPPEN = [
    {"key": "standort", "titel": "Standort", "vorgabe": True, "fest": True},
    {"key": "bevoelkerung", "titel": "Bevölkerung & Wohnen", "vorgabe": True},
    {"key": "wettbewerb", "titel": "Wettbewerb", "vorgabe": True},
    {"key": "erreichbarkeit", "titel": "Erreichbarkeit zu Fuß", "vorgabe": False},
    {"key": "verkehr", "titel": "Verkehr & ÖPNV", "vorgabe": True},
    {"key": "detail", "titel": "Detail & abgeleitete Werte", "vorgabe": False},
]

VERGLEICH_SPALTEN = [
    # --- Standort (immer sichtbar, erste Spalte bleibt beim Scrollen stehen) ---
    {"key": "label", "titel": "Bezeichnung", "gruppe": "standort"},
    # Die einzigen beiden Werte in dieser Tabelle, die nicht aus einer API
    # stammen — sie kommen vom Nutzer und sind so beschriftet.
    {"key": "bewertung", "titel": "Eigene Note (1–5)", "gruppe": "standort"},
    {"key": "stand", "titel": "Arbeitsstand", "gruppe": "standort"},
    {"key": "notiz", "titel": "Eigene Notiz", "gruppe": "standort"},
    {"key": "adresse", "titel": "Adresse", "gruppe": "standort"},
    {"key": "gemeinde", "titel": "Gemeinde", "gruppe": "standort"},
    {"key": "radius", "titel": "Radius (m)", "gruppe": "standort"},

    # --- Bevölkerung und Wohnen ---
    {"key": "einwohner", "titel": "Einwohner", "gruppe": "bevoelkerung"},
    {"key": "durchschnittsalter", "titel": "Durchschnittsalter", "gruppe": "bevoelkerung"},
    {"key": "haushaltsgroesse", "titel": "Haushaltsgröße", "gruppe": "detail"},
    # Kreiswert aus den VGRdL — die ehrliche Kaufkraft-Näherung. In der
    # Detailgruppe, weil er innerhalb einer Stadt keine Viertel unterscheidet.
    {"key": "einkommen_kreis", "titel": "Verf. Einkommen €/Einw. (Kreis)",
     "gruppe": "detail"},
    # "stellen" legt die Nachkommastellen in Tabelle und Export fest. Ohne die
    # Angabe rundet die Oberfläche auf eine Stelle — bei kleinen Verhältniszahlen
    # verschwindet damit genau der Unterschied, den man vergleichen will.
    {"key": "miete_qm", "titel": "Nettokaltmiete €/m²", "stellen": 2,
     "gruppe": "bevoelkerung"},
    {"key": "leerstandsquote", "titel": "Leerstandsquote %", "stellen": 2,
     "gruppe": "bevoelkerung"},

    # --- Wettbewerb ---
    {"key": "gastro_gesamt", "titel": "Gastronomie gesamt", "gruppe": "wettbewerb"},
    {"key": "fast_food", "titel": "davon Schnellrestaurants", "gruppe": "wettbewerb"},
    {"key": "gastro_bis_150", "titel": "Gastronomie bis 150 m", "gruppe": "detail"},
    {"key": "gastro_bis_300", "titel": "Gastronomie bis 300 m", "gruppe": "wettbewerb"},
    {"key": "naechster_wettbewerber", "titel": "Nächster Betrieb (m)",
     "gruppe": "wettbewerb"},
    # Für Franchisenehmer: ein hoher Kettenanteil heißt, andere Systeme haben
    # diese Lage bereits professionell geprüft — und besetzen sie. In der
    # Detailgruppe, damit die Vorgabeansicht schmal bleibt.
    {"key": "ketten_anteil", "titel": "Kettenanteil % (berechnet)", "stellen": 1,
     "gruppe": "detail"},
    {"key": "wettbewerb_je_1000", "titel": "Wettbewerber je 1.000 Einw. (berechnet)",
     "stellen": 1, "gruppe": "wettbewerb"},
    {"key": "fastfood_je_1000", "titel": "Schnellrestaurants je 1.000 Einw. (berechnet)",
     "stellen": 2, "gruppe": "detail"},

    # --- Erreichbarkeit zu Fuß (nur belegt, wenn Block 4b geladen war) ---
    {"key": "einwohner_gehweg", "titel": "Einwohner zu Fuß erreichbar",
     "gruppe": "erreichbarkeit"},
    {"key": "erschliessung_einwohner", "titel": "Erschließungsgrad Einwohner %",
     "stellen": 1, "gruppe": "erreichbarkeit"},
    {"key": "gastro_gehweg", "titel": "Gastronomie zu Fuß erreichbar",
     "gruppe": "erreichbarkeit"},
    {"key": "umwegfaktor", "titel": "Umwegfaktor (Median)", "stellen": 2,
     "gruppe": "erreichbarkeit"},

    # --- Verkehr und ÖPNV ---
    {"key": "frequenzbringer", "titel": "Frequenzbringer", "gruppe": "verkehr"},
    {"key": "haltestellen", "titel": "Haltestellen", "gruppe": "verkehr"},
    {"key": "linien", "titel": "Linien (eindeutig)", "gruppe": "detail"},
    {"key": "abfahrten", "titel": "Abfahrten/Tag (GTFS)", "gruppe": "verkehr"},
    {"key": "abfahrten_mittag", "titel": "Abfahrten 11–14 Uhr", "gruppe": "verkehr"},
    # Für Abendkonzepte (Bar, Abendlokal) das relevantere Fenster.
    {"key": "abfahrten_abend", "titel": "Abfahrten 17–22 Uhr", "gruppe": "detail"},
    # Für Nachtkonzepte (Bar, Club): kommt das Publikum nach Mitternacht weg?
    {"key": "abfahrten_nacht", "titel": "Abfahrten 22–1 Uhr", "gruppe": "detail"},
    {"key": "mittagsanteil", "titel": "Anteil Mittag % (berechnet)", "stellen": 1,
     "gruppe": "detail"},
    {"key": "abfahrten_je_einwohner", "titel": "Abfahrten je Einwohner (berechnet)",
     "stellen": 2, "gruppe": "detail"},
    {"key": "dtv_kfz", "titel": "Kfz/Tag stärkste Zählstelle", "gruppe": "verkehr"},
    {"key": "dtv_sv_anteil", "titel": "Schwerverkehr %", "gruppe": "detail"},
    {"key": "rad_je_tag", "titel": "Radfahrende/Tag (Messung)", "gruppe": "detail"},

    # --- Weiteres ---
    {"key": "ags", "titel": "Gemeindeschlüssel", "gruppe": "detail"},
    {"key": "ketten", "titel": "davon Ketten", "gruppe": "detail"},
    {"key": "rad_entfernung", "titel": "Entfernung Zählstelle (m)", "gruppe": "detail"},
    {"key": "neubau_anteil", "titel": "Gebäude ab 2020 %", "stellen": 1,
     "gruppe": "detail"},
    {"key": "leerstand_osm", "titel": "Leerstände (OSM)", "gruppe": "detail"},
    {"key": "erzeugt", "titel": "Abgerufen am", "gruppe": "detail"},
    {"key": "geprueft", "titel": "Zuletzt geprüft", "gruppe": "detail"},

    # --- Kreisprofil (Regionalatlas) — Kreiswerte, deshalb Detailgruppe:
    # innerhalb einer Stadt unterscheiden sie keine Viertel, zwischen zwei
    # Kandidaten in verschiedenen Kreisen sind sie genau der Unterschied.
    {"key": "uebernachtungen_je_ew", "titel": "Übernachtungen je Einw. (Kreis)",
     "stellen": 1, "gruppe": "detail"},
    {"key": "et_je_1000_ew", "titel": "Erwerbstätige am Arbeitsort je 1.000 EW (Kreis)",
     "gruppe": "detail"},
    {"key": "arbeitslosenquote", "titel": "Arbeitslosenquote % (Kreis)",
     "stellen": 1, "gruppe": "detail"},
    {"key": "bev_entwicklung", "titel": "Bevölkerungsentw. je 10.000 EW (Kreis)",
     "stellen": 1, "gruppe": "detail"},

    # --- Klima (DWD, nächste Station) — für Außengastronomie-Konzepte.
    {"key": "sommertage", "titel": "Sommertage/Jahr (DWD-Station)",
     "stellen": 1, "gruppe": "detail"},
    {"key": "sonnenschein", "titel": "Sonnenstunden/Jahr (DWD-Station)",
     "gruppe": "detail"},

    # --- Pendler (Gemeindewert) — Tagesbevölkerung: positiver Saldo heißt,
    # tagsüber sind mehr Menschen da, als hier wohnen.
    {"key": "pendler_saldo", "titel": "Pendlersaldo (Gemeinde)", "gruppe": "detail"},
    {"key": "einpendler_quote", "titel": "Einpendlerquote % (Gemeinde)",
     "stellen": 1, "gruppe": "detail"},

    # --- Gastro-Dynamik (OSM-Historie) — Trendzahl, misst auch
    # Kartier-Aktivität; deshalb Detailgruppe.
    {"key": "gastro_trend", "titel": "Gastro-Trend (OSM-Objekte, Mehrjahr)",
     "gruppe": "detail"},

    # --- Overture-Abgleich: OSM-Untergrenze plus Nur-Overture-Treffer.
    # Abgeleiteter Wert → Detailgruppe, damit die Vorgabeansicht schlank bleibt.
    {"key": "wettbewerb_kombiniert", "titel": "Gastro kombiniert (OSM+Overture)",
     "gruppe": "detail"},

    # --- Öffnungszeiten-Lücken (Mindestzahlen aus OSM).
    {"key": "sonntag_offen", "titel": "Sonntags geöffnet (mind., OSM)",
     "gruppe": "detail"},
    {"key": "nach22_offen", "titel": "Nach 22 Uhr geöffnet (mind., OSM)",
     "gruppe": "detail"},

    # --- Wirtschaftskraft (Regionalatlas, Kreiswert).
    {"key": "bip_je_ew", "titel": "BIP je Einwohner € (Kreis)",
     "gruppe": "detail"},

    # --- München-Quellen: leer außerhalb der Stadt, deshalb Detailgruppe.
    {"key": "baustellen_laufend", "titel": "Baustellen laufend im Radius (M)",
     "gruppe": "detail"},
    {"key": "maerkte_reichweite", "titel": "Städt. Märkte bis 2 km (M)",
     "gruppe": "detail"},
    {"key": "messe_distanz_m", "titel": "Nächstes Messegelände m (M)",
     "gruppe": "detail"},
    {"key": "erhaltungssatzung", "titel": "Erhaltungssatzung § 172 BauGB (M)",
     "gruppe": "detail"},
    {"key": "einpersonenhaushalte", "titel": "Einpersonenhaushalte % (Bezirk M)",
     "stellen": 1, "gruppe": "detail"},

    # --- Kurzzeitvermietung (Inside Airbnb) — nur für Städte mit Datensatz.
    {"key": "airbnb_im_radius", "titel": "Airbnb-Inserate im Radius",
     "gruppe": "detail"},

    # --- Amtlicher Gastro-Anker (Regionaldatenbank, Opt-in) — leer ohne
    # hinterlegte Kennung.
    {"key": "ust_je_pflichtigem", "titel": "Umsatz je USt-Pflichtigem Gastgewerbe € (Kreis)",
     "gruppe": "detail"},
]


def _row_for(saved: dict[str, Any]) -> dict[str, Any]:
    p = saved.get("payload") or {}
    punkt = p.get("punkt") or {}
    bl = p.get("bloecke") or {}
    z = (bl.get("zensus") or {}).get("data") or {}
    o = (bl.get("osm") or {}).get("data") or {}
    g = (bl.get("gtfs") or {}).get("data") or {}
    rad = ((bl.get("radzaehlung") or {}).get("data") or {}).get("naechste") or {}
    eink = ((bl.get("einkommen") or {}).get("data") or {}) or {}
    kp = {
        i.get("schluessel"): i.get("kreis")
        for i in (((bl.get("kreisprofil") or {}).get("data") or {})
                  .get("indikatoren") or [])
    }
    kl = {
        k.get("schluessel"): k.get("wert")
        for k in (((bl.get("klima") or {}).get("data") or {})
                  .get("kennzahlen") or [])
    }
    pen = ((bl.get("pendler") or {}).get("data") or {}) or {}
    dyn = (((bl.get("dynamik") or {}).get("data") or {})
           .get("veraenderung") or {})
    gw = ((bl.get("gehweg") or {}).get("data") or {}) or {}
    gw_gas = gw.get("gastronomie") or {}
    gw_zen = gw.get("zensus") or {}
    vm = ((bl.get("verkehrsmenge") or {}).get("data") or {}) or {}
    vms = vm.get("staerkste") or {}
    bev = z.get("bevoelkerung") or {}
    woh = z.get("wohnen") or {}
    zus = o.get("zusammenfassung") or {}
    gas = zus.get("gastronomie") or {}
    einwohner = _wert(bev.get("einwohner"))
    abfahrten = (g or {}).get("abfahrten_gesamt")
    mittag = (g or {}).get("abfahrten_mittag")
    fastfood = (gas.get("nach_typ") or {}).get("Schnellrestaurant")
    stufen = {s["bis_m"]: s["anzahl"] for s in (gas.get("nach_entfernung") or [])}
    return {
        "id": saved.get("id"),
        "label": saved.get("label"),
        "bewertung": saved.get("bewertung"),
        "stand": saved.get("stand"),
        "stand_grund": saved.get("stand_grund"),
        "notiz": saved.get("notiz"),
        "adresse": punkt.get("adresse"),
        "gemeinde": punkt.get("gemeinde"),
        "ags": punkt.get("ags"),
        "radius": saved.get("radius"),
        "einwohner": einwohner,
        "durchschnittsalter": _wert(bev.get("durchschnittsalter")),
        "haushaltsgroesse": _wert(bev.get("haushaltsgroesse")),
        "miete_qm": _wert(woh.get("miete_qm")),
        "einkommen_kreis": (eink.get("kreis") or {}).get("wert_eur"),
        "uebernachtungen_je_ew": kp.get("uebernachtungen_je_ew"),
        "et_je_1000_ew": kp.get("et_je_1000_ew"),
        "arbeitslosenquote": kp.get("arbeitslosenquote"),
        "bev_entwicklung": kp.get("bev_entwicklung"),
        "sommertage": kl.get("sommertage"),
        "sonnenschein": kl.get("sonnenschein"),
        "pendler_saldo": pen.get("saldo"),
        "einpendler_quote": pen.get("einpendler_quote"),
        "gastro_trend": dyn.get("absolut"),
        "wettbewerb_kombiniert": (
            (((bl.get("overture") or {}).get("data") or {}) or {})
            .get("kombiniert_gesamt")
        ),
        "sonntag_offen": (gas.get("oeffnungszeiten") or {}).get("sonntag_offen"),
        "nach22_offen": (gas.get("oeffnungszeiten") or {}).get("nach22_offen"),
        "bip_je_ew": kp.get("bip_je_ew"),
        "baustellen_laufend": (
            ((bl.get("baustellen") or {}).get("data") or {}).get("laufend")
        ),
        "maerkte_reichweite": (
            len(((bl.get("maerkte") or {}).get("data")).get("in_reichweite") or [])
            if (bl.get("maerkte") or {}).get("data") else None
        ),
        "messe_distanz_m": (
            (((bl.get("messe") or {}).get("data") or {})
             .get("naechstes_gelaende") or {}).get("distanz_m")
        ),
        "erhaltungssatzung": (
            ("Ja" if (((bl.get("planung") or {}).get("data") or {})
                      .get("erhaltungssatzung") or {}).get("betroffen")
             else "Nein")
            if ((bl.get("planung") or {}).get("data") or {}).get("erhaltungssatzung")
            is not None
            else None
        ),
        "airbnb_im_radius": (
            ((bl.get("airbnb") or {}).get("data") or {}).get("im_radius")
            if (bl.get("airbnb") or {}).get("data") else None
        ),
        "ust_je_pflichtigem": (
            ((((bl.get("genesis") or {}).get("data") or {}).get("umsatz") or {})
             .get("aktuell") or {}).get("je_pflichtigem_eur")
        ),
        "einpersonenhaushalte": next(
            (
                (z_.get("bezirk") or {}).get("wert")
                for z_ in (((bl.get("indikatoren") or {}).get("data") or {})
                           .get("indikatoren") or [])
                if z_.get("schluessel") == "einpersonenhaushalte"
            ),
            None,
        ),
        "leerstandsquote": _wert(woh.get("leerstandsquote")),
        "gastro_gesamt": gas.get("gesamt"),
        "fast_food": fastfood,
        "ketten": gas.get("ketten"),
        # Ein Betrieb in 50 m konkurriert anders als einer am Rand des Umkreises.
        "gastro_bis_150": stufen.get(150),
        "gastro_bis_300": stufen.get(300),
        "naechster_wettbewerber": gas.get("naechster_m"),
        # Sättigung: wie viele Betriebe teilen sich die Wohnbevölkerung. Sagt
        # nichts über Zulauf von außen — in der Innenstadt deshalb hoch, ohne
        # dass der Standort schlecht wäre.
        "wettbewerb_je_1000": je_bezugsgroesse(gas.get("gesamt"), einwohner, 1000, 1),
        # Für einen Imbiss sind 30 Cafés kein Wettbewerb — die engere Zahl.
        "fastfood_je_1000": je_bezugsgroesse(fastfood, einwohner, 1000, 2),
        # Systemgastronomie prüft Standorte professionell: ein hoher Anteil
        # heißt, die Lage ist geprüft — und besetzt.
        "ketten_anteil": je_bezugsgroesse(gas.get("ketten"), gas.get("gesamt"), 100, 1),
        "frequenzbringer": (zus.get("frequenzbringer") or {}).get("gesamt"),
        "haltestellen": (zus.get("oepnv") or {}).get("haltestellen"),
        "linien": (zus.get("oepnv") or {}).get("linien_eindeutig"),
        "abfahrten": abfahrten,
        # Eine Pendlerhaltestelle hat ihre Spitzen um 8 und um 18 Uhr und ist
        # mittags leer — das trennt die beiden Fälle.
        "abfahrten_mittag": mittag,
        "abfahrten_abend": (g or {}).get("abfahrten_abend"),
        "abfahrten_nacht": (g or {}).get("abfahrten_nacht"),
        "mittagsanteil": je_bezugsgroesse(mittag, abfahrten, 100, 1),
        # Näherung für Zulauf, den der Zensus nicht sieht: viele Abfahrten bei
        # wenig Wohnbevölkerung heißt, die Leute kommen von woanders.
        "abfahrten_je_einwohner": je_bezugsgroesse(abfahrten, einwohner, 1, 2),
        "dtv_kfz": vms.get("dtv_kfz"),
        "dtv_sv_anteil": vms.get("schwerverkehr_anteil"),
        "rad_je_tag": rad.get("je_tag_vorjahr"),
        "rad_entfernung": rad.get("distanz_m"),
        "neubau_anteil": woh.get("neubau_anteil"),
        "einwohner_gehweg": gw_zen.get("einwohner_gehweg"),
        "erschliessung_einwohner": gw_zen.get("erschliessungsgrad"),
        "gastro_gehweg": gw_gas.get("im_gehradius"),
        "umwegfaktor": gw_gas.get("umwegfaktor_median"),
        "leerstand_osm": (zus.get("leerstand") or {}).get("gesamt"),
        "erzeugt": (p.get("meta") or {}).get("erzeugt"),
        "geprueft": (
            time.strftime("%Y-%m-%d", time.gmtime(saved["geprueft_am"]))
            if saved.get("geprueft_am") else None
        ),
        "lat": saved.get("lat"),
        "lon": saved.get("lon"),
    }


def _compact(payload: dict[str, Any]) -> dict[str, Any]:
    """Für die Ablage: Rohlisten kürzen, Kennzahlen und Quellen behalten."""
    import copy

    p = copy.deepcopy(payload)
    z = ((p.get("bloecke") or {}).get("zensus") or {}).get("data")
    if isinstance(z, dict):
        z.pop("zellen", None)
    return p


def point_to_csv(data: dict[str, Any]) -> str:
    """Ein Punkt als CSV — je Zeile eine Kennzahl mit Quelle und Stand (Spec §5)."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Block", "Kennzahl", "Wert", "Einheit", "Zellen/Basis", "Quelle", "Stand", "Lizenz"])

    punkt = data.get("punkt") or {}
    meta = data.get("meta") or {}
    for k, v in punkt.items():
        w.writerow(["Kopf", k, v, "", "", "abgeleitet", meta.get("erzeugt", ""), ""])

    bl = data.get("bloecke") or {}

    def prov(name: str) -> tuple[str, str, str]:
        p = (bl.get(name) or {}).get("provenance") or {}
        return p.get("source", ""), p.get("stand", ""), p.get("license", "")

    zsrc, zstand, zlic = prov("zensus")
    z = (bl.get("zensus") or {}).get("data") or {}
    for block, felder in (("Bevölkerung", z.get("bevoelkerung")), ("Wohnen", z.get("wohnen"))):
        for key, node in (felder or {}).items():
            if isinstance(node, dict) and "wert" in node:
                einheit = _einheit(key)
                w.writerow(
                    [block, key, node["wert"], einheit,
                     f"{node.get('zellen', '')}/{node.get('zellen_gesamt', '')} Zellen",
                     zsrc, zstand, zlic]
                )
            elif isinstance(node, dict):
                for sub, snode in node.items():
                    if isinstance(snode, dict) and "wert" in snode:
                        w.writerow(
                            [block, f"{key}: {sub}", snode["wert"], "",
                             f"{snode.get('zellen', '')}/{snode.get('zellen_gesamt', '')} Zellen",
                             zsrc, zstand, zlic]
                        )

    osrc, ostand, olic = prov("osm")
    o = (bl.get("osm") or {}).get("data") or {}
    zus = o.get("zusammenfassung") or {}
    for block, felder in zus.items():
        for key, val in (felder or {}).items():
            if isinstance(val, dict):
                for sub, sval in val.items():
                    w.writerow([block, f"{key}: {sub}", sval, "", "", osrc, ostand, olic])
            else:
                w.writerow([block, key, val, "", "", osrc, ostand, olic])

    gsrc, gstand, glic = prov("gtfs")
    g = (bl.get("gtfs") or {}).get("data") or {}
    rad = ((bl.get("radzaehlung") or {}).get("data") or {}).get("naechste") or {}
    vm = ((bl.get("verkehrsmenge") or {}).get("data") or {}) or {}
    vms = vm.get("staerkste") or {}
    if g:
        w.writerow(["Verkehr", "Abfahrten gesamt", g.get("abfahrten_gesamt"), "je Tag",
                    g.get("referenzdatum", ""), gsrc, gstand, glic])
        for h, n in (g.get("abfahrten_je_stunde") or {}).items():
            w.writerow(["Verkehr", f"Abfahrten {h}:00", n, "je Stunde",
                        g.get("referenzdatum", ""), gsrc, gstand, glic])

    rsrc, rstand, rlic = prov("radzaehlung")
    r = (bl.get("radzaehlung") or {}).get("data") or {}
    for s_ in r.get("in_reichweite") or []:
        w.writerow(["Radverkehr", f"Zählstelle {s_['name']}", s_.get("je_tag_vorjahr"),
                    "Radfahrende je Tag", f"{s_['distanz_m']} m entfernt",
                    rsrc, rstand, rlic])

    vsrc, vstand, vlic = prov("verkehrsmenge")
    v = (bl.get("verkehrsmenge") or {}).get("data") or {}
    for z in v.get("zaehlstellen") or []:
        w.writerow(["Verkehrsmenge", f"{z['strasse']} (Zählstelle {z['zaehlstelle']})",
                    z.get("dtv_kfz"), "Kfz je Tag", f"{z['distanz_m']} m entfernt",
                    vsrc, vstand, vlic])

    for i, hinweis in enumerate(data.get("grenzen") or [], 1):
        w.writerow(["Grenzen", f"Hinweis {i}", hinweis, "", "", "", "", ""])

    return buf.getvalue()


def _einheit(key: str) -> str:
    if key.startswith("anteil") or key.endswith("quote"):
        return "%"
    if key == "miete_qm":
        return "€/m²"
    if key.startswith("flaeche"):
        return "m²"
    if key == "durchschnittsalter":
        return "Jahre"
    if key == "haushaltsgroesse":
        return "Personen"
    if key == "einwohner":
        return "Personen"
    return ""
