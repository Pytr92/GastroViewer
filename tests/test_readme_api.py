"""Die API-Tabelle im README darf nicht hinter den Routen zurückbleiben.

Vorher fehlten 20 der 71 Routen. /docs (OpenAPI) ist die vollständige
Referenz — aber wer das README liest, soll nicht raten müssen, was es gibt."""

from __future__ import annotations

import re
from pathlib import Path

from conftest import api_routen

from gastroviewer.api import create_app
from gastroviewer.config import Settings

README = Path(__file__).resolve().parents[1] / "README.md"


def tabellen_pfade() -> set[str]:
    """Alle Pfade aus der API-Tabelle; ``{a\\|b}``-Gruppen ausmultipliziert,
    ``{id}``-Parameter auf ``{…}`` normiert, Query-Strings abgeschnitten."""
    text = README.read_text(encoding="utf-8")
    tabelle = text[text.index("## API"):text.index("Interaktive Doku unter")]
    pfade: set[str] = set()
    for treffer in re.finditer(r"`(?:[A-Z/]+ )?(/[^`?\s]+)", tabelle):
        pfad = treffer.group(1).strip()
        gruppen = re.findall(r"\{([^}]*\\\|[^}]*)\}", pfad)
        varianten = [pfad]
        for g in gruppen:
            varianten = [v.replace("{" + g + "}", teil) for v in varianten
                         for teil in g.split("\\|")]
        for v in varianten:
            pfade.add(re.sub(r"\{[^}]+\}", "{}", v))
    return pfade


def test_jede_route_steht_im_readme():
    app = create_app(Settings())
    routen = sorted({r.path for r in api_routen(app) if r.path.startswith("/api")})
    assert len(routen) >= 60
    im_readme = tabellen_pfade()
    fehlt = [r for r in routen if re.sub(r"\{[^}]+\}", "{}", r) not in im_readme]
    assert not fehlt, f"Routen ohne Zeile in der README-API-Tabelle: {fehlt}"
