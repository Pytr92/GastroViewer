"""Standortprofil: Erfüllt ein Kandidat die eigenen Mindestanforderungen?

Das Werkzeug zeigt bisher Daten. Ein Franchisenehmer, der dreißig Adressen
im Jahr ansieht, stellt aber eine andere Frage: **Welche davon erfülle ich
überhaupt?** Jedes System hat ein schriftliches Standortprofil — mindestens
so viele Einwohner, mindestens so viel Verkehr, höchstens so viele
Wettbewerber in Reichweite.

Dieses Modul prüft ein solches Profil gegen die Zeilen der
Vergleichstabelle. Drei Ergebnisse sind möglich, und der dritte ist der
wichtigste:

* **erfüllt** — der Wert liegt auf der richtigen Seite der Schwelle,
* **nicht erfüllt** — er liegt darunter bzw. darüber,
* **nicht prüfbar** — für diesen Standort liegt der Wert nicht vor.

„Nicht prüfbar" wird nie zu „erfüllt" aufgerundet. Ein fehlender Wert ist
kein bestandenes Kriterium, sondern eine offene Frage — und offene Fragen
gehören vor die Besichtigung, nicht danach.

Ebenso ausdrücklich: Es gibt Kriterien, die **keine** offene Datenquelle
beantwortet (Sichtbarkeit von der Straße, Abbiegemöglichkeit,
Grundstücksgröße, tatsächliche Miete, Verfügbarkeit). Sie stehen in
``NICHT_PRUEFBAR`` und werden immer mitangezeigt. Ein Profil, das nur die
prüfbaren Kriterien nennt, verleitet sonst zu dem Fehlschluss, ein grüner
Haken bedeute „geeignet".
"""

from __future__ import annotations

from typing import Any

#: Vergleichsspalten, die kein Kriterium sein können — Texte, Schlüssel und
#: Zeitstempel. Alles andere in VERGLEICH_SPALTEN ist eine Zahl.
KEINE_KRITERIEN = {
    "label", "notiz", "stand", "stand_grund", "bewertung", "adresse",
    "gemeinde", "ags", "erzeugt", "geprueft", "radius",
}

RICHTUNGEN = {
    "min": "mindestens",
    "max": "höchstens",
}

#: Was ein Standortprofil typischerweise noch verlangt — und was aus offenen
#: Daten nachweislich nicht zu beantworten ist. Diese Liste ist Teil des
#: Ergebnisses, nicht eine Fußnote.
NICHT_PRUEFBAR = [
    "Sichtbarkeit von der Hauptverkehrsstraße",
    "Zufahrt und Abbiegemöglichkeit (auch: richtige Straßenseite im "
    "Feierabendverkehr)",
    "Grundstücks- und Verkaufsfläche, Frontlänge",
    "Eigene Stellplätze auf dem Grundstück",
    "Tatsächliche Miete und Nebenkosten",
    "Verfügbarkeit der Fläche und Bereitschaft des Eigentümers",
    "Zustand der Bausubstanz, Abluft- und Fettabscheider-Möglichkeit",
]


class ProfilFehler(ValueError):
    """Ein Kriterium, das sich nicht auswerten lässt."""


def pruefe_kriterium(zeile: dict[str, Any], kriterium: dict[str, Any],
                     ) -> dict[str, Any]:
    """Ein einzelnes Kriterium gegen eine Vergleichszeile."""
    key = kriterium.get("key")
    richtung = kriterium.get("richtung")
    if not key or key in KEINE_KRITERIEN:
        raise ProfilFehler(f"Unbrauchbares Kriterium: {key!r}")
    if richtung not in RICHTUNGEN:
        raise ProfilFehler(
            f"Unbekannte Richtung {richtung!r} — möglich: "
            f"{', '.join(RICHTUNGEN)}")
    try:
        schwelle = float(kriterium.get("wert"))
    except (TypeError, ValueError) as err:
        raise ProfilFehler(
            f"Kriterium {key!r} braucht einen Zahlenwert.") from err

    wert = zeile.get(key)
    ergebnis = {
        "key": key,
        "richtung": richtung,
        "schwelle": schwelle,
        "ko": bool(kriterium.get("ko")),
        "wert": wert,
    }
    if not isinstance(wert, (int, float)) or isinstance(wert, bool):
        # Kein Wert heißt nicht „bestanden". Der Unterschied ist der Kern
        # dieses Moduls.
        ergebnis["stand"] = "nicht_pruefbar"
        return ergebnis
    ergebnis["stand"] = (
        "erfuellt"
        if (wert >= schwelle if richtung == "min" else wert <= schwelle)
        else "nicht_erfuellt")
    return ergebnis


def pruefe_profil(zeile: dict[str, Any], profil: list[dict[str, Any]],
                  ) -> dict[str, Any]:
    """Alle Kriterien gegen einen Standort.

    ``durchgefallen`` ist wahr, sobald ein als K.O. markiertes Kriterium
    **nicht erfüllt** ist — ein nicht prüfbares K.O.-Kriterium lässt den
    Standort ausdrücklich nicht durchfallen, es macht ihn nur offen.
    """
    ergebnisse = [pruefe_kriterium(zeile, k) for k in profil]
    zaehler = {"erfuellt": 0, "nicht_erfuellt": 0, "nicht_pruefbar": 0}
    for e in ergebnisse:
        zaehler[e["stand"]] += 1
    durchgefallen = any(
        e["ko"] and e["stand"] == "nicht_erfuellt" for e in ergebnisse)
    offene_ko = [e["key"] for e in ergebnisse
                 if e["ko"] and e["stand"] == "nicht_pruefbar"]
    return {
        "ergebnisse": ergebnisse,
        **zaehler,
        "gesamt": len(ergebnisse),
        "durchgefallen": durchgefallen,
        "offene_ko_kriterien": offene_ko,
        "nicht_pruefbar_grundsaetzlich": NICHT_PRUEFBAR,
    }


def moegliche_kriterien(spalten: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aus den Vergleichsspalten die, die sich als Kriterium eignen.

    Abgeleitet statt gepflegt: Kommt eine neue Kennzahl in die
    Vergleichstabelle, steht sie automatisch als Kriterium zur Verfügung —
    eine zweite Liste würde auseinanderlaufen.
    """
    return [
        {"key": c["key"], "titel": c["titel"], "gruppe": c["gruppe"],
         "einheit": c.get("einheit", ""), "stellen": c.get("stellen", 0)}
        for c in spalten if c["key"] not in KEINE_KRITERIEN
    ]
