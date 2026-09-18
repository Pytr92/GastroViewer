"""Gemerkte Punkte: Merken, Vergleich, Sicherung, Neu prüfen, Wächter,
Verlauf, Export.

Reihenfolge zählt: die festen Pfade unter ``/api/points/`` stehen vor
``/api/points/{point_id}`` — sonst finge der Pfadparameter das Wort ab und
antwortete mit 422."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import sqlite3
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from ..cache import STAENDE, STAND_SCHLUESSEL, AsyncCache, pruefe_punkt
from ..kriterien import ProfilFehler, moegliche_kriterien, pruefe_kriterium, pruefe_profil
from ..sources.base import SourceError
from ..vergleich import (VERGLEICH_GRUPPEN, VERGLEICH_SPALTEN, VERLAUF_KENNZAHLEN,
                         _compact, _row_for, point_to_csv)
from ._gemeinsam import svc, validiere_punkt as _validate
from .modelle import Profil, PunkteSicherung, PunktNotiz, SavePoint

router = APIRouter()


@router.get("/api/points")
async def list_points(request: Request):
    """Die Liste ohne Datenpakete — den vollen Datenstand eines Punkts
    liefert ``/api/points/{id}``. Bei dutzenden gemerkten Adressen wären
    es sonst viele Megabyte je Ebenen-Aktualisierung."""
    cache: AsyncCache = request.app.state.cache
    rows = await asyncio.to_thread(cache.sync.list_points_kurz)
    return {"anzahl": len(rows), "punkte": rows}


@router.post("/api/points")
async def save_point(request: Request, body: SavePoint):
    _validate(body.lat, body.lon, body.radius)
    service = svc(request)
    payload = await service.point(body.lat, body.lon, body.radius)
    # Gehstrecken nur übernehmen, wenn sie schon berechnet sind — das Merken
    # eines Punktes darf keine 1–3-MB-Abfrage auslösen.
    gw = await service.gehweg_aus_cache(body.lat, body.lon, body.radius)
    if gw is not None:
        payload["bloecke"]["gehweg"] = gw.to_dict()
    # Dasselbe fürs Fahrzeit-Einzugsgebiet: Es ist die größte Abfrage des
    # Werkzeugs und läuft nur auf Knopfdruck. Liegt ein Ergebnis vor,
    # wandert es in den Punkt und damit in den Standortbericht.
    fz = await service.fahrzeit_aus_cache(body.lat, body.lon)
    if fz is not None:
        payload["bloecke"]["fahrzeit"] = fz.to_dict()
    cache: AsyncCache = request.app.state.cache
    pid = await asyncio.to_thread(
        cache.sync.save_point,
        body.label,
        body.lat,
        body.lon,
        body.radius,
        _compact(payload),
    )
    return {"id": pid, "label": body.label}


@router.patch("/api/points/{point_id}")
async def punkt_notiz(request: Request, point_id: int, body: PunktNotiz):
    """Eigene Notiz und Bewertung — die einzige Stelle, an der eine Wertung
    in die Daten kommt, und sie kommt ausdrücklich vom Nutzer."""
    cache: AsyncCache = request.app.state.cache
    # Nur die tatsächlich mitgeschickten Felder schreiben: Wer den
    # Arbeitsstand ändert, darf damit nicht die Notiz löschen.
    felder = {k: v for k, v in body.model_dump().items()
              if k in body.model_fields_set}
    if felder.get("stand") not in (None, "", *STAND_SCHLUESSEL):
        raise HTTPException(
            422, f"Unbekannter Arbeitsstand: {felder['stand']!r}. "
            f"Möglich sind: {', '.join(STAND_SCHLUESSEL)}.")
    ok = await cache.set_point_felder(point_id, felder)
    if not ok:
        raise HTTPException(404, "Punkt nicht gefunden.")
    return {"id": point_id, **felder}


@router.delete("/api/points/{point_id}")
async def delete_point(request: Request, point_id: int):
    cache: AsyncCache = request.app.state.cache
    ok = await asyncio.to_thread(cache.sync.delete_point, point_id)
    if not ok:
        raise HTTPException(404, "Punkt nicht gefunden.")
    return {"geloescht": point_id}


@router.get("/api/points/vergleich")
async def vergleich(request: Request):
    cache: AsyncCache = request.app.state.cache
    rows = await asyncio.to_thread(cache.sync.list_points)
    return {
        "spalten": VERGLEICH_SPALTEN,
        "gruppen": VERGLEICH_GRUPPEN,
        # Die Auswahl kommt aus dem Backend, damit sie nur an einer
        # Stelle steht — die Oberfläche erfindet keine Arbeitsstände.
        "staende": [{"key": k, "label": v} for k, v in STAENDE],
        "zeilen": [_row_for(r) for r in rows],
    }


@router.get("/api/points/export")
async def export_points(request: Request):
    """Datensicherung: alle gemerkten Punkte samt Verlauf als eine Datei.

    Monate Sucharbeit hängen sonst an einer einzigen SQLite-Datei auf
    einem Rechner. Die Antwort ist als Download deklariert."""
    cache: AsyncCache = request.app.state.cache
    daten = await asyncio.to_thread(cache.sync.export_points)
    datum = time.strftime("%Y-%m-%d", time.localtime())
    return JSONResponse(
        daten,
        headers={
            "Content-Disposition":
                f'attachment; filename="gastroviewer-punkte-{datum}.json"'
        },
    )


@router.post("/api/points/import")
async def import_points(request: Request, daten: PunkteSicherung):
    """Spielt eine Sicherung ein. Neue IDs; exakte Dubletten (Label,
    Koordinaten, Radius, Anlagezeitpunkt) werden übersprungen.

    Struktur und Typen prüft das Modell (falsche Struktur war vorher
    ein TypeError und damit HTTP 500), den Wertebereich jedes Punkts
    dieselbe Regel wie bei jeder Anfrage — „Neu prüfen" und der Wächter
    reichen die gespeicherten Werte sonst ungeprüft an Overpass weiter."""
    cache: AsyncCache = request.app.state.cache
    for i, p in enumerate(daten.punkte):
        try:
            pruefe_punkt(p.lat, p.lon, p.radius)
        except ValueError as err:
            raise HTTPException(
                422, f"Punkt {i + 1} („{p.label}“): {err}") from err
    try:
        ergebnis = await asyncio.to_thread(
            cache.sync.import_points, daten.model_dump())
    except ValueError as err:
        raise HTTPException(422, str(err)) from err
    except (KeyError, TypeError, sqlite3.Error) as err:
        raise HTTPException(
            422, f"Sicherung nicht lesbar ({type(err).__name__}: {err}) — "
            "Datei beschädigt?"
        ) from err
    return ergebnis

# Muss NACH /api/points/vergleich und den festen Pfaden (export/import)
# registriert sein — sonst finge der Pfadparameter das Wort ab und
# antwortete mit 422.


# Muss NACH /api/points/vergleich und den festen Pfaden (export/import)
# registriert sein — sonst finge der Pfadparameter das Wort ab und
# antwortete mit 422.
@router.get("/api/points/kriterien")
async def kriterien_auswahl():
    """Welche Kennzahlen sich als Kriterium eignen.

    Abgeleitet aus den Vergleichsspalten, damit eine neue Kennzahl
    automatisch zur Verfügung steht statt in einer zweiten Liste zu
    fehlen."""
    return {"kriterien": moegliche_kriterien(VERGLEICH_SPALTEN)}


@router.post("/api/points/kriterien")
async def kriterien_pruefen(request: Request, profil: Profil):
    """Das eigene Standortprofil gegen alle gemerkten Punkte.

    Das Profil kommt mit der Anfrage: Es ist eine Einstellung des
    Nutzers und liegt in seinem Browser, nicht in der Datenbank des
    Werkzeugs."""
    cache: AsyncCache = request.app.state.cache
    rows = await asyncio.to_thread(cache.sync.list_points)
    liste = [k.model_dump() for k in profil.kriterien]
    # Unbekannte Kennzahlen vorab abweisen — auch ohne gemerkte Punkte.
    # Vorher zählte ein Tippfehler im Key für jeden Standort als „nicht
    # prüfbar", als fehlten die Daten.
    bekannte = {c["key"] for c in VERGLEICH_SPALTEN}
    try:
        for k in liste:
            pruefe_kriterium({}, k, bekannte)
    except ProfilFehler as err:
        raise HTTPException(422, str(err)) from err
    ergebnisse = []
    for r in rows:
        zeile = _row_for(r)
        try:
            pruefung = pruefe_profil(zeile, liste, bekannte)
        except ProfilFehler as err:
            raise HTTPException(422, str(err)) from err
        ergebnisse.append({
            "id": r["id"], "label": r["label"],
            "stand": r.get("stand"), **pruefung,
        })
    return {"anzahl": len(ergebnisse), "punkte": ergebnisse}


@router.get("/api/points/kannibalisierung")
async def punkte_kannibalisierung(
    request: Request, a: int = Query(...), b: int = Query(...),
):
    """Gemeinsame Einwohner zweier gespeicherter Punkte (Umkreis-
    Überlappung auf dem Zensusgitter) — macht aus der „Kreise
    überschneiden sich"-Warnung eine Zahl."""
    cache: AsyncCache = request.app.state.cache
    row_a = await asyncio.to_thread(cache.sync.get_point, a)
    row_b = await asyncio.to_thread(cache.sync.get_point, b)
    if row_a is None or row_b is None:
        raise HTTPException(404, "Punkt nicht gefunden.")
    for row in (row_a, row_b):
        _validate(row["lat"], row["lon"], row["radius"])
    # Der einzige Endpunkt, der eine Quelle am Block-Mechanismus vorbei
    # aufruft — ein Zensus-Ausfall darf hier kein 500 sein, sondern
    # eine Meldung, die die Ursache nennt.
    try:
        return await svc(request).kannibalisierung(row_a, row_b)
    except SourceError as err:
        raise HTTPException(
            502, f"Zensus-Dienst nicht erreichbar: {err.message}") from err


@router.get("/api/points/{point_id}")
async def get_point(request: Request, point_id: int):
    """Ein gemerkter Punkt mit vollem Datenstand — Grundlage des Berichts."""
    cache: AsyncCache = request.app.state.cache
    row = await asyncio.to_thread(cache.sync.get_point, point_id)
    if row is None:
        raise HTTPException(404, "Punkt nicht gefunden.")
    return {**row, "zeile": _row_for(row)}


@router.post("/api/points/{point_id}/pruefung")
async def punkt_pruefung(request: Request, point_id: int):
    """„Neu prüfen": dieselben Quellen erneut abfragen — am Cache vorbei —
    und die Unterschiede zum gespeicherten Stand ausweisen.

    Standortsuche dauert Monate. Ein neuer Wettbewerber oder ein
    verschwundener Betrieb (freies Ladenlokal UND ein Konkurrent weniger)
    ist genau die Veränderung, die man sonst erst vor Ort bemerkt.
    """
    cache: AsyncCache = request.app.state.cache
    row = await asyncio.to_thread(cache.sync.get_point, point_id)
    if row is None:
        raise HTTPException(404, "Punkt nicht gefunden.")

    # Bestände, die vor der Importprüfung eingespielt wurden, laufen
    # hier zum ersten Mal durch die Bereichsregel.
    _validate(row["lat"], row["lon"], row["radius"])
    service = svc(request)
    neu = await service.point(row["lat"], row["lon"], row["radius"], refresh=True)
    # Gehstrecken werden bewusst NICHT neu geladen (1–3 MB je Punkt) —
    # liegt ein frischer Stand im Cache, wird er übernommen.
    gw = await service.gehweg_aus_cache(row["lat"], row["lon"], row["radius"])
    if gw is not None:
        neu["bloecke"]["gehweg"] = gw.to_dict()

    # Ein Quellenausfall ist kein neuer Datenstand. Overpass antwortet
    # laut eigener Messung in 3 von 7 Fällen mit 504 — vorher wurde dann
    # der leere Block gespeichert: alle Betriebe „verschwunden", die
    # Vergleichstabelle leer, und der Nullstand blieb für immer im
    # Verlauf. Jetzt behält jeder ausgefallene Block den alten Stand
    # und wird als „nicht geprüft" ausgewiesen.
    alte_bloecke = (row.get("payload") or {}).get("bloecke") or {}
    nicht_geprueft = []
    for name, block in list(neu["bloecke"].items()):
        if block.get("ok"):
            continue
        fehler = (block.get("error") or {}).get("message")
        nicht_geprueft.append({"block": name, "fehler": fehler})
        if name in alte_bloecke:
            neu["bloecke"][name] = alte_bloecke[name]
    osm_frisch = bool((neu["bloecke"].get("osm") or {}).get("ok")) and not any(
        e["block"] == "osm" for e in nicht_geprueft)
    beweglich = ("osm", "gtfs", "radzaehlung", "verkehrsmenge")
    # „Frisch" heißt: geantwortet UND etwas geliefert — ein nicht
    # importierter Fahrplan ist ok=True mit data=None und kein Beleg.
    frisch = [n for n in beweglich
              if n not in {e["block"] for e in nicht_geprueft}
              and (neu["bloecke"].get(n) or {}).get("ok")
              and (neu["bloecke"].get(n) or {}).get("data") is not None]
    if not frisch:
        # Nichts Bewegliches ist neu — ein Verlaufseintrag wäre nur der
        # alte Stand mit neuem Datum, im Bericht ein falscher Zeitpunkt.
        return {
            "id": point_id,
            "label": row.get("label"),
            "ok": False,
            "gespeichert": False,
            "nicht_geprueft": nicht_geprueft,
            "veraendert": [], "neue_betriebe": [], "verschwundene_betriebe": [],
            "fehler": "Keine der beweglichen Quellen (OSM, GTFS, Zählstellen) "
                      "hat geantwortet — der gespeicherte Stand bleibt unverändert.",
            "hinweise": ["Später noch einmal prüfen; Overpass ist ein "
                         "Spendendienst und zeitweise überlastet."],
        }

    alt_zeile = _row_for(row)
    neu_kompakt = _compact(neu)
    neu_zeile = _row_for({**row, "payload": neu_kompakt})

    veraendert = []
    for key, titel in VERLAUF_KENNZAHLEN:
        a, n = alt_zeile.get(key), neu_zeile.get(key)
        if a != n:
            veraendert.append({"key": key, "titel": titel, "alt": a, "neu": n})

    def _gastro(payload: dict[str, Any]) -> dict[Any, dict[str, Any]]:
        liste = (((payload.get("bloecke") or {}).get("osm") or {})
                 .get("data") or {}).get("gastronomie") or []
        return {g.get("id"): g for g in liste if g.get("id") is not None}

    alt_g = _gastro(row.get("payload") or {})
    neu_g = _gastro(neu_kompakt)

    def _kurz(g: dict[str, Any]) -> dict[str, Any]:
        return {"name": g.get("name"), "typ": g.get("typ_label"),
                "distanz_m": g.get("distanz_m")}

    # Der Betriebsvergleich braucht den frischen OSM-Block — ist er
    # ausgefallen, gibt es keinen Vergleich, nicht „alle verschwunden".
    if osm_frisch:
        neue = [_kurz(g) for gid, g in neu_g.items() if gid not in alt_g]
        weg = [_kurz(g) for gid, g in alt_g.items() if gid not in neu_g]
    else:
        neue, weg = [], []
    neue.sort(key=lambda g: g.get("distanz_m") or 0)
    weg.sort(key=lambda g: g.get("distanz_m") or 0)

    ok = await asyncio.to_thread(
        cache.sync.replace_point_payload, point_id, neu_kompakt
    )
    if not ok:
        raise HTTPException(404, "Punkt nicht gefunden.")

    return {
        "id": point_id,
        "label": row.get("label"),
        "ok": True,
        "gespeichert": True,
        "geprueft_am": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "nicht_geprueft": nicht_geprueft,
        "veraendert": veraendert,
        "neue_betriebe": neue,
        "verschwundene_betriebe": weg,
        "hinweise": [
            "Ein verschwundener Betrieb ist zunächst eine OSM-Änderung — "
            "erst die Begehung macht daraus ein freies Ladenlokal.",
            "Zensuswerte ändern sich nicht: der Stichtag bleibt der "
            "15.05.2022. Beweglich sind OSM, GTFS und die Zählstellen.",
        ],
    }


@router.get("/api/points/{point_id}/waechter")
async def punkt_waechter(request: Request, point_id: int,
                         refresh: bool = False):
    """Veränderungs-Wächter: gespeicherten Gastro-Stand gegen eine
    frische OSM-Zählung halten — **ohne** den gespeicherten Stand zu
    überschreiben. Der leichte Bruder von „neu prüfen": eine einzige
    Quelle (Overpass, standardmäßig über den Cache), keine
    Nebenwirkungen. Erst „neu prüfen" übernimmt den neuen Stand."""
    cache: AsyncCache = request.app.state.cache
    row = await asyncio.to_thread(cache.sync.get_point, point_id)
    if row is None:
        raise HTTPException(404, "Punkt nicht gefunden.")

    _validate(row["lat"], row["lon"], row["radius"])
    osm = await svc(request).osm(row["lat"], row["lon"], row["radius"],
                                 refresh)
    if not osm.ok:
        return {"id": point_id, "label": row.get("label"),
                "ok": False, "fehler": (osm.error or {}).get("message")}

    def _gastro_map(liste):
        return {g.get("id"): g for g in (liste or [])
                if g.get("id") is not None}

    # ".get("data") or {}" statt Default-Argument: gespeicherte Punkte
    # tragen bei OSM-Ausfall data=None — der Key existiert, ist aber null.
    alt = _gastro_map(((((row.get("payload") or {}).get("bloecke") or {})
                       .get("osm") or {}).get("data") or {}).get("gastronomie"))
    neu = _gastro_map((osm.data or {}).get("gastronomie"))

    def _kurz(g):
        return {"name": g.get("name"), "typ": g.get("typ_label"),
                "distanz_m": g.get("distanz_m")}

    neue = sorted((_kurz(g) for gid, g in neu.items() if gid not in alt),
                  key=lambda g: g.get("distanz_m") or 0)
    weg = sorted((_kurz(g) for gid, g in alt.items() if gid not in neu),
                 key=lambda g: g.get("distanz_m") or 0)
    return {
        "id": point_id,
        "label": row.get("label"),
        "gespeichert_am": row.get("updated_at") or row.get("created_at"),
        "ok": True,
        "aus_cache": bool(osm.provenance and osm.provenance.cached),
        "gastro_gespeichert": len(alt),
        "gastro_jetzt": len(neu),
        "neue_betriebe": neue,
        "verschwundene_betriebe": weg,
        "hinweis": (
            "Nur der OSM-Gastro-Stand wird verglichen; der gespeicherte "
            "Punkt bleibt unverändert. Übernehmen: „neu prüfen“."
        ),
    }


@router.get("/api/points/{point_id}/verlauf")
async def punkt_verlauf(request: Request, point_id: int):
    """Alle abgelegten Stände eines Punktes, ältester zuerst, der aktuelle
    Stand als letzter Eintrag."""
    cache: AsyncCache = request.app.state.cache
    row = await asyncio.to_thread(cache.sync.get_point, point_id)
    if row is None:
        raise HTTPException(404, "Punkt nicht gefunden.")
    alt = await asyncio.to_thread(cache.sync.list_verlauf, point_id)

    def _stand(ts: float | None, payload: dict[str, Any], aktuell: bool):
        return {
            "ts": time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts)) if ts else None,
            "aktuell": aktuell,
            "zeile": _row_for({**row, "payload": payload}),
        }

    staende = [_stand(v.get("ts"), v.get("payload") or {}, False) for v in alt]
    staende.append(_stand(
        row.get("geprueft_am") or row.get("created_at"),
        row.get("payload") or {}, True,
    ))
    return {"id": point_id, "label": row.get("label"),
            "anzahl": len(staende), "staende": staende}


@router.get("/api/export/point.json")
async def export_json(request: Request, lat: float, lon: float, r: int = 600):
    _validate(lat, lon, r)
    data = await svc(request).point(lat, lon, r)
    name = f"standort_{lat:.5f}_{lon:.5f}_{r}m.json"
    return Response(
        content=json.dumps(data, ensure_ascii=False, indent=2),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/api/export/point.csv")
async def export_csv(request: Request, lat: float, lon: float, r: int = 600):
    _validate(lat, lon, r)
    data = await svc(request).point(lat, lon, r)
    csv_text = point_to_csv(data)
    name = f"standort_{lat:.5f}_{lon:.5f}_{r}m.csv"
    return PlainTextResponse(
        csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/api/export/vergleich.csv")
async def export_vergleich(request: Request):
    cache: AsyncCache = request.app.state.cache
    rows = await asyncio.to_thread(cache.sync.list_points)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([c["titel"] for c in VERGLEICH_SPALTEN])
    for r in rows:
        vals = _row_for(r)
        w.writerow([vals.get(c["key"], "") for c in VERGLEICH_SPALTEN])
    return PlainTextResponse(
        buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="standortvergleich.csv"'},
    )
