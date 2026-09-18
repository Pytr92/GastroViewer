"""Pydantic-Modelle der Schnittstelle.

Müssen auf Modulebene stehen: mit ``from __future__ import annotations``
sind Annotationen Strings, die FastAPI nur im Modul-Namensraum auflösen
kann. In einer Funktion definiert, hielte FastAPI ein Modell für einen
Query-Parameter."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SchaetzEingaben(BaseModel):
    """Alle Annahmen der Umsatzschätzung — jede einzelne kommt aus der Oberfläche.
    Es gibt keinen Wert, den der Server hinter dem Rücken des Nutzers setzt."""

    # Vorbelegt mit 0, damit ein Punkt ohne Zensuszelle bzw. ohne OSM-Objekte
    # rechenbar bleibt statt mit einem Pflichtfeldfehler abzubrechen.
    einwohner: float = Field(0, ge=0)
    wettbewerber: int = Field(0, ge=0)
    besuche_je_einwohner: float = Field(..., gt=0)
    bon_min: float = Field(..., gt=0)
    bon_max: float = Field(..., gt=0)
    marktanteil_min_prozent: float | None = Field(None, ge=0, le=100)
    marktanteil_max_prozent: float | None = Field(None, ge=0, le=100)
    unsicherheitsfaktor: float = Field(2.0, ge=1)
    oeffnungstage: int = Field(360, gt=0, le=366)
    oeffnungsstunden: float = Field(12.0, gt=0, le=24)
    mietanteil_min_prozent: float = Field(10.0, ge=0, le=100)
    mietanteil_max_prozent: float = Field(14.0, ge=0, le=100)
    # Prüfstein gegen die Wirklichkeit. Geht in keine Rechnung ein und wird
    # nicht gespeichert — er wird nur gegenübergestellt.
    kalibrierung_umsatz_eur: float | None = Field(None, ge=0)
    kalibrierung_bezeichnung: str | None = Field(None, max_length=120)
    # Franchise-Kostenprobe: Sätze aus dem Franchisevertrag bzw. der eigenen
    # Kalkulation. Ohne Eingabe findet die Probe nicht statt — es gibt bewusst
    # keine "typischen" Vorgabesätze.
    franchisegebuehr_prozent: float | None = Field(None, ge=0, le=100)
    werbeabgabe_prozent: float | None = Field(None, ge=0, le=100)
    wareneinsatz_prozent: float | None = Field(None, ge=0, le=100)
    personalkosten_prozent: float | None = Field(None, ge=0, le=100)
    # Mietprobe gegen ein konkretes Exposé — Werte aus dem Angebot des
    # Vermieters, keine Vorgaben.
    flaeche_qm: float | None = Field(None, gt=0, le=100_000)
    angebotsmiete_qm: float | None = Field(None, ge=0, le=10_000)
    # Lage-Anker aus dem Zensus-Gitter (Wohnungsmiete, vorbefüllt und sichtbar).
    # Geht in keine Umsatzrechnung ein — nur in die Einordnung der Mietprobe.
    zensus_wohnmiete_qm: float | None = Field(None, gt=0, le=100)


class GenesisZugang(BaseModel):
    """Kennung für die Regionaldatenbank (Opt-in). Wird nur lokal abgelegt
    und vor dem Speichern live beim Dienst geprüft."""

    kennung: str = Field(..., min_length=1, max_length=120)
    passwort: str = Field(..., min_length=1, max_length=200)


class Kriterium(BaseModel):
    """Ein Kriterium des eigenen Standortprofils."""

    key: str = Field(..., max_length=60)
    richtung: str = Field(..., pattern="^(min|max)$")
    wert: float
    #: K.-o.-Kriterium: nicht erfüllt heißt, der Standort fällt durch.
    ko: bool = False


class Profil(BaseModel):
    kriterien: list[Kriterium] = Field(default_factory=list, max_length=40)


class PunktNotiz(BaseModel):
    """Eigene Einschätzung zu einem gemerkten Punkt.

    Das Werkzeug bewertet bewusst nicht und stellt keine Rangfolge auf — der
    Nutzer darf und soll das aber. Beide Felder sind als eigene Einschätzung
    gekennzeichnet und gehen in keine Rechnung ein.
    """

    notiz: str | None = Field(None, max_length=2000)
    bewertung: int | None = Field(None, ge=1, le=5)
    #: Arbeitsstand der Standortsuche (siehe cache.STAENDE) und, bei einer
    #: Ablehnung, der Grund. Beides ist Arbeitsstand, keine Bewertung des
    #: Standorts durch das Werkzeug.
    stand: str | None = Field(None, max_length=40)
    stand_grund: str | None = Field(None, max_length=500)


class SavePoint(BaseModel):
    """Muss auf Modulebene stehen: mit ``from __future__ import annotations`` sind
    Annotationen Strings, die FastAPI nur im Modul-Namensraum auflösen kann. In einer
    Funktion definiert, hielte FastAPI das Modell für einen Query-Parameter."""

    label: str = Field(..., min_length=1, max_length=120)
    lat: float
    lon: float
    radius: int = 600


class VerlaufEintrag(BaseModel):
    ts: float
    payload: dict | None = None


class PunktSicherung(BaseModel):
    """Ein Punkt in einer Sicherung (siehe Cache.export_points). Felder, die
    das Werkzeug nicht kennt, werden ignoriert — eine spätere Fassung darf
    mehr schreiben."""

    label: str = Field(..., min_length=1, max_length=120)
    lat: float
    lon: float
    radius: int
    created_at: float
    payload: dict | None = None
    notiz: str | None = None
    bewertung: int | None = Field(None, ge=1, le=5)
    geprueft_am: float | None = None
    stand: str | None = Field(None, max_length=40)
    stand_grund: str | None = Field(None, max_length=500)
    verlauf: list[VerlaufEintrag] = []


class PunkteSicherung(BaseModel):
    """Die Sicherung als Ganzes. ``format`` und ``version`` bleiben frei,
    damit cache.import_points weiter „keine Punkte-Sicherung dieses
    Werkzeugs" sagen kann statt Pydantic „Feld version: fehlt"."""

    format: str | None = None
    version: int | None = None
    punkte: list[PunktSicherung] = []
