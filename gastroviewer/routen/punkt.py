"""Alles zu einem Punkt: ``/api/point`` und die Quellen einzeln."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from ..service import GRENZEN
from ..sources import boris, links
from ._gemeinsam import svc, validiere_punkt as _validate

router = APIRouter()


@router.get("/api/point")
async def point(
    request: Request,
    lat: float = Query(...),
    lon: float = Query(...),
    r: int = Query(600),
    refresh: bool = Query(False),
):
    _validate(lat, lon, r)
    return await svc(request).point(lat, lon, r, refresh)


@router.get("/api/point/adresse")
async def point_adresse(
    request: Request, lat: float, lon: float, refresh: bool = False
):
    _validate(lat, lon, 600)
    return (await svc(request).adresse(lat, lon, refresh)).to_dict()


@router.get("/api/point/zensus")
async def point_zensus(
    request: Request, lat: float, lon: float, r: int = 600, refresh: bool = False
):
    _validate(lat, lon, r)
    return (await svc(request).zensus(lat, lon, r, refresh)).to_dict()


@router.get("/api/point/osm")
async def point_osm(
    request: Request, lat: float, lon: float, r: int = 600, refresh: bool = False
):
    _validate(lat, lon, r)
    return (await svc(request).osm(lat, lon, r, refresh)).to_dict()


@router.get("/api/point/gtfs")
async def point_gtfs(request: Request, lat: float, lon: float, r: int = 600):
    _validate(lat, lon, r)
    return (await svc(request).gtfs(lat, lon, r)).to_dict()


@router.get("/api/point/radzaehlung")
async def point_radzaehlung(request: Request, lat: float, lon: float, r: int = 600):
    """Gemessene Radverkehrszahlen der Landeshauptstadt München."""
    _validate(lat, lon, r)
    return (await svc(request).radzaehlung(lat, lon, r)).to_dict()


@router.get("/api/point/verkehrsmenge")
async def point_verkehrsmenge(request: Request, lat: float, lon: float, r: int = 600):
    """Durchschnittliche tägliche Verkehrsstärke aus der bayerischen
    Straßenverkehrszählung."""
    _validate(lat, lon, r)
    return (await svc(request).verkehrsmenge(lat, lon, r)).to_dict()


@router.get("/api/point/gehweg")
async def point_gehweg(
    request: Request, lat: float, lon: float, r: int = 600, refresh: bool = False
):
    """Gehstrecken statt Luftlinie.

    Bewusst nicht Teil von ``/api/point``: das Fußwegenetz ist die größte
    Overpass-Antwort des Werkzeugs und wird nur auf Anforderung geladen.
    """
    _validate(lat, lon, r)
    return (await svc(request).gehweg(lat, lon, r, refresh)).to_dict()


@router.get("/api/point/marke")
async def point_marke(
    request: Request,
    lat: float,
    lon: float,
    marke: str = Query(..., min_length=2, max_length=60),
    r: int = Query(10000),
):
    """Gebietsschutz-Check: Betriebe der eigenen Marke im großen Umkreis.

    Für Franchisenehmer eine Vertragsfrage — Kannibalisierung und
    Gebietsschutz hängen an der Entfernung zum nächsten eigenen Betrieb.
    Deshalb ein eigener, größerer Radius als bei der Punktanalyse."""
    from ..sources.marke import MAX_RADIUS_M, MIN_RADIUS_M

    _validate(lat, lon, 600)
    if not (MIN_RADIUS_M <= r <= MAX_RADIUS_M):
        raise HTTPException(
            422, f"Radius muss zwischen {MIN_RADIUS_M} und {MAX_RADIUS_M} m liegen."
        )
    if '"' in marke or "\\" in marke:
        raise HTTPException(
            422, "Anführungszeichen und Backslash sind im Markennamen nicht erlaubt."
        )
    return (await svc(request).marke(lat, lon, r, marke)).to_dict()


@router.get("/api/point/planung")
async def point_planung(
    request: Request, lat: float, lon: float, r: int = 600,
    bundesland_code: str | None = None,
):
    """Hochwassergefahr und Bebauungsplan am Punkt. Der Bundesland-Code
    aus dem Zensus wählt den Dienst (Bayern: LfU, sonst BfG/LAWA)."""
    _validate(lat, lon, r)
    return (await svc(request).planung(
        lat, lon, r, bundesland_code=bundesland_code)).to_dict()


@router.get("/api/point/klima")
async def point_klima(request: Request, lat: float, lon: float):
    """Klimanormalwerte 1991–2020 der jeweils nächsten DWD-Station —
    für Außengastronomie (Sommertage, Sonne, Niederschlag)."""
    _validate(lat, lon, 600)
    return (await svc(request).klima(lat, lon)).to_dict()


@router.get("/api/point/overture")
async def point_overture(request: Request, lat: float, lon: float, r: int = 600):
    """Zweite Wettbewerbsquelle: Overture Places (lokaler Import) mit
    Abgleich gegen die OSM-Gastronomie — Untergrenze trifft Kontrolle."""
    _validate(lat, lon, r)
    return (await svc(request).overture(lat, lon, r)).to_dict()


@router.get("/api/point/laerm")
async def point_laerm(
    request: Request, lat: float, lon: float,
    bundesland_code: str | None = None,
):
    """Straßenlärm am Punkt (Umgebungslärmkartierung, LfU Bayern):
    LDEN und LNight in dB(A) mit Kartierungsjahr."""
    _validate(lat, lon, 600)
    return (await svc(request).laerm(lat, lon, bundesland_code)).to_dict()


@router.get("/api/point/leerstandsmelder")
async def point_leerstandsmelder(
    request: Request, lat: float, lon: float, r: int = 600,
    refresh: bool = False,
):
    """Bürgerschaftlich gemeldete Leerstände (Leerstandsmelder.de) im
    Umfeld — zweite Untergrenze neben dem OSM-Leerstand, mit
    Lizenz-Warnung."""
    _validate(lat, lon, r)
    return (await svc(request).leerstandsmelder(lat, lon, r, refresh)).to_dict()


@router.get("/api/point/dynamik")
async def point_dynamik(request: Request, lat: float, lon: float, r: int = 600):
    """Gastro-Dynamik aus der OSM-Historie (ohsome): Jahresreihe der
    Gastro-Objekte im Umkreis — wächst die Lage oder stirbt sie?"""
    _validate(lat, lon, r)
    return (await svc(request).dynamik(lat, lon, r)).to_dict()


@router.get("/api/point/baustellen")
async def point_baustellen(
    request: Request, lat: float, lon: float, r: int = 600,
    refresh: bool = False,
):
    """Baustellen-Vorschau der Stadt München im Umkreis — mit Umriss,
    Zeitraum und Gehweg-/Sperrungs-Erkennung. Außerhalb Münchens leer,
    mit Begründung."""
    _validate(lat, lon, r)
    return (await svc(request).baustellen(lat, lon, r, refresh)).to_dict()


@router.get("/api/point/maerkte")
async def point_maerkte(
    request: Request, lat: float, lon: float, r: int = 600,
    refresh: bool = False,
):
    """Städtische Märkte München (Wochen-/Bauernmärkte …) in Reichweite."""
    _validate(lat, lon, r)
    return (await svc(request).maerkte(lat, lon, r, refresh)).to_dict()


@router.get("/api/point/messe")
async def point_messe(
    request: Request, lat: float, lon: float, refresh: bool = False,
):
    """Messe-Kalender München: laufende und kommende Veranstaltungen mit
    Besucher-Jahresbilanz. Jenseits von 20 km um die Gelände leer, mit
    Begründung."""
    _validate(lat, lon, 600)
    return (await svc(request).messe(lat, lon, refresh)).to_dict()


@router.get("/api/point/tourismus")
async def point_tourismus(
    request: Request, lat: float, lon: float, refresh: bool = False,
):
    """Tourismus-Saisonalität München: stadtweite Monatszahlen zu Gästen
    und Übernachtungen. Außerhalb Münchens leer, mit Begründung."""
    _validate(lat, lon, 600)
    return (await svc(request).tourismus(lat, lon, refresh)).to_dict()


@router.get("/api/point/airbnb")
async def point_airbnb(
    request: Request, lat: float, lon: float, r: int = 600,
    refresh: bool = False,
):
    """Kurzzeitvermietung im Umkreis (Inside Airbnb, CC BY 4.0):
    Inserate, Zimmertypen, Bewertungs-Aktivität, Median-Preis.
    Nur für Städte mit Inside-Airbnb-Datensatz (München, Berlin)."""
    _validate(lat, lon, r)
    s = svc(request)
    adresse = await s.adresse(lat, lon)
    return (
        await s.airbnb(lat, lon, r, adresse.data if adresse.ok else None,
                       refresh)
    ).to_dict()


@router.get("/api/point/indikatoren")
async def point_indikatoren(request: Request, lat: float, lon: float):
    """Viertel-Steckbrief (Indikatorenatlas München): Jahresreihen des
    Stadtbezirks gegen die Stadt. Die Adresse kommt aus dem ohnehin
    gecachten Nominatim-Ergebnis."""
    _validate(lat, lon, 600)
    s = svc(request)
    adresse = await s.adresse(lat, lon)
    return (
        await s.indikatoren(adresse.data if adresse.ok else None, lat, lon)
    ).to_dict()


@router.get("/api/point/lage")
async def point_lage(request: Request, lat: float, lon: float, r: int = 600, refresh: bool = False):
    """Lage-Indikatoren am Punkt (Wien): Kurzparkzone, Fußgänger- und
    Begegnungszonen, Geschäftsstraßen, Realnutzung, Gebäudeinformation."""
    _validate(lat, lon, r)
    return (await svc(request).lage(lat, lon, r, refresh)).to_dict()


@router.get("/api/point/fahrzeit")
async def point_fahrzeit(
    request: Request,
    lat: float = Query(...), lon: float = Query(...),
    minuten: int = Query(10, ge=5, le=10),
):
    """Erreichbare Fläche mit dem Auto — auf Anforderung (Phase 0: die
    Abfrage ist gross und die oeffentlichen Spiegel antworten zeitweise
    mit HTTP 504)."""
    _validate(lat, lon, 600)
    return (await svc(request).fahrzeit(lat, lon, minuten)).to_dict()


@router.get("/api/point/liefergebiet")
async def point_liefergebiet(
    request: Request, lat: float, lon: float,
    minuten: int = Query(10, ge=5, le=15),
):
    """Rad-Liefergebiet: erreichbare Einwohner in X Minuten Fahrstrecke
    (Radprofil, pauschal 15 km/h). Wie der Gehweg-Block nur auf
    Anforderung — das Wegenetz ist eine große Overpass-Abfrage."""
    _validate(lat, lon, 600)
    return (await svc(request).liefergebiet(lat, lon, minuten)).to_dict()


@router.get("/api/point/links")
async def point_links(
    request: Request,
    lat: float,
    lon: float,
    r: int = 600,
    gemeinde: str | None = None,
    plz: str | None = None,
    ags: str | None = None,
    bundesland_code: str | None = None,
):
    _validate(lat, lon, r)
    return {
        "bodenrichtwerte": boris.links_for(bundesland_code, gemeinde),
        "weiterfuehrend": links.build(
            lat, lon, r, gemeinde=gemeinde, plz=plz, ags=ags,
            land=(await svc(request).land(lat, lon)).code,
        ),
        "grenzen": GRENZEN,
    }


@router.get("/api/point/oepnv-einzug")
async def point_oepnv_einzug(
    request: Request, lat: float, lon: float,
    minuten: int = Query(30, ge=10, le=45),
    refresh: bool = False,
):
    """ÖPNV-Einzugsgebiet aus dem lokal importierten GTFS-Fahrplan:
    erreichbare Halte in N Minuten (Referenz-Dienstag, 12:00, max.
    zwei Umstiege) samt Einwohner-Näherung. Rechnet einige Sekunden —
    deshalb nur auf Anforderung."""
    _validate(lat, lon, 600)
    return (await svc(request).oepnv_einzug(lat, lon, minuten, refresh)).to_dict()


@router.get("/api/point/luft")
async def point_luft(
    request: Request, lat: float, lon: float, refresh: bool = False,
):
    """Luftqualitätsindex der nächsten Messstation (UBA/Länder) —
    gemessene Stundenwerte, mit Entfernung und Stationsart."""
    _validate(lat, lon, 600)
    return (await svc(request).luft(lat, lon, refresh)).to_dict()


@router.get("/api/point/ihk-berlin")
async def point_ihk_berlin(
    request: Request, lat: float, lon: float, r: int = 600,
    refresh: bool = False,
):
    """Gastronomie-Bestand aus den IHK-Berlin-Gewerbedaten (CC0).
    Auf Anforderung: Der erste Abruf lädt eine rund 125 MB große
    Datei, danach liegt sie 30 Tage im Cache."""
    _validate(lat, lon, r)
    return (await svc(request).ihk_berlin(lat, lon, r, refresh)).to_dict()


@router.get("/api/point/baurecht")
async def point_baurecht(
    request: Request, lat: float, lon: float, refresh: bool = False,
):
    """Baurechtlicher Rahmen am Punkt: Art der baulichen Nutzung nach
    BauNVO (wo offen verfügbar), sonst Planumring bzw. die Aussage
    „kein Plan → § 34 BauGB". Ersetzt keine Bauvoranfrage."""
    _validate(lat, lon, 600)
    return (await svc(request).baurecht(lat, lon, refresh)).to_dict()


@router.get("/api/point/frequenz")
async def point_frequenz(
    request: Request, lat: float, lon: float, refresh: bool = False,
):
    """Gemessene Passantenfrequenz der nächsten offenen Zählstelle —
    Tagesgang statt Tagessumme. Nur wenige Straßen in Deutschland sind
    so vermessen; sonst bleibt der Block ehrlich leer."""
    _validate(lat, lon, 600)
    return (await svc(request).frequenz(lat, lon, refresh)).to_dict()


@router.get("/api/point/sonne")
async def point_sonne(
    request: Request, lat: float, lon: float, refresh: bool = False,
):
    """Besonnung und Verschattung am Punkt — Sonnenstunden je Stichtag
    aus Sonnenstand und Nachbarbebauung. Für Außengastronomie der
    Unterschied zwischen Abendsonne und Dauerschatten."""
    _validate(lat, lon, 600)
    return (await svc(request).sonne(lat, lon, refresh)).to_dict()
