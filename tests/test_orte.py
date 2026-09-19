"""Die Orts-Registry: welche Stadt bedient welchen Block, in welcher
Reihenfolge — und dass die Kästen nicht über die Grenze greifen.

Bis 0.6.0 stand diese Auskunft als ``if``-Kette in sieben Methoden von
``service.py``. Was hier geprüft wird, ist die Tabelle selbst; dass der
Service sie richtig fragt, prüfen die Rundläufe in ``test_api.py``,
``test_salzburg.py`` und ``test_de_verkehr.py``.
"""

from __future__ import annotations

import pytest

from gastroviewer import orte
from gastroviewer.config import TTL_KLASSEN

WIEN = (48.2082, 16.3738)
SALZBURG = (47.8003, 13.0430)
FREILASSING = (47.8400, 12.9800)   # deutsch, liegt im Salzburger Kasten
MUENCHEN = (48.1372, 11.5755)
STUTTGART = (48.7758, 9.1829)
HAMBURG = (53.5511, 9.9937)
BERLIN = (52.5219, 13.4132)


def test_jede_quelle_hat_einen_ttl_eintrag():
    """Ein Cache-Name ohne TTL-Eintrag fiele still auf die kurze Dauer."""
    ohne = sorted({q.cache for o in orte.ORTE for q in o.quellen.values()} - set(TTL_KLASSEN))
    assert not ohne, f"Cache-Namen ohne TTL-Eintrag: {ohne}"


def test_reihenfolge_feiner_dienst_vor_flaechendienst():
    """Stuttgart vor Baden-Württemberg, alle Städte vor Bayern."""
    baustellen = [o.name for o in orte.fuer_block("baustellen", "DE")]
    assert baustellen.index("Stuttgart") < baustellen.index("Baden-Württemberg")
    verkehr = [o.name for o in orte.fuer_block("verkehrsmenge", "DE")]
    assert verkehr[-1] == "Bayern", "BAYSIS deckt das ganze Land ab und kommt zuletzt"
    assert verkehr.index("Baden-Württemberg") < verkehr.index("Bayern")


def test_land_trennt_ueberlappende_kaesten():
    """Der Salzburger Stadtkasten reicht über die Grenze bis Freilassing.
    Ohne die Landesprüfung hätte ein deutscher Punkt dort den Salzburger
    WFS gefragt."""
    salzburg = next(o for o in orte.ORTE if o.name == "Salzburg")
    assert salzburg.im_kasten(*FREILASSING), "Vorbedingung: Freilassing liegt im Kasten"
    assert salzburg.land == "AT"
    assert salzburg not in orte.fuer_block("baustellen", "DE")
    assert salzburg in orte.fuer_block("baustellen", "AT")
    # Umgekehrt: der bayerische Kasten reicht über Salzburg, zählt dort aber nicht.
    bayern = next(o for o in orte.ORTE if o.name == "Bayern")
    assert bayern.im_kasten(*SALZBURG) and bayern not in orte.fuer_block("verkehrsmenge", "AT")


@pytest.mark.parametrize("block,punkt,land,erwartet", [
    ("verkehrsmenge", WIEN, "AT", "Wien"),
    ("verkehrsmenge", BERLIN, "DE", "Berlin"),
    ("verkehrsmenge", HAMBURG, "DE", "Hamburg"),
    ("verkehrsmenge", STUTTGART, "DE", "Baden-Württemberg"),
    ("verkehrsmenge", MUENCHEN, "DE", "Bayern"),
    ("baustellen", STUTTGART, "DE", "Stuttgart"),
    ("baustellen", SALZBURG, "AT", "Salzburg"),
    ("baustellen", MUENCHEN, "DE", None),          # München ist die Auffangquelle
    ("lage", WIEN, "AT", "Wien"),
    ("lage", HAMBURG, "DE", "Hamburg"),
    ("lage", MUENCHEN, "DE", None),
    ("indikatoren", HAMBURG, "DE", "Hamburg"),
    ("luft", WIEN, "AT", "Wien"),
    ("luft", MUENCHEN, "DE", None),
    ("baurecht", SALZBURG, "AT", "Salzburg"),
])
def test_zustaendiger_ort(block, punkt, land, erwartet):
    treffer = [o.name for o in orte.fuer_block(block, land) if o.im_kasten(*punkt)]
    assert (treffer[0] if treffer else None) == erwartet, treffer


def test_uebersicht_ist_vollstaendig():
    u = orte.uebersicht()
    assert {e["ort"] for e in u} == {"Wien", "Salzburg", "Hamburg", "Berlin", "Stuttgart",
                                     "Baden-Württemberg", "Bayern"}
    assert orte.bloecke() == {"maerkte", "baustellen", "baurecht", "lage", "indikatoren",
                              "verkehrsmenge", "radzaehlung", "luft"}
    for e in u:
        assert e["bloecke"] and e["land"] in ("DE", "AT")


def test_bundesland_nur_wo_der_kasten_weit_reicht():
    """Nur Baden-Württemberg prüft zusätzlich das Bundesland: Sein Kasten
    deckt Teile von Bayern, Hessen und der Schweiz mit ab."""
    mit = [o.name for o in orte.ORTE if o.bundesland_iso]
    assert mit == ["Baden-Württemberg"]
