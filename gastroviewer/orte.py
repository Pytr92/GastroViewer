"""Registry der Städte und Regionen mit eigenen Punktdiensten.

Bis 0.6.0 stand die Ortsweiche als ``if``-Kette in sieben Methoden von
``service.py``: fünfundzwanzig Zweige der Form „liegt der Punkt in X,
dann lade Y und cache es unter Z“. Jede neue Stadt bedeutete einen
weiteren Zweig an mehreren Stellen, und welche Stadt welchen Block
bedient, ließ sich nur durch Lesen der ganzen Datei beantworten.

Hier steht dieselbe Auskunft einmal als Tabelle: je Ort ein Kasten und
je Block eine Quelle mit Cache-Namen und Lader. ``service.py`` fragt die
Tabelle, die Methoden behalten nur noch ihre Auffangquelle (München,
BASt, der Bundesdienst).

Zwei Dinge, die die ``if``-Kette nicht konnte und diese Tabelle regelt:

* **Das Land entscheidet mit.** Der Salzburger Stadtkasten reicht über
  die Grenze bis Freilassing, der bayerische Kasten über halb
  Oberösterreich. Vorher hätte ein Freilassinger Punkt den Salzburger
  WFS gefragt. Jede Quelle nennt ihr Land; der Service kennt das Land
  des Punktes ohnehin (``service.land``) und gibt es mit.
* **Die Reihenfolge ist sichtbar.** Stuttgart steht vor
  Baden-Württemberg, weil der Stadtdienst feiner ist als die
  Landesdatei. In der Kette war das eine Zeilenreihenfolge, hier ist es
  die Listenreihenfolge mit Begründung daneben.

Die Lader bekommen den Service übergeben: Sie brauchen ``outbound``,
``settings`` und die stadtweit einmal gecachten Landesdateien (etwa die
5-MB-Monatsdatei der Wiener Dauerzählstellen), die als Methoden dort
liegen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .sources import berlin as berlin_mod
from .sources import hamburg as hamburg_mod
from .sources import mobidata_bw as mobidata_mod
from .sources import salzburg as salzburg_mod
from .sources import wien as wien_mod
from .sources import wien_profil as wien_profil_mod
from .sources import wien_verkehr as wien_verkehr_mod
from .sources import bayern

# Der Lader bekommt (service, lat, lon, radius, refresh, adresse) und gibt
# ein SourceResult zurück. ``adresse`` ist nur für die Blöcke gesetzt, die
# sie brauchen (Viertel-Steckbrief).
Lader = Callable[[Any, float, float, int, bool, dict[str, Any] | None], Awaitable[Any]]


@dataclass(frozen=True)
class Quelle:
    """Ein Block, den dieser Ort bedient."""

    cache: str
    laden: Lader
    #: Blöcke ohne Umkreis (Steckbrief, Luft) bekommen den Radius nicht in
    #: den Cache-Schlüssel — sonst läge derselbe Wert unter fünf Schlüsseln.
    mit_radius: bool = True


@dataclass(frozen=True)
class Ort:
    """Eine Stadt oder Region mit eigenen Diensten.

    ``kasten`` ist (Süd, West, Nord, Ost) und grob: Er spart den Netzaufruf,
    entscheidet aber nichts allein — ``land`` muss zum Land des Punktes
    passen, sonst zählt der Ort nicht.
    """

    name: str
    land: str
    kasten: tuple[float, float, float, float]
    quellen: dict[str, Quelle] = field(default_factory=dict)
    #: Wenn gesetzt, muss auch das Bundesland der Adresse passen. Für
    #: Flächenländer, deren Kasten weit über die Landesgrenze reicht.
    bundesland_iso: str | None = None

    def im_kasten(self, lat: float, lon: float) -> bool:
        sued, west, nord, ost = self.kasten
        return sued <= lat <= nord and west <= lon <= ost


# --------------------------------------------------------------- Lader
# Jeweils eine Zeile, damit die Tabelle unten lesbar bleibt.

def _wien_maerkte(s, lat, lon, r, refresh, a):
    return wien_mod.maerkte_load(s.outbound, lat, lon, r)


def _wien_baustellen(s, lat, lon, r, refresh, a):
    return wien_mod.baustellen_load(s.outbound, lat, lon, r)


def _wien_baurecht(s, lat, lon, r, refresh, a):
    return wien_mod.baurecht_load(s.outbound, lat, lon)


def _wien_lage(s, lat, lon, r, refresh, a):
    return wien_profil_mod.lage_load(s.outbound, lat, lon, r)


def _wien_zaehlbezirk(s, lat, lon, r, refresh, a):
    return wien_profil_mod.zaehlbezirk_load(s.outbound, lat, lon, (a or {}).get("ortsteil"),
                                            s._wien_zb_daten)


def _wien_verkehrsmenge(s, lat, lon, r, refresh, a):
    return wien_verkehr_mod.kfz_load(s.outbound, lat, lon, r, lambda: s._wien_kfz_daten(refresh))


def _wien_luft(s, lat, lon, r, refresh, a):
    return wien_verkehr_mod.luft_load(s.outbound, lat, lon)


def _salzburg_maerkte(s, lat, lon, r, refresh, a):
    return salzburg_mod.maerkte_load(s.outbound, lat, lon, r)


def _salzburg_baustellen(s, lat, lon, r, refresh, a):
    return salzburg_mod.baustellen_load(s.outbound, lat, lon, r)


def _salzburg_baurecht(s, lat, lon, r, refresh, a):
    return salzburg_mod.baurecht_load(s.outbound, lat, lon)


def _salzburg_lage(s, lat, lon, r, refresh, a):
    return salzburg_mod.lage_load(s.outbound, lat, lon, r)


def _hamburg_maerkte(s, lat, lon, r, refresh, a):
    return hamburg_mod.maerkte_load(s.outbound, s.settings, lat, lon, r)


def _hamburg_baustellen(s, lat, lon, r, refresh, a):
    return hamburg_mod.baustellen_load(s.outbound, s.settings, lat, lon, r)


def _hamburg_rad(s, lat, lon, r, refresh, a):
    return hamburg_mod.rad_load(s.outbound, s.settings, lat, lon, r)


def _hamburg_verkehrsmenge(s, lat, lon, r, refresh, a):
    return hamburg_mod.verkehrsmengen_load(s.outbound, s.settings, lat, lon, r)


def _hamburg_stadtteil(s, lat, lon, r, refresh, a):
    return hamburg_mod.stadtteil_load(s.outbound, lat, lon)


def _hamburg_lage(s, lat, lon, r, refresh, a):
    return hamburg_mod.lage_load(s.outbound, lat, lon, r)


def _berlin_baustellen(s, lat, lon, r, refresh, a):
    return berlin_mod.baustellen_load(s.outbound, s.settings, lat, lon, r)


def _berlin_verkehrsmenge(s, lat, lon, r, refresh, a):
    return berlin_mod.verkehrsmengen_load(s.outbound, s.settings, lat, lon, r)


def _stuttgart_baustellen(s, lat, lon, r, refresh, a):
    return mobidata_mod.stuttgart_baustellen_load(s.outbound, lat, lon, r)


def _bw_baustellen(s, lat, lon, r, refresh, a):
    return mobidata_mod.roadworks_load(s.outbound, lat, lon, r, lambda: s._mobidata_roadworks(refresh))


def _bw_rad(s, lat, lon, r, refresh, a):
    return mobidata_mod.eco_load(s.outbound, lat, lon, r, lambda: s._mobidata_eco(refresh))


def _bw_verkehrsmenge(s, lat, lon, r, refresh, a):
    return mobidata_mod.svz_load(s.outbound, lat, lon, r, lambda: s._mobidata_svz(refresh))


def _bw_lage(s, lat, lon, r, refresh, a):
    return s._lage_bw(lat, lon, r)


def _bayern_verkehrsmenge(s, lat, lon, r, refresh, a):
    return bayern.verkehrsmengen(s.outbound, s.settings, lat, lon, r)


# --------------------------------------------------------------- Tabelle
# Reihenfolge = Vorrang. Wo sich Kästen überlappen, gewinnt der feinere
# Dienst: Stuttgart vor Baden-Württemberg, Städte vor Flächenländern.

ORTE: list[Ort] = [
    Ort("Wien", "AT", wien_mod.STADT_BBOX, {
        "maerkte": Quelle("wien_maerkte", _wien_maerkte),
        "baustellen": Quelle("wien_baustellen", _wien_baustellen),
        "baurecht": Quelle("baurecht_at", _wien_baurecht, mit_radius=False),
        "lage": Quelle("wien_lage", _wien_lage),
        "indikatoren": Quelle("wien_zaehlbezirk", _wien_zaehlbezirk, mit_radius=False),
        "verkehrsmenge": Quelle("wien_verkehrsmenge", _wien_verkehrsmenge),
        "luft": Quelle("wien_luft", _wien_luft, mit_radius=False),
    }),
    Ort("Salzburg", "AT", salzburg_mod.STADT_BBOX, {
        "maerkte": Quelle("salzburg_maerkte", _salzburg_maerkte),
        "baustellen": Quelle("salzburg_baustellen", _salzburg_baustellen),
        "baurecht": Quelle("baurecht_at", _salzburg_baurecht, mit_radius=False),
        "lage": Quelle("salzburg_lage", _salzburg_lage),
    }),
    Ort("Hamburg", "DE", hamburg_mod.STADT_BBOX, {
        "maerkte": Quelle("hamburg_maerkte", _hamburg_maerkte),
        "baustellen": Quelle("hamburg_baustellen", _hamburg_baustellen),
        "radzaehlung": Quelle("hamburg_rad", _hamburg_rad),
        "verkehrsmenge": Quelle("hamburg_verkehrsmenge", _hamburg_verkehrsmenge),
        "indikatoren": Quelle("hamburg_stadtteil", _hamburg_stadtteil, mit_radius=False),
        "lage": Quelle("hamburg_lage", _hamburg_lage),
    }),
    Ort("Berlin", "DE", berlin_mod.STADT_BBOX, {
        "baustellen": Quelle("berlin_baustellen", _berlin_baustellen),
        "verkehrsmenge": Quelle("berlin_verkehrsmenge", _berlin_verkehrsmenge),
    }),
    # Stuttgart vor Baden-Württemberg: die Stadt meldet ihre Baustellen
    # punktgenau, die Landesdatei nur das klassifizierte Netz.
    Ort("Stuttgart", "DE", mobidata_mod.STUTTGART_BBOX, {
        "baustellen": Quelle("stuttgart_baustellen", _stuttgart_baustellen),
    }),
    Ort("Baden-Württemberg", "DE", mobidata_mod.BW_BBOX, {
        "baustellen": Quelle("mobidata_baustellen", _bw_baustellen),
        "radzaehlung": Quelle("mobidata_rad", _bw_rad),
        "verkehrsmenge": Quelle("svz_bw_punkt", _bw_verkehrsmenge),
        "lage": Quelle("mobidata_lage", _bw_lage),
    }, bundesland_iso="DE-BW"),
    # Bayern zuletzt: BAYSIS deckt das ganze Land ab, der Kasten reicht
    # aber bis über die Grenze — deshalb erst nach allen feineren Diensten.
    Ort("Bayern", "DE", bayern.BAYERN_BBOX, {
        "verkehrsmenge": Quelle("baysis", _bayern_verkehrsmenge),
    }),
]


def fuer_block(block: str, land: str | None = None) -> list[Ort]:
    """Die Orte, die diesen Block bedienen, in Vorrangreihenfolge."""
    return [o for o in ORTE if block in o.quellen and (land is None or o.land == land)]


def bloecke() -> set[str]:
    """Alle Blöcke, für die überhaupt ein Ort zuständig ist."""
    return {b for o in ORTE for b in o.quellen}


def uebersicht() -> list[dict[str, Any]]:
    """Tabelle für Doku und Tests: welcher Ort bedient welche Blöcke."""
    return [{"ort": o.name, "land": o.land, "bundesland_iso": o.bundesland_iso,
             "bloecke": sorted(o.quellen), "caches": sorted(q.cache for q in o.quellen.values())}
            for o in ORTE]


__all__ = ["ORTE", "Ort", "Quelle", "fuer_block", "bloecke", "uebersicht"]
