"""Sicherheitslage des Kreises — Polizeiliche Kriminalstatistik (BKA).

Für Nachtgastronomie (Bar, Club, Spätbetrieb) gehört die Sicherheitslage
des Umfelds in die Standortabwägung: Straßenkriminalität, Gewaltdelikte
und Raub gegen Geschäfte sagen etwas über Türsteher-Bedarf,
Versicherungsprämien und Gästeempfinden.

Phase-0 am 2026-08-08 mit echtem Download verifiziert:

* ``https://www.bka.de/SharedDocs/Downloads/DE/Publikationen/
  PolizeilicheKriminalstatistik/2024/Kreis/Faelle/
  KR-F-01-T01-Kreise-Faelle-HZ_xls.xlsx?__blob=publicationFile&v=4``
  — HTTP 200, 2,1 MB, ein Arbeitsblatt, 16 809 Zeilen:
  **400 Kreise × 41 ausgewählte Straftaten(gruppen)**, Datenzeilen ab
  Zeile 10. „V1.0 erstellt am: 05.03.2025".
* Spalten: A Straftatenschlüssel (``------`` = insgesamt), B Straftat,
  C Gemeindeschlüssel (5-stellig), D Kreisname, E Kreisart (KfS/LK/SK/K/RV),
  F erfasste Fälle, G Häufigkeitszahl (Fälle je 100 000 Einwohner,
  Einwohnerbasis Zensus 2022), L aufgeklärte Fälle, M Aufklärungsquote %.
* Stichprobe München (09162): 93 854 Fälle insgesamt, HZ 6 304,3,
  Aufklärungsquote 63,1 % — gegen die Datei geprüft.

Das XLSX wird mit der Standardbibliothek gelesen (ZIP + XML), damit keine
neue Abhängigkeit nötig ist. Der Jahresdownload wird **einmal** geladen
und reduziert gecacht; jeder Punkt schlägt danach nur noch lokal nach.

Ehrlichkeit zuerst: Die Häufigkeitszahlen je Kreis sind laut
BKA-Interpretationshilfe nur eingeschränkt vergleichbar (Anzeigeverhalten,
Tatortprinzip, Großstadteffekte durch Einpendler und Touristen, die
Straftaten „mitbringen", aber nicht im Nenner stehen). Der Hinweis steht
am Block — deshalb war die Quelle bisher nur ein Link.
"""

from __future__ import annotations

import time
import zipfile
from io import BytesIO
from typing import Any
from xml.etree import ElementTree

from .base import Provenance, SourceError, SourceResult, now_iso

JAHR = 2024
XLSX_URL = (
    "https://www.bka.de/SharedDocs/Downloads/DE/Publikationen/"
    f"PolizeilicheKriminalstatistik/{JAHR}/Kreis/Faelle/"
    "KR-F-01-T01-Kreise-Faelle-HZ_xls.xlsx?__blob=publicationFile&v=4"
)
PORTAL = (
    "https://www.bka.de/DE/AktuelleInformationen/StatistikenLagebilder/"
    f"PolizeilicheKriminalstatistik/PKS{JAHR}/PKSTabellen/"
    "KreisFalltabellen/kreisfalltabellen.html"
)
# Nachgeprüft am 2026-08-08: Das BKA-Impressum stellt die Webinhalte unter
# Urheberrecht und gestattet Kopien „nur für den privaten Bereich" — eine
# offene Datenlizenz (dl-de, CC) nennt das BKA nicht. Dieses Werkzeug lädt
# die veröffentlichte Tabelle direkt beim BKA (wie ein Browser-Download),
# wertet sie lokal aus und zeigt die Zahlen mit Quellenangabe. Die Zahlen
# selbst sind amtliche Fakten; die Grenze steht als Warnung am Block.
LIZENZ = (
    "© Bundeskriminalamt, Polizeiliche Kriminalstatistik — keine offene "
    "Datenlizenz; Impressum gestattet Kopien nur für den privaten Bereich. "
    "Anzeige hier mit Quellenangabe, lokal geladen."
)

# Auswahl fürs Gastro-Umfeld. Schlüssel exakt wie in Spalte A der Datei;
# "------" ist dort wörtlich der Schlüssel der Gesamtzeile.
INSGESAMT = "------"
AUSWAHL = {
    "899000": "Straßenkriminalität",
    "892000": "Gewaltkriminalität",
    "224000": "Vorsätzliche einfache Körperverletzung",
    "212000": "Raub gegen Geschäfte/Kassenräume",
    "674000": "Sachbeschädigung",
    "730000": "Rauschgiftdelikte",
}

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_T = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"


def _zahl(s: str | None) -> float | None:
    if s is None or s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def zeilen_aus_xlsx(daten: bytes) -> list[dict[str, str]]:
    """XLSX (ZIP + SpreadsheetML) → Zeilen als {Spaltenbuchstabe: Rohwert}.

    Bewusst Standardbibliothek statt openpyxl: eine Tabelle, ein Blatt,
    keine Formeln — mehr braucht es nicht, und der Server bleibt ohne
    zusätzliche Abhängigkeit.
    """
    try:
        z = zipfile.ZipFile(BytesIO(daten))
        shared: list[str] = []
        wurzel = ElementTree.fromstring(z.read("xl/sharedStrings.xml"))
        for si in wurzel.findall("m:si", _NS):
            shared.append("".join(t.text or "" for t in si.iter(_T)))
        blatt = ElementTree.fromstring(z.read("xl/worksheets/sheet1.xml"))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise SourceError(
            "parse",
            "BKA-Kreistabelle ließ sich nicht als XLSX lesen — "
            "Format geändert?",
            detail=str(exc),
        ) from exc

    zeilen: list[dict[str, str]] = []
    for reihe in blatt.find("m:sheetData", _NS).findall("m:row", _NS):
        werte: dict[str, str] = {}
        for zelle in reihe.findall("m:c", _NS):
            v = zelle.find("m:v", _NS)
            if v is None or v.text is None:
                continue
            # Zellreferenz "C1234" → Spaltenbuchstabe(n) ohne Zeilennummer.
            spalte = "".join(ch for ch in (zelle.get("r") or "") if ch.isalpha())
            werte[spalte] = (
                shared[int(v.text)] if zelle.get("t") == "s" else v.text
            )
        if werte:
            zeilen.append(werte)
    return zeilen


def aufbereiten(zeilen: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    """Zeilen → je Kreis (AGS5) die Gesamtzeile plus ausgewählte Delikte.

    Bricht ab statt zu raten, wenn die erwarteten Kopfzeilen fehlen —
    dann hat das BKA das Tabellenlayout geändert.
    """
    kopf_ok = any(
        w.get("A") == "Schlüssel" and w.get("C", "").startswith("Gemeinde")
        for w in zeilen[:8]
    )
    if not kopf_ok:
        raise SourceError(
            "parse",
            "BKA-Kreistabelle hat unerwartete Kopfzeilen — Layout geändert?",
        )

    kreise: dict[str, dict[str, Any]] = {}
    for w in zeilen:
        ags = (w.get("C") or "").strip()
        schluessel = (w.get("A") or "").strip()
        if len(ags) != 5 or not ags.isdigit():
            continue
        eintrag = kreise.setdefault(ags, {
            "name": (w.get("D") or "").strip() or None,
            "kreisart": (w.get("E") or "").strip() or None,
            "delikte": {},
        })
        if schluessel != INSGESAMT and schluessel not in AUSWAHL:
            continue
        faelle = _zahl(w.get("F"))
        eintrag["delikte"][schluessel] = {
            "name": ("Straftaten insgesamt" if schluessel == INSGESAMT
                     else AUSWAHL[schluessel]),
            "faelle": int(faelle) if faelle is not None else None,
            "hz": round(_zahl(w.get("G")), 1) if _zahl(w.get("G")) is not None else None,
            "aufklaerungsquote": (
                round(_zahl(w.get("M")), 1)
                if _zahl(w.get("M")) is not None else None
            ),
        }
    if not kreise:
        raise SourceError("parse", "BKA-Kreistabelle ohne verwertbare Kreiszeilen.")
    return kreise


def _rang(kreise: dict[str, dict[str, Any]], ags5: str, schluessel: str) -> dict[str, Any] | None:
    """Rang der Häufigkeitszahl unter allen Kreisen (1 = höchste Belastung)
    plus Median als Vergleichswert — beides aus derselben Datei gerechnet,
    nichts geschätzt."""
    werte = sorted(
        (k["delikte"].get(schluessel, {}).get("hz")
         for k in kreise.values()
         if k["delikte"].get(schluessel, {}).get("hz") is not None),
        reverse=True,
    )
    eigener = kreise.get(ags5, {}).get("delikte", {}).get(schluessel, {}).get("hz")
    if eigener is None or not werte:
        return None
    mitte = len(werte) // 2
    median = (werte[mitte] if len(werte) % 2
              else (werte[mitte - 1] + werte[mitte]) / 2)
    return {
        "rang": werte.index(eigener) + 1,
        "von": len(werte),
        "median_hz": round(median, 1),
    }


def auswerten(kreise: dict[str, dict[str, Any]], ags: str) -> dict[str, Any] | None:
    """Blockdaten für den Kreis des Gemeindeschlüssels (erste 5 Stellen)."""
    ags5 = (ags or "")[:5]
    kreis = kreise.get(ags5)
    if not kreis:
        return None
    delikte = []
    for schluessel in [INSGESAMT, *AUSWAHL]:
        d = kreis["delikte"].get(schluessel)
        if not d:
            continue
        delikte.append({**d, "schluessel": schluessel,
                        "vergleich": _rang(kreise, ags5, schluessel)})
    return {
        "ags": ags5,
        "kreis": kreis["name"],
        "kreisart": kreis["kreisart"],
        "jahr": JAHR,
        "delikte": delikte,
        "portal": PORTAL,
    }


HINWEISE = [
    "Häufigkeitszahl (HZ) = Fälle je 100 000 Einwohner, Einwohnerbasis "
    "Zensus 2022. Laut BKA-Interpretationshilfe sind Kreisvergleiche nur "
    "eingeschränkt belastbar: Anzeigeverhalten und Kontrolldichte "
    "unterscheiden sich, und in Großstädten zählen Einpendler und "
    "Touristen als Tatverdächtige/Geschädigte mit, stehen aber nicht im "
    "Einwohner-Nenner — die HZ von Metropolen ist dadurch systematisch "
    "überzeichnet.",
    "Kreiswert — innerhalb einer Stadt unterscheidet er keine Viertel. "
    "Das Bahnhofsviertel und die Wohnstraße haben dieselbe Zahl.",
    "Das BKA stellt die Tabelle ohne offene Datenlizenz bereit (Impressum: "
    "Kopien nur für den privaten Bereich). Für die eigene "
    "Standortentscheidung ansehen — nicht weiterveröffentlichen.",
]


async def load(
    ags: str,
    kreise_laden,
) -> SourceResult:
    """Blockergebnis. ``kreise_laden`` liefert die (gecachte) bundesweite
    Kreistabelle — hier wird nur noch lokal nachgeschlagen."""
    started = time.perf_counter()
    try:
        kreise = await kreise_laden()
    except SourceError as err:
        return SourceResult.failed(
            "pks", err, int((time.perf_counter() - started) * 1000)
        )

    data = auswerten(kreise, ags)
    warnungen: list[str] = []
    if data is None:
        warnungen.append(
            f"Kreis {ags[:5]} steht nicht in der BKA-Kreistabelle {JAHR} — "
            "bei Gebietsreformen kann der Schlüssel abweichen."
        )
    else:
        data["hinweise"] = HINWEISE

    return SourceResult(
        name="pks",
        ok=True,
        data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnungen,
        provenance=Provenance(
            source=f"BKA — Polizeiliche Kriminalstatistik {JAHR}, Kreistabelle",
            license=LIZENZ,
            endpoint=XLSX_URL,
            stand=f"Berichtsjahr {JAHR} (V1.0 vom 05.03.2025)",
            retrieved_at=now_iso(),
            note=(
                "Jahrestabelle einmal geladen und lokal ausgewertet. "
                "Rang und Median sind aus derselben Tabelle gerechnet."
            ),
        ),
    )
