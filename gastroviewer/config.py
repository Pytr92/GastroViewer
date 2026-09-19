"""Konfiguration. Alles über Umgebungsvariablen überschreibbar.

Plattformunabhängig: Pfade über pathlib, Datenverzeichnis im Home des Nutzers
(macOS ~/Library-frei, damit auf allen Systemen gleich).
"""

from __future__ import annotations

from . import __version__

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def default_data_dir() -> Path:
    override = os.environ.get("GASTROVIEWER_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".gastroviewer"


# ------------------------------------------------------------- Cache-Dauern
#
# Je Quelle (Name aus service._cached) die TTL-Klasse: ein Attributname der
# Settings oder eine feste Sekundenzahl — mit Begründung. Wer eine Quelle
# ergänzt, trägt sie hier ein; tests/test_ttl.py prüft das per AST gegen
# service.py und friert die Dauern ein, damit sie nicht unbemerkt wandern.
TTL_KLASSEN: dict[str, str | int] = {
    # --- Netz- und Wegeberechnungen: teuer, ändern sich in Wochen
    "gehweg": "ttl_gehweg",         # Fußwegenetz, 1–3 MB je Punkt
    "planung": "ttl_gehweg",        # Hochwasser, B-Plan, Erhaltungssatzung
    "liefergebiet": "ttl_gehweg",   # Rad-Liefergebiet auf dem Wegenetz
    "fahrzeit": "ttl_gehweg",       # Auto-Einzugsgebiet, größte Abfrage
    # --- OSM und Kurzlebiges: ein Tag
    "overpass": "ttl_osm",          # kombinierte Overpass-Abfrage je Punkt
    "marke_basis": "ttl_osm",       # Gebietsschutz-Check (Overpass, 20 km)
    "scan": "ttl_osm",              # Flächen-Scan je Kartenausschnitt
    "vorschlaege": "ttl_osm",       # Adressvorschläge (Photon)
    "oepnv_einzug": "ttl_osm",      # Runden-Router, lokal gerechnet
    "muenchen_baustellen": "ttl_osm",  # rollierende Vier-Wochen-Vorschau
    "hamburg_baustellen": "ttl_osm",   # dito Hamburg
    "berlin_baustellen": "ttl_osm",    # dito Berlin
    "stuttgart_baustellen": "ttl_osm", # dito Stuttgart
    "mobidata_roadworks": "ttl_osm",   # Landesdatei BW, laufend
    "mobidata_baustellen": "ttl_osm",
    "mobidata_eco": "ttl_osm",         # Radzähler-Tageswerte der laufenden Woche
    "mobidata_rad": "ttl_osm",
    "mobidata_lage": "ttl_osm",        # Ladesäulen mit Belegung
    "hamburg_lage": "ttl_osm",         # Parkhäuser mit Belegung
    "leerstandsmelder": "ttl_osm",     # Weltbestand, laufend gemeldet, 3 MB
    "leerstandsmelder_punkt": "ttl_osm",
    "muenchen_rad": "ttl_osm",      # Raddauerzählstellen mit laufendem Monat
    "hamburg_rad": "ttl_osm",       # dito Hamburg
    "muenchen_messe": "ttl_osm",    # Messe-Kalender: kommende Termine
    "muenchen_tourismus": "ttl_osm",  # Monatszahlen, monatlich fortgeschrieben
    "hamburg_maerkte": "ttl_osm",   # Hamburger Marktliste wechselt saisonal —
                                    # bewusst kürzer als die Münchner (30 d)
    "baysis": "ttl_osm",            # BAYSIS-Verkehrsmengen (Dienstantwort)
    # --- Amtliche Bestände: einmal im Jahr fortgeschrieben
    "zensus": "ttl_zensus",         # Zensus 2022, Stichtag fest
    "zensus_gitter": "ttl_zensus",  # Übersichtsgitter 1 km / 10 km
    "nominatim_reverse": "ttl_nominatim",
    "nominatim_search": "ttl_nominatim",
    "einkommen": "ttl_zensus",      # Regionalatlas-Kreiswerte
    "kreisprofil": "ttl_zensus",    # dito
    "klima": "ttl_zensus",          # DWD-Normalperiode 1991–2020
    "pendler": "ttl_zensus",        # Pendlerrechnung, ein Berichtsjahr
    "dynamik": "ttl_zensus",        # OSM-Jahresreihe, Datenpunkt 1. Januar
    "muenchen_rad_jahr": "ttl_zensus",  # abgeschlossenes Jahr
    "laerm": "ttl_zensus",          # EU-Lärmkartierung, alle fünf Jahre
    "muenchen_indikatoren": "ttl_zensus",  # Stadtbezirks-Jahresreihen
    "muenchen_maerkte": "ttl_zensus",      # städtische Marktliste, selten geändert
    "airbnb": "ttl_zensus",         # Inside Airbnb, quartalsweise
    "genesis": "ttl_zensus",        # Regionaldatenbank, jährlich
    "bast": "ttl_zensus",           # BASt-Jahresdatei, bundesweit
    "bast_punkt": "ttl_zensus",
    "berlin_verkehrsmenge": "ttl_zensus",  # Verkehrsmodell 2023
    "hamburg_verkehrsmenge": "ttl_zensus", # Zählungen mit Jahr
    "mobidata_svz": "ttl_zensus",     # SVZ 2024, Landesdatei
    "svz_bw_punkt": "ttl_zensus",
    "hamburg_stadtteil": "ttl_zensus", # Regionalstatistik, jährlich
    "pks": "ttl_zensus",            # BKA-Kreistabelle, Berichtsjahr
    "pks_kreis": "ttl_zensus",
    "luft_stationen": "ttl_zensus",  # Stationsliste, selten geändert
    "wahl": "ttl_zensus",           # endgültiges Wahlergebnis
    "wahl_gemeinde": "ttl_zensus",
    "register": "ttl_zensus",       # eingefrorener lokaler Bestand
    "kalender": "ttl_zensus",       # Feiertage und Ferien eines Jahres
    "ihk_berlin": "ttl_zensus",     # IHK-Bestand, monatlich, 125 MB
    "ihk_punkt": "ttl_zensus",
    "baurecht": "ttl_zensus",       # Bebauungspläne, Jahre in Aufstellung
    "frequenz": "ttl_zensus",       # Passantenfrequenz, Stundenmittel
    "frequenz_augsburg": "ttl_zensus",
    "sonne": "ttl_zensus",          # Besonnung hängt am Gebäudebestand
    "klima_at": "ttl_zensus",       # GeoSphere-Normalwerte 1991–2020, fest
    "klima_at_stationen": "ttl_zensus",  # Stationsliste, ändert sich in Monaten
    "laerm_at": "ttl_zensus",       # EU-Lärmkartierung, alle fünf Jahre
    "planung_at": "ttl_gehweg",     # LFRZ-Hochwasser und Wiener Schutzzonen
    "baurecht_at": "ttl_zensus",    # Wiener Flächenwidmung, Jahre in Kraft
    "wien_maerkte": "ttl_zensus",   # Wiener Marktliste, selten geändert
    "wien_baustellen": "ttl_osm",   # angemeldete Baustellen, laufend gepflegt
    "salzburg_maerkte": "ttl_zensus",   # Salzburger Marktliste, selten geändert
    "salzburg_baustellen": "ttl_osm",   # Baustellen und Grabungen, laufend gepflegt
    "salzburg_lage": "ttl_osm",         # Kurzparkzonen
    "tourismus_at": "ttl_gehweg",   # Nächtigungsreihe je Bundesland, monatlich
    "tourismus_at_daten": "ttl_gehweg",  # die eingedampfte Gesamtdatei
    "wahl_at": "ttl_zensus",        # NRW 2024, endgültig
    "wahl_at_daten": "ttl_zensus",  # Ergebnisdatei und GKZ-Liste
    "kreisprofil_at": "ttl_zensus", # Gemeindeprofil, jährliche Tabelle
    "gemeinde_at_daten": "ttl_zensus",  # die eingedampfte Gemeindetabelle
    "gemeinde_at_gkz": "ttl_zensus",    # Gemeindekennziffer am Punkt (GEODATA-WFS)
    "immobilien_at_daten": "ttl_zensus", # drei ODS-Dateien, jährlich
    "immobilien_at": "ttl_zensus",      # Bezirkswerte daraus
    "wien_zaehlbezirk": "ttl_zensus",   # Zählbezirks-Steckbrief, jährlich
    "wien_zb_daten": "ttl_zensus",      # die eingedampfte Zählbezirks-CSV
    "wien_lage": "ttl_osm",             # Zonen und Nutzung, laufend gepflegt
    "wien_kfz_daten": "ttl_zensus",     # Monats-CSV der Dauerzählstellen, monatlich fortgeschrieben
    "wien_verkehrsmenge": "ttl_zensus", # Jahresmittel je Zählstelle
    # --- Stundenwerte
    "luft_punkt": 3600,             # Luftqualitätsindex, stündlich veröffentlicht
    "wien_luft": 3600,              # Lumes-Halbstundenwerte
}
_TTL_GEWARNT: set[str] = set()


@dataclass
class Settings:
    # --- Server ---
    host: str = field(default_factory=lambda: _env("GASTROVIEWER_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("GASTROVIEWER_PORT", 8000))

    # --- Ablage ---
    data_dir: Path = field(default_factory=default_data_dir)

    # --- Herkunftsprüfung ---
    # Der Server läuft ohne Anmeldung auf dem eigenen Rechner. Zwei Angriffe
    # brauchen trotzdem keine Anmeldung: DNS-Rebinding (eine fremde Webseite
    # lässt ihren Namen auf 127.0.0.1 zeigen und liest die API aus) und CSRF
    # (eine fremde Seite schickt POST /api/points oder POST
    # /api/genesis/zugang aus dem Browser des Nutzers). Beides erkennt man am
    # Host- bzw. Origin-Header. Erlaubt sind IP-Adressen und localhost — und
    # was hier ausdrücklich eingetragen ist (etwa ein Hostname im LAN).
    erlaubte_hosts: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            h.strip().lower()
            for h in _env("GASTROVIEWER_ERLAUBTE_HOSTS", "").split(",")
            if h.strip()
        )
    )

    # --- Identifikation gegenüber den Diensten ---
    # Nominatim antwortet ohne User-Agent mit HTTP 403 (in Phase 0 geprüft).
    # Kontaktadresse laut Nutzungsbedingungen Pflicht -> per Env setzbar.
    contact: str = field(
        default_factory=lambda: _env(
            "GASTROVIEWER_CONTACT", "https://github.com/Pytr92/GastroViewer"
        )
    )
    #: Aus gastroviewer/__init__.py — die eine Quelle der Versionsnummer.
    version: str = __version__

    # --- Overpass ---
    overpass_endpoints: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            e.strip()
            for e in _env(
                "GASTROVIEWER_OVERPASS_ENDPOINTS",
                "https://overpass-api.de/api/interpreter,"
                "https://overpass.kumi.systems/api/interpreter,"
                "https://overpass.private.coffee/api/interpreter",
            ).split(",")
            if e.strip()
        )
    )
    overpass_timeout: float = field(
        default_factory=lambda: _env_float("GASTROVIEWER_OVERPASS_TIMEOUT", 90.0)
    )
    # Overpass ist ein Spendenprojekt: höchstens eine Abfrage gleichzeitig
    # (Semaphore im Rate-Limiter, umschließt die ganze Anfrage) und dieser
    # Mindestabstand zwischen zwei Starts.
    overpass_min_interval: float = field(
        default_factory=lambda: _env_float("GASTROVIEWER_OVERPASS_MIN_INTERVAL", 1.0)
    )

    # --- Nominatim ---
    nominatim_base: str = field(
        default_factory=lambda: _env(
            "GASTROVIEWER_NOMINATIM_BASE", "https://nominatim.openstreetmap.org"
        )
    )
    # Nutzungsbedingung: maximal 1 Anfrage pro Sekunde. Keine Empfehlung.
    nominatim_min_interval: float = field(
        default_factory=lambda: _env_float("GASTROVIEWER_NOMINATIM_MIN_INTERVAL", 1.0)
    )
    nominatim_timeout: float = field(
        default_factory=lambda: _env_float("GASTROVIEWER_NOMINATIM_TIMEOUT", 30.0)
    )

    # --- Zensus 2022 (ArcGIS FeatureServer) ---
    zensus_base: str = field(
        default_factory=lambda: _env(
            "GASTROVIEWER_ZENSUS_BASE",
            "https://services2.arcgis.com/jUpNdisbWqRpMo35/arcgis/rest/services"
            "/Zensus2022_grid_final/FeatureServer",
        )
    )
    zensus_layer: int = field(default_factory=lambda: _env_int("GASTROVIEWER_ZENSUS_LAYER", 0))
    zensus_page_size: int = field(
        default_factory=lambda: _env_int("GASTROVIEWER_ZENSUS_PAGE_SIZE", 2000)
    )
    zensus_timeout: float = field(
        default_factory=lambda: _env_float("GASTROVIEWER_ZENSUS_TIMEOUT", 60.0)
    )
    # Schutz gegen Endlosschleifen bei der Paginierung.
    zensus_max_pages: int = field(
        default_factory=lambda: _env_int("GASTROVIEWER_ZENSUS_MAX_PAGES", 10)
    )

    # --- Cache-TTL in Sekunden (Spec §2) ---
    ttl_osm: int = field(default_factory=lambda: _env_int("GASTROVIEWER_TTL_OSM", 24 * 3600))
    ttl_zensus: int = field(
        default_factory=lambda: _env_int("GASTROVIEWER_TTL_ZENSUS", 30 * 24 * 3600)
    )
    ttl_nominatim: int = field(
        default_factory=lambda: _env_int("GASTROVIEWER_TTL_NOMINATIM", 30 * 24 * 3600)
    )
    # Das Fußwegenetz ist mit 1–3 MB je Punkt die größte Overpass-Antwort des
    # Werkzeugs und ändert sich in Wochen, nicht in Stunden. Entsprechend lange
    # bleibt es liegen — das ist Rücksicht auf einen Spendendienst.
    ttl_gehweg: int = field(
        default_factory=lambda: _env_int("GASTROVIEWER_TTL_GEHWEG", 14 * 24 * 3600)
    )

    # --- Regionalatlas (verfügbares Einkommen, Kreisebene) ---
    # ArcGIS-Server der IT.NRW hinter dem Regionalatlas der Statistischen
    # Ämter; am 02.08.2026 verifiziert (Tabelle regionalatlas.ai016_1).
    regionalatlas_base: str = field(
        default_factory=lambda: _env(
            "GASTROVIEWER_REGIONALATLAS_BASE",
            "https://www.gis-idmz.nrw.de/arcgis/rest/services/stba/regionalatlas"
            "/MapServer",
        )
    )

    # --- DWD Open Data (Klimanormalwerte 1991–2020) ---
    # Offene Textdateien, am 03.08.2026 verifiziert (Werte + Stationsliste
    # je Parameter, Latin-1, Semikolon-getrennt).
    dwd_base: str = field(
        default_factory=lambda: _env(
            "GASTROVIEWER_DWD_BASE",
            "https://opendata.dwd.de/climate_environment/CDC"
            "/observations_germany/climate/multi_annual/mean_91-20",
        )
    )

    # --- ohsome (OSM-Historie, Gastro-Dynamik) ---
    # Offene API des HeiGIT Heidelberg, ohne Konto; am 04.08.2026 verifiziert
    # (POST /elements/count mit bcircles, filter, time).
    ohsome_base: str = field(
        default_factory=lambda: _env(
            "GASTROVIEWER_OHSOME_BASE", "https://api.ohsome.org/v1"
        )
    )

    # --- GTFS (Phase 3) ---
    gtfs_url: str = field(
        default_factory=lambda: _env(
            "GASTROVIEWER_GTFS_URL", "https://download.gtfs.de/germany/free/latest.zip"
        )
    )

    @property
    def db_path(self) -> Path:
        return self.data_dir / "gastroviewer.sqlite"

    @property
    def gtfs_db_path(self) -> Path:
        return self.data_dir / "gtfs.sqlite"

    @property
    def overture_db_path(self) -> Path:
        return self.data_dir / "overture.sqlite"

    @property
    def register_db_path(self) -> Path:
        return self.data_dir / "register.sqlite"

    @property
    def raster_at_db_path(self) -> Path:
        """Eurostat-Bevölkerungsraster (1 km) für Österreich, lokal importiert."""
        return self.data_dir / "raster_at.sqlite"

    @property
    def user_agent(self) -> str:
        return f"gastroviewer/{self.version} ({self.contact})"

    def ttl_for(self, source: str) -> int:
        """Cache-Dauer je Quelle — Nachschlag in TTL_KLASSEN, exakter Name.

        Vorher eine Kette aus 30 ``startswith``-Zweigen: reihenfolgeabhängig,
        mit toten Regeln, und 16 Quellen fielen still auf den Default. Jetzt
        steht jede Quelle mit Klasse und Begründung in der Tabelle; ein
        unbekannter Name bekommt die kurze OSM-Dauer (irrt Richtung
        „frischer", nie Richtung „veraltet") und eine einmalige Warnung."""
        klasse = TTL_KLASSEN.get(source)
        if klasse is None:
            if source not in _TTL_GEWARNT:
                _TTL_GEWARNT.add(source)
                logging.getLogger(__name__).warning(
                    "Quelle %r hat keinen Eintrag in TTL_KLASSEN — kurze TTL "
                    "(ttl_osm) als Rückfall.", source)
            return self.ttl_osm
        return getattr(self, klasse) if isinstance(klasse, str) else int(klasse)

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # Eine hinterlegte Kontaktadresse gilt, sobald das Datenverzeichnis
        # bekannt ist — aber nur, wenn keine Umgebungsvariable gesetzt ist.
        # Was jemand ausdrücklich in die Umgebung schreibt, schlägt eine
        # Datei, die er vor Monaten einmal ausgefüllt hat.
        if not _env("GASTROVIEWER_CONTACT", ""):
            hinterlegt = lade_kontakt(self.data_dir)
            if hinterlegt:
                self.contact = hinterlegt


#: Wo die Kontaktadresse liegt. Bewusst eine eigene, gut auffindbare Datei
#: und kein Eintrag in der Cache-Datenbank: Wer sie ändern oder löschen
#: will, soll das ohne Werkzeug tun können.
KONTAKT_DATEI = "kontakt.txt"

#: Absichtlich großzügig. Die Adresse geht an fremde Dienste; sie muss
#: erkennbar eine Kontaktmöglichkeit sein, aber das Werkzeug ist nicht der
#: Ort, an dem entschieden wird, welche Adressen es gibt.
_KONTAKT_MUSTER = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def kontakt_gueltig(adresse: str) -> bool:
    """Sieht das nach einer erreichbaren Adresse aus?

    Geprüft wird die Form, nicht die Existenz — zustellen kann das Werkzeug
    nichts. Eine falsche Adresse hier ist schlimmer als keine: Nominatim
    verlangt sie ausdrücklich, um bei Problemen jemanden erreichen zu
    können, und eine erfundene Adresse macht dieses Versprechen wertlos.
    """
    adresse = (adresse or "").strip()
    return bool(_KONTAKT_MUSTER.match(adresse)) and len(adresse) <= 200


def lade_kontakt(data_dir: Path) -> str | None:
    pfad = Path(data_dir) / KONTAKT_DATEI
    try:
        adresse = pfad.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return adresse or None


def speichere_kontakt(data_dir: Path, adresse: str) -> None:
    pfad = Path(data_dir) / KONTAKT_DATEI
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(adresse.strip() + "\n", encoding="utf-8")


def loesche_kontakt(data_dir: Path) -> bool:
    pfad = Path(data_dir) / KONTAKT_DATEI
    if pfad.exists():
        pfad.unlink()
        return True
    return False


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def set_settings(settings: Settings) -> None:
    """Nur für Tests."""
    global _settings
    _settings = settings
