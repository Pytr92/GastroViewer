"""Kreis- und Gemeindewerte, Erkundungsebenen, Geocoding, Kartendienste,
GENESIS-Zugang."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from ..http import Outbound
from ..laender import GESAMT_BBOX
from ..sources import genesis as genesis_mod, wms
from ._gemeinsam import cfg, svc, validiere_punkt as _validate
from .modelle import GenesisZugang

router = APIRouter()


@router.get("/api/genesis")
async def genesis(
    request: Request,
    ags: str = Query(..., min_length=5, max_length=8),
):
    """Amtliche Gastro-Anker aus der Regionaldatenbank (Opt-in mit
    kostenloser Kennung): Umsatz je Umsatzsteuerpflichtigem im
    Gastgewerbe und Gewerbean-/-abmeldungen, jeweils Kreiswerte."""
    if not ags.isdigit():
        raise HTTPException(422, "Der Gemeindeschlüssel besteht aus Ziffern.")
    return (await svc(request).genesis(ags)).to_dict()


@router.get("/api/genesis/zugang")
async def genesis_zugang(request: Request):
    """Nur der Status — Kennung maskiert, das Passwort verlässt den
    Server in keiner Antwort."""
    zugang = genesis_mod.lade_zugang(cfg(request))
    if zugang is None:
        return {"konfiguriert": False,
                "registrierung": genesis_mod.REGISTRIERUNG}
    k = zugang["kennung"]
    return {
        "konfiguriert": True,
        "quelle": zugang["quelle"],
        "kennung_maskiert": k[:2] + "…" if len(k) > 2 else "…",
        "registrierung": genesis_mod.REGISTRIERUNG,
    }


@router.post("/api/genesis/zugang")
async def genesis_zugang_setzen(request: Request, body: GenesisZugang):
    """Prüft die Kennung live beim Dienst (logincheck) und legt sie nur
    bei Erfolg lokal ab — Datei im Datenverzeichnis, Rechte 0600."""
    out: Outbound = request.app.state.outbound
    zugang = {"kennung": body.kennung, "passwort": body.passwort}
    try:
        ok, meldung = await genesis_mod.logincheck(out, zugang)
    except Exception as exc:  # noqa: BLE001 — Netzfehler klar benennen
        raise HTTPException(
            502, f"Der Anmelde-Check war nicht erreichbar: {exc}"
        ) from exc
    if not ok:
        raise HTTPException(
            422, f"Die Regionaldatenbank lehnt die Kennung ab: {meldung}"
        )
    genesis_mod.speichere_zugang(cfg(request), body.kennung, body.passwort)
    return {"gespeichert": True, "meldung": meldung}


@router.delete("/api/genesis/zugang")
async def genesis_zugang_loeschen(request: Request):
    zugang = genesis_mod.lade_zugang(cfg(request))
    if zugang and zugang["quelle"] == "umgebung":
        raise HTTPException(
            409,
            "Die Kennung kommt aus Umgebungsvariablen "
            "(GASTROVIEWER_GENESIS_KENNUNG) — dort entfernen.",
        )
    return {"geloescht": genesis_mod.loesche_zugang(cfg(request))}


@router.get("/api/einkommen")
async def einkommen(
    request: Request,
    ags: str = Query(..., min_length=5, max_length=8),
):
    """Verfügbares Einkommen je Einwohner (VGRdL) für den Kreis des
    Gemeindeschlüssels — die ehrliche Kaufkraft-Näherung: amtlich, aber
    Kreisebene."""
    if not ags.isdigit():
        raise HTTPException(422, "Der Gemeindeschlüssel besteht aus Ziffern.")
    return (await svc(request).einkommen(ags)).to_dict()


@router.get("/api/kreisprofil")
async def kreisprofil(
    request: Request,
    ags: str = Query("", max_length=8),
    lat: float | None = None, lon: float | None = None,
):
    """Kreisprofil aus dem Regionalatlas: Übernachtungen, Erwerbstätige
    am Arbeitsort, Arbeitsmarkt, Bevölkerungsbewegung — Kreiswerte. Ohne
    Schlüssel, mit Koordinaten (Österreich): das Gemeindeprofil von
    Statistik Austria über die Adresse des Punkts."""
    if ags:
        if not ags.isdigit() or len(ags) < 5:
            raise HTTPException(422, "Der Gemeindeschlüssel besteht aus 5 bis 8 Ziffern.")
        return (await svc(request).kreisprofil(ags)).to_dict()
    if lat is None or lon is None:
        raise HTTPException(422, "Gemeindeschlüssel oder Koordinaten angeben.")
    _validate(lat, lon, 600)
    return (await svc(request).kreisprofil_ohne_schluessel(lat, lon)).to_dict()


@router.get("/api/kalender")
async def kalender(request: Request, ags: str = "",
                   lat: float | None = None, lon: float | None = None,
                   refresh: bool = False):
    """Feiertage und Schulferien des Bundeslandes als Kontext — ohne
    Verrechnung in irgendeine Kennzahl. Ohne Gemeindeschlüssel (außerhalb
    Deutschlands) kommt das Bundesland aus der Adresse des Punkts."""
    if lat is not None and lon is not None:
        _validate(lat, lon, 600)
    return (await svc(request).kalender(ags or None, refresh, lat=lat, lon=lon)).to_dict()


@router.get("/api/wahl")
async def wahl(
    request: Request,
    ags: str = Query("", max_length=8),
    lat: float | None = None, lon: float | None = None,
):
    """Zweitstimmen der Bundestagswahl 2025 auf Wahlkreisebene für die
    Gemeinde des Schlüssels — Struktur-Marker mit Deutungs-Warnung. Ohne
    Schlüssel, mit Koordinaten (Österreich): Nationalratswahl 2024 über
    Bundesland und Gemeindename aus der Adresse des Punkts."""
    if ags:
        if not ags.isdigit() or len(ags) < 5:
            raise HTTPException(422, "Der Gemeindeschlüssel besteht aus 5 bis 8 Ziffern.")
        return (await svc(request).wahl(ags)).to_dict()
    if lat is None or lon is None:
        raise HTTPException(422, "Gemeindeschlüssel oder Koordinaten angeben.")
    _validate(lat, lon, 600)
    return (await svc(request).wahl_ohne_schluessel(lat, lon)).to_dict()


@router.get("/api/pks")
async def pks(
    request: Request,
    ags: str = Query(..., min_length=5, max_length=8),
):
    """Sicherheitslage des Kreises: PKS-Kreistabelle des BKA (Fälle,
    Häufigkeitszahl, Aufklärungsquote, Rang unter 400 Kreisen) — mit
    dem BKA-Hinweis zur eingeschränkten Vergleichbarkeit."""
    if not ags.isdigit():
        raise HTTPException(422, "Der Gemeindeschlüssel besteht aus Ziffern.")
    return (await svc(request).pks(ags)).to_dict()


@router.get("/api/register")
async def register(
    request: Request,
    # Vier Stellen: österreichische Postleitzahl — der Block antwortet
    # dann ehrlich „nur Deutschland" statt mit einem Eingabefehler.
    plz: str | None = Query(None, min_length=4, max_length=5),
):
    """Handelsregister-Umfeld der Standort-PLZ aus dem einmal
    importierten OffeneRegister-Bestand (Stand 2019)."""
    if plz is not None and not plz.isdigit():
        raise HTTPException(422, "Die Postleitzahl besteht aus fünf Ziffern.")
    return (await svc(request).register(plz)).to_dict()


@router.get("/api/pendler")
async def pendler(
    request: Request,
    ags: str = Query(..., min_length=8, max_length=8),
):
    """Pendlerverflechtungen der Gemeinde (Pendlerrechnung der Länder):
    Ein-/Auspendler, Saldo, Quoten, wichtigste Herkünfte und Ziele."""
    if not ags.isdigit():
        raise HTTPException(422, "Der Gemeindeschlüssel besteht aus Ziffern.")
    return (await svc(request).pendler(ags)).to_dict()


@router.get("/api/gitter")
async def gitter(
    request: Request,
    ebene: str = Query(..., description="1km oder 10km"),
    west: float = Query(...),
    sued: float = Query(...),
    ost: float = Query(...),
    nord: float = Query(...),
):
    """Übersichtsgitter für die Erkundung: WO ist es interessant?

    Der Umkreis beantwortet die Frage nur für einen Punkt; diese Ebene
    zeigt Einwohnerdichte flächig — 1 km für eine Stadt, 10 km für ein
    Land. Ganz München sind 613 Zellen, ganz Bayern 1.083 (gemessen)."""
    from ..sources.zensus import GITTER_EBENEN

    if ebene not in GITTER_EBENEN:
        raise HTTPException(422, "ebene muss 1km oder 10km sein.")
    if not (west < ost and sued < nord):
        raise HTTPException(422, "Box muss west<ost und sued<nord erfüllen.")
    if not (GESAMT_BBOX[1] - 0.5 <= west and ost <= GESAMT_BBOX[3] + 0.5
            and GESAMT_BBOX[0] - 0.5 <= sued and nord <= GESAMT_BBOX[2] + 0.5):
        raise HTTPException(422, "Box liegt außerhalb der unterstützten Länder.")
    max_lon, max_lat = GITTER_EBENEN[ebene]["max_spanne"]
    if (ost - west) > max_lon or (nord - sued) > max_lat:
        raise HTTPException(
            422,
            f"Ausschnitt zu groß für die {ebene}-Ebene — weiter herauszoomen "
            "wechselt auf das gröbere Gitter.",
        )
    return (await svc(request).gitter(ebene, west, sued, ost, nord)).to_dict()


@router.get("/api/scan")
async def scan(
    request: Request,
    west: float = Query(...),
    sued: float = Query(...),
    ost: float = Query(...),
    nord: float = Query(...),
):
    """Flächen-Scan: Einwohner je Gastronomiebetrieb im 300-m-Umfeld,
    je 100-m-Zelle. Beantwortet „WO im Viertel ist das Verhältnis aus
    Nachfrage und Angebot am günstigsten?" — der Umkreis beantwortet das
    nur für einen Punkt, die Erkundungsebene nur grob."""
    from ..sources.scan import MAX_SPANNE

    if not (west < ost and sued < nord):
        raise HTTPException(422, "Box muss west<ost und sued<nord erfüllen.")
    if not (GESAMT_BBOX[1] - 0.5 <= west and ost <= GESAMT_BBOX[3] + 0.5
            and GESAMT_BBOX[0] - 0.5 <= sued and nord <= GESAMT_BBOX[2] + 0.5):
        raise HTTPException(422, "Box liegt außerhalb der unterstützten Länder.")
    if (ost - west) > MAX_SPANNE[0] or (nord - sued) > MAX_SPANNE[1]:
        raise HTTPException(
            422,
            "Ausschnitt zu groß für den Flächen-Scan — er arbeitet auf dem "
            "100-m-Gitter und ist auf rund 4×5 km begrenzt. Für die große "
            "Fläche ist die Übersichtsebene (1/10 km) da.",
        )
    return (await svc(request).scan(west, sued, ost, nord)).to_dict()


@router.get("/api/geocode")
async def geocode(
    request: Request,
    q: str = Query(..., min_length=2),
    refresh: bool = Query(False),
):
    return (await svc(request).suche(q, refresh)).to_dict()


@router.get("/api/geocode/vorschlaege")
async def geocode_vorschlaege(
    request: Request,
    q: str = Query(..., min_length=3),
):
    """Adress-Vorschläge beim Tippen — nur über Photon (die
    Nominatim-Nutzungsbedingungen untersagen Autocomplete). Kurzer
    Cache je Eingabe, damit Zurücktippen nichts erneut abfragt."""
    return (await svc(request).vorschlaege(q)).to_dict()


@router.get("/api/wms")
async def wms_dienste(request: Request, bundesland_code: str | None = None):
    """Konfiguration der Kartenebene. Ohne verifizierten Dienst wird der
    Grund genannt statt einer geratenen URL."""
    if bundesland_code:
        return wms.fuer_bundesland(bundesland_code)
    return wms.alle()


@router.get("/api/wms/ebenen")
async def wms_ebenen(request: Request, bundesland_code: str | None = None):
    """Zusätzliche amtliche Kartenebenen des Landes (Luftbild, Flurstücke)."""
    return {"ebenen": wms.zusatzebenen(bundesland_code)}


@router.get("/api/wms/bodenrichtwert")
async def wms_bodenrichtwert(
    request: Request, lat: float, lon: float, bundesland_code: str | None = None
):
    """GetFeatureInfo beim Landesdienst — über das Backend, weil ein fetch
    aus dem Browser an CORS scheitern würde."""
    _validate(lat, lon, 600)
    out: Outbound = request.app.state.outbound
    res = await wms.feature_info(out, cfg(request), lat, lon, bundesland_code)
    return res.to_dict()
