"""Amtliche Gastro-Anker aus der Regionaldatenbank Deutschland (GENESIS).

Zwei Tabellen der Statistischen Ämter, beide Kreisebene, beide am 2026-08-07
über den öffentlichen Werteabruf der Website Ende-zu-Ende verifiziert
(Struktur, Merkmalscodes und Sollwerte — München 2023: 4 019
Umsatzsteuerpflichtige im Gastgewerbe mit 6 584 298 Tsd. € steuerbarem
Umsatz; 2025: 15 350 Gewerbeanmeldungen, 10 245 Abmeldungen):

* ``73311-01-02-4`` — Umsatzsteuerpflichtige und steuerbarer Umsatz nach
  WZ-2008-Abschnitten, 2009–2023. Gastgewerbe = Abschnitt I. Daraus folgt
  der amtliche Anker „steuerbarer Umsatz je Umsatzsteuerpflichtigem" für
  die eigene Umsatzschätzung.
* ``52311-01-04-4`` — Gewerbean- und -abmeldungen (Jahressumme, alle
  Wirtschaftszweige — eine Branchen-Trennung gibt es auf Kreisebene nicht).

Warum Opt-in mit Konto: Der automatisierte Abruf läuft ausschließlich über
die GENESIS-REST-Schnittstelle (``/genesisws/rest/2020``), und die verlangt
eine — kostenlose — Kennung. Die ``robots.txt`` der Website untersagt
automatisierte Zugriffe auf die Weboberfläche komplett (``Disallow: /``),
deshalb wird der anonyme Browser-Werteabruf hier bewusst **nicht**
nachgebaut. Ohne hinterlegte Kennung bleibt der Block leer und erklärt den
Weg; das Grundprinzip „keine Konten" gilt weiter für alle anderen Quellen.

Zugangsdaten: Umgebungsvariablen ``GASTROVIEWER_GENESIS_KENNUNG`` /
``GASTROVIEWER_GENESIS_PASSWORT`` oder die Datei ``genesis-zugang.json`` im
Datenverzeichnis (legt die Oberfläche an; nur lokal, Dateirechte 0600).
Die Kennung wandert in HTTP-Header und POST-Body — nie in eine URL, damit
sie in keinem Protokoll auftaucht (das Outbound-Log speichert nur URLs).

Format der Antwort (GENESIS V5, live geprüft): ``ffcsv`` — Semikolon-CSV im
englischen Langformat, eine Zeile je Wert, Spalten u. a. ``time``,
``1_variable_code``/``…_attribute_code`` (Region), ``2_…`` (WZ bzw.
An-/Abmeldegrund), ``value``, ``value_variable_code``.
"""

from __future__ import annotations

import csv
import io
import json
import os
import time
from typing import Any

from ..config import Settings
from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, now_iso

REST_BASE = "https://www.regionalstatistik.de/genesisws/rest/2020"
TAB_UMSATZ = "73311-01-02-4"
TAB_GEWERBE = "52311-01-04-4"

# Gemeindeebene — Phase-0 am 2026-08-07 über den öffentlichen Werteabruf
# verifiziert (Struktur, Codes und Sollwerte; Fixtures unter
# ``fixtures/raw_genesis_gemeinde_ffcsv.json``):
#
# * ``13111-01-03-5`` — SV-Beschäftigte am **Arbeitsort**, Stichtag 30.06.
#   (Zeitcode STAG, Wertcode ERW032). Der Tagesbevölkerungs-Indikator, den
#   es unterhalb der Kreisebene sonst nirgends offen gibt: München
#   976 230 (30.06.2025), Garching b.München 32 823.
# * ``45412-01-03-5`` — Tourismus-Jahressumme der Gemeinde (GAST01
#   Ankünfte, GAST02 Übernachtungen, GAST04 geöffnete Betriebe, GAST05
#   Schlafgelegenheiten). München 2024: 19 712 703 Übernachtungen.
# * ``13211-01-03-5`` — Arbeitslose im Jahresdurchschnitt (ERWP06).
#   Garching 2025: 347.
#
# Befund zur Klassifikation: **Kreisfreie Städte führen im
# Gemeinde-Merkmal (GEMEIN) keinen eigenen Knoten** — sie kommen als
# KREISE-Zeilen mit dem 5-stelligen Schlüssel zurück (im Werteabruf
# nachgeprüft, Wildcard ``09162*`` liefert nur den Kreisknoten). Der
# Abruf versucht deshalb je nach Schlüssel GEMEIN (AGS8) und fällt auf
# KREISE (AGS5) zurück; beide Zeilenformen stehen in den Fixtures.
TAB_BESCHAEFTIGTE = "13111-01-03-5"
TAB_TOURISMUS_GEMEINDE = "45412-01-03-5"
TAB_ARBEITSLOSE_GEMEINDE = "13211-01-03-5"
# Bautätigkeit (Z-Runde, Phase-0 am 2026-08-08 über den öffentlichen
# Werteabruf aufgezeichnet): je Gemeinde und Jahr die Wohngebäude
# (BAUGEB01 inkl. Wohnheime) mit Gebäuden (BAU015), Wohnungen (WOHN01)
# und Wohnfläche (FLC001, 1000 qm); Untergliederung nach Wohnungszahl
# (WHGZHL…) wird ignoriert — es zählt die Insgesamt-Zeile.
# München 2024: 7 118 genehmigte, 5 915 fertiggestellte Wohnungen.
TAB_BAUGENEHMIGUNGEN = "31111-01-02-5"
TAB_BAUFERTIGSTELLUNGEN = "31121-01-02-5"

LIZENZ = (
    "Datenlizenz Deutschland Namensnennung 2.0 (dl-de/by-2-0) · "
    "Statistische Ämter des Bundes und der Länder (Regionaldatenbank)"
)
REGISTRIERUNG = (
    "https://www.regionalstatistik.de/genesis/online?Menu=Registrierung"
)

# Ab hier beginnt die WZ-2008-Zeitreihe der Umsatzsteuertabelle.
START_JAHR = 2009

OPT_IN_HINWEIS = (
    "Dieser Block ist ein Opt-in: Er braucht eine kostenlose Kennung bei "
    "regionalstatistik.de (Regionaldatenbank der Statistischen Ämter). "
    "Ohne Kennung bleibt er leer — alle anderen Blöcke funktionieren "
    "weiterhin ohne Konto."
)


# ------------------------------------------------------------- Zugang

def _zugang_datei(settings: Settings):
    return settings.data_dir / "genesis-zugang.json"


def lade_zugang(settings: Settings) -> dict[str, str] | None:
    """Kennung/Passwort aus Umgebung oder lokaler Datei. Umgebung gewinnt."""
    kennung = os.environ.get("GASTROVIEWER_GENESIS_KENNUNG")
    passwort = os.environ.get("GASTROVIEWER_GENESIS_PASSWORT")
    if kennung and passwort:
        return {"kennung": kennung, "passwort": passwort, "quelle": "umgebung"}
    pfad = _zugang_datei(settings)
    if pfad.exists():
        try:
            roh = json.loads(pfad.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None
        if roh.get("kennung") and roh.get("passwort"):
            return {
                "kennung": str(roh["kennung"]),
                "passwort": str(roh["passwort"]),
                "quelle": "datei",
            }
    return None


def speichere_zugang(settings: Settings, kennung: str, passwort: str) -> None:
    pfad = _zugang_datei(settings)
    pfad.write_text(
        json.dumps({"kennung": kennung, "passwort": passwort}),
        encoding="utf-8",
    )
    try:
        os.chmod(pfad, 0o600)
    except OSError:
        pass  # z. B. Windows — dort gibt es keine POSIX-Rechte


def loesche_zugang(settings: Settings) -> bool:
    pfad = _zugang_datei(settings)
    if pfad.exists():
        pfad.unlink()
        return True
    return False


def _auth(zugang: dict[str, str]) -> dict[str, str]:
    # Header, nicht URL-Parameter — die URL landet im Outbound-Protokoll.
    return {"username": zugang["kennung"], "password": zugang["passwort"]}


async def logincheck(
    out: Outbound, zugang: dict[str, str]
) -> tuple[bool, str]:
    """Prüft die Kennung beim Dienst. Live verifiziert: gültige Kennungen
    antworten „…erfolgreich an- und abgemeldet…", falsche mit einer
    Fehlermeldung — jeweils HTTP 200."""
    text = await out.post_text(
        "genesis",
        f"{REST_BASE}/helloworld/logincheck",
        headers=_auth(zugang),
        data={"language": "de"},
        timeout=30.0,
        limiter="genesis",
        min_interval=1.0,
    )
    try:
        payload = json.loads(text)
    except ValueError:
        return False, f"Unerwartete Antwort des Dienstes: {text[:200]}"
    status = str(payload.get("Status") or "")
    return "erfolgreich" in status.lower(), status


# --------------------------------------------------------------- ffcsv

PFLICHT_SPALTEN = {
    "time", "1_variable_code", "1_variable_attribute_code",
    "value", "value_variable_code",
}


def parse_ffcsv(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    felder = set(reader.fieldnames or [])
    if not PFLICHT_SPALTEN <= felder:
        raise SourceError(
            "parse",
            "GENESIS-ffcsv hat unerwartete Spalten — Format geändert? "
            f"Kopfzeile: {';'.join(sorted(felder))[:200]}",
        )
    return list(reader)


def _zahl(v: Any) -> float | int | None:
    """GENESIS-Qualitätszeichen („-" nichts vorhanden, „." unbekannt, „x"
    nicht sinnvoll, „…" fällt später an, „/" nicht sicher genug) → None."""
    s = str(v or "").strip()
    if s in ("", "-", ".", "...", "…", "x", "/"):
        return None
    try:
        zahl = float(s.replace(",", "."))
    except ValueError:
        return None
    return int(zahl) if zahl == int(zahl) else zahl


def _kreis_zeilen(
    rows: list[dict[str, str]], ags5: str
) -> tuple[list[dict[str, str]], str | None]:
    treffer = [
        r for r in rows
        if r.get("1_variable_code") == "KREISE"
        and r.get("1_variable_attribute_code") == ags5
    ]
    name = treffer[0].get("1_variable_attribute_label") if treffer else None
    return treffer, name


def umsatz_auswerten(rows: list[dict[str, str]], ags5: str) -> dict[str, Any]:
    """Tabelle 73311-01-02-4: je Jahr Umsatzsteuerpflichtige (STR007) und
    steuerbarer Umsatz in Tsd. € (UMS031) für das Gastgewerbe (WZ08-I),
    dazu der Gesamtumsatz aller Abschnitte (WZ08-A-S) für die Anteilszahl."""
    zeilen, name = _kreis_zeilen(rows, ags5)
    je_jahr: dict[int, dict[str, Any]] = {}
    for r in zeilen:
        if not str(r.get("time") or "").isdigit():
            continue
        jahr = int(r["time"])
        wz = r.get("2_variable_attribute_code")
        wert = _zahl(r.get("value"))
        code = r.get("value_variable_code")
        slot = je_jahr.setdefault(jahr, {})
        if wz == "WZ08-I":
            if code == "STR007":
                slot["pflichtige"] = wert
            elif code == "UMS031":
                slot["umsatz_tsd"] = wert
        elif wz == "WZ08-A-S" and code == "UMS031":
            slot["umsatz_alle_tsd"] = wert

    reihe: list[dict[str, Any]] = []
    for jahr in sorted(je_jahr):
        s = je_jahr[jahr]
        p, u = s.get("pflichtige"), s.get("umsatz_tsd")
        reihe.append({
            "jahr": jahr,
            "pflichtige": p,
            "umsatz_tsd_eur": u,
            # Berechnet aus zwei amtlichen Größen — Division, kein gewählter
            # Faktor.
            "je_pflichtigem_eur": round(u * 1000 / p) if p and u else None,
        })
    aktuell = next(
        (r for r in reversed(reihe) if r["je_pflichtigem_eur"] is not None),
        None,
    )
    anteil = None
    if aktuell:
        alle = je_jahr.get(aktuell["jahr"], {}).get("umsatz_alle_tsd")
        if alle and aktuell["umsatz_tsd_eur"]:
            anteil = round(aktuell["umsatz_tsd_eur"] / alle * 100, 1)
    return {
        "kreis_name": name,
        "aktuell": aktuell,
        "anteil_am_gesamtumsatz_prozent": anteil,
        "reihe": reihe[-10:],
    }


# ------------------------------------------------- Gemeinde-Tabellen

def _jahr(zeit: str) -> int | None:
    """GENESIS-Zeitangabe → Jahr. JAHR-Tabellen liefern „2024",
    STAG-Tabellen (Stichtag) „2025-06-30"."""
    s = str(zeit or "")[:4]
    return int(s) if s.isdigit() else None


def _gemeinde_zeilen(
    rows: list[dict[str, str]], ags8: str
) -> tuple[list[dict[str, str]], str | None, str | None]:
    """Zeilen des Gemeindeknotens. Echte Gemeinden kommen als
    GEMEIN-Zeilen mit AGS8, kreisfreie Städte nur als KREISE-Zeilen mit
    dem 5-stelligen Schlüssel (sie haben keinen eigenen Gemeindeknoten —
    Phase-0-Befund). GEMEIN gewinnt, damit der gleichzeitig enthaltene
    Landkreis nie mit der Gemeinde verwechselt wird."""
    gem = [r for r in rows
           if r.get("1_variable_code") == "GEMEIN"
           and r.get("1_variable_attribute_code") == ags8]
    if gem:
        return gem, gem[0].get("1_variable_attribute_label"), "Gemeinde"
    kreis = [r for r in rows
             if r.get("1_variable_code") == "KREISE"
             and r.get("1_variable_attribute_code") == ags8[:5]]
    if kreis:
        return (kreis, kreis[0].get("1_variable_attribute_label"),
                "kreisfreie Stadt")
    return [], None, None


def _insgesamt(r: dict[str, str]) -> bool:
    """Nur Insgesamt-Zeilen: alle Untergliederungs-Attribute leer
    (ffcsv führt z. B. NAT/GES oder Personengruppen als 2_/3_-Spalten)."""
    return not (r.get("2_variable_attribute_code")
                or r.get("3_variable_attribute_code"))


def _reihe_aufbauen(
    je_jahr: dict[int, dict[str, Any]], feld: str
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    reihe = [{"jahr": j, **je_jahr[j]} for j in sorted(je_jahr)]
    aktuell = next(
        (r for r in reversed(reihe) if r.get(feld) is not None), None)
    return reihe, aktuell


def beschaeftigte_auswerten(
    rows: list[dict[str, str]], ags8: str
) -> dict[str, Any]:
    """Tabelle 13111-01-03-5: SV-Beschäftigte am Arbeitsort je Stichtag
    30.06. — der Tagesbevölkerungs-Indikator der Gemeinde."""
    zeilen, name, ebene = _gemeinde_zeilen(rows, ags8)
    je_jahr: dict[int, dict[str, Any]] = {}
    for r in zeilen:
        jahr = _jahr(r.get("time"))
        if jahr is None or r.get("value_variable_code") != "ERW032":
            continue
        if not _insgesamt(r):
            continue
        je_jahr[jahr] = {"beschaeftigte": _zahl(r.get("value"))}
    reihe, aktuell = _reihe_aufbauen(je_jahr, "beschaeftigte")
    veraenderung = None
    if aktuell:
        frueher = next(
            (r for r in reihe
             if r["jahr"] == aktuell["jahr"] - 5
             and r.get("beschaeftigte")), None)
        if frueher and aktuell["beschaeftigte"]:
            veraenderung = round(
                (aktuell["beschaeftigte"] / frueher["beschaeftigte"] - 1)
                * 100, 1)
    return {"name": name, "ebene": ebene, "aktuell": aktuell,
            "veraenderung_5j_prozent": veraenderung, "reihe": reihe[-10:]}


_TOURISMUS_FELDER = {
    "GAST01": "ankuenfte",
    "GAST02": "uebernachtungen",
    "GAST04": "betriebe",
    "GAST05": "schlafgelegenheiten",
}


def tourismus_gemeinde_auswerten(
    rows: list[dict[str, str]], ags8: str
) -> dict[str, Any]:
    """Tabelle 45412-01-03-5: Tourismus-Jahressumme der Gemeinde."""
    zeilen, name, ebene = _gemeinde_zeilen(rows, ags8)
    je_jahr: dict[int, dict[str, Any]] = {}
    for r in zeilen:
        jahr = _jahr(r.get("time"))
        feld = _TOURISMUS_FELDER.get(r.get("value_variable_code") or "")
        if jahr is None or feld is None or not _insgesamt(r):
            continue
        je_jahr.setdefault(jahr, {})[feld] = _zahl(r.get("value"))
    reihe, aktuell = _reihe_aufbauen(je_jahr, "uebernachtungen")
    return {"name": name, "ebene": ebene, "aktuell": aktuell,
            "reihe": reihe[-10:]}


def arbeitslose_auswerten(
    rows: list[dict[str, str]], ags8: str
) -> dict[str, Any]:
    """Tabelle 13211-01-03-5: Arbeitslose im Jahresdurchschnitt."""
    zeilen, name, ebene = _gemeinde_zeilen(rows, ags8)
    je_jahr: dict[int, dict[str, Any]] = {}
    for r in zeilen:
        jahr = _jahr(r.get("time"))
        if jahr is None or r.get("value_variable_code") != "ERWP06":
            continue
        if not _insgesamt(r):
            continue
        je_jahr[jahr] = {"arbeitslose": _zahl(r.get("value"))}
    reihe, aktuell = _reihe_aufbauen(je_jahr, "arbeitslose")
    return {"name": name, "ebene": ebene, "aktuell": aktuell,
            "reihe": reihe[-10:]}


_BAU_FELDER = {
    "WOHN01": "wohnungen",
    "BAU015": "gebaeude",
    "FLC001": "wohnflaeche_1000qm",
}


def bau_auswerten(rows: list[dict[str, str]], ags8: str) -> dict[str, Any]:
    """Tabellen 31111-01-02-5 / 31121-01-02-5: Wohnungsbau der Gemeinde.

    Anders als bei den übrigen Gemeindetabellen ist die Insgesamt-Zeile
    hier nicht die mit leeren Untergliederungen: das 2er-Merkmal trägt
    immer die Gebäudeart (BAUGEB01 = Wohngebäude inkl. Wohnheime), erst
    das 3er-Merkmal (Wohnungszahl-Klassen) muss leer sein."""
    zeilen, name, ebene = _gemeinde_zeilen(rows, ags8)
    je_jahr: dict[int, dict[str, Any]] = {}
    for r in zeilen:
        jahr = _jahr(r.get("time"))
        feld = _BAU_FELDER.get(r.get("value_variable_code") or "")
        if jahr is None or feld is None:
            continue
        if (r.get("2_variable_attribute_code") != "BAUGEB01"
                or r.get("3_variable_attribute_code")):
            continue
        je_jahr.setdefault(jahr, {})[feld] = _zahl(r.get("value"))
    reihe, aktuell = _reihe_aufbauen(je_jahr, "wohnungen")
    return {"name": name, "ebene": ebene, "aktuell": aktuell,
            "reihe": reihe[-10:]}


# Attribut-Codes der Gewerbeanzeigentabelle (live aus dem ffcsv abgelesen).
_GEWERBE_FELDER = {
    ("GEW011", None): "anmeldungen",
    ("GEW011", "GEWM0"): "neuerrichtungen",
    ("GEW011", "GEWM3"): "betriebsgruendungen",
    ("GEW013", None): "abmeldungen",
    ("GEW013", "GEWM6"): "aufgaben",
    ("GEW013", "GEWM9"): "betriebsaufgaben",
}


def gewerbe_auswerten(rows: list[dict[str, str]], ags5: str) -> dict[str, Any]:
    """Tabelle 52311-01-04-4: An-/Abmeldungen je Jahr, darunter
    Neuerrichtungen bzw. Aufgaben. Zeilen ohne ``2_variable_attribute_code``
    sind die Insgesamt-Werte."""
    zeilen, name = _kreis_zeilen(rows, ags5)
    je_jahr: dict[int, dict[str, Any]] = {}
    for r in zeilen:
        if not str(r.get("time") or "").isdigit():
            continue
        jahr = int(r["time"])
        code = r.get("value_variable_code")
        grund = r.get("2_variable_attribute_code") or None
        feld = _GEWERBE_FELDER.get((code, grund))
        if feld is None:
            continue
        je_jahr.setdefault(jahr, {})[feld] = _zahl(r.get("value"))

    reihe: list[dict[str, Any]] = []
    for jahr in sorted(je_jahr):
        s = je_jahr[jahr]
        an, ab = s.get("anmeldungen"), s.get("abmeldungen")
        reihe.append({
            "jahr": jahr,
            **s,
            "saldo": (an - ab) if an is not None and ab is not None else None,
        })
    aktuell = next(
        (r for r in reversed(reihe) if r.get("anmeldungen") is not None),
        None,
    )
    return {"kreis_name": name, "aktuell": aktuell, "reihe": reihe[-10:]}


# ---------------------------------------------------------------- Abruf

async def _tabelle(
    out: Outbound, zugang: dict[str, str], name: str, ags5: str,
    regionalvariable: str = "KREISE",
) -> tuple[str, str | None]:
    """Eine Tabelle als ffcsv-Text. Die REST-Antwort ist JSON mit dem CSV in
    ``Object.Content``; einzelne GENESIS-Stände liefern das CSV auch direkt —
    beide Formen werden angenommen, alles andere scheitert mit Begründung."""
    text = await out.post_text(
        "genesis",
        f"{REST_BASE}/data/table",
        headers=_auth(zugang),
        data={
            "name": name,
            "area": "all",
            # Merkmalscode aus dem Tabellenaufbau (öffentlich einsehbar):
            # KREISE = Kreisfreie Städte und Kreise, GEMEIN = Gemeinden.
            "regionalvariable": regionalvariable,
            "regionalkey": ags5,
            "startyear": str(START_JAHR),
            "format": "ffcsv",
            "language": "de",
            "compress": "false",
        },
        timeout=90.0,
        limiter="genesis",
        min_interval=1.0,
    )
    t = text.lstrip()
    if not t.startswith("{"):
        return t, None
    try:
        payload = json.loads(t)
    except ValueError as exc:
        raise SourceError(
            "parse", f"GENESIS-Antwort weder JSON noch CSV: {t[:200]}"
        ) from exc
    status = payload.get("Status") or {}
    inhalt = ((payload.get("Object") or {}).get("Content")) or ""
    if not inhalt:
        raise SourceError(
            "api_error",
            "GENESIS lieferte keinen Tabelleninhalt: "
            + str(status.get("Content") or status or "unbekannter Grund")[:300],
        )
    code = status.get("Code")
    warnung = (
        str(status.get("Content"))[:200]
        if isinstance(code, int) and code != 0 else None
    )
    return inhalt, warnung


HINWEISE = [
    "Die Umsatzsteuerstatistik zählt nur Steuerpflichtige über 22 000 € "
    "Jahresumsatz — und zwar am **Unternehmenssitz**: Ketten und "
    "Hotelgesellschaften mit Sitz im Kreis heben den Durchschnitt kräftig. "
    "Der typische einzelne Betrieb liegt unter diesem Mittelwert.",
    "„Gastgewerbe“ (WZ-Abschnitt I) umfasst Beherbergung **und** "
    "Gastronomie — eine feinere Trennung (nur WZ 56 Gastronomie) gibt es "
    "auf Kreisebene nicht.",
    "Die Gewerbeanzeigen zählen **alle Wirtschaftszweige**, nicht nur "
    "Gastronomie — auf Kreisebene ohne Branchen-Aufteilung. Als Maß für "
    "die Gründungsdynamik des Kreises, nicht der Branche.",
]

GEMEINDE_HINWEISE = [
    "**Beschäftigte am Arbeitsort** ist der Tagesbevölkerungs-Indikator "
    "fürs Mittagsgeschäft: Wer hier arbeitet, isst hier zu Mittag — "
    "unabhängig davon, wo er wohnt. Stichtag jeweils 30.06.; feiner als "
    "die Gemeinde wird der Wert aus Datenschutzgründen nirgends "
    "veröffentlicht.",
    "Bei **kreisfreien Städten** ist die Gemeinde flächengleich mit dem "
    "Kreis — die Gemeindewerte sind dann Stadtwerte und bringen gegenüber "
    "dem Kreisprofil keine feinere Auflösung. Ihren Wert entfalten sie im "
    "Umland: Garching, Erding oder Freising bekommen eigene Zahlen statt "
    "des Landkreis-Durchschnitts.",
    "Die **Bau-Pipeline** (genehmigte minus fertiggestellte Wohnungen) "
    "zeigt kommende Nachfrage: Was heute genehmigt ist, sind in zwei bis "
    "drei Jahren Bewohner. Gezählt werden Wohnungen in Wohngebäuden "
    "(inkl. Wohnheimen) — der Zensus-Neubauhinweis ist dagegen auf 2022 "
    "eingefroren.",
]


GEMEINDE_TABELLEN = (
    ("beschaeftigte", TAB_BESCHAEFTIGTE, beschaeftigte_auswerten),
    ("tourismus", TAB_TOURISMUS_GEMEINDE, tourismus_gemeinde_auswerten),
    ("arbeitslose", TAB_ARBEITSLOSE_GEMEINDE, arbeitslose_auswerten),
    ("baugenehmigungen", TAB_BAUGENEHMIGUNGEN, bau_auswerten),
    ("baufertigstellungen", TAB_BAUFERTIGSTELLUNGEN, bau_auswerten),
)


async def _gemeinde_laden(
    out: Outbound, zugang: dict[str, str], ags8: str,
    warnungen: list[str],
) -> dict[str, Any] | None:
    """Die drei Gemeindetabellen. Kreisfreie Städte (AGS endet auf 000)
    haben keinen Gemeindeknoten und werden direkt über KREISE abgerufen;
    für alle anderen gilt GEMEIN mit KREISE-Rückfall, falls ein Stand der
    Klassifikation den Schlüssel nicht kennt."""
    kreisfrei = ags8.endswith("000")
    versuche = (
        [("KREISE", ags8[:5])] if kreisfrei
        else [("GEMEIN", ags8), ("KREISE", ags8[:5])]
    )
    ergebnis: dict[str, Any] = {
        "ags": ags8, "name": None, "ebene": None,
        "beschaeftigte": None, "tourismus": None, "arbeitslose": None,
        "baugenehmigungen": None, "baufertigstellungen": None,
        "hinweise": GEMEINDE_HINWEISE,
    }
    geliefert = False
    for schluessel, tabelle, auswerten_fn in GEMEINDE_TABELLEN:
        for variable, key in versuche:
            try:
                text, warnung = await _tabelle(
                    out, zugang, tabelle, key, regionalvariable=variable)
            except SourceError as err:
                warnungen.append(f"Tabelle {tabelle} ({variable}): "
                                 f"{err.message}")
                continue
            if warnung:
                warnungen.append(f"Tabelle {tabelle}: {warnung}")
            try:
                teil = auswerten_fn(parse_ffcsv(text), ags8)
            except SourceError as err:
                warnungen.append(f"Tabelle {tabelle}: {err.message}")
                break
            if teil.get("reihe"):
                ergebnis[schluessel] = teil
                ergebnis["name"] = ergebnis["name"] or teil.get("name")
                ergebnis["ebene"] = ergebnis["ebene"] or teil.get("ebene")
                geliefert = True
                break
    return ergebnis if geliefert else None


async def load(
    out: Outbound, settings: Settings, ags: str
) -> SourceResult:
    """Blockergebnis für den Kreis. Ohne Kennung: leer mit Erklärung, ohne
    dass eine Anfrage hinausgeht."""
    started = time.perf_counter()
    ags5 = "".join(c for c in str(ags) if c.isdigit())[:5]
    zugang = lade_zugang(settings)
    if zugang is None:
        return SourceResult(
            name="genesis",
            ok=True,
            data=None,
            warnings=[OPT_IN_HINWEIS],
        )
    if len(ags5) < 5:
        return SourceResult(
            name="genesis", ok=True, data=None,
            warnings=["Ohne Kreisschlüssel lässt sich kein Kreiswert abrufen."],
        )

    ags8 = "".join(c for c in str(ags) if c.isdigit())[:8]
    warnungen: list[str] = []
    daten: dict[str, Any] = {
        "ags": ags5,
        "kreis": None,
        "umsatz": None,
        "gewerbe": None,
        "gemeinde": None,
        "hinweise": HINWEISE,
    }
    fehler: SourceError | None = None
    for schluessel, tabelle, auswerten_fn in (
        ("umsatz", TAB_UMSATZ, umsatz_auswerten),
        ("gewerbe", TAB_GEWERBE, gewerbe_auswerten),
    ):
        try:
            text, warnung = await _tabelle(out, zugang, tabelle, ags5)
            if warnung:
                warnungen.append(f"Tabelle {tabelle}: {warnung}")
            ergebnis = auswerten_fn(parse_ffcsv(text), ags5)
            daten[schluessel] = ergebnis
            if daten["kreis"] is None:
                daten["kreis"] = ergebnis.get("kreis_name")
        except SourceError as err:
            fehler = err
            warnungen.append(f"Tabelle {tabelle}: {err.message}")

    if len(ags8) == 8:
        daten["gemeinde"] = await _gemeinde_laden(
            out, zugang, ags8, warnungen)

    if (daten["umsatz"] is None and daten["gewerbe"] is None
            and daten["gemeinde"] is None):
        return SourceResult.failed(
            "genesis",
            fehler or SourceError("api_error", "Keine der Tabellen lieferbar."),
            int((time.perf_counter() - started) * 1000),
        )
    return SourceResult(
        name="genesis",
        ok=True,
        data=daten,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnungen,
        provenance=Provenance(
            source=(
                "Regionaldatenbank Deutschland (GENESIS): Umsatzsteuerstatistik "
                f"{TAB_UMSATZ}, Gewerbeanzeigen {TAB_GEWERBE}; Gemeindeebene: "
                f"SV-Beschäftigte am Arbeitsort {TAB_BESCHAEFTIGTE}, "
                f"Tourismus {TAB_TOURISMUS_GEMEINDE}, "
                f"Arbeitslose {TAB_ARBEITSLOSE_GEMEINDE}, "
                f"Baugenehmigungen {TAB_BAUGENEHMIGUNGEN}, "
                f"Baufertigstellungen {TAB_BAUFERTIGSTELLUNGEN}"
            ),
            license=LIZENZ,
            endpoint=f"{REST_BASE}/data/table",
            stand="jährliche Fortschreibung; Jahre siehe Reihen im Block",
            retrieved_at=now_iso(),
            note=(
                "Abruf mit hinterlegter (kostenloser) Kennung — Opt-in. "
                "Kreis- und Gemeindewerte, kein Punktbezug."
            ),
        ),
    )
