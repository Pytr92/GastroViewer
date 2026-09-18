"""Länder-Registry: was das Werkzeug je Land weiß.

Bis Version 0.3 steckte „Deutschland" an rund einem Dutzend Stellen im
Code: die Bereichsregel (47–55,5 N / 5,5–15,5 O), ``countrycodes=de`` beim
Geocoder, der Feiertagsabruf mit ``countryIsoCode=DE``, das Bundesland aus
dem Gemeindeschlüssel, der Kartenhintergrund basemap.de. Hier steht das an
einer Stelle je Land — und jede Quelle sagt, für welche Länder sie gilt.

Grundsatz: Ein Punkt in einem anderen Land bekommt keine falschen Zahlen
aus deutschen Diensten (der nächste DWD-Wetterdienst hinter der Grenze,
das BASt-Netz, der Zensus-Gitterdienst), sondern eine ehrliche Antwort:
„Für Österreich gibt es diese Quelle nicht." Eine Quelle ohne Eintrag in
:data:`QUELLEN_NUR` gilt als länderunabhängig (OpenStreetMap, ohsome,
Leerstandsmelder …).

Die Kästen sind grob und überlappen sich: Südbayern liegt im Kasten
Österreichs und umgekehrt. Deshalb entscheidet bei einem Punkt in beiden
Kästen der Geocoder (``country_code`` von Nominatim), nicht die Geometrie.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Land:
    code: str
    """ISO 3166-1 alpha-2, z. B. ``DE``."""
    name: str
    bbox: tuple[float, float, float, float]
    """Grober Kasten (Süd, West, Nord, Ost) in Grad — nur zur Vorauswahl."""
    geocoder_code: str
    """Nominatim ``countrycodes``-Wert (klein)."""
    feiertage_iso: str
    """OpenHolidaysAPI ``countryIsoCode``."""
    laender: dict[str, tuple[str, str]]
    """ISO 3166-2 → (interner Schlüssel, Name). DE: ``DE-BY`` → (``09``, Bayern);
    AT: ``AT-9`` → (``9``, Wien)."""
    karte: dict[str, Any]
    """Amtlicher Kartenhintergrund für die Oberfläche (Schlüssel, Name, Lizenz)."""
    hinweis: str
    """Was in diesem Land fehlt — steht in der Oberfläche und im Bericht."""

    def im_kasten(self, lat: float, lon: float) -> bool:
        s, w, n, o = self.bbox
        return s <= lat <= n and w <= lon <= o


DE = Land(
    code="DE", name="Deutschland",
    bbox=(47.0, 5.5, 55.5, 15.5),
    geocoder_code="de", feiertage_iso="DE",
    laender={
        "DE-SH": ("01", "Schleswig-Holstein"), "DE-HH": ("02", "Hamburg"),
        "DE-NI": ("03", "Niedersachsen"), "DE-HB": ("04", "Bremen"),
        "DE-NW": ("05", "Nordrhein-Westfalen"), "DE-HE": ("06", "Hessen"),
        "DE-RP": ("07", "Rheinland-Pfalz"), "DE-BW": ("08", "Baden-Württemberg"),
        "DE-BY": ("09", "Bayern"), "DE-SL": ("10", "Saarland"),
        "DE-BE": ("11", "Berlin"), "DE-BB": ("12", "Brandenburg"),
        "DE-MV": ("13", "Mecklenburg-Vorpommern"), "DE-SN": ("14", "Sachsen"),
        "DE-ST": ("15", "Sachsen-Anhalt"), "DE-TH": ("16", "Thüringen"),
    },
    karte={"schluessel": "basemap_de", "name": "basemap.de (amtlich)",
           "lizenz": "GeoBasis-DE / BKG, dl-de/by-2-0"},
    hinweis="",
)

AT = Land(
    code="AT", name="Österreich",
    # Nördlichster Punkt Haugschlag 49,02 N, südlichster Eibiswald 46,37 N,
    # westlichster Bangs 9,53 O, östlichster Deutsch Jahrndorf 17,16 O.
    bbox=(46.35, 9.5, 49.05, 17.2),
    geocoder_code="at", feiertage_iso="AT",
    laender={
        "AT-1": ("1", "Burgenland"), "AT-2": ("2", "Kärnten"),
        "AT-3": ("3", "Niederösterreich"), "AT-4": ("4", "Oberösterreich"),
        "AT-5": ("5", "Salzburg"), "AT-6": ("6", "Steiermark"),
        "AT-7": ("7", "Tirol"), "AT-8": ("8", "Vorarlberg"), "AT-9": ("9", "Wien"),
    },
    karte={"schluessel": "basemap_at", "name": "basemap.at (amtlich)",
           "lizenz": "basemap.at, CC BY 4.0"},
    hinweis=(
        "Österreich kennt keine Bodenrichtwerte (kein Gutachterausschuss-System), "
        "keine offene Kriminalstatistik je Bezirk, keine offene Passantenfrequenz "
        "und kein offenes Firmenbuch — diese Blöcke bleiben hier leer."
    ),
)

LAENDER: dict[str, Land] = {DE.code: DE, AT.code: AT}
"""Unterstützte Länder in Vorzugsreihenfolge (bei Überlappung zählt das erste)."""

GESAMT_BBOX = (
    min(land.bbox[0] for land in LAENDER.values()),
    min(land.bbox[1] for land in LAENDER.values()),
    max(land.bbox[2] for land in LAENDER.values()),
    max(land.bbox[3] for land in LAENDER.values()),
)
"""Süd, West, Nord, Ost über alle Länder — für Kartenausschnitte (Gitter, Scan)."""


def laender_fuer_punkt(lat: float, lon: float) -> list[Land]:
    """Alle Länder, in deren Kasten der Punkt liegt — leer, wenn keines."""
    return [land for land in LAENDER.values() if land.im_kasten(lat, lon)]


def unterstuetzt(lat: float, lon: float) -> bool:
    return bool(laender_fuer_punkt(lat, lon))


def land_eindeutig(lat: float, lon: float) -> Land | None:
    """Das Land, wenn genau ein Kasten passt — sonst ``None`` (dann muss der
    Geocoder entscheiden)."""
    treffer = laender_fuer_punkt(lat, lon)
    return treffer[0] if len(treffer) == 1 else None


def land_aus_code(code: str | None) -> Land | None:
    """Aus ``country_code`` des Geocoders (``de``, ``at`` …) oder einem
    ISO-Code — unbekannt → ``None``."""
    if not code:
        return None
    return LAENDER.get(str(code).strip().upper()[:2])


def land_aus_iso(iso: str | None) -> tuple[Land, str, str] | None:
    """``ISO 3166-2`` (``DE-BY``, ``AT-9``) → (Land, interner Schlüssel, Name)."""
    if not iso:
        return None
    iso = str(iso).strip().upper()
    for land in LAENDER.values():
        if iso in land.laender:
            schluessel, name = land.laender[iso]
            return land, schluessel, name
    return None


def iso_aus_schluessel(land: Land, schluessel: str | None) -> str | None:
    """Umkehrung: interner Schlüssel (``09``, ``9``) → ISO 3166-2."""
    if schluessel is None:
        return None
    for iso, (s, _name) in land.laender.items():
        if s == str(schluessel):
            return iso
    return None


# Quellen, die es nur in bestimmten Ländern gibt — mit dem Grund, den die
# Oberfläche zeigt. Alles, was hier nicht steht, gilt überall (OSM, ohsome,
# Leerstandsmelder, Overture, Inside Airbnb je Stadt, Besonnung).
QUELLEN_NUR: dict[str, tuple[set[str], str]] = {
    # klima und laerm fehlen hier bewusst: in Österreich antworten GeoSphere
    # (sources/klima_at.py) und lärminfo.at (sources/laerm_at.py).
    "luft": ({"DE"}, "Das Luftmessnetz kommt vom Umweltbundesamt (Deutschland); der "
                     "europäische Spiegel für Österreich hinkt Monate hinterher (geprüft 18.09.2026)."),
    # planung und baurecht fehlen hier bewusst: in Österreich antworten der
    # LFRZ-Hochwasserdienst (sources/planung_at.py) und die Wiener
    # Flächenwidmung (sources/wien.py); außerhalb Wiens sagt der
    # Baurecht-Block ehrlich „kein offener Dienst".
    "verkehrsmenge": ({"DE"}, "BAYSIS und BASt zählen nur deutsche Straßen."),
    "frequenz": ({"DE"}, "Gemessene Passantenfrequenz gibt es offen nur in drei deutschen Städten."),
    "register": ({"DE"}, "Das Registerumfeld kommt aus dem deutschen Handelsregister (OffeneRegister)."),
    "einkommen": ({"DE"}, "Kreiswerte kommen aus dem deutschen Regionalatlas."),
    "kreisprofil": ({"DE"}, "Kreiswerte kommen aus dem deutschen Regionalatlas."),
    "pendler": ({"DE"}, "Die Pendlerrechnung liegt nur für deutsche Gemeinden vor."),
    "genesis": ({"DE"}, "Die Regionaldatenbank ist eine deutsche Quelle."),
    "pks": ({"DE"}, "Die Kriminalstatistik je Kreis veröffentlicht nur das BKA."),
    "wahl": ({"DE"}, "Das Wahlergebnis kommt von der Bundeswahlleiterin."),
    # zensus fehlt hier bewusst: in Österreich antwortet das lokal importierte
    # Eurostat-Raster (sources/raster_at.py) unter demselben Blocknamen.
    "gitter": ({"DE"}, "Das Übersichtsgitter kommt aus dem Zensus-2022-Gitterdienst."),
    "scan": ({"DE"}, "Der Flächen-Scan rechnet auf dem Zensus-2022-Gitter."),
    "bodenrichtwert": ({"DE"}, "Bodenrichtwerte kennen nur die deutschen Gutachterausschüsse."),
}


def quelle_fehlt(name: str, land: Land) -> str | None:
    """Warnung, wenn ``name`` in ``land`` nicht angeboten wird — sonst ``None``."""
    eintrag = QUELLEN_NUR.get(name)
    if eintrag is None or land.code in eintrag[0]:
        return None
    laender, grund = eintrag
    wo = ", ".join(LAENDER[c].name for c in sorted(laender) if c in LAENDER)
    return f"Nur für {wo} verfügbar — {grund} Für {land.name} bleibt der Block leer."
