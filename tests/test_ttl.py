"""Cache-Dauern: jede Quelle aus service.py steht in der Tabelle, und die
Dauern wandern nicht unbemerkt."""

from __future__ import annotations

import ast
import logging
from pathlib import Path

from gastroviewer.config import TTL_KLASSEN, Settings

SERVICE = Path(__file__).resolve().parents[1] / "gastroviewer" / "service.py"


# Die Ortsweiche (``service._ort_quelle``) holt den Cache-Namen aus der
# Registry statt aus einem Literal. Das ist die einzige erlaubte Ausnahme;
# ihre Namen kommen unten aus ``orte`` dazu.
CACHE_AUS_REGISTRY = "q.cache"


def quellen_aus_service() -> set[str]:
    """Erstes Argument jedes ``self._cached(...)``-Aufrufs — per AST, nicht
    per grep: ein Kommentar oder ein f-String soll den Test nicht täuschen.

    Dazu die Cache-Namen der Orts-Registry: seit 0.6.1 steht die Ortsweiche
    als Tabelle in ``orte.py``, ihre Namen erreichen ``_cached`` über eine
    Variable. Beide Wege zusammen sind der vollständige Bestand."""
    from gastroviewer import orte

    namen = {q.cache for ort in orte.ORTE for q in ort.quellen.values()}
    for node in ast.walk(ast.parse(SERVICE.read_text(encoding="utf-8"))):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_cached" and node.args):
            erstes = node.args[0]
            if (isinstance(erstes, ast.Attribute)
                    and ast.unparse(erstes) == CACHE_AUS_REGISTRY):
                continue
            assert isinstance(erstes, ast.Constant) and isinstance(erstes.value, str), (
                f"Quellenname muss ein Literal oder {CACHE_AUS_REGISTRY} sein (Zeile {node.lineno})")
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
            "muenchen_baustellen", "muenchen_messe", "muenchen_rad", "muenchen_tourismus", "wien_baustellen", "wien_lage", "salzburg_baustellen", "salzburg_lage",
            "stuttgart_baustellen", "mobidata_roadworks", "mobidata_baustellen", "mobidata_eco", "mobidata_rad",
            "mobidata_lage", "hamburg_lage",
            "oepnv_einzug", "overpass", "scan", "vorschlaege"},
    1209600: {"fahrzeit", "gehweg", "liefergebiet", "planung", "planung_at",
              "tourismus_at", "tourismus_at_daten"},
    3600: {"luft_punkt", "wien_luft"},
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


def test_jeder_limiter_hat_genau_einen_abstand():
    """Ein Limiter wird beim ersten Aufruf mit seinem Mindestabstand
    angelegt; ein zweiter Aufruf mit anderem Abstand wirft zur Laufzeit.

    Das ist keine Theorie: Der erste Live-Lauf der Vollprüfung brachte das
    Gemeindeprofil zum Scheitern, weil ``statistik_at`` an einer Stelle mit
    0,5 s und an drei anderen mit 1,0 s angelegt wurde — je nachdem, welcher
    Block zuerst lief. Die Attrappen der Tests kennen keine Limiter, deshalb
    fällt so etwas offline sonst nirgends auf.
    """
    import ast as _ast
    import collections

    paare = collections.defaultdict(set)
    stellen = collections.defaultdict(list)
    for pfad in (SERVICE.parent).rglob("*.py"):
        baum = _ast.parse(pfad.read_text(encoding="utf-8"))
        for knoten in _ast.walk(baum):
            if not isinstance(knoten, _ast.Call):
                continue
            kw = {k.arg: k.value for k in knoten.keywords if k.arg}
            limiter, abstand = kw.get("limiter"), kw.get("min_interval")
            if (isinstance(limiter, _ast.Constant) and isinstance(limiter.value, str)
                    and isinstance(abstand, _ast.Constant)):
                paare[limiter.value].add(abstand.value)
                stellen[limiter.value].append(f"{pfad.name}:{knoten.lineno}")

    assert len(paare) >= 20, "der Test sollte die echten Quellmodule lesen"
    uneinheitlich = {name: (sorted(werte), stellen[name])
                     for name, werte in paare.items() if len(werte) > 1}
    assert not uneinheitlich, (
        "Limiter mit mehreren Mindestabständen — der zweite Aufruf wirft zur "
        f"Laufzeit: {uneinheitlich}")
