"""Planungsrecht und Hochwasserrisiko Österreich.

Gegenstück zu ``planung.py``: dieselbe Blockform (``hochwasser`` mit
``betroffen``, ``gebiete``, ``hq_haeufig``, ``hq_100``, ``hq_extrem``,
``dienst``; ``erhaltungssatzung`` mit ``betroffen``, ``gebiete``;
``portale``, ``hinweise``), damit Oberfläche und Bericht nichts
unterscheiden müssen.

**Hochwasser** kommt bundesweit vom INSPIRE-Dienst des BML (Betrieb LFRZ,
``https://inspire.lfrz.gv.at/000801/ows``). Live belegt am 18.09.2026
(fixtures/at, AT-Probe Runde 1–3):

* Die Layer heißen wie ihre Titel, mit Leerzeichen —
  ``Hochwasserueberflutungsflaechen HQ30`` / ``HQ100`` / ``HQ300``,
  ``Hochwasserrisikogebiete HQ100``, ``Rote Gefahrenzonen aus der
  Gefahrenzonenplanung``, ``Gelbe Gefahrenzonen …``. Die Kurznamen aus
  Runde 2 (``000801:UEFF_HQ100``) gaben ``LayerNotDefined``.
* GetFeatureInfo mit ``crs=CRS:84`` und ``info_format=application/json``
  antwortet mit einer GeoJSON-FeatureCollection; die Feature-``id`` trägt
  den Layernamen als Präfix (``Hochwasserrisikogebiete HQ100.3856``).
  Belegt am Kremser Donauufer: Risikogebiet ``Wachau`` (``SZENARIO``
  ``HQ100``, ``BUNDESLAND`` Niederösterreich, ``PROJEKTID`` NOE-Donau).
* An den sieben Probepunkten (Wien-Donau, Handelskai, Lobau,
  Stephansplatz, Linz, Krems, Graz) antworteten die Überflutungsflächen-
  und Gefahrenzonen-Layer leer — ein positiver Beleg für deren Feldnamen
  fehlt also; ausgewertet werden sie über ``SZENARIO`` bzw. das
  Layer-Präfix, mehr braucht der Block nicht.

Die HQ-Stufen entsprechen den deutschen: HQ30 ≙ HQhäufig, HQ100 ≙ HQ100,
HQ300 ≙ HQextrem. Rote Gefahrenzonen (Wildbach und Lawine, ständige
Gefährdung) zählen wie HQhäufig, gelbe wie HQ100. **Risikogebiete** sind
etwas anderes als Überflutungsflächen: die für das Hochwasserrisiko-
management ausgewiesenen Gebiete (HWRM-RL), oft ganze Talabschnitte —
der Block führt sie getrennt und sagt, dass das keine berechnete
Überflutung ist.

**Bebauungsplan** (Flächenwidmungs- und Bebauungsplan) ist Landesrecht;
offen und punktgenau gibt es ihn hier nur für Wien (``wien.py``) — und
zwar im Baurecht-Block, weil dort die Widmung samt Gastronomie-Einordnung
hingehört. **Schutzzonen** (§ 7 Bauordnung für Wien) sind das Gegenstück
zur Erhaltungssatzung und erscheinen unter demselben Schlüssel.
"""

from __future__ import annotations

import time
from typing import Any

from ..http import Outbound
from .base import Provenance, SourceError, SourceResult, now_iso
from . import wien as wien_mod

HOCHWASSER_URL = "https://inspire.lfrz.gv.at/000801/ows"
HOCHWASSER_LIZENZ = ("BML — Wasserinformationssystem Austria (WISA), INSPIRE-Dienst "
                     "Hochwasser (LFRZ); Creative Commons Namensnennung 4.0 (CC BY 4.0)")
BOX = 0.0004

# Layername → (Schlüssel im Block, Stufe, lesbarer Name)
HOCHWASSER_LAYER: dict[str, tuple[str, str]] = {
    "Hochwasserueberflutungsflaechen HQ30": ("hq_haeufig", "HQ30 (häufig)"),
    "Hochwasserueberflutungsflaechen HQ100": ("hq_100", "HQ100"),
    "Hochwasserueberflutungsflaechen HQ300": ("hq_extrem", "HQ300 (extrem)"),
    "Rote Gefahrenzonen aus der Gefahrenzonenplanung": ("hq_haeufig", "Rote Gefahrenzone"),
    "Gelbe Gefahrenzonen aus der Gefahrenzonenplanung": ("hq_100", "Gelbe Gefahrenzone"),
}
RISIKO_LAYER = "Hochwasserrisikogebiete HQ100"

HINWEISE = [
    "Die Überflutungsflächen sind Berechnungsergebnisse der Hochwasser-"
    "gefahrenkarten (HWRM-Richtlinie), keine Zusage. Für Versicherung und "
    "Ausbau zählt die Auskunft der Wasserrechtsbehörde (Bezirkshauptmannschaft "
    "bzw. Magistrat) oder des Landes.",
    "Ein **Risikogebiet** ist keine Überflutungsfläche: Es ist ein für das "
    "Risikomanagement ausgewiesener Abschnitt (oft ein ganzes Tal), in dem "
    "einzelne Grundstücke trocken liegen können — und umgekehrt.",
    "Bebauungsplan und Flächenwidmung sind in Österreich Landesrecht und "
    "liegen offen nur für Wien punktgenau vor (Block „Baurecht“). Anderswo "
    "gibt die Gemeinde Auskunft (Flächenwidmungsplan am Gemeindeamt).",
    "In einer **Schutzzone** (§ 7 Bauordnung für Wien) sind Abbruch, Umbau "
    "und Änderungen der Fassade bewilligungspflichtig und werden nach dem "
    "Stadtbild beurteilt — Außenwerbung, Schanigarten-Überdachung und "
    "Lüftungsführung eingeschlossen.",
]

PORTALE = [
    {"titel": "WISA — Hochwasserrisikokarten (BML)",
     "url": "https://maps.wisa.bml.gv.at/gefahren-und-risikokarten-zweiter-zyklus"},
    {"titel": "HORA — Naturgefahren-Karte Österreich",
     "url": "https://www.hora.gv.at/"},
    {"titel": "Flächenwidmungs- und Bebauungsplan Wien (Stadtplan)",
     "url": "https://www.wien.gv.at/flaechenwidmung/public/"},
]


def gfi_params(layers: list[str], lat: float, lon: float, box: float = BOX) -> dict[str, str]:
    """GetFeatureInfo mitten in einer kleinen Box, ``CRS:84`` (lon,lat)."""
    namen = ",".join(layers)
    return {
        "service": "WMS", "version": "1.3.0", "request": "GetFeatureInfo",
        "layers": namen, "query_layers": namen, "styles": "",
        "crs": "CRS:84",
        "bbox": f"{lon - box},{lat - box},{lon + box},{lat + box}",
        "width": "101", "height": "101", "i": "50", "j": "50",
        "info_format": "application/json", "feature_count": "10",
    }


def layer_aus_id(fid: Any) -> str | None:
    """``Hochwasserrisikogebiete HQ100.3856`` → Layername."""
    s = str(fid or "")
    return s.rsplit(".", 1)[0] if "." in s else None


def hochwasser_aufbereiten(payload: Any, *, layer: str | None = None) -> dict[str, Any]:
    """Treffer der Überflutungs- und Gefahrenzonen-Layer → Blockform.

    ``layer`` ist der gefragte Layer, wenn nur einer gefragt wurde; bei einer
    Sammelabfrage steht er im Präfix der Feature-``id``."""
    ergebnis: dict[str, Any] = {
        "betroffen": False, "gebiete": [], "risikogebiete": [],
        "hq_haeufig": False, "hq_100": False, "hq_extrem": False,
    }
    for f in (payload or {}).get("features") or [] if isinstance(payload, dict) else []:
        p = {k: v for k, v in (f.get("properties") or {}).items() if v not in (None, "")}
        name = layer_aus_id(f.get("id")) or layer
        eintrag = {
            "gewaesser": p.get("LABEL") or p.get("GEWAESSER") or p.get("PROJEKTID"),
            "jaehrlichkeit": None,
            "ermittelt": str(p.get("BEGINNLIFE") or "")[:10] or None,
            "amt": None,
            "bundesland": p.get("BUNDESLAND"),
            "zustaendig": p.get("ZUSTAENDIG"),
            "layer": name,
            "rohwerte": p,
        }
        if name == RISIKO_LAYER:
            eintrag["jaehrlichkeit"] = f"Risikogebiet {p.get('SZENARIO') or 'HQ100'}"
            ergebnis["risikogebiete"].append(eintrag)
            continue
        stufe = HOCHWASSER_LAYER.get(name or "")
        if stufe is None:
            # Unbekannter Layer: über das Szenario einordnen, sonst HQ100.
            sz = str(p.get("SZENARIO") or "").upper()
            schl = ("hq_haeufig" if "30" in sz else "hq_extrem" if "300" in sz else "hq_100")
            stufe = (schl, sz or (name or "Überflutungsfläche"))
        eintrag["jaehrlichkeit"] = stufe[1]
        ergebnis[stufe[0]] = True
        ergebnis["gebiete"].append(eintrag)
    ergebnis["betroffen"] = bool(ergebnis["gebiete"])
    reihe = {"hq_haeufig": 0, "hq_100": 1, "hq_extrem": 2}
    ergebnis["gebiete"].sort(
        key=lambda g: reihe.get(HOCHWASSER_LAYER.get(g["layer"] or "", ("hq_100",))[0], 1))
    return ergebnis


async def hochwasser(out: Outbound, lat: float, lon: float) -> dict[str, Any]:
    """Alle sechs Layer in einer GetFeatureInfo-Abfrage (GeoServer ordnet
    die Treffer über das id-Präfix dem Layer zu)."""
    payload = await out.get_json(
        "lfrz_hochwasser", HOCHWASSER_URL,
        params=gfi_params(list(HOCHWASSER_LAYER) + [RISIKO_LAYER], lat, lon),
        timeout=60.0, limiter="lfrz", min_interval=1.0,
    )
    daten = hochwasser_aufbereiten(payload)
    daten["dienst"] = "lfrz"
    daten["geprueft"] = "HQ30, HQ100, HQ300 sowie rote und gelbe Gefahrenzonen"
    return daten


TEXTE = {
    "hochwasser_leer": (
        "Keine Überflutungsfläche und keine Gefahrenzone am Punkt (geprüft für "
        "HQ30, HQ100, HQ300, rote und gelbe Gefahrenzonen). Das ist eine Aussage "
        "über die berechneten Flächen, keine Zusage."),
    "bebauungsplan_leer": (
        "Flächenwidmung und Bebauungsplan sind Landesrecht — für Wien steht die "
        "Widmung im Block „Baurecht“, anderswo gibt die Gemeinde Auskunft."),
    "erhaltungssatzung_titel": "Schutzzone (§ 7 Bauordnung für Wien)",
    "erhaltungssatzung_leer": "Der Punkt liegt in keiner Schutzzone.",
    "erhaltungssatzung_treffer": (
        "Abbruch, Umbau und Fassadenänderungen sind hier bewilligungspflichtig "
        "und werden nach dem Stadtbild beurteilt (§ 7 BO für Wien)."),
    "erhaltungssatzung_nicht_abgefragt": (
        "Schutzzonen sind hier nur für Wien eingebunden — außerhalb sagt der "
        "Block dazu nichts."),
}


async def load(out: Outbound, lat: float, lon: float) -> SourceResult:
    started = time.perf_counter()
    warnungen: list[str] = []
    data: dict[str, Any] = {"portale": PORTALE, "hinweise": HINWEISE, "land": "AT",
                            "texte": TEXTE}
    try:
        data["hochwasser"] = await hochwasser(out, lat, lon)
    except SourceError as err:
        return SourceResult.failed("planung", err, int((time.perf_counter() - started) * 1000))
    if data["hochwasser"]["risikogebiete"]:
        namen = ", ".join(str(g["gewaesser"] or "ohne Namen")
                          for g in data["hochwasser"]["risikogebiete"])
        warnungen.append(
            f"Der Punkt liegt im Hochwasser-Risikogebiet „{namen}“ (HWRM-Richtlinie) — "
            "ein Abschnitt mit ausgewiesenem Risiko, nicht zwingend eine berechnete "
            "Überflutungsfläche.")
    if wien_mod.in_wien(lat, lon):
        try:
            data["erhaltungssatzung"] = await wien_mod.schutzzonen(out, lat, lon)
        except SourceError as err:
            warnungen.append(f"Schutzzonen der Stadt Wien nicht abrufbar: {err.message}")
    else:
        warnungen.append(TEXTE["erhaltungssatzung_nicht_abgefragt"])
    return SourceResult(
        name="planung", ok=True, data=data,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnungen,
        provenance=Provenance(
            source=("Hochwassergefahren- und -risikokarten Österreich (BML/WISA, "
                    "INSPIRE-Dienst LFRZ)" + (" · Schutzzonen: Stadt Wien (WFS data.wien.gv.at)"
                                              if wien_mod.in_wien(lat, lon) else "")),
            license=HOCHWASSER_LIZENZ + (" · " + wien_mod.LIZENZ if wien_mod.in_wien(lat, lon)
                                         else ""),
            endpoint=HOCHWASSER_URL,
            retrieved_at=now_iso(),
            note=("Punktabfrage über GetFeatureInfo (CRS:84). HQ30 ≙ HQhäufig, "
                  "HQ300 ≙ HQextrem; rote Gefahrenzonen zählen wie HQ30, gelbe wie HQ100."),
        ),
    )


def baurecht_ohne_dienst(land_name: str = "Österreich") -> SourceResult:
    """Baurecht-Block außerhalb Wiens: ehrlich leer, in der Blockform von
    ``baurecht.py`` (``stufe`` ``kein_dienst``)."""
    from .baurecht import HINWEISE as BAURECHT_HINWEISE

    return SourceResult(
        name="baurecht", ok=True,
        data={"stufe": "kein_dienst", "gebiet": None, "baugebiete": [], "plaene": [],
              "sanierungsgebiete": [], "denkmale": [], "paragraf_34": False,
              "hinweise": BAURECHT_HINWEISE[:1] + [
                  "In Österreich ist die Flächenwidmung Landesrecht; offen und "
                  "punktgenau liegt sie nur für Wien vor (Widmungsklasse nach der "
                  "Bauordnung für Wien). Anderswo gibt die Gemeinde Auskunft."]},
        warnings=[f"Für diesen Ort in {land_name} gibt es keinen offenen "
                  "Flächenwidmungs-Dienst, den dieses Werkzeug auswerten kann — "
                  "eingebunden ist nur Wien."],
        provenance=Provenance(source="Bauleitplanung (kein offener Dienst)",
                              license="je Land verschieden", retrieved_at=now_iso()),
    )
