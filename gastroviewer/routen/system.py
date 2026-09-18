"""Zustand, Statistik, Protokoll, Cache."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, Request

from ..cache import AsyncCache
from ..http import Outbound
from ..sources import gtfs
from ._gemeinsam import RADIUS_CHOICES, cfg

router = APIRouter()


@router.get("/api/health")
async def health(request: Request):
    s = cfg(request)
    return {
        "status": "ok",
        "version": s.version,
        "user_agent": s.user_agent,
        "datenverzeichnis": str(s.data_dir),
        "gtfs": gtfs.status(s),
        "radien": list(RADIUS_CHOICES),
    }


@router.get("/api/stats")
async def stats(request: Request):
    cache: AsyncCache = request.app.state.cache
    out: Outbound = request.app.state.outbound
    data = await cache.stats()
    data["rate_limiter"] = out.limiters.stats()
    data["endpunkte"] = {
        "overpass": list(cfg(request).overpass_endpoints),
        "nominatim": cfg(request).nominatim_base,
        "zensus": cfg(request).zensus_base,
    }
    return data


@router.get("/api/outbound")
async def outbound_log(request: Request, seit: float = Query(0, description="Unix-Zeit")):
    cache: AsyncCache = request.app.state.cache
    rows = await asyncio.to_thread(cache.sync.outbound_since, seit)
    return {"anzahl": len(rows), "eintraege": rows}


@router.delete("/api/cache")
async def clear_cache(request: Request, quelle: str | None = None):
    cache: AsyncCache = request.app.state.cache
    n = await asyncio.to_thread(cache.sync.clear, quelle)
    return {"geloescht": n, "quelle": quelle or "alle"}
