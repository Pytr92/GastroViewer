"""Tourismus-Saisonalität: Monatszahlen Gäste und Übernachtungen für München.

Das Kreisprofil (Block 3c) trägt die **Jahressumme** der Übernachtungen — für
jeden Kreis in Deutschland. Was dort fehlt, ist der Jahresverlauf: Ein
Standort, der vom Tourismus lebt, braucht die Antwort auf „Wie tief ist der
Januar?“. Monatswerte je Kreis gibt es bundesweit **nicht** offen (Phase-0
am 2026-08-07: Regionaldatenbank 45412-… führt nur Jahressummen je Kreis,
Destatis-GENESIS verlangt für den Datenabruf eine Kennung) — das Statistische
Amt München veröffentlicht sie für die Stadt als offene CSV.

Verifiziert am 2026-08-07: CKAN-Datensatz ``monatszahlen-tourismus`` auf
``opendata.muenchen.de`` (Statistisches Amt München, Datenlizenz Deutschland
Namensnennung 2.0). Komma-getrennt; ``MONATSZAHL`` ∈ {Gäste, Übernachtungen},
``AUSPRAEGUNG`` ∈ {Ausland, Inland, insgesamt}; ``MONAT`` als ``JJJJMM`` oder
``Summe`` (Jahressumme); Fehlwerte als ``NA``. Reihen ab 2006; die jüngsten
Monate des laufenden Jahres sind noch leer.
"""

from __future__ import annotations

import csv
import io
import time
from typing import Any

from ..config import Settings
from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, now_iso
from .baustellen import STADT_BBOX

CSV_URL = (
    "https://opendata.muenchen.de/dataset/3621ad08-aa97-4c2b-b0b0-82780375743c/"
    "resource/4f00274a-ef75-41e5-b5c1-15f22c9f8a12/download/tourismus.csv"
)
LIZENZ = (
    "Datenlizenz Deutschland Namensnennung 2.0 (dl-de/by-2-0) · "
    "© Statistisches Amt München, Open-Data-Portal der Landeshauptstadt München"
)
ROHDATEN = "https://opendata.muenchen.de/dataset/monatszahlen-tourismus"

# So viele abgeschlossene Jahre gehen in die Saisonkurve ein (gewählter Wert:
# lang genug zum Glätten, kurz genug, um Corona-ferne Jahre zu bevorzugen).
SAISON_JAHRE = 5

MONATSNAMEN = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
               "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]


def _zahl(text: Any) -> int | None:
    t = str(text or "").strip()
    if not t or t.upper() == "NA":
        return None
    try:
        return int(float(t.replace(",", ".")))
    except ValueError:
        return None


def parse_monatszahlen(csv_text: str) -> dict[str, dict[str, int]]:
    """CSV → ``{"Übernachtungen|insgesamt": {"202506": 1785072, …}, …}``.

    Jahressummen-Zeilen (``MONAT = Summe``) werden unter dem Schlüssel
    ``JJJJ|Summe`` abgelegt — sie ersparen das Aufaddieren angebrochener Jahre.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    pflicht = {"MONATSZAHL", "AUSPRAEGUNG", "JAHR", "MONAT", "WERT"}
    if not pflicht.issubset(set(reader.fieldnames or [])):
        raise SourceError(
            "parse",
            "Die Tourismus-CSV hat nicht mehr die erwarteten Spalten — "
            f"gefunden: {reader.fieldnames}",
        )
    reihen: dict[str, dict[str, int]] = {}
    for row in reader:
        wert = _zahl(row.get("WERT"))
        if wert is None:
            continue
        schluessel = f"{(row.get('MONATSZAHL') or '').strip()}|{(row.get('AUSPRAEGUNG') or '').strip()}"
        monat = (row.get("MONAT") or "").strip()
        if monat == "Summe":
            monat = f"{(row.get('JAHR') or '').strip()}|Summe"
        elif not (len(monat) == 6 and monat.isdigit()):
            continue
        reihen.setdefault(schluessel, {})[monat] = wert
    return reihen


def _monate_sortiert(reihe: dict[str, int]) -> list[str]:
    return sorted(m for m in reihe if "|" not in m)


def _fmt(ym: str) -> str:
    return f"{MONATSNAMEN[int(ym[4:6]) - 1]} {ym[:4]}"


def auswerten(reihen: dict[str, dict[str, int]]) -> dict[str, Any]:
    uebern = reihen.get("Übernachtungen|insgesamt") or {}
    gaeste = reihen.get("Gäste|insgesamt") or {}
    uebern_ausland = reihen.get("Übernachtungen|Ausland") or {}
    monate = _monate_sortiert(uebern)
    if len(monate) < 24:
        raise SourceError(
            "parse",
            "Zu wenige gefüllte Monate in der Tourismus-CSV — "
            f"gefunden: {len(monate)}.",
        )

    letzte12 = monate[-12:]
    fenster = [{"monat": _fmt(m), "wert": uebern[m]} for m in letzte12]
    summe_12m = sum(uebern[m] for m in letzte12)

    vorjahr12 = [f"{int(m[:4]) - 1}{m[4:]}" for m in letzte12]
    veraenderung = None
    if all(m in uebern for m in vorjahr12):
        basis = sum(uebern[m] for m in vorjahr12)
        if basis:
            veraenderung = round((summe_12m - basis) / basis * 100, 1)

    gaeste_12m = None
    dauer = None
    if all(m in gaeste for m in letzte12):
        gaeste_12m = sum(gaeste[m] for m in letzte12)
        if gaeste_12m:
            dauer = round(summe_12m / gaeste_12m, 2)

    ausland_prozent = None
    if all(m in uebern_ausland for m in letzte12):
        ausland_prozent = round(
            sum(uebern_ausland[m] for m in letzte12) / summe_12m * 100, 1
        )

    # Saisonkurve über die letzten abgeschlossenen Jahre: Mittelwert je
    # Kalendermonat, als Index gegen den Jahresdurchschnitt (100 = Durchschnitt).
    jahre_komplett = sorted(
        {m[:4] for m in monate}
        - {j for j in {m[:4] for m in monate}
           if sum(1 for m in monate if m[:4] == j) < 12}
    )[-SAISON_JAHRE:]
    saison = None
    if jahre_komplett:
        mittel = []
        for kal in range(1, 13):
            werte = [uebern[f"{j}{kal:02d}"] for j in jahre_komplett]
            mittel.append(sum(werte) / len(werte))
        schnitt = sum(mittel) / 12
        saison = {
            "jahre": [int(j) for j in jahre_komplett],
            "index": [
                {"monat": MONATSNAMEN[i], "index": round(m / schnitt * 100)}
                for i, m in enumerate(mittel)
            ],
        }
        staerkster = max(saison["index"], key=lambda x: x["index"])
        schwaechster = min(saison["index"], key=lambda x: x["index"])
        saison["staerkster"] = staerkster
        saison["schwaechster"] = schwaechster

    jahressummen = sorted(
        (m for m in uebern if m.endswith("|Summe")), key=lambda m: m[:4]
    )[-10:]
    jahresreihe = [
        {"jahr": int(m[:4]), "uebernachtungen": uebern[m]} for m in jahressummen
    ]

    return {
        "letzte_12_monate": fenster,
        "uebernachtungen_12m": summe_12m,
        "veraenderung_vorjahr_prozent": veraenderung,
        "gaeste_12m": gaeste_12m,
        "aufenthaltsdauer_naechte": dauer,
        "ausland_anteil_prozent": ausland_prozent,
        "saison": saison,
        "jahresreihe": jahresreihe,
        "rohdaten": ROHDATEN,
    }


HINWEISE = [
    "Die Zahlen erfassen **gewerbliche Beherbergungsbetriebe** — private "
    "Kurzzeitvermietung (Block 5d) kommt obendrauf.",
    "Die Werte gelten **stadtweit** und ändern sich nicht mit dem gewählten "
    "Punkt; sie beantworten die Frage nach dem Jahresverlauf, nicht die nach "
    "der Lage.",
    "Die Aufenthaltsdauer ist eine abgeleitete Zahl: Übernachtungen der "
    "letzten 12 Monate geteilt durch Gäste derselben Monate.",
    "Liegen Corona-Jahre (2020–2022) in der Saisonkurve, drücken Lockdown-"
    "Monate Winter und Frühjahr zusätzlich — die einbezogenen Jahre stehen "
    "deshalb direkt an der Kurve.",
]


async def load(
    out: Outbound,
    settings: Settings,
    lat: float,
    lon: float,
) -> SourceResult:
    started = time.perf_counter()
    sued, west, nord, ost = STADT_BBOX
    if not (sued <= lat <= nord and west <= lon <= ost):
        return SourceResult(
            name="tourismus",
            ok=True,
            data=None,
            warnings=[
                "Die Monatszahlen des Statistischen Amts gelten für die Stadt "
                "München. Für jeden anderen Kreis steht die Jahressumme der "
                "Übernachtungen im Kreisprofil (Block 3c) — Monatswerte je "
                "Kreis gibt es bundesweit nicht als offene Quelle "
                "(Regionaldatenbank: nur Jahressummen; Destatis: Abruf nur "
                "mit Kennung)."
            ],
        )
    try:
        csv_text = await out.get_text(
            "muenchen_tourismus",
            CSV_URL,
            timeout=60.0,
            limiter="muenchen",
            min_interval=1.0,
        )
    except SourceError as err:
        return SourceResult.failed(
            "tourismus", err, int((time.perf_counter() - started) * 1000)
        )

    try:
        data = auswerten(parse_monatszahlen(csv_text))
    except SourceError as err:
        return SourceResult.failed(
            "tourismus", err, int((time.perf_counter() - started) * 1000)
        )
    data["hinweise"] = HINWEISE

    letzter = data["letzte_12_monate"][-1]["monat"]
    return SourceResult(
        name="tourismus",
        ok=True,
        data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=[],
        provenance=Provenance(
            source="Monatszahlen Tourismus (Statistisches Amt München)",
            license=LIZENZ,
            endpoint=CSV_URL,
            stand=f"Monatsreihe ab 2006, jüngster gefüllter Monat {letzter}",
            retrieved_at=now_iso(),
            note=(
                "Stadtweite Werte der amtlichen Beherbergungsstatistik; "
                "die jüngsten Monate laufen der Veröffentlichung einige "
                "Wochen hinterher."
            ),
        ),
    )
