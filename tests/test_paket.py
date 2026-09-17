"""Das macOS-Programmpaket — geprüft wird die Verpackung, nicht das Programm.

Der Fehler in v0.1.0 lag nicht im Code: Im Release lag die nackte
PyInstaller-Datei, ohne Endung und ohne Paket. Der Finder kennt dafür keine
Zuordnung, ein Doppelklick zeigte den Binärinhalt als Zeichensalat. Ein
Testlauf, der nur das Programm prüft, hätte davon nie etwas gemerkt.

Deshalb prüft diese Datei genau die drei Stellen, an denen ein
Programmpaket unbrauchbar wird, ohne dass es beim Bauen auffällt:

1. der Finder findet die Startdatei nicht (``CFBundleExecutable`` zeigt ins
   Leere),
2. die Startdatei verliert ihr Ausführungsrecht auf dem Weg durch das ZIP,
3. der Installer-Workflow lädt eine Datei hoch, die der Release-Schritt
   unter einem anderen Namen sucht — das fällt sonst erst beim Release auf.

``codesign``, ``plutil`` und ``ditto`` gibt es nur auf dem Mac; das Skript
hat für alle drei einen Rückfall, und die Prüfung hier läuft deshalb auf
jedem System.
"""

from __future__ import annotations

import plistlib
import re
import shutil
import stat
import subprocess
import zipfile
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
SKRIPT = WURZEL / "packaging" / "macos_app.sh"
WORKFLOW = WURZEL / ".github" / "workflows" / "installer.yml"


@pytest.fixture(scope="module")
def paket(tmp_path_factory):
    """Baut das Paket einmal aus einer Attrappe statt aus 16 MB PyInstaller.

    Was hier geprüft wird, hängt nicht am Inhalt der Startdatei — nur an
    ihrer Lage, ihren Rechten und dem, was die Info.plist über sie behauptet.
    """
    if shutil.which("bash") is None:
        pytest.skip("bash fehlt.")
    if shutil.which("ditto") is None and shutil.which("zip") is None:
        pytest.skip("Weder ditto noch zip vorhanden — kein ZIP prüfbar.")
    ordner = tmp_path_factory.mktemp("paket")
    attrappe = ordner / "GastroViewer"
    attrappe.write_text("#!/bin/sh\necho Attrappe\n")
    attrappe.chmod(0o755)
    subprocess.run(
        ["bash", str(SKRIPT), str(attrappe), str(ordner), "GastroViewer-macOS-Probe"],
        check=True, capture_output=True, text=True,
    )
    return ordner


def test_finder_findet_die_startdatei(paket):
    """Der Kern: Was die Info.plist als Startdatei nennt, muss es geben.

    Zeigt ``CFBundleExecutable`` ins Leere, meldet macOS beim Doppelklick
    „Die Anwendung kann nicht geöffnet werden" — und zwar erst beim
    Empfänger, nicht beim Bauen.
    """
    app = paket / "GastroViewer.app"
    angaben = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    start = app / "Contents" / "MacOS" / angaben["CFBundleExecutable"]
    assert start.is_file(), f"Startdatei laut Info.plist fehlt: {start}"
    assert start.stat().st_mode & stat.S_IXUSR


def test_paket_weist_sich_als_programm_aus(paket):
    """Ohne APPL und ohne Kennung behandelt der Finder den Ordner als Ordner."""
    angaben = plistlib.loads(
        (paket / "GastroViewer.app" / "Contents" / "Info.plist").read_bytes())
    assert angaben["CFBundlePackageType"] == "APPL"
    assert angaben["CFBundleIdentifier"].count(".") >= 2
    assert angaben["CFBundleName"] == "GastroViewer"


def test_version_kommt_aus_pyproject(paket):
    """Eine zweite, von Hand gepflegte Versionsnummer wäre eine, die abweicht."""
    erwartet = re.search(
        r'^version = "(.*)"', (WURZEL / "pyproject.toml").read_text(), re.M).group(1)
    angaben = plistlib.loads(
        (paket / "GastroViewer.app" / "Contents" / "Info.plist").read_bytes())
    assert angaben["CFBundleShortVersionString"] == erwartet


def test_ausfuehrungsrecht_ueberlebt_das_zip(paket):
    """Der stille Totalausfall: ausgepackt, aber nicht mehr ausführbar.

    Genau deshalb packt das Skript mit ``ditto`` statt mit ``zip`` — und
    genau deshalb wird die Rechtemaske hier im Archiv nachgesehen, statt sie
    zu glauben.
    """
    archiv = paket / "GastroViewer-macOS-Probe.zip"
    assert archiv.exists()
    with zipfile.ZipFile(archiv) as z:
        namen = z.namelist()
        # keepParent: Beim Auspacken entsteht der Ordner GastroViewer.app,
        # nicht ein Haufen loser Dateien im Download-Ordner.
        assert all(n.startswith("GastroViewer.app/") for n in namen), namen
        eintrag = z.getinfo("GastroViewer.app/Contents/MacOS/GastroViewer")
    assert (eintrag.external_attr >> 16) & stat.S_IXUSR, \
        "Die Startdatei kommt ohne Ausführungsrecht beim Empfänger an."


def test_workflow_laedt_hoch_was_das_release_sucht():
    """Umbenannte Artefakte fallen sonst erst im Release-Schritt auf.

    Der Bau-Job lädt ``hochladen:`` hoch, der Release-Job kopiert Dateien
    unter festem Namen — stimmt beides nicht überein, laufen alle vier
    Builds grün und das Release bleibt leer.
    """
    text = WORKFLOW.read_text()
    hochgeladen = re.findall(r"^\s*hochladen:\s*(\S+)\s*$", text, re.M)
    assert len(hochgeladen) == 4, hochgeladen
    release = text.split("Dateien fürs Release benennen", 1)[1]
    for pfad in hochgeladen:
        name = Path(pfad).name
        assert name in release, f"{name} wird hochgeladen, aber nicht ins Release kopiert."


def test_macos_paket_ist_der_weg_ins_release():
    """macOS bekommt das ZIP mit dem Programmpaket — nicht die lose Datei.

    Der Rückfall auf die nackte Binärdatei wäre wieder v0.1.0.
    """
    text = WORKFLOW.read_text()
    for zeile in re.findall(r"^\s*hochladen:\s*(\S+)\s*$", text, re.M):
        if "macOS" in zeile:
            assert zeile.endswith(".zip"), zeile


def test_versionsnummern_stimmen_ueberein():
    """Vier Stellen halten die Version — sie dürfen nicht auseinanderlaufen.

    Die Nummer steht in ``pyproject.toml`` (Paket), ``__init__.py``,
    ``config.py`` (sie geht als Kennzeichen an fremde Dienste) und
    ``api.py`` (sie steht in der API-Beschreibung). Läuft eine davon weg,
    sendet das Werkzeug eine andere Version, als es ist — und genau dieses
    Kennzeichen ist der Anlass, aus dem ein Dienst jemanden anschreibt statt
    zu sperren.
    """
    stellen = {
        "pyproject.toml": r'^version = "(.+)"',
        "gastroviewer/__init__.py": r'^__version__ = "(.+)"',
        "gastroviewer/config.py": r'version: str = "(.+)"',
        "gastroviewer/api.py": r'version="(\d[^"]*)"',
    }
    gefunden = {}
    for datei, muster in stellen.items():
        treffer = re.search(muster, (WURZEL / datei).read_text(), re.M)
        assert treffer, f"Keine Version in {datei} gefunden."
        gefunden[datei] = treffer.group(1)
    assert len(set(gefunden.values())) == 1, gefunden


def test_finder_argument_wird_weggeworfen():
    """``-psn_0_…`` vom macOS-Fensterserver darf den Start nicht abbrechen.

    Ohne dieses Filter beendet sich das Programm beim Doppelklick mit
    „unrecognized arguments" — unsichtbar, weil ein ``.app`` keine Konsole
    hat. Echte Argumente müssen unangetastet durchkommen.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "launcher_probe", WURZEL / "packaging" / "launcher.py")
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)

    assert modul.argumente(["-psn_0_1234567"]) == []
    assert modul.argumente([]) == []
    assert modul.argumente(["serve", "--port", "8000"]) == ["serve", "--port", "8000"]
    # Ein echter Tippfehler bleibt ein Tippfehler.
    assert modul.argumente(["--prt", "8000"]) == ["--prt", "8000"]
