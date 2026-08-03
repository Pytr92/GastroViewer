"""Kreisprofil — vier amtliche Blicke auf den Kreis, aus dem Regionalatlas.

Aufbauend auf dem für das verfügbare Einkommen verifizierten Kartendienst
(``einkommen.py`` dokumentiert den Weg dorthin) liest dieses Modul vier
weitere Indikatortabellen der Statistischen Ämter:

* **Beherbergung** (``ai012_5``): Übernachtungen je Einwohner und
  durchschnittliche Aufenthaltsdauer — Touristen sind Zulauf, den der
  Zensus (Wohnbevölkerung) nicht sieht.
* **Erwerbstätige am Arbeitsort** (``ai007_1``): Erwerbstätige je 1.000
  Einwohner im erwerbsfähigen Alter — die ehrliche Tagesbevölkerungs-
  Näherung. Die Erwerbstätigenrechnung der Länder zählt am **Arbeitsort**;
  ein Wert über 1.000 heißt: mehr Arbeitsplätze als Erwerbsfähige, also
  Einpendler. Dazu der Anteil des Bereichs Handel/Verkehr/Gastgewerbe.
* **Beschäftigtenquote** (``ai007_2``) und **Arbeitslosenquote**
  (``ai008_1_5``): Arbeitsmarkt — für die Gastronomie doppelt lesbar, als
  Kaufkraft-Umfeld und als Personalverfügbarkeit.
* **Bevölkerungsstand und -bewegung** (``ai002_1_5``): Entwicklung im Jahr
  und Wanderungssaldo je 10.000 Einwohner, Bevölkerungsdichte — wächst
  oder schrumpft die Region, in die ein langer Mietvertrag fällt?

Live-Gegenprobe am 03.08.2026 (München Stadt / Bayern / Deutschland):
Übernachtungen je EW 13,2 / 7,8 / 5,9 (2024) — Erwerbstätige je 1.000 EW
1.159 / 924 / 869 (2024, München als Einpendler-Magnet über 1.000) —
Arbeitslosenquote 5,4 / 4,0 / 6,3 % (2025) — Bevölkerungsentwicklung
+108,8 / +54,9 / +14,5 je 10.000 EW (2024). Plausibilisiert gegen die
Veröffentlichungen der ET-Rechnung und der Bundesagentur für Arbeit.

Wie beim Einkommen gilt: **Kreiswerte.** Innerhalb einer Großstadt
unterscheiden sie keine Viertel. Jede Tabelle hat ihr eigenes jüngstes
Datenjahr — es wird je Tabelle ausgewiesen, nicht vermischt.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from ..config import Settings
from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, now_iso
from .einkommen import LICENSE, kreis_aus_ags

# Welche Tabelle liefert welche Indikatoren. Feldnamen und Titel stammen aus
# dem Dienstekatalog des Regionalatlas (services.json der Anwendung) und
# wurden live gegen die Tabellen geprüft — kein Feld ist geraten.
TABELLEN: list[dict[str, Any]] = [
    {
        "tabelle": "regionalatlas.ai012_5",
        "thema": "Tourismus (Beherbergung)",
        "indikatoren": [
            {"schluessel": "uebernachtungen_je_ew", "feld": "ai1202",
             "titel": "Gästeübernachtungen je Einwohner und Jahr",
             "einheit": None, "stellen": 1, "verlauf": True},
            {"schluessel": "aufenthaltsdauer", "feld": "ai1201",
             "titel": "Durchschnittliche Aufenthaltsdauer",
             "einheit": "Tage", "stellen": 1, "verlauf": False},
        ],
    },
    {
        "tabelle": "regionalatlas.ai007_1",
        "thema": "Erwerbstätige am Arbeitsort",
        "indikatoren": [
            {"schluessel": "et_je_1000_ew", "feld": "ai0701",
             "titel": "Erwerbstätige am Arbeitsort je 1.000 EW (15–64)",
             "einheit": None, "stellen": 0, "verlauf": True},
            {"schluessel": "et_gastgewerbe", "feld": "ai0707",
             "titel": "Anteil Handel, Verkehr, Gastgewerbe, Inform./Komm.",
             "einheit": "%", "stellen": 1, "verlauf": False},
        ],
    },
    {
        "tabelle": "regionalatlas.ai007_2",
        "thema": "Arbeitsmarkt",
        "indikatoren": [
            {"schluessel": "beschaeftigtenquote", "feld": "ai0710",
             "titel": "Beschäftigtenquote (Wohnort, 15–64)",
             "einheit": "%", "stellen": 1, "verlauf": False},
        ],
    },
    {
        "tabelle": "regionalatlas.ai008_1_5",
        "thema": "Arbeitsmarkt",
        "indikatoren": [
            {"schluessel": "arbeitslosenquote", "feld": "ai0801",
             "titel": "Arbeitslosenquote",
             "einheit": "%", "stellen": 1, "verlauf": True},
        ],
    },
    {
        "tabelle": "regionalatlas.ai002_1_5",
        "thema": "Bevölkerung",
        "indikatoren": [
            {"schluessel": "bev_entwicklung", "feld": "ai0202",
             "titel": "Bevölkerungsentwicklung im Jahr je 10.000 EW",
             "einheit": None, "stellen": 1, "verlauf": True},
            {"schluessel": "wanderungssaldo", "feld": "ai0212",
             "titel": "Wanderungssaldo je 10.000 EW",
             "einheit": None, "stellen": 1, "verlauf": False},
            {"schluessel": "bev_dichte", "feld": "ai0201",
             "titel": "Bevölkerungsdichte (EW je km²)",
             "einheit": None, "stellen": 0, "verlauf": False},
        ],
    },
]

VERLAUF_JAHRE = 10


def _layer_json(tabelle: str) -> str:
    return json.dumps({
        "source": {
            "type": "dataLayer",
            "dataSource": {
                "type": "table",
                "workspaceId": "gdb",
                "dataSourceName": tabelle,
            },
        }
    })


def _wert(v: Any) -> float | None:
    """Regionalatlas kennt Sperr-/Fehlwerte als riesige Platzhalterzahlen
    (2222222…, 5555555…). Alles jenseits einer Million ist bei diesen
    Verhältniskennzahlen kein Messwert und wird zu „liegt nicht vor"."""
    if not isinstance(v, (int, float)):
        return None
    if abs(v) >= 1_000_000:
        return None
    return v


def auswerten_tabelle(
    payload: dict[str, Any], eintrag: dict[str, Any], kreis: str, land: str
) -> list[dict[str, Any]]:
    """Je Indikator das jüngste Jahr, in dem der **Kreis** einen Wert hat;
    Land und Bund werden zum selben Jahr gelesen (oder bleiben leer)."""
    zeilen: dict[str, dict[int, dict[str, Any]]] = {}
    namen: dict[str, str] = {}
    for f in payload.get("features", []):
        a = f.get("attributes") or {}
        ags2 = str(a.get("ags2") or "").strip()
        jahr = a.get("jahr2")
        if not ags2 or not isinstance(jahr, int):
            continue
        zeilen.setdefault(ags2, {})[jahr] = a
        name = str(a.get("gen2") or "").strip()
        if name:
            namen[ags2] = name

    ergebnisse: list[dict[str, Any]] = []
    for ind in eintrag["indikatoren"]:
        feld = ind["feld"]
        kreisjahre = {
            j: _wert(a.get(feld))
            for j, a in zeilen.get(kreis, {}).items()
            if _wert(a.get(feld)) is not None
        }
        if not kreisjahre:
            continue
        jahr = max(kreisjahre)
        e: dict[str, Any] = {
            "schluessel": ind["schluessel"],
            "titel": ind["titel"],
            "thema": eintrag["thema"],
            "einheit": ind["einheit"],
            "stellen": ind["stellen"],
            "jahr": jahr,
            "kreis": kreisjahre[jahr],
            "land": _wert(zeilen.get(land, {}).get(jahr, {}).get(feld)),
            "bund": _wert(zeilen.get("DG", {}).get(jahr, {}).get(feld)),
        }
        if ind["verlauf"]:
            e["verlauf_kreis"] = [
                {"jahr": j, "wert": w} for j, w in sorted(kreisjahre.items())
            ][-VERLAUF_JAHRE:]
        e["_namen"] = namen
        ergebnisse.append(e)
    return ergebnisse


async def load(out: Outbound, settings: Settings, ags: str) -> SourceResult:
    started = time.perf_counter()
    kreis = kreis_aus_ags(ags)
    if kreis is None:
        return SourceResult(
            name="kreisprofil", ok=True, data=None,
            warnings=["Ohne Gemeindeschlüssel lässt sich kein Kreiswert zuordnen."],
        )
    land = kreis[:2]
    url = f"{settings.regionalatlas_base}/dynamicLayer/query"

    async def hole(eintrag: dict[str, Any]) -> dict[str, Any] | SourceError:
        form = {
            "layer": _layer_json(eintrag["tabelle"]),
            "where": f"ags2 IN ('{kreis}','{land}','DG')",
            "outFields": "*",
            "returnGeometry": "false",
            "f": "json",
        }
        try:
            payload = await out.post_json(
                "kreisprofil", url, data=form, timeout=settings.zensus_timeout
            )
        except SourceError as err:
            return err
        if isinstance(payload, dict) and "error" in payload:
            err = payload["error"]
            return SourceError(
                "api_error",
                f"Regionalatlas meldet Fehler {err.get('code')} für "
                f"{eintrag['tabelle']}: {err.get('message')}",
            )
        return payload if isinstance(payload, dict) else {}

    antworten = await asyncio.gather(*(hole(e) for e in TABELLEN))

    indikatoren: list[dict[str, Any]] = []
    warnings: list[str] = []
    namen: dict[str, str] = {}
    for eintrag, antwort in zip(TABELLEN, antworten):
        if isinstance(antwort, SourceError):
            warnings.append(f"{eintrag['thema']}: {antwort.message}")
            continue
        for e in auswerten_tabelle(antwort, eintrag, kreis, land):
            namen.update(e.pop("_namen"))
            indikatoren.append(e)

    if not indikatoren:
        # Keine einzige Tabelle lieferte etwas — als Fehler ausweisen, nicht
        # als leerer Erfolg, damit der Block in der UI ehrlich rot wird.
        fehler = SourceError(
            "api_error",
            "Der Regionalatlas lieferte für keinen der Kreisprofil-Indikatoren "
            "einen Wert. " + " · ".join(warnings),
        )
        return SourceResult.failed(
            "kreisprofil", fehler, int((time.perf_counter() - started) * 1000)
        )

    jahre = sorted({i["jahr"] for i in indikatoren})
    data = {
        "gebiete": {
            "kreis": {"ags": kreis, "name": namen.get(kreis)},
            "land": {"ags": land, "name": namen.get(land)},
            "bund": {"ags": "DG", "name": namen.get("DG") or "Deutschland"},
        },
        "indikatoren": indikatoren,
    }
    return SourceResult(
        name="kreisprofil",
        ok=True,
        data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnings,
        provenance=Provenance(
            source=(
                "Regionalatlas Deutschland — Statistische Ämter des Bundes "
                "und der Länder (Beherbergungsstatistik, ET-Rechnung, "
                "Arbeitsmarktstatistik der BA, Bevölkerungsfortschreibung)"
            ),
            license=LICENSE,
            endpoint=url,
            stand="Datenjahre " + "–".join(
                [str(jahre[0])] + ([str(jahre[-1])] if len(jahre) > 1 else [])
            ),
            retrieved_at=now_iso(),
            note=(
                "Kreiswerte — innerhalb einer Großstadt unterscheiden sie "
                "keine Viertel. Jede Kennzahl trägt ihr eigenes Datenjahr."
            ),
        ),
    )
