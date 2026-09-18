"""Cache-Dauern: jede Quelle aus service.py steht in der Tabelle, und die
Dauern wandern nicht unbemerkt."""

from __future__ import annotations

import ast
import logging
from pathlib import Path

from gastroviewer.config import TTL_KLASSEN, Settings

SERVICE = Path(__file__).resolve().parents[1] / "gastroviewer" / "service.py"


def quellen_aus_service() -> set[str]:
    """Erstes Argument jedes ``self._cached(...)``-Aufrufs — per AST, nicht
    per grep: ein Kommentar oder ein f-String soll den Test nicht täuschen."""
    namen = set()
    for node in ast.walk(ast.parse(SERVICE.read_text(encoding="utf-8"))):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_cached" and node.args):
            erstes = node.args[0]
            assert isinstance(erstes, ast.Constant) and isinstance(erstes.value, str), (
                f"Quellenname muss ein Literal sein (Zeile {node.lineno})")
            namen.add(erstes.value)
    return namen


def test_jede_quelle_hat_einen_eintrag():
    quellen = quellen_aus_service()
    assert len(quellen) >= 50, "der Test sollte den echten Service lesen"
    fehlen = quellen - set(TTL_KLASSEN)
    assert not fehlen, f"ohne TTL-Eintrag (fielen vorher still auf den Default): {sorted(fehlen)}"
    ueberzaehlig = set(TTL_KLASSEN) - quellen
    assert not ueberzaehlig, f"in der Tabelle, aber von keinem _cached genutzt: {sorted(ueberzaehlig)}"


# Schnappschuss der Dauern VOR dem Umbau der Präfixkette (Settings ohne
# Umgebungsvariablen: osm 24 h, zensus 30 d, gehweg 14 d). Eine bewusste
# Änderung ändert diesen Test mit — eine unbemerkte fällt hier auf.
ERWARTET = {
    86400: {"baysis", "berlin_baustellen", "hamburg_baustellen", "hamburg_maerkte",
            "hamburg_rad", "leerstandsmelder", "leerstandsmelder_punkt", "marke_basis",
            "muenchen_baustellen", "muenchen_messe", "muenchen_rad", "muenchen_tourismus", "wien_baustellen", "wien_lage",
            "oepnv_einzug", "overpass", "scan", "vorschlaege"},
    1209600: {"fahrzeit", "gehweg", "liefergebiet", "planung", "planung_at",
              "tourismus_at", "tourismus_at_daten"},
    3600: {"luft_punkt"},
}


def test_dauern_sind_eingefroren(monkeypatch):
    for var in ("GASTROVIEWER_TTL_OSM", "GASTROVIEWER_TTL_ZENSUS",
                "GASTROVIEWER_TTL_NOMINATIM", "GASTROVIEWER_TTL_GEHWEG"):
        monkeypatch.delenv(var, raising=False)
    s = Settings()
    for sekunden, namen in ERWARTET.items():
        for name in namen:
            assert s.ttl_for(name) == sekunden, name
    lang = set(TTL_KLASSEN) - set().union(*ERWARTET.values())
    for name in lang:
        assert s.ttl_for(name) == 2592000, f"{name}: 30 Tage erwartet"


def test_unbekannte_quelle_faellt_auf_kurze_dauer_und_warnt_einmal(caplog):
    s = Settings()
    with caplog.at_level(logging.WARNING, logger="gastroviewer.config"):
        assert s.ttl_for("voellig_neu_xyz") == s.ttl_osm
        assert s.ttl_for("voellig_neu_xyz") == s.ttl_osm
    assert sum("voellig_neu_xyz" in r.getMessage() for r in caplog.records) == 1
