"""Konfiguration. Alles über Umgebungsvariablen überschreibbar.

Plattformunabhängig: Pfade über pathlib, Datenverzeichnis im Home des Nutzers
(macOS ~/Library-frei, damit auf allen Systemen gleich).
"""

from __future__ import annotations

import os
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


@dataclass
class Settings:
    # --- Server ---
    host: str = field(default_factory=lambda: _env("GASTROVIEWER_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("GASTROVIEWER_PORT", 8000))

    # --- Ablage ---
    data_dir: Path = field(default_factory=default_data_dir)

    # --- Identifikation gegenüber den Diensten ---
    # Nominatim antwortet ohne User-Agent mit HTTP 403 (in Phase 0 geprüft).
    # Kontaktadresse laut Nutzungsbedingungen Pflicht -> per Env setzbar.
    contact: str = field(
        default_factory=lambda: _env(
            "GASTROVIEWER_CONTACT", "https://github.com/Pytr92/GastroViewer"
        )
    )
    version: str = "0.1.0"

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
    # Overpass ist ein Spendenprojekt: höchstens eine Abfrage gleichzeitig,
    # Mindestabstand zwischen zwei Abfragen.
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
    def user_agent(self) -> str:
        return f"gastroviewer/{self.version} ({self.contact})"

    def ttl_for(self, source: str) -> int:
        if (source.startswith("gehweg") or source.startswith("planung")
                or source.startswith("liefergebiet")):
            return self.ttl_gehweg
        if source.startswith("overpass"):
            return self.ttl_osm
        if source.startswith("nominatim"):
            return self.ttl_nominatim
        if source.startswith("zensus"):
            return self.ttl_zensus
        # Regionalatlas-Kreiswerte (Einkommen, Kreisprofil) ändern sich
        # einmal im Jahr.
        if source.startswith("einkommen") or source.startswith("kreisprofil"):
            return self.ttl_zensus
        # DWD-Klimanormalwerte 1991–2020 sind bis zur nächsten Normalperiode
        # fest — längste TTL im Werkzeug.
        if source.startswith("klima"):
            return self.ttl_zensus
        # Pendlerrechnung: ein Berichtsjahr, einmal jährlich fortgeschrieben.
        if source.startswith("pendler"):
            return self.ttl_zensus
        # OSM-Jahresreihe: der jüngste Datenpunkt ist der 1. Januar — vor dem
        # Jahreswechsel ändert sich an der Reihe nichts Wesentliches.
        if source.startswith("dynamik"):
            return self.ttl_zensus
        # Tageswerte-Jahresdatei der Radzählstellen: ein abgeschlossenes Jahr,
        # fortgeschrieben erst mit dem nächsten Jahrgang.
        if source.startswith("muenchen_rad_jahr"):
            return self.ttl_zensus
        # Lärmkartierung: EU-Rhythmus alle fünf Jahre.
        if source.startswith("laerm"):
            return self.ttl_zensus
        return self.ttl_osm

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


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
