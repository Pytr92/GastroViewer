"""Einstiegspunkt für das Doppelklick-Paket (PyInstaller).

Identisch zur CLI (``python -m gastroviewer``) — nur als eigene Datei, weil
PyInstaller ein Skript als Startpunkt erwartet. Ohne Argumente startet das
gefrorene Paket das Startfenster (siehe ``__main__.main``).
"""

from __future__ import annotations

import multiprocessing
import sys

from gastroviewer.__main__ import main


def argumente(argv: list[str]) -> list[str]:
    """Die Argumente, die wirklich vom Benutzer kommen.

    Startet man ein ``.app``-Bundle aus dem Finder, hängt der
    Fensterserver von macOS gelegentlich eine Prozesskennung als erstes
    Argument an: ``-psn_0_123456``. Das ist kein Tippfehler des Benutzers,
    sondern Betriebssystemkram — ``argparse`` kennt die Option aber nicht,
    bricht mit „unrecognized arguments" ab und beendet sich mit Code 2.

    Beim Doppelklick ist das der schlimmste denkbare Fehler: Es gibt kein
    Konsolenfenster, in dem die Meldung stünde. Das Programm blitzt kurz im
    Dock auf und verschwindet — ohne jeden Hinweis, warum. Deshalb wird das
    Argument hier weggeworfen, und zwar nur hier im gefrorenen Paket: Wer
    ``gastroviewer`` im Terminal aufruft, soll für einen echten Tippfehler
    weiterhin die Fehlermeldung bekommen.
    """
    return [a for a in argv if not a.startswith("-psn_")]


if __name__ == "__main__":
    # Pflicht in gefrorenen Windows-Paketen: ohne freeze_support würde jeder
    # von multiprocessing gestartete Kindprozess das ganze Programm neu starten.
    multiprocessing.freeze_support()
    raise SystemExit(main(argumente(sys.argv[1:])))
