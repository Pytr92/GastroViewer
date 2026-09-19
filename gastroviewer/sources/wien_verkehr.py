"""Wien: Kfz-Dauerzählstellen (Verkehrsmenge) und Luftgütemessnetz (Luft).

Beide Blöcke waren bis hierher „nur für Deutschland“. Die Stadt Wien
liefert offen, was BASt/BAYSIS und das UBA-Messnetz dort liefern —
in anderer Form, deshalb ein eigenes Modul, das die **Blockformen** der
deutschen Module nachbaut (``bast.aufbereiten`` und ``luft.load``).

Live belegt am 18.09.2026 (fixtures/at, Runden 6 und 7):

* **Kfz-Dauerzählstellen** (MA 46): Lage als WFS-Layer ``DAUERZAEHLOGD``
  (87 Punkte mit ``ZST_ID``, ``ZST_NAME``, ``STR_NR``, ``RICHTUNG_1/2``),
  Werte als Monats-CSV ``dauerzaehlstellen.csv`` (cp1252, ``;``; 5 MB,
  49 000 Zeilen 2016–2025). Je Zählstelle, Monat, Richtung (``RINAME``,
  darunter ``Gesamt``) und Fahrzeugtyp (``Kfz`` / ``LkwÄ``) der DTV
  Montag–Sonntag (``DTVMS``), werktags (``DTVMF``), Samstag/Sonntag
  (``DTVSA``/``DTVSF``) und der Spitzentag. 71 der 87 Zählstellen haben
  Werte im jüngsten Jahr.
* **Luftgütemessnetz** (MA 22): Lage als WFS-Layer ``LUFTGUETENETZOGD``
  (18 Stationen, ``NAME_KURZ`` = Lumes-Kürzel), Halbstundenwerte als
  ``lumesakt-v2.csv`` (cp1252, ``;``, vier Kopfzeilen: Komponente,
  Mittelungsart, Einheit). NO2 als HMW, PM10/PM2.5 als MW24 und HMW,
  O3 als 1MW und HMW; ``NE`` = nicht erfasst, ``---`` = Ausfall.
  Der deutsche Block zeigt den **UBA-Luftqualitätsindex**; Wien führt
  keinen — hier wird derselbe Index nach den UBA-Klassengrenzen aus
  den Wiener Werten gebildet und das steht so am Block.
"""

from __future__ import annotations

import csv
import io
import re
import time
from typing import Any, Awaitable, Callable

from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, bearing_label, haversine_m, now_iso
from .wien import LIZENZ, WFS_URL, _features, _punkt, in_wien

KFZ_CSV_URL = "https://www.wien.gv.at/data/ogd/ma46/dauerzaehlstellen.csv"
KFZ_PORTAL = "https://www.data.gv.at/katalog/dataset/stadt-wien_dauerzhlstellenwien"
LUFT_CSV_URL = "https://go.gv.at/l9lumesakt"
LUFT_PORTAL = "https://www.wien.gv.at/umwelt/luft/messwerte/"
MAX_DISTANZ_M = 2000
MAX_LUFT_DISTANZ_M = 6000

MONATE = {"JAN": 1, "FEB": 2, "MÄR": 3, "MAR": 3, "APR": 4, "MAI": 5, "JUN": 6, "JUL": 7, "AUG": 8,
          "SEP": 9, "OKT": 10, "NOV": 11, "DEZ": 12}


def _zahl(s: Any) -> float | None:
    if s is None:
        return None
    t = str(s).strip().replace("\xa0", "")
    if not t or t in ("NE", "---", "-"):
        return None
    try:
        return float(t.replace(",", "."))
    except ValueError:
        return None


def _monat(s: str) -> int | None:
    return MONATE.get(re.sub(r"[^A-ZÄ]", "", (s or "").upper())[:3])


# ---------------------------------------------------------- Kfz-Zählstellen

def kfz_reduzieren(csv_text: str) -> dict[str, Any]:
    """Aus der Monats-CSV je Zählstelle (``ZNR``) die zwölf jüngsten
    Monate mit Gesamtwerten: ``{"jahr": 2025, "stellen": {znr: {...}}}``.

    Jahresmittel = Mittel der ``DTVMS`` über die Monate des jüngsten
    Jahres mit Werten; Schwerverkehr aus den ``LkwÄ``-Zeilen desselben
    Zeitraums. Zählstellen ohne Werte im jüngsten Jahr bleiben mit dem
    letzten Jahr, das sie haben — mit dem Jahr am Wert."""
    zeilen: dict[int, list[dict[str, Any]]] = {}
    for r in csv.DictReader(io.StringIO(csv_text), delimiter=";"):
        try:
            znr = int(r.get("ZNR") or "")
            jahr = int(r.get("JAHR") or "")
        except ValueError:
            continue
        if (r.get("RINAME") or "").strip() != "Gesamt":
            continue
        m = _monat(r.get("MONAT") or "")
        if m is None:
            continue
        zeilen.setdefault(znr, []).append({
            "jahr": jahr, "monat": m, "typ": (r.get("FZTYP") or "").strip(),
            "name": (r.get("ZNAME") or "").strip(), "strasse": f"{(r.get('STRTYP') or '').strip()}{(r.get('STRNR') or '').strip()}",
            "dtvms": _zahl(r.get("DTVMS")), "dtvmf": _zahl(r.get("DTVMF")),
            "dtvsa": _zahl(r.get("DTVSA")), "dtvsf": _zahl(r.get("DTVSF")),
            "tvmax": _zahl(r.get("TVMAX")), "tvmaxt": (r.get("TVMAXT") or "").strip() or None,
        })
    stellen: dict[str, Any] = {}
    juengstes = 0
    for znr, rows in zeilen.items():
        kfz = [r for r in rows if r["typ"] == "Kfz" and r["dtvms"] is not None]
        if not kfz:
            continue
        jahr = max(r["jahr"] for r in kfz)
        juengstes = max(juengstes, jahr)
        kj = [r for r in kfz if r["jahr"] == jahr]
        lkw = [r for r in rows if r["typ"] != "Kfz" and r["jahr"] == jahr and r["dtvms"] is not None]
        spitze = max(kj, key=lambda r: r["tvmax"] or 0)

        def mittel(rs: list[dict[str, Any]], feld: str) -> int | None:
            w = [r[feld] for r in rs if r[feld] is not None]
            return round(sum(w) / len(w)) if w else None

        stellen[str(znr)] = {
            "name": kj[0]["name"], "strasse": kj[0]["strasse"], "jahr": jahr, "monate": len(kj),
            "dtv_kfz": mittel(kj, "dtvms"), "dtv_werktag": mittel(kj, "dtvmf"),
            "dtv_samstag": mittel(kj, "dtvsa"), "dtv_sonntag": mittel(kj, "dtvsf"),
            "dtv_schwerverkehr": mittel(lkw, "dtvms"),
            "spitzentag": {"kfz": spitze["tvmax"], "tag": spitze["tvmaxt"], "monat": spitze["monat"]}
            if spitze["tvmax"] else None,
        }
    return {"jahr": juengstes or None, "stellen": stellen}


def kfz_aufbereiten(features: list[dict[str, Any]], werte: dict[str, Any], lat: float, lon: float,
                    radius: int) -> dict[str, Any]:
    """Blockform von ``bast.aufbereiten`` — plus Werktag/Wochenende und
    Spitzentag, die es dort nicht gibt."""
    treffer = []
    stellen = werte.get("stellen") or {}
    for f in features:
        pkt = _punkt(f)
        p = f.get("properties") or {}
        if pkt is None or p.get("ZST_ID") is None:
            continue
        dist = haversine_m(lat, lon, *pkt)
        if dist > MAX_DISTANZ_M:
            continue
        w = stellen.get(str(p.get("ZST_ID"))) or {}
        kfz, sv = w.get("dtv_kfz"), w.get("dtv_schwerverkehr")
        richtungen = " ↔ ".join(x for x in (p.get("RICHTUNG_1"), p.get("RICHTUNG_2")) if x)
        treffer.append({
            "strasse": f"{p.get('ZST_NAME') or w.get('name') or '?'}" + (f" ({p.get('STR_NR')})" if p.get("STR_NR") else ""),
            "zaehlstelle": f"{p.get('ZST_ID')} · {richtungen}" if richtungen else str(p.get("ZST_ID")),
            "zaehlart": "Dauerzählstelle (MA 46)",
            "lat": pkt[0], "lon": pkt[1], "distanz_m": round(dist),
            "richtung": bearing_label(lat, lon, *pkt), "im_radius": dist <= radius,
            "dtv_kfz": kfz,
            "dtv_leichtverkehr": (kfz - sv if kfz is not None and sv is not None else None),
            "dtv_schwerverkehr": sv,
            "schwerverkehr_anteil": (round(sv / kfz * 100, 1) if kfz and sv is not None and kfz > 0 else None),
            "dtv_werktag": w.get("dtv_werktag"), "dtv_samstag": w.get("dtv_samstag"),
            "dtv_sonntag": w.get("dtv_sonntag"), "spitzentag": w.get("spitzentag"),
            "jahr": w.get("jahr"), "monate": w.get("monate"), "lage": p.get("LAGE"),
        })
    treffer.sort(key=lambda s: s["distanz_m"])
    treffer = treffer[:12]
    mit_wert = [s for s in treffer if s["dtv_kfz"] is not None]
    return {
        "zaehlstellen": treffer,
        "naechste": treffer[0] if treffer else None,
        "staerkste": max(mit_wert, key=lambda s: s["dtv_kfz"]) if mit_wert else None,
        "im_radius": [s for s in treffer if s["im_radius"]],
        "max_distanz_m": MAX_DISTANZ_M,
        "jahr": werte.get("jahr"),
        "dienst": "wien",
        "portal": KFZ_PORTAL,
        "portal_titel": "Dauerzählstellen der Stadt Wien (MA 46)",
        "netz_hinweis": ("Gezählt werden die Wiener Hauptstraßen (Bundesstraßen B, Gürtel, Brücken) — "
                         "87 Dauerzählstellen; Bezirksstraßen und Fußgängerzonen fehlen. "),
        "stadt": "Wien",
    }


KFZ_HINWEISE = [
    "DTV = durchschnittlicher täglicher Verkehr Montag–Sonntag am Querschnitt, hier das "
    "Mittel der Monatswerte des jüngsten Jahres mit Daten (Anzahl Monate am Wert). "
    "Schwerverkehr sind Lkw-Äquivalente (LkwÄ) derselben Monate.",
    "Werktag/Samstag/Sonntag getrennt: Für Gastronomie zählt, ob die Achse am Wochenende "
    "leerer oder voller ist als unter der Woche — der Spitzentag zeigt Event- und Ferienverkehr.",
]


async def kfz_load(out: Outbound, lat: float, lon: float, radius: int,
                   werte_laden: Callable[[], Awaitable[dict[str, Any]]]) -> SourceResult:
    started = time.perf_counter()
    try:
        features = await _features(out, "wien_verkehr", "DAUERZAEHLOGD", None, 200)
        werte = await werte_laden()
    except SourceError as err:
        return SourceResult.failed("verkehrsmenge", err, int((time.perf_counter() - started) * 1000))
    data = kfz_aufbereiten(features, werte, lat, lon, radius)
    data["hinweise"] = KFZ_HINWEISE
    warnungen: list[str] = []
    if not data["zaehlstellen"]:
        warnungen.append(f"Keine Wiener Dauerzählstelle innerhalb von {MAX_DISTANZ_M} m — gezählt "
                         "werden nur die Hauptachsen.")
    elif data["staerkste"] is None:
        warnungen.append("Die Zählstellen im Umkreis haben in der Monatsdatei keine Werte (Umbau, Ausfall).")
    return SourceResult(
        name="verkehrsmenge", ok=True, data=data,
        duration_ms=int((time.perf_counter() - started) * 1000), warnings=warnungen,
        provenance=Provenance(
            source=f"Kfz-Dauerzählstellen der Stadt Wien (MA 46) — Monatswerte, jüngstes Jahr {data['jahr'] or '?'}",
            license=LIZENZ, endpoint=KFZ_CSV_URL,
            stand=f"Monatsdatei, Jahr {data['jahr'] or '?'}", retrieved_at=now_iso(),
            note="Lage aus dem WFS-Layer DAUERZAEHLOGD, Werte aus der Monats-CSV (einmal geladen, "
                 "lokal gemittelt). Blockform wie BASt/BAYSIS.",
        ),
    )


# ---------------------------------------------------------------- Luft

# UBA-Klassengrenzen des Luftqualitätsindex (Obergrenzen je Stufe 1–5):
# NO2 Stundenwert, PM10 und PM2.5 Tagesmittel, O3 Stundenwert.
GRENZEN = {
    "NO2": (20, 40, 100, 200), "PM10": (20, 35, 50, 100), "PM25": (10, 20, 25, 50), "O3": (60, 120, 180, 240),
}
INDEX_LABELS = {1: "sehr gut", 2: "gut", 3: "mäßig", 4: "schlecht", 5: "sehr schlecht"}
KOMPONENTEN = {"NO2": "Stickstoffdioxid (NO₂)", "PM10": "Feinstaub (PM₁₀)", "PM25": "Feinstaub (PM₂,₅)",
               "O3": "Ozon (O₃)", "SO2": "Schwefeldioxid (SO₂)", "CO": "Kohlenmonoxid (CO)"}
# Welche Mittelungsart je Komponente in den Index eingeht (wie beim UBA).
MITTEL_FUER_INDEX = {"NO2": "HMW", "PM10": "MW24", "PM25": "MW24", "O3": "1MW"}


def teilindex(komponente: str, wert: float | None) -> int | None:
    g = GRENZEN.get(komponente)
    if g is None or wert is None:
        return None
    for stufe, grenze in enumerate(g, start=1):
        if wert <= grenze:
            return stufe
    return 5


def lumes_parsen(csv_text: str) -> dict[str, dict[str, Any]]:
    """Die Lumes-Datei in ``{kuerzel: {"stand": ..., "werte": {komp: {mittel: wert}}}}``.

    Kopf: Zeile 0 Version/Zeitstempel, Zeile 1 Komponenten (``Zeit-X``
    vor jeder Gruppe), Zeile 2 Mittelungsart, Zeile 3 Einheit."""
    rows = list(csv.reader(io.StringIO(csv_text), delimiter=";"))
    if len(rows) < 5:
        raise SourceError("parse_error", "Lumes-Datei ohne Kopfzeilen.")
    komp, mittel, einheit = rows[1], rows[2], rows[3]
    stationen: dict[str, dict[str, Any]] = {}
    for r in rows[4:]:
        if not r or not r[0].strip():
            continue
        werte: dict[str, dict[str, Any]] = {}
        zeit: dict[str, str] = {}
        for i, k in enumerate(komp):
            if i >= len(r) or not k:
                continue
            if k.startswith("Zeit-"):
                zeit[k[5:]] = r[i].strip()
                continue
            v = _zahl(r[i])
            m = mittel[i] if i < len(mittel) else ""
            werte.setdefault(k, {})[m or "HMW"] = v
            werte[k]["_einheit"] = einheit[i] if i < len(einheit) else None
            werte[k]["_zeit"] = zeit.get(k) or zeit.get("NO2")
        stationen[r[0].strip()] = {"werte": werte, "stand": rows[0][2] if len(rows[0]) > 2 else None}
    return stationen


def _stand_iso(s: str | None) -> str | None:
    """``18.09.2026, 21:30`` → ``2026-09-18T21:30`` (Lumes-Zeit MESZ/MEZ)."""
    if not s:
        return None
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4}),?\s*(\d{2}):(\d{2})", s.strip())
    if not m:
        return s
    return f"{m[3]}-{m[2]}-{m[1]}T{m[4]}:{m[5]}"


def luft_auswerten(station: dict[str, Any], stationsname: str) -> dict[str, Any] | None:
    """Blockform von ``luft.aktuellster_eintrag`` (``index``, ``komponenten``…)."""
    werte = station.get("werte") or {}
    komponenten = []
    stand = None
    for code, titel in KOMPONENTEN.items():
        w = werte.get(code)
        if not w:
            continue
        mittel = MITTEL_FUER_INDEX.get(code, "HMW")
        wert = w.get(mittel)
        if wert is None:
            wert, mittel = w.get("HMW"), "HMW"
        if wert is None and all(v is None for k, v in w.items() if not k.startswith("_")):
            continue
        ti = teilindex(code, wert) if mittel == MITTEL_FUER_INDEX.get(code) else None
        komponenten.append({
            "komponente": titel, "einheit": w.get("_einheit"), "wert": wert,
            "mittelung": {"HMW": "Halbstundenmittel", "MW24": "Tagesmittel (24 h)", "1MW": "Stundenmittel",
                          "MW8": "Achtstundenmittel"}.get(mittel, mittel),
            "teilindex": ti, "teilindex_label": INDEX_LABELS.get(ti) if ti else None,
        })
        stand = stand or _stand_iso(w.get("_zeit"))
    if not any(k["wert"] is not None for k in komponenten):
        return None
    indizes = [k["teilindex"] for k in komponenten if k["teilindex"]]
    gesamt = max(indizes) if indizes else None
    return {
        "stand": stand, "index": gesamt, "index_label": INDEX_LABELS.get(gesamt) if gesamt else None,
        "unvollstaendig": any(k["wert"] is None for k in komponenten),
        "komponenten": komponenten,
    }


LUFT_HINWEISE = [
    "Wien führt keinen amtlichen Luftqualitätsindex; die Stufen hier folgen den **Klassengrenzen "
    "des deutschen UBA-Index** (NO₂ und O₃ als Stunden-/Halbstundenwert, Feinstaub als Tagesmittel), "
    "angewandt auf die Wiener Halbstundenwerte — vergleichbar mit dem deutschen Block, nicht amtlich.",
    "Nicht jede Station misst alles: Stephansplatz NO₂/O₃/SO₂, Taborstraße Feinstaub und NO₂. "
    "Der Block nimmt die nächste Station mit Werten; die Entfernung steht dabei.",
]


def luft_aufbereiten(features: list[dict[str, Any]], lumes: dict[str, dict[str, Any]], lat: float,
                     lon: float) -> tuple[dict[str, Any] | None, list[str]]:
    kandidaten = []
    for f in features:
        pkt = _punkt(f)
        p = f.get("properties") or {}
        if pkt is None or not p.get("NAME_KURZ"):
            continue
        d = haversine_m(lat, lon, *pkt)
        if d <= MAX_LUFT_DISTANZ_M:
            kandidaten.append((d, pkt, p))
    kandidaten.sort(key=lambda k: k[0])
    warnungen: list[str] = []
    for d, pkt, p in kandidaten:
        st = lumes.get(p["NAME_KURZ"])
        if not st:
            continue
        eintrag = luft_auswerten(st, p.get("NAME") or p["NAME_KURZ"])
        if eintrag is None:
            warnungen.append(f"Station {p.get('NAME')} liefert derzeit keine Luftwerte — nächste Station versucht.")
            continue
        station = {"code": p["NAME_KURZ"], "name": p.get("NAME"), "stadt": "Wien", "lat": pkt[0], "lon": pkt[1],
                   "distanz_m": round(d), "richtung": bearing_label(lat, lon, *pkt),
                   "standort": p.get("STANDORT"), "nutzung": p.get("NUTZUNG"), "info": p.get("URL_INFO")}
        return {"station": station, **eintrag, "hinweise": LUFT_HINWEISE, "portal": LUFT_PORTAL,
                "portal_titel": "Luftmesswerte der Stadt Wien (MA 22)", "dienst": "wien"}, warnungen
    if not kandidaten:
        warnungen.append(f"Keine Wiener Luftmessstation innerhalb von {MAX_LUFT_DISTANZ_M // 1000} km.")
    else:
        warnungen.append("Keine der nahen Stationen liefert derzeit Werte.")
    return None, warnungen


async def luft_load(out: Outbound, lat: float, lon: float) -> SourceResult:
    started = time.perf_counter()
    try:
        features = await _features(out, "wien_luft", "LUFTGUETENETZOGD", None, 50)
        text = await out.get_text("wien_luft", LUFT_CSV_URL, timeout=30.0, limiter="wien", min_interval=0.5,
                                  encoding="cp1252")
        lumes = lumes_parsen(text)
    except SourceError as err:
        return SourceResult.failed("luft", err, int((time.perf_counter() - started) * 1000))
    data, warnungen = luft_aufbereiten(features, lumes, lat, lon)
    return SourceResult(
        name="luft", ok=True, data=data, duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnungen,
        provenance=Provenance(
            source="Luftgütemessnetz der Stadt Wien (MA 22, Lumes) — aktuelle Halbstundenwerte",
            license=LIZENZ, endpoint=LUFT_CSV_URL,
            stand=(data or {}).get("stand") or "aktuell", retrieved_at=now_iso(),
            note="Stationslage aus dem WFS-Layer LUFTGUETENETZOGD; Werte aus lumesakt-v2.csv. "
                 "Indexstufen nach UBA-Klassengrenzen gebildet, nicht amtlich.",
        ),
    )


__all__ = ["KFZ_CSV_URL", "LUFT_CSV_URL", "WFS_URL", "in_wien", "kfz_reduzieren", "kfz_aufbereiten", "kfz_load",
           "lumes_parsen", "luft_auswerten", "luft_aufbereiten", "luft_load", "teilindex"]
