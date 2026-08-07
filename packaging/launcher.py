"""Einstiegspunkt für das Doppelklick-Paket (PyInstaller).

Identisch zur CLI (``python -m gastroviewer``) — nur als eigene Datei, weil
PyInstaller ein Skript als Startpunkt erwartet. Ohne Argumente startet das
gefrorene Paket den Server und öffnet den Browser (siehe ``__main__.main``).
"""

from __future__ import annotations

import multiprocessing
import sys

from gastroviewer.__main__ import main

if __name__ == "__main__":
    # Pflicht in gefrorenen Windows-Paketen: ohne freeze_support würde jeder
    # von multiprocessing gestartete Kindprozess das ganze Programm neu starten.
    multiprocessing.freeze_support()
    raise SystemExit(main(sys.argv[1:]))
