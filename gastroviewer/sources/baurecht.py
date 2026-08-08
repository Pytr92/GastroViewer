"""Baurecht am Punkt — darf hier überhaupt Gastronomie betrieben werden?

Das ist die Frage, die jede Umsatzprognose schlägt: Baurecht ist keine
Wahrscheinlichkeit, sondern ein Ja oder Nein. Beantworten lässt sie sich
aus offenen Daten leider nur an wenigen Orten.

**Der Phase-0-Befund (2026-08-08) ist ernüchternd und steht so im Block:**
Der bundesweite Geodatenkatalog kennt 566.145 Datensätze zu Bebauungsplänen,
aber nur 15 mit dem Objekt ``BP_BaugebietsTeilFlaeche`` — also mit der
Art der baulichen Nutzung (Kerngebiet, Mischgebiet, Gewerbegebiet …), die
über die Zulässigkeit entscheidet. Alles andere ist der bloße Umring des
Plans mit einem PDF-Link.

Deshalb drei Stufen, jede klar beschriftet:

1. **Gebietsart punktgenau** (Hamburg, Freiburg) — die eigentliche Antwort,
   inklusive Festsetzungstext und Maß der Nutzung.
2. **Planumring mit PDF** (Berlin) — „hier gilt Plan X", ohne flächenscharfe
   Nutzungsart. Der Nutzen liegt im Absprung ins PDF.
3. **Kein Plan gefunden** — dann gilt § 34 BauGB (Einfügen in die Eigenart
   der näheren Umgebung), und in gewachsener Gemengelage ist Gastronomie
   meist zulässig. Das ist eine *echte* Aussage, keine Fehlanzeige.

Dazu zwei Berliner Restriktionen mit unmittelbarer Rechtsfolge:
Sanierungsgebiete (§§ 144/145 BauGB: Nutzungsänderung genehmigungspflichtig)
und die Denkmalliste (betrifft Umbau, Lüftung, Außenwerbung, Bestuhlung).

Nicht enthalten, mit Grund: **München** behält sich sämtliche Rechte an
seinen Bauleitplandaten vor (keine offenen Daten), **Bayerns** Landesdienst
führt nur Umringe und antwortet in den geprüften Großstädten leer, und
**Sperrzeiten** existieren bundesweit in keiner maschinenlesbaren Form —
sie sind Landes- und Kommunalrecht, GovData und der Geokatalog liefern
dafür null Treffer.
"""

from __future__ import annotations

from typing import Any

from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, now_iso

# Achsenreihenfolge: Mit "urn:ogc:def:crs:EPSG::4326" liefern die
# deegree-Dienste stumm 0 Treffer (lat/lon-Vertauschung). CRS84 ist
# lon/lat und in Phase 0 als der zuverlässige Weg bestätigt.
CRS = "urn:ogc:def:crs:OGC:1.3:CRS84"
# Halber Kantenlänge der Abfrage-Bbox in Grad (~11 m). Klein genug, dass
# das Ergebnis den Punkt meint, groß genug gegen Rundungsfehler.
BBOX_GRAD = 0.0001

# Art der baulichen Nutzung nach BauNVO — und was sie für Gastronomie
# bedeutet. Die Einordnung ist bewusst knapp und als Orientierung
# gekennzeichnet: Was der konkrete Plan festsetzt, steht im Plan.
BAUNVO_DEUTUNG = {
    "Kleinsiedlungsgebiet": ("WS", "Schank- und Speisewirtschaften nur "
                             "ausnahmsweise zulässig."),
    "ReinesWohngebiet": ("WR", "Gastronomie in aller Regel unzulässig — "
                         "nur ausnahmsweise für den Gebietsbedarf."),
    "AllgWohngebiet": ("WA", "Schank- und Speisewirtschaften zur Versorgung "
                       "des Gebiets allgemein zulässig; größere Betriebe "
                       "und Vergnügungsstätten nicht."),
    "BesonderesWohngebiet": ("WB", "Schank- und Speisewirtschaften allgemein "
                             "zulässig."),
    "Dorfgebiet": ("MD", "Schank- und Speisewirtschaften allgemein zulässig."),
    "DoerflichesWohngebiet": ("MDW", "Schank- und Speisewirtschaften "
                              "allgemein zulässig."),
    "Mischgebiet": ("MI", "Schank- und Speisewirtschaften allgemein "
                    "zulässig — der klassische Gastronomie-Standort."),
    "UrbanesGebiet": ("MU", "Schank- und Speisewirtschaften allgemein "
                      "zulässig; auf Nachbarschaftsverträglichkeit achten."),
    "Kerngebiet": ("MK", "Schank- und Speisewirtschaften allgemein zulässig "
                   "— die für Gastronomie günstigste Gebietsart."),
    "Gewerbegebiet": ("GE", "Schank- und Speisewirtschaften allgemein "
                      "zulässig; Wohnnutzung dagegen kaum — abends oft "
                      "wenig Laufkundschaft."),
    "Industriegebiet": ("GI", "Nur Kantinen für den Betriebsbedarf; "
                        "öffentliche Gastronomie regelmäßig unzulässig."),
    "SondergebietErholung": ("SO", "Zulässigkeit richtet sich allein nach "
                             "der Zweckbestimmung des Sondergebiets."),
    "SonstigesSondergebiet": ("SO", "Zulässigkeit richtet sich allein nach "
                              "der Zweckbestimmung des Sondergebiets."),
}

# Nur Dienste, die in Phase 0 mit einer echten Punktabfrage geantwortet
# haben. Der Kreis Wesel/KRZN führt dieselben Objekte (dl-de/zero-2-0),
# ist hier aber nicht aufgenommen, weil die Probeabfrage für die geprüfte
# Koordinate leer blieb — er gehört erst nach eigener Phase 0 dazu.
XPLAN_DIENSTE = (
    {
        "gebiet": "Hamburg",
        "url": ("https://hh.xplan.diplanung.de/xplansyn-wfs/services"
                "/xplansynwfs"),
        "lizenz": ("Datenlizenz Deutschland Namensnennung 2.0 "
                   "(dl-de/by-2-0) · Freie und Hansestadt Hamburg"),
        "bbox": (53.39, 8.10, 53.97, 10.35),
    },
    {
        "gebiet": "Freiburg im Breisgau",
        "url": ("https://xplanung.freiburg.de/xplan-services-wfs-syn"
                "/services/xplansynwfs"),
        "lizenz": "Stadt Freiburg im Breisgau, offene Geodaten",
        "bbox": (47.90, 7.65, 48.07, 7.98),
    },
)

BERLIN_BBOX = (52.33, 13.08, 52.68, 13.77)
BERLIN_DIENSTE = {
    "bplan": ("https://gdi.berlin.de/services/wfs/bplan", "b_bp_fs"),
    "sanierung": ("https://gdi.berlin.de/services/wfs/sanier",
                  "a_sanier_umfassend"),
    "denkmal": ("https://gdi.berlin.de/services/wfs/denkmale", "denkmale"),
}
BERLIN_LIZENZ = ("Datenlizenz Deutschland – Zero – Version 2.0 "
                 "(dl-de/zero-2-0) · Geoportal Berlin")

PARAGRAF_34 = (
    "An diesem Punkt liegt in den offenen Daten **kein Bebauungsplan**. "
    "Dann gilt § 34 BauGB: Zulässig ist, was sich nach Art und Maß in die "
    "Eigenart der näheren Umgebung einfügt. In einer gewachsenen "
    "Gemengelage mit vorhandener Gastronomie spricht das regelmäßig für "
    "die Zulässigkeit — verbindlich ist aber nur die Bauaufsicht."
)

HINWEISE = [
    "Diese Angaben ersetzen **keine Bauvoranfrage**. Verbindlich ist "
    "allein die Auskunft der zuständigen Bauaufsichtsbehörde; der "
    "Festsetzungstext des Plans kann von der Regel der BauNVO abweichen.",
    "Die **Art der baulichen Nutzung** ist bundesweit fast nirgends offen "
    "maschinenlesbar: Der Geodatenkatalog kennt 566.145 Datensätze zu "
    "Bebauungsplänen, aber nur 15 mit der Gebietsart. Punktgenau "
    "beantworten können das hier nur Hamburg und Freiburg.",
    "**Sperrzeiten** (bis wann darf ausgeschenkt werden?) gibt es in "
    "keiner maschinenlesbaren Quelle — sie sind Landes- und "
    "Kommunalrecht. Dafür bleibt der Griff zur örtlichen Verordnung.",
]


def _bbox(lat: float, lon: float) -> str:
    return (f"{lon - BBOX_GRAD},{lat - BBOX_GRAD},"
            f"{lon + BBOX_GRAD},{lat + BBOX_GRAD},{CRS}")


def _in_bbox(lat: float, lon: float, box: tuple[float, ...]) -> bool:
    return box[0] <= lat <= box[2] and box[1] <= lon <= box[3]


def dienst_fuer(lat: float, lon: float) -> dict[str, Any] | None:
    for d in XPLAN_DIENSTE:
        if _in_bbox(lat, lon, d["bbox"]):
            return d
    return None


def deuten(art: str | None) -> dict[str, Any] | None:
    """BauNVO-Gebietsart → Kürzel und Gastronomie-Einordnung."""
    if not art:
        return None
    treffer = BAUNVO_DEUTUNG.get(art)
    if treffer is None:
        return {"art": art, "kuerzel": None,
                "gastronomie": "Einordnung nur über den Festsetzungstext."}
    return {"art": art, "kuerzel": treffer[0], "gastronomie": treffer[1]}


def parse_baugebiete(antwort: dict[str, Any]) -> list[dict[str, Any]]:
    """XPlanSyn-GeoJSON → Baugebiets-Teilflächen am Punkt."""
    flaechen = []
    for f in antwort.get("features") or []:
        p = f.get("properties") or {}
        art = p.get("besondereArtDerBaulNutzungWert")
        flaechen.append({
            "plan": p.get("xpPlanName"),
            "art": art,
            "deutung": deuten(art),
            "allgemeine_art": p.get("allgArtDerBaulNutzungWert"),
            "rechtsstand": p.get("rechtsstandWert"),
            "aufschrift": p.get("aufschrift"),
            "grz": p.get("GRZ"),
            "gfz": p.get("GFZ"),
            "text": (p.get("text") or "")[:400] or None,
        })
    # Doppelte Flächen desselben Plans mit gleicher Art zusammenfassen.
    gesehen, eindeutig = set(), []
    for fl in flaechen:
        schluessel = (fl["plan"], fl["art"], fl["aufschrift"])
        if schluessel in gesehen:
            continue
        gesehen.add(schluessel)
        eindeutig.append(fl)
    return eindeutig


def parse_berlin_bplan(antwort: dict[str, Any]) -> list[dict[str, Any]]:
    """Berliner Planumringe. Das Feld ``inhalt`` ist eine planweite
    Aufzählung, **nicht** flächenscharf — entsprechend beschriftet."""
    plaene = []
    for f in antwort.get("features") or []:
        p = f.get("properties") or {}
        if str(p.get("bp_rechtsstand") or "").startswith("Teilweise unterg"):
            continue
        plaene.append({
            "plan": p.get("planname"),
            "art": p.get("planartname"),
            "rechtsstand": p.get("bp_rechtsstand"),
            "bereich": p.get("bereich"),
            "bezirk": p.get("bezirk"),
            "festgesetzt_am": p.get("festsg_am"),
            "inhalt_planweit": p.get("inhalt"),
            "pdf": p.get("scan_www") or None,
        })
    return plaene


def parse_berlin_sanierung(antwort: dict[str, Any]) -> list[dict[str, Any]]:
    gebiete = []
    for f in antwort.get("features") or []:
        p = f.get("properties") or {}
        gebiete.append({
            "name": p.get("gebietsname"),
            "bezirk": p.get("bezirk"),
            "verfahren": p.get("verfahren"),
            "in_kraft_seit": p.get("f_in_kraft"),
            "flaeche_ha": p.get("fl_in_ha"),
        })
    return gebiete


def parse_berlin_denkmal(antwort: dict[str, Any]) -> list[dict[str, Any]]:
    denkmale = []
    for f in antwort.get("features") or []:
        p = f.get("properties") or {}
        denkmale.append({"typ": p.get("typ"), "id": p.get("id"),
                         "link": p.get("link")})
    return denkmale


async def _wfs(out: Outbound, quelle: str, url: str, typ: str,
               lat: float, lon: float) -> dict[str, Any]:
    try:
        return await out.get_json(
            quelle, url,
            params={
                "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
                "TYPENAMES": typ, "outputFormat": "application/json",
                "count": "20", "bbox": _bbox(lat, lon),
            },
            timeout=60.0, limiter=quelle, min_interval=1.0,
        )
    except SourceError as err:
        # Der Berliner Geodienst nutzt ein Wurzelzertifikat, das ältere
        # Zertifikatsspeicher nicht kennen — ohne Übersetzung landet das
        # als unverständlicher TLS-Fehler beim Nutzer.
        if "certificate" in (err.detail or err.message or "").lower():
            raise SourceError(
                "tls",
                "Der Geodienst nutzt ein Wurzelzertifikat, das dieses "
                "System nicht kennt. Abhilfe: Zertifikatsspeicher "
                "aktualisieren (z. B. `pip install --upgrade certifi`).",
                detail=err.detail,
            ) from err
        raise


async def load(out: Outbound, lat: float, lon: float) -> SourceResult:
    """Baurechtlicher Rahmen am Punkt, so weit offene Daten ihn hergeben."""
    daten: dict[str, Any] = {
        "stufe": None, "gebiet": None, "baugebiete": [], "plaene": [],
        "sanierungsgebiete": [], "denkmale": [],
        "paragraf_34": False, "hinweise": HINWEISE,
    }
    warnungen: list[str] = []

    dienst = dienst_fuer(lat, lon)
    if dienst is not None:
        antwort = await _wfs(out, "xplan", dienst["url"],
                             "xplan:BP_BaugebietsTeilFlaeche", lat, lon)
        daten["baugebiete"] = parse_baugebiete(antwort)
        daten["gebiet"] = dienst["gebiet"]
        lizenz = dienst["lizenz"]
        if daten["baugebiete"]:
            daten["stufe"] = "gebietsart"
        else:
            daten["stufe"] = "kein_plan"
            daten["paragraf_34"] = True
            warnungen.append(PARAGRAF_34)
    elif _in_bbox(lat, lon, BERLIN_BBOX):
        daten["gebiet"] = "Berlin"
        lizenz = BERLIN_LIZENZ
        url, typ = BERLIN_DIENSTE["bplan"]
        daten["plaene"] = parse_berlin_bplan(
            await _wfs(out, "berlin_bplan", url, typ, lat, lon))
        for schluessel, parser, ziel in (
            ("sanierung", parse_berlin_sanierung, "sanierungsgebiete"),
            ("denkmal", parse_berlin_denkmal, "denkmale"),
        ):
            url, typ = BERLIN_DIENSTE[schluessel]
            try:
                daten[ziel] = parser(
                    await _wfs(out, f"berlin_{schluessel}", url, typ,
                               lat, lon))
            except SourceError as err:
                warnungen.append(f"{schluessel.capitalize()}: {err.message}")
        if daten["plaene"]:
            daten["stufe"] = "umring"
            warnungen.append(
                "Für Berlin liefern die offenen Daten nur den Planumring "
                "mit PDF-Link — die Art der baulichen Nutzung steht im "
                "Plan selbst, nicht flächenscharf in den Daten.")
        else:
            daten["stufe"] = "kein_plan"
            daten["paragraf_34"] = True
            warnungen.append(PARAGRAF_34)
    else:
        lizenz = "je Gebiet verschieden — hier kein offener Dienst"
        daten["stufe"] = "kein_dienst"
        warnungen.append(
            "Für diesen Ort gibt es keinen offenen Bauleitplan-Dienst, den "
            "dieses Werkzeug auswerten kann. Punktgenaue Gebietsarten "
            "liefern bundesweit nur Hamburg und Freiburg; Berlin liefert "
            "Planumringe. München behält sich alle Rechte an seinen "
            "Bauleitplandaten vor, Bayerns Landesdienst führt nur Umringe "
            "und antwortet in den Großstädten leer.")

    if daten["sanierungsgebiete"]:
        warnungen.append(
            "**Sanierungsgebiet:** Nutzungsänderungen und bauliche "
            "Änderungen brauchen hier zusätzlich eine Genehmigung nach "
            "§§ 144/145 BauGB — das betrifft den Umbau eines Ladens zur "
            "Gastronomie unmittelbar.")
    if daten["denkmale"]:
        warnungen.append(
            f"**Denkmalschutz:** {len(daten['denkmale'])} eingetragene "
            "Objekte am Punkt. Umbau, Lüftungsführung, Außenwerbung und "
            "Bestuhlung sind dann genehmigungspflichtig.")

    return SourceResult(
        name="baurecht", ok=True, data=daten, warnings=warnungen,
        provenance=Provenance(
            source=f"Bauleitplanung {daten['gebiet'] or '(kein Dienst)'}",
            license=lizenz,
            stand="laufend fortgeschrieben",
            retrieved_at=now_iso(),
            note=("Punktabfrage über WFS; ersetzt keine Bauvoranfrage."),
        ),
    )
