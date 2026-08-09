"""Ein kleines Fenster, das den Server startet, seinen Zustand zeigt und
zur Oberfläche verlinkt.

Bisher war der Doppelklick-Start ein Konsolenfenster: Der Server lief darin,
und das Fenster zu schließen war der Aus-Schalter. Das funktioniert, sagt
aber nichts — man sieht nicht, ob der Server bereit ist, was er im
Hintergrund tut oder wohin man im Browser gehen muss.

**Der Server läuft im selben Prozess**, in einem eigenen Faden. Das ist
bewusst so und nicht als Kindprozess: Ein gefrorenes Einzeldatei-Paket
(PyInstaller onefile) noch einmal als Unterprozess zu starten heißt, das
ganze Paket ein zweites Mal auszupacken — und beim Beenden bliebe die Frage,
ob wirklich alles weg ist. Im selben Prozess gibt es weder verwaiste
Prozesse noch PID-Dateien noch plattformabhängige Signalbehandlung.

**Ehrlichkeit vor Grün.** Der Zustand „läuft" wird erst gemeldet, wenn der
Server tatsächlich geantwortet hat — nicht, wenn der Faden gestartet wurde.
Antwortet auf dem Port etwas, das nicht dieses Werkzeug ist, sagt das
Fenster das ausdrücklich, statt einen Erfolg vorzutäuschen.

Die Fensterlogik hier ist von der Darstellung getrennt: `zustand` und
`hintergrund_fakten` sind reine Funktionen und werden in der Testsuite
gegen aufgezeichnete echte Antworten geprüft. `tkinter` wird erst beim
Öffnen des Fensters geladen — auf einem Linux ohne `python3-tk` bleibt der
Rest des Werkzeugs damit uneingeschränkt benutzbar.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from .config import Settings, kontakt_gueltig, speichere_kontakt

# Wie lange ein Start dauern darf, bevor „startet …" zu „antwortet nicht"
# wird. Großzügig, weil der erste Start eines gefrorenen Pakets das Paket
# erst auspacken muss.
STARTFENSTER_S = 60.0
TAKT_S = 1.5


class Zustand:
    """Die Zustände, die das Fenster unterscheidet. Keiner wird geraten."""

    AUS = "aus"
    STARTET = "startet"
    LAEUFT = "laeuft"
    ANTWORTET_NICHT = "antwortet_nicht"
    FREMD = "fremd"
    FEHLER = "fehler"


BESCHRIFTUNG = {
    Zustand.AUS: ("Nicht gestartet", "#8a8a8a"),
    Zustand.STARTET: ("Startet …", "#b8860b"),
    Zustand.LAEUFT: ("Läuft — bereit", "#2f712c"),
    Zustand.ANTWORTET_NICHT: ("Gestartet, antwortet aber nicht", "#b04a1a"),
    Zustand.FREMD: ("Port belegt — von einem anderen Programm", "#a01c1c"),
    Zustand.FEHLER: ("Start fehlgeschlagen", "#a01c1c"),
}


def zustand(*, faden_laeuft: bool, gesund: bool, fremd: bool,
            fehler: str | None, seit_s: float) -> str:
    """Der angezeigte Zustand aus den beobachteten Tatsachen.

    Reine Funktion, damit sie prüfbar ist. Die Reihenfolge der Fälle ist
    die Aussage: Ein Fehler schlägt alles, ein fremdes Programm auf dem
    Port schlägt „läuft", und „läuft" verlangt zwingend eine Antwort.
    """
    if fehler:
        return Zustand.FEHLER
    if fremd:
        return Zustand.FREMD
    if not faden_laeuft:
        return Zustand.AUS
    if gesund:
        return Zustand.LAEUFT
    if seit_s < STARTFENSTER_S:
        return Zustand.STARTET
    return Zustand.ANTWORTET_NICHT


def _mb(bytes_: Any) -> str | None:
    try:
        return f"{float(bytes_) / 1_000_000:.0f} MB"
    except (TypeError, ValueError):
        return None


def hintergrund_fakten(health: dict[str, Any] | None,
                       stats: dict[str, Any] | None,
                       datenverzeichnis: str | None = None,
                       ) -> list[tuple[str, str]]:
    """Was im Hintergrund läuft — ausschließlich Belegbares.

    Jede Zeile stammt aus einer Antwort des eigenen Servers. Fehlt ein
    Wert, wird die Zeile weggelassen statt mit einer Schätzung gefüllt.
    Bewusst **nicht** angezeigt: Speicher- oder Prozessorlast (sagt nichts
    über die Arbeit des Werkzeugs), „alles in Ordnung" ohne Antwort, oder
    ein Fortschrittsbalken mit geratener Restzeit.
    """
    zeilen: list[tuple[str, str]] = []
    h = health or {}
    if h.get("version"):
        zeilen.append(("Version", str(h["version"])))
    verzeichnis = h.get("datenverzeichnis") or datenverzeichnis
    if verzeichnis:
        zeilen.append(("Datenverzeichnis", str(verzeichnis)))
    # Das Kennzeichen, mit dem die Abrufe hinausgehen — die Stelle, an der
    # die eingetragene Kontaktadresse tatsächlich auftaucht. Angezeigt wird
    # der Wert des Servers, nicht der eingetippte: Nur so sieht man, ob die
    # Adresse wirklich angekommen ist.
    if h.get("user_agent"):
        zeilen.append(("Kennzeichen der Abrufe", str(h["user_agent"])))

    gtfs = h.get("gtfs") or {}
    if gtfs.get("importiert"):
        teile = [f"Fahrplan {gtfs.get('fahrplan_von', '?')}–{gtfs.get('fahrplan_bis', '?')}"]
        if gtfs.get("groesse_mb"):
            teile.append(f"{gtfs['groesse_mb']:.0f} MB")
        zeilen.append(("ÖPNV-Fahrplan (GTFS)", ", ".join(teile)))
    elif gtfs:
        zeilen.append(("ÖPNV-Fahrplan (GTFS)", "nicht importiert"))

    s = stats or {}
    if isinstance(s.get("total"), int):
        zeilen.append(("Zwischenspeicher", f"{s['total']:,} Einträge".replace(",", ".")))
    if isinstance(s.get("outbound_24h"), int):
        zeilen.append(("Abrufe (24 h)", str(s["outbound_24h"])))
    if isinstance(s.get("overpass_24h"), int):
        zeilen.append(("davon Overpass", str(s["overpass_24h"])))
    return zeilen


def _hole(url: str, zeit: float = 2.0) -> dict[str, Any] | None:
    """Ein Abruf gegen den eigenen Server, am Proxy vorbei."""
    oeffner = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with oeffner.open(url, timeout=zeit) as antwort:
            return json.loads(antwort.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def ist_unser_server(basis: str) -> tuple[bool, bool]:
    """(antwortet_etwas, ist_unser_werkzeug).

    Der Unterschied ist wichtig: Auf Port 8000 kann irgendetwas lauschen.
    Nur wenn ``/api/health`` mit unserem Statusfeld antwortet, gehört der
    Port uns — sonst ist er fremd belegt und der Start muss unterbleiben.
    """
    daten = _hole(f"{basis}/api/health")
    if daten is None:
        return False, False
    return True, daten.get("status") == "ok"


class Serverlauf:
    """Der Server in einem Faden desselben Prozesses.

    ``uvicorn.Server`` bringt dafür alles mit: ``run()`` blockiert im
    Faden, ``should_exit`` beendet ihn geordnet. Ein Fehler beim Start
    (belegter Port, fehlende Datei) landet in ``fehler`` und wird
    angezeigt, statt lautlos zu verschwinden.
    """

    def __init__(self, settings: Settings, host: str, port: int) -> None:
        self.settings = settings
        self.host = host
        self.port = port
        self.fehler: str | None = None
        self.gestartet_um: float | None = None
        self._faden: threading.Thread | None = None
        self._server: Any = None

    @property
    def basis(self) -> str:
        gastgeber = "127.0.0.1" if self.host == "0.0.0.0" else self.host
        return f"http://{gastgeber}:{self.port}"

    @property
    def laeuft(self) -> bool:
        return self._faden is not None and self._faden.is_alive()

    @property
    def seit_s(self) -> float:
        return 0.0 if self.gestartet_um is None else time.monotonic() - self.gestartet_um

    def starten(self) -> None:
        if self.laeuft:
            return
        import uvicorn

        from .api import create_app

        self.fehler = None
        config = uvicorn.Config(
            create_app(self.settings), host=self.host, port=self.port,
            log_level="warning")
        self._server = uvicorn.Server(config)

        def lauf() -> None:
            try:
                self._server.run()
            except Exception as err:                      # noqa: BLE001
                self.fehler = f"{type(err).__name__}: {err}"

        self.gestartet_um = time.monotonic()
        self._faden = threading.Thread(target=lauf, name="gastroviewer-server",
                                       daemon=True)
        self._faden.start()

    def beenden(self, warten_s: float = 10.0) -> bool:
        """Geordnet beenden. Gibt zurück, ob der Faden wirklich weg ist."""
        if self._server is not None:
            self._server.should_exit = True
        if self._faden is not None:
            self._faden.join(timeout=warten_s)
            weg = not self._faden.is_alive()
            if weg:
                self._faden = None
                self.gestartet_um = None
            return weg
        return True


def _fenster_bauen(lauf: Serverlauf, selbsttest: bool = False):
    """Baut das Fenster. `tkinter` wird erst hier geladen."""
    import tkinter as tk
    import webbrowser
    from tkinter import ttk

    wurzel = tk.Tk()
    wurzel.title("GastroViewer — Standort-Datenterminal")
    wurzel.minsize(600, 560)
    rahmen = ttk.Frame(wurzel, padding=16)
    rahmen.pack(fill="both", expand=True)

    lampe = tk.Label(rahmen, text="●", font=("", 22), fg="#8a8a8a")
    lampe.grid(row=0, column=0, sticky="w")
    status = ttk.Label(rahmen, text="Nicht gestartet", font=("", 13, "bold"))
    status.grid(row=0, column=1, sticky="w", padx=(8, 0))

    knopf = ttk.Button(rahmen, text="Starten")
    knopf.grid(row=1, column=0, columnspan=2, sticky="w", pady=(12, 4))

    link = tk.Label(rahmen, text=lauf.basis, fg="#1f5f8b", cursor="hand2")
    link.grid(row=2, column=0, columnspan=2, sticky="w")
    link_hinweis = ttk.Label(
        rahmen, text="(anklicken, sobald der Server läuft)",
        foreground="#666")
    link_hinweis.grid(row=3, column=0, columnspan=2, sticky="w")

    ttk.Separator(rahmen, orient="horizontal").grid(
        row=4, column=0, columnspan=2, sticky="ew", pady=12)

    # --- Kontaktadresse ---------------------------------------------------
    # Nominatim verlangt in seinen Nutzungsbedingungen ausdrücklich eine
    # Kontaktmöglichkeit im User-Agent, damit der Betreiber bei Problemen
    # jemanden erreichen kann. Bisher ging das nur über eine
    # Umgebungsvariable — wer das Doppelklick-Paket benutzt, hat davon
    # nichts. Deshalb hier ein Feld.
    ttk.Label(rahmen, text="Kontaktadresse für die Datendienste",
              font=("", 10, "bold")).grid(row=5, column=0, columnspan=2, sticky="w")
    ttk.Label(
        rahmen, justify="left", foreground="#666", wraplength=520,
        text=("OpenStreetMap/Nominatim verlangt eine erreichbare Adresse im "
              "Kennzeichen der Abrufe — damit der Betreiber sich melden kann, "
              "statt einfach zu sperren. Sie wird nur mitgesendet, nirgends "
              "hinterlegt und für nichts anderes benutzt."),
    ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(2, 4))

    kontakt_zeile = ttk.Frame(rahmen)
    kontakt_zeile.grid(row=7, column=0, columnspan=2, sticky="ew")
    kontakt_feld = ttk.Entry(kontakt_zeile, width=38)
    vorbelegt = lauf.settings.contact or ""
    kontakt_feld.insert(0, vorbelegt if "@" in vorbelegt else "")
    kontakt_feld.pack(side="left")
    kontakt_knopf = ttk.Button(kontakt_zeile, text="Speichern")
    kontakt_knopf.pack(side="left", padx=(8, 0))
    kontakt_meldung = ttk.Label(rahmen, text="", justify="left", wraplength=520)
    kontakt_meldung.grid(row=8, column=0, columnspan=2, sticky="w", pady=(2, 0))

    def kontakt_speichern() -> None:
        adresse = kontakt_feld.get().strip()
        if not kontakt_gueltig(adresse):
            kontakt_meldung.configure(
                text="Das sieht nicht nach einer E-Mail-Adresse aus. Eine "
                     "erfundene Adresse wäre schlimmer als keine — dann "
                     "lieber leer lassen.",
                foreground="#a01c1c")
            return
        speichere_kontakt(lauf.settings.data_dir, adresse)
        lauf.settings.contact = adresse
        if lauf.laeuft:
            # Das Kennzeichen entsteht beim Aufbau der Anwendung. Damit die
            # neue Adresse wirklich mitgeht, muss der Server neu starten —
            # das wird getan und gesagt, statt es stillschweigend erst beim
            # nächsten Programmstart wirken zu lassen.
            lauf.beenden()
            lauf.starten()
            kontakt_meldung.configure(
                text=f"Gespeichert: {adresse} — der Server wurde dafür neu "
                     "gestartet.", foreground="#2f712c")
        else:
            kontakt_meldung.configure(
                text=f"Gespeichert: {adresse}", foreground="#2f712c")
        aktualisieren()

    kontakt_knopf.configure(command=kontakt_speichern)

    ttk.Separator(rahmen, orient="horizontal").grid(
        row=9, column=0, columnspan=2, sticky="ew", pady=12)
    ttk.Label(rahmen, text="Was im Hintergrund läuft",
              font=("", 10, "bold")).grid(row=10, column=0, columnspan=2, sticky="w")
    fakten = ttk.Label(rahmen, text="—", justify="left", foreground="#333")
    fakten.grid(row=11, column=0, columnspan=2, sticky="w", pady=(4, 0))
    rahmen.columnconfigure(1, weight=1)

    def oeffnen(_ereignis: Any = None) -> None:
        if lauf.laeuft:
            webbrowser.open(lauf.basis)

    link.bind("<Button-1>", oeffnen)

    def umschalten() -> None:
        if lauf.laeuft:
            knopf.state(["disabled"])
            lauf.beenden()
            knopf.state(["!disabled"])
        else:
            antwortet, unser = ist_unser_server(lauf.basis)
            if antwortet and not unser:
                lauf.fehler = (f"Auf Port {lauf.port} antwortet ein anderes "
                               "Programm. Bitte einen anderen Port wählen.")
                aktualisieren()
                return
            lauf.starten()
        aktualisieren()

    knopf.configure(command=umschalten)

    def aktualisieren() -> None:
        antwortet, unser = (False, False)
        if lauf.laeuft or lauf.gestartet_um is not None:
            antwortet, unser = ist_unser_server(lauf.basis)
        z = zustand(faden_laeuft=lauf.laeuft, gesund=unser,
                    fremd=antwortet and not unser and not lauf.laeuft,
                    fehler=lauf.fehler, seit_s=lauf.seit_s)
        text, farbe = BESCHRIFTUNG[z]
        if z == Zustand.FEHLER and lauf.fehler:
            text = f"{text}: {lauf.fehler}"
        status.configure(text=text)
        lampe.configure(fg=farbe)
        knopf.configure(text="Beenden" if lauf.laeuft else "Starten")
        link_hinweis.configure(
            text="(anklicken — die Oberfläche ist bereit)" if z == Zustand.LAEUFT
            else "(anklicken, sobald der Server läuft)")
        if unser:
            zeilen = hintergrund_fakten(_hole(f"{lauf.basis}/api/health"),
                                        _hole(f"{lauf.basis}/api/stats"),
                                        str(lauf.settings.data_dir))
            fakten.configure(text="\n".join(f"{k}: {v}" for k, v in zeilen) or "—")
        else:
            fakten.configure(
                text="Wird angezeigt, sobald der Server antwortet.")
        if not selbsttest:
            wurzel.after(int(TAKT_S * 1000), aktualisieren)

    def schliessen() -> None:
        if lauf.laeuft:
            lauf.beenden(warten_s=5.0)
        wurzel.destroy()

    wurzel.protocol("WM_DELETE_WINDOW", schliessen)
    return wurzel, aktualisieren, umschalten


def starte_fenster(settings: Settings, host: str, port: int,
                   sofort_starten: bool = True,
                   selbsttest: bool = False) -> int:
    """Öffnet das Fenster. Rückgabe ist der Exitcode."""
    lauf = Serverlauf(settings, host, port)
    try:
        wurzel, aktualisieren, umschalten = _fenster_bauen(lauf, selbsttest)
    except ImportError as err:
        print("Das Startfenster braucht tkinter, das hier fehlt: "
              f"{err}\nUnter Linux nachinstallieren (z. B. "
              "'sudo apt install python3-tk') — oder ohne Fenster starten:\n"
              "  gastroviewer serve --browser")
        return 3
    except Exception as err:                              # noqa: BLE001
        # Typisch auf einem Rechner ohne Bildschirmsitzung (Bauknecht,
        # SSH-Sitzung): tkinter ist da, findet aber keine Anzeige. Eigener
        # Exitcode, damit der Paketbau das von einem echten Fehler
        # unterscheiden kann — übersprungen ist nicht bestanden.
        if "display" in str(err).lower() or "TclError" in type(err).__name__:
            print(f"Keine Bildschirmsitzung für das Fenster: {err}\n"
                  "Ohne Fenster starten:  gastroviewer serve --browser")
            return 4
        raise
    if sofort_starten:
        umschalten()
    aktualisieren()
    if selbsttest:
        # Bauen, einmal aktualisieren, sauber schließen — ohne Ereignis-
        # schleife. So lässt sich im Installer-Bau prüfen, dass das Fenster
        # auf der Zielplattform überhaupt entsteht.
        lauf.beenden(warten_s=5.0)
        wurzel.destroy()
        print("Startfenster: Selbsttest bestanden.")
        return 0
    wurzel.mainloop()
    return 0
