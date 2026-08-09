# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-Bauplan für das Doppelklick-Paket (Windows/macOS/Linux).

Aufruf aus dem Repo-Wurzelverzeichnis:

    pyinstaller --clean --noconfirm packaging/gastroviewer.spec

Entscheidungen:

* **Eine Datei** (onefile): eine einzige ausführbare Datei zum Weitergeben.
  Beim Start entpackt PyInstaller nach ``sys._MEIPASS`` — die Oberfläche
  (``gastroviewer/static``) wird dorthin mitgepackt, und zwar unter genau dem
  Pfad, den ``api.STATIC_DIR`` (``Path(__file__).parent / "static"``) erwartet.
* **Mit Konsolenfenster**: Fehlermeldungen und das Abruf-Protokoll bleiben
  sichtbar. Seit es das Startfenster gibt, ist die Konsole nicht mehr der
  Aus-Schalter, sondern nur noch die Protokollansicht — bewusst behalten,
  weil ein Fehler beim Start sonst spurlos verschwände.
* Die ``uvicorn``-Untermodule stehen explizit hier, weil uvicorn sie zur
  Laufzeit über Strings lädt ("uvicorn.loops.auto" …) — die statische Analyse
  von PyInstaller sieht solche Importe nicht.
* ``overturemaps``/``pyarrow`` sind bewusst NICHT im Paket (mehrere hundert
  MB); der Overture-Import bleibt ein optionaler Schritt mit Python.
"""

from pathlib import Path

WURZEL = Path(SPECPATH).parent

a = Analysis(
    [str(WURZEL / "packaging" / "launcher.py")],
    pathex=[str(WURZEL)],
    binaries=[],
    datas=[
        (str(WURZEL / "gastroviewer" / "static"), "gastroviewer/static"),
    ],
    hiddenimports=[
        # Das Startfenster laedt tkinter erst beim Oeffnen — die statische
        # Analyse findet solche Importe zwar, hier steht es zur Sicherheit
        # ausdruecklich, weil ohne Fenster der Doppelklick-Start ins Leere
        # liefe.
        "tkinter",
        "tkinter.ttk",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Groß und im Paket nicht gebraucht (nur für den optionalen
        # Overture-Import mit normalem Python nötig).
        "overturemaps",
        "pyarrow",
        "numpy",
        "pandas",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="GastroViewer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
