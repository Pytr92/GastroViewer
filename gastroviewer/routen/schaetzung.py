"""Umsatzschätzung (§9) — eigener, klar getrennter Reiter."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..schaetzung import Eingaben, rechne, vorgaben_aus_punkt
from ._gemeinsam import svc, validiere_punkt as _validate
from .modelle import SchaetzEingaben

router = APIRouter()


@router.get("/api/schaetzung/vorgaben")
async def schaetzung_vorgaben(
    request: Request, lat: float, lon: float, r: int = 600
):
    """Füllt die Eingabefelder aus den Daten des Punktes vor — vorbefüllt,
    nicht festgelegt. Jeder Wert nennt seine Herkunft."""
    _validate(lat, lon, r)
    service = svc(request)
    punkt = await service.point(lat, lon, r)
    # Gehstrecken nur, wenn sie schon berechnet sind — die Vorgaben zu
    # holen darf keine 1–3-MB-Abfrage auslösen.
    gw = await service.gehweg_aus_cache(lat, lon, r)
    if gw is not None:
        punkt["bloecke"]["gehweg"] = gw.to_dict()
    return vorgaben_aus_punkt(punkt)


@router.post("/api/schaetzung")
async def schaetzung(body: SchaetzEingaben):
    ergebnis = rechne(Eingaben(**body.model_dump()))
    if not ergebnis["ok"]:
        raise HTTPException(422, "; ".join(ergebnis["fehler"]))
    return ergebnis
