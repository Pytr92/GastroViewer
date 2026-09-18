"""Feiertage und Schulferien des Bundeslandes — als Kontext, nicht als Score.

Ein Standortwerkzeug bewertet Orte, keine Betriebstage: Feiertage sind für
alle Standorte eines Landes gleich und unterscheiden Marienplatz nicht von
Sendlinger Tor. Genau **eine** Sache ist standortrelevant, und nur im
Zusammenspiel mit anderen Blöcken: die **Lage und Länge der Sommerferien**.

In einem Universitätsviertel bricht das Geschäft in den Semester- und
Schulferien ein, in einer Tourismuslage ist es umgekehrt der Höhepunkt.
Wer den Tourismus-Jahresgang (Block 5e/5b) und die Studierendenzahl (3e)
danebenlegt, sieht, in welche Richtung es für den eigenen Standort geht.

Deshalb bewusst: ein **Kontextband**, keine Kennzahl, keine Verrechnung.
Die Ableitung „Ferien ⇒ mehr Umsatz" wäre standortabhängig und damit
erfunden.

Quelle ist die OpenHolidaysAPI (ODbL, offenes Datenrepository). Sie ist
gegen die amtlichen iCal-Dateien der Kultusministerkonferenz gegengeprüft
(Phase 0 2026-08-08, Baden-Württemberg 2026/27: identische Termine). Die
KMK selbst taugt nicht als Live-Quelle — ihre Download-Adressen tragen
einen wechselnden TYPO3-Hash, und Feiertage führt sie gar nicht.
"""

from __future__ import annotations

import re

import datetime as dt
from typing import Any

from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, now_iso

BASE = "https://openholidaysapi.org"
LIZENZ = ("Open Database License (ODbL) · OpenHolidaysAPI "
          "(openpotato/STÜBER SYSTEMS GmbH)")
AMTLICH = ("Ferientermine amtlich: Kultusministerkonferenz, "
           "https://www.kmk.org/service/ferienregelung/ferienkalender.html")

# Bundesland-Code aus den ersten beiden Stellen des Gemeindeschlüssels.
LAND_NACH_AGS = {
    "01": ("DE-SH", "Schleswig-Holstein"),
    "02": ("DE-HH", "Hamburg"),
    "03": ("DE-NI", "Niedersachsen"),
    "04": ("DE-HB", "Bremen"),
    "05": ("DE-NW", "Nordrhein-Westfalen"),
    "06": ("DE-HE", "Hessen"),
    "07": ("DE-RP", "Rheinland-Pfalz"),
    "08": ("DE-BW", "Baden-Württemberg"),
    "09": ("DE-BY", "Bayern"),
    "10": ("DE-SL", "Saarland"),
    "11": ("DE-BE", "Berlin"),
    "12": ("DE-BB", "Brandenburg"),
    "13": ("DE-MV", "Mecklenburg-Vorpommern"),
    "14": ("DE-SN", "Sachsen"),
    "15": ("DE-ST", "Sachsen-Anhalt"),
    "16": ("DE-TH", "Thüringen"),
}

HINWEISE = [
    "Örtliche Feiertage (etwa das Augsburger Friedensfest am 8. August) führt die Quelle beim Bundesland mit; sie zählen hier nicht als Landesfeiertag, sondern stehen gesondert unter feiertage_lokal.",
    "Feiertage und Ferien gelten für das **ganze Bundesland** — sie "
    "unterscheiden zwei Standorte derselben Stadt nicht. Der Block steht "
    "hier als Kontext, nicht als Bewertung, und fließt in keine Kennzahl.",
    "Aussagekräftig wird er erst im Zusammenspiel: Die **Sommerferien** "
    "neben dem Tourismus-Jahresgang und der Studierendenzahl zeigen, ob "
    "ein Standort in den Ferien leerläuft (Uni- und Bürolage) oder "
    "aufdreht (Tourismuslage).",
    "**Mariä Himmelfahrt** führt die Quelle pauschal für ganz Bayern; "
    "gesetzlicher Feiertag ist der Tag aber nur in den überwiegend "
    "katholischen Gemeinden (1 704 von 2 056).",
]


def land_aus_ags(ags: str | None) -> tuple[str, str] | None:
    ziffern = "".join(c for c in str(ags or "") if c.isdigit())
    return LAND_NACH_AGS.get(ziffern[:2])


# OpenHolidaysAPI führt Österreichs Länder mit eigenen Codes (Subdivisions:
# AT-WI für Wien), nicht mit ISO 3166-2 (AT-9). Nominatim liefert ISO —
# hier die Brücke. Live belegt am 18.09.2026 (fixtures/at).
OPENHOLIDAYS_CODE = {
    "AT-1": "AT-BL", "AT-2": "AT-KÄ", "AT-3": "AT-NÖ", "AT-4": "AT-OÖ",
    "AT-5": "AT-SB", "AT-6": "AT-SM", "AT-7": "AT-TI", "AT-8": "AT-VA",
    "AT-9": "AT-WI",
}

AT_HINWEISE = [
    "Feiertage und Ferien gelten für das **ganze Bundesland** — sie "
    "unterscheiden zwei Standorte derselben Stadt nicht. Der Block steht "
    "hier als Kontext, nicht als Bewertung, und fließt in keine Kennzahl.",
    "Landespatrone (Leopoldi in Wien und Niederösterreich, Josefi, Florian, "
    "Rupert, Martini) sind keine gesetzlichen Feiertage nach dem "
    "Arbeitsruhegesetz — schulfrei ja, Läden offen; die Quelle führt sie "
    "als regionale Termine.",
    "Die **Sommerferien** beginnen im Osten (Wien, Niederösterreich, "
    "Burgenland) eine Woche früher als im Westen; die Semesterferien im "
    "Februar sind je Land gestaffelt.",
]


def land_aus_kennung(kennung: str | None) -> tuple[str, str] | None:
    """Gemeindeschlüssel (DE) **oder** ISO-3166-2-Code (``DE-BY``, ``AT-9``)
    → (ISO-Code, Name). Der Punkt entscheidet, was er hat: in Deutschland
    liefert der Zensus den AGS, in Österreich Nominatim den ISO-Code."""
    from ..laender import land_aus_iso

    if not kennung:
        return None
    text = str(kennung).strip()
    if re.match(r"^[A-Za-z]{2}-", text):
        treffer = land_aus_iso(text)
        return (text.upper(), treffer[2]) if treffer else None
    return land_aus_ags(text)


def _name(eintrag: dict[str, Any]) -> str | None:
    for n in eintrag.get("name") or []:
        if n.get("text"):
            return n["text"]
    return None


def parse_feiertage(antwort: Any) -> list[dict[str, Any]]:
    tage = []
    for e in antwort or []:
        if not e.get("startDate"):
            continue
        eintrag = {
            "datum": e["startDate"],
            "name": _name(e),
            "bundesweit": bool(e.get("nationwide")),
        }
        # Die Quelle führt für Bayern auch das Augsburger Friedensfest mit
        # (regionalScope "Local", nur DE-BY-AU). Gesetzlicher Feiertag ist es
        # allein im Stadtgebiet Augsburg — als bayernweiter Tag gezählt wäre
        # es ein erfundener Ruhetag für den Rest des Landes.
        if e.get("regionalScope") == "Local":
            eintrag["lokal"] = True
            eintrag["gilt_in"] = [
                s.get("code") for s in (e.get("subdivisions") or []) if s.get("code")]
        tage.append(eintrag)
    return sorted(tage, key=lambda t: t["datum"])


def parse_ferien(antwort: Any) -> list[dict[str, Any]]:
    zeiten = []
    for e in antwort or []:
        von, bis = e.get("startDate"), e.get("endDate")
        if not von or not bis:
            continue
        try:
            tage = (dt.date.fromisoformat(bis)
                    - dt.date.fromisoformat(von)).days + 1
        except ValueError:
            tage = None
        zeiten.append({"von": von, "bis": bis, "name": _name(e), "tage": tage})
    return sorted(zeiten, key=lambda z: z["von"])


def auswerten(land: tuple[str, str], jahr: int,
              feiertage: list[dict[str, Any]],
              ferien: list[dict[str, Any]]) -> dict[str, Any]:
    sommer = max(
        (f for f in ferien if "Sommer" in (f["name"] or "")),
        key=lambda f: f["tage"] or 0, default=None)
    return {
        "bundesland": land[1],
        "code": land[0],
        "jahr": jahr,
        "feiertage_gesamt": sum(1 for t in feiertage if not t.get("lokal")),
        "feiertage_landesspezifisch": sum(
            1 for t in feiertage if not t["bundesweit"] and not t.get("lokal")),
        "feiertage_lokal": [t for t in feiertage if t.get("lokal")],
        "sommerferien": sommer,
        "ferien": ferien,
        "feiertage": feiertage,
        "hinweise": AT_HINWEISE if land[0].startswith("AT") else HINWEISE,
    }


async def load(out: Outbound, kennung: str | None, jahr: int) -> SourceResult:
    land = land_aus_kennung(kennung)
    if land is None:
        return SourceResult(
            name="kalender", ok=True, data=None,
            warnings=["Ohne Gemeindeschlüssel lässt sich kein Bundesland "
                      "und damit kein Feiertagskalender zuordnen."],
            provenance=Provenance(source="OpenHolidaysAPI", license=LIZENZ),
        )
    staat = land[0][:2]
    params = {
        "countryIsoCode": staat, "languageIsoCode": "DE",
        "subdivisionCode": OPENHOLIDAYS_CODE.get(land[0], land[0]),
        "validFrom": f"{jahr}-01-01", "validTo": f"{jahr}-12-31",
    }
    feiertage = parse_feiertage(await out.get_json(
        "kalender", f"{BASE}/PublicHolidays", params=params, timeout=30.0,
        limiter="kalender", min_interval=0.5))
    ferien = parse_ferien(await out.get_json(
        "kalender", f"{BASE}/SchoolHolidays", params=params, timeout=30.0,
        limiter="kalender", min_interval=0.5))

    warnungen: list[str] = []
    if not feiertage and not ferien:
        # HTTP 200 mit leerer Liste heißt „außerhalb des Datenbestands",
        # nicht „keine Feiertage" — der Unterschied ist wichtig.
        raise SourceError(
            "leer",
            f"Für {jahr} liegen in der Quelle keine Termine vor — der "
            "Datenbestand reicht derzeit bis etwa 2030.")
    if not ferien:
        warnungen.append(
            f"Für {jahr} sind keine Schulferien hinterlegt (der Bestand "
            "endet je nach Land unterschiedlich früh).")
    return SourceResult(
        name="kalender", ok=True,
        data=auswerten(land, jahr, feiertage, ferien),
        warnings=warnungen,
        provenance=Provenance(
            source=f"Feiertage und Schulferien {land[1]}",
            license=LIZENZ, endpoint=BASE, stand=str(jahr),
            retrieved_at=now_iso(), note=AMTLICH),
    )
