"""Bodenrichtwerte — Verweise statt geratener Werte.

Spec §4.5: BORIS-D deckt Bayern, Baden-Württemberg, Saarland, Schleswig-Holstein
und Mecklenburg-Vorpommern aus rechtlichen Gründen nicht ab. Für Länder ohne in
Phase 0 bestätigtes Portal wird **keine URL geraten**, sondern ein Suchlink erzeugt.

Alle hier fest hinterlegten URLs wurden am 2026-08-01 mit HTTP 200 bestätigt
(siehe ``docs/endpoints-verified.md``).
"""

from __future__ import annotations

from urllib.parse import quote_plus

from .zensus import BUNDESLAENDER

BORIS_D = "https://bodenrichtwerte-boris.de/boris-d/?lang=de"

# Länder, die BORIS-D nicht führt (Spec §4.5, [V]).
NICHT_IN_BORIS_D = {"09", "08", "10", "01", "13"}

# In Phase 0 mit HTTP 200 bestätigte Landesportale.
LANDESPORTALE_VERIFIZIERT = {
    "08": ("Gutachterausschüsse Baden-Württemberg", "https://www.gutachterausschuesse-bw.de/"),
    "06": ("BORIS Hessen", "https://hvbg.hessen.de/immobilienwerte/boris-hessen"),
    "11": (
        "Gutachterausschuss Berlin",
        "https://www.berlin.de/gutachterausschuss/marktinformationen/bodenrichtwerte/",
    ),
    "12": ("BORIS Brandenburg", "https://boris.brandenburg.de/"),
}


def suchlink(land: str) -> str:
    return f"https://duckduckgo.com/?q={quote_plus(f'Bodenrichtwerte {land} Gutachterausschuss Portal')}"


def links_for(bundesland_code: str | None, gemeinde: str | None = None) -> dict:
    """Gibt die passenden Verweise zurück, klar getrennt nach Belegstatus."""
    if not bundesland_code:
        return {
            "bundesland": None,
            "hinweis": (
                "Ohne Bundesland (kein AGS aus dem Zensus-Gitter) lässt sich das "
                "zuständige Portal nicht bestimmen."
            ),
            "links": [{"titel": "BORIS-D (Bund)", "url": BORIS_D, "status": "bestätigt"}],
        }

    land = BUNDESLAENDER.get(bundesland_code, bundesland_code)
    links = []
    hinweis = None

    if bundesland_code in LANDESPORTALE_VERIFIZIERT:
        titel, url = LANDESPORTALE_VERIFIZIERT[bundesland_code]
        links.append({"titel": titel, "url": url, "status": "bestätigt"})

    if bundesland_code in NICHT_IN_BORIS_D:
        hinweis = (
            f"{land} ist aus rechtlichen Gründen nicht in BORIS-D enthalten. "
            "Zuständig ist das Landesportal."
        )
        if bundesland_code not in LANDESPORTALE_VERIFIZIERT:
            links.append(
                {
                    "titel": f"Bodenrichtwerte {land} suchen",
                    "url": suchlink(land),
                    "status": "Suchlink — keine URL geraten",
                }
            )
    else:
        links.append(
            {
                "titel": f"BORIS-D (enthält {land})",
                "url": BORIS_D,
                "status": "bestätigt",
            }
        )

    if gemeinde:
        links.append(
            {
                "titel": f"Gutachterausschuss {gemeinde} suchen",
                "url": f"https://duckduckgo.com/?q={quote_plus(f'Gutachterausschuss {gemeinde} Bodenrichtwert')}",
                "status": "Suchlink",
            }
        )

    return {
        "bundesland": land,
        "bundesland_code": bundesland_code,
        "hinweis": hinweis,
        "links": links,
        "quelle": (
            "Keine Bodenrichtwerte abgerufen. Es gibt keinen bundesweit einheitlichen "
            "offenen Dienst; die Portale werden verlinkt statt Werte zu schätzen."
        ),
    }
