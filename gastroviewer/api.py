"""HTTP-Schnittstelle.

Neben ``/api/point`` (alles auf einmal) gibt es je Quelle einen eigenen Endpunkt.
Das Frontend ruft die einzeln auf, damit jeder Block seinen eigenen Ladezustand
und seine eigene Fehlermeldung bekommt (Spec §5) — und damit der Ausfall einer
Quelle die übrigen nicht aufhält.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .cache import AsyncCache
from .config import Settings, get_settings
from .http import Outbound
from .service import PointService

STATIC_DIR = __import__("pathlib").Path(__file__).parent / "static"
from .routen import ALLE_ROUTER
# Öffentliche Namen, die Tests, Skripte und ältere Aufrufer von hier beziehen:
from .routen._gemeinsam import RADIUS_CHOICES  # noqa: F401
from .routen.modelle import (  # noqa: F401
    GenesisZugang, Kriterium, Profil, PunkteSicherung, PunktNotiz, PunktSicherung,
    SavePoint, SchaetzEingaben, VerlaufEintrag,
)
from .vergleich import (  # noqa: F401
    VERGLEICH_GRUPPEN, VERGLEICH_SPALTEN, VERLAUF_KENNZAHLEN, _row_for,
    je_bezugsgroesse, point_to_csv,
)

__all__ = [
    "create_app", "lifespan", "validierungsfehler_text", "STATIC_DIR", "RADIUS_CHOICES",
    "GenesisZugang", "Kriterium", "Profil", "PunkteSicherung", "PunktNotiz",
    "PunktSicherung", "SavePoint", "SchaetzEingaben", "VerlaufEintrag",
    "VERGLEICH_GRUPPEN", "VERGLEICH_SPALTEN", "VERLAUF_KENNZAHLEN",
    "je_bezugsgroesse", "point_to_csv",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    settings.ensure_dirs()
    cache = AsyncCache(settings.db_path)
    outbound = Outbound(settings, cache)
    await outbound.start()
    app.state.cache = cache
    app.state.outbound = outbound
    app.state.service = PointService(settings, cache, outbound)
    try:
        yield
    finally:
        await outbound.aclose()


def _name_erlaubt(name: str, erlaubte: tuple[str, ...]) -> bool:
    """Nur Namen, die im Browser wirklich „dieser Rechner" bedeuten.

    DNS-Rebinding braucht zwingend einen DNS-Namen — eine IP-Adresse kann
    niemand umbiegen. Deshalb sind IP-Literale (127.0.0.1, ::1, jede
    LAN-Adresse bei --host 0.0.0.0) und localhost immer erlaubt, alles
    andere nur, wenn es ausdrücklich in GASTROVIEWER_ERLAUBTE_HOSTS steht.
    """
    name = (name or "").strip().lower().rstrip(".")
    if not name:
        return False
    if name == "localhost" or name.endswith(".localhost"):
        return True
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        pass
    return name in erlaubte


def _host_erlaubt(host_header: str, erlaubte: tuple[str, ...]) -> bool:
    """Host-Header ohne Port — auch für IPv6-Literale wie [::1]:8000."""
    try:
        name = urlsplit("//" + (host_header or "").strip()).hostname or ""
    except ValueError:
        return False
    return _name_erlaubt(name, erlaubte)


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(
        title="Standort-Datenterminal",
        description="Offene Daten zu einem Punkt in Deutschland. Daten-Browser, kein Prognose-Tool.",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = settings or get_settings()

    @app.middleware("http")
    async def herkunft_pruefen(request: Request, call_next):
        """Host- und Origin-Prüfung — siehe Settings.erlaubte_hosts.

        Der Host-Header muss zu diesem Rechner passen (sonst 400: das ist
        DNS-Rebinding). Schreibende Anfragen aus einem Browser tragen einen
        Origin-Header; stammt er von einer fremden Seite, ist es CSRF (403).
        Anfragen ohne Origin (curl, die Testsuite, das Startfenster) sind
        keine Browser-Anfragen und bleiben unberührt.
        """
        erlaubte = request.app.state.settings.erlaubte_hosts
        if not _host_erlaubt(request.headers.get("host", ""), erlaubte):
            return JSONResponse(
                {"detail": "Unerwarteter Host-Header — der Server antwortet nur "
                           "unter seiner eigenen Adresse (Schutz gegen "
                           "DNS-Rebinding). Eigene Hostnamen über "
                           "GASTROVIEWER_ERLAUBTE_HOSTS freigeben."},
                status_code=400,
            )
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin is not None:
                try:
                    herkunft = urlsplit(origin).hostname or ""
                except ValueError:
                    herkunft = ""
                if not _name_erlaubt(herkunft, erlaubte):
                    return JSONResponse(
                        {"detail": "Schreibende Anfrage von einer fremden Seite "
                                   "abgelehnt (Schutz gegen CSRF)."},
                        status_code=403,
                    )
        return await call_next(request)

    # Die Routen liegen thematisch getrennt unter gastroviewer/routen/ —
    # Reihenfolge wie dort festgelegt.
    for router in ALLE_ROUTER:
        app.include_router(router)

    # --------------------------------------------------------- Frontend

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

        @app.get("/")
        async def index():
            return FileResponse(STATIC_DIR / "index.html")

        @app.get("/bericht")
        async def bericht():
            """Druckbarer Standortbericht zu einem gemerkten Punkt
            (?punkt=ID). PDF entsteht über die Druckfunktion des Browsers —
            ohne zusätzliche Abhängigkeit."""
            return FileResponse(STATIC_DIR / "bericht.html")

        @app.get("/duell")
        async def duell():
            """Duell-Bericht „A gegen B" (?a=ID&b=ID): zwei gemerkte Punkte
            Spalte an Spalte, mit beiden Lagekarten — die Endauswahl ist fast
            immer ein Zweikampf."""
            return FileResponse(STATIC_DIR / "duell.html")

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(request: Request, exc: RequestValidationError):
        """Eingabefehler als ein deutscher Satz statt als Pydantic-Liste.

        FastAPI antwortet sonst mit ``{"detail": [{loc, msg, type}, …]}`` —
        die Oberfläche zeigt ``detail`` als Text und machte daraus
        „[object Object]". Die deutschen Meldungen aus rechne() erreichte
        nie jemand, weil Pydantic vorher englisch abwies."""
        return JSONResponse(
            status_code=422,
            content={"detail": validierungsfehler_text(exc.errors())},
        )

    @app.exception_handler(500)
    async def on_error(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={"fehler": f"{type(exc).__name__}: {exc}"},
        )

    return app


# ------------------------------------------------------------- Helfer


# Pydantic-Fehlertypen (pydantic-core ``type``) → deutsche Satzteile. Was
# hier fehlt, bekommt die englische Originalmeldung — besser als nichts.
_VALIDIERUNGS_TEXTE = {
    "missing": "fehlt",
    "greater_than": "muss größer als {gt} sein",
    "greater_than_equal": "muss mindestens {ge} sein",
    "less_than": "muss kleiner als {lt} sein",
    "less_than_equal": "darf höchstens {le} sein",
    "int_parsing": "muss eine ganze Zahl sein",
    "int_type": "muss eine ganze Zahl sein",
    "int_from_float": "muss eine ganze Zahl sein",
    "float_parsing": "muss eine Zahl sein",
    "float_type": "muss eine Zahl sein",
    "bool_parsing": "muss ja oder nein sein",
    "bool_type": "muss ja oder nein sein",
    "string_type": "muss ein Text sein",
    "string_too_short": "ist zu kurz (mindestens {min_length} Zeichen)",
    "string_too_long": "ist zu lang (höchstens {max_length} Zeichen)",
    "list_type": "muss eine Liste sein",
    "dict_type": "muss ein Objekt sein",
    "model_attributes_type": "muss ein Objekt sein",
    "model_type": "muss ein Objekt sein",
    "json_invalid": "ist kein gültiges JSON",
    "enum": "hat keinen der erlaubten Werte",
    "literal_error": "hat keinen der erlaubten Werte",
}


def validierungsfehler_text(fehler: list[dict[str, Any]]) -> str:
    """Pydantic-Fehlerliste → ein lesbarer deutscher Satz.

    ``loc`` nennt den Weg zum Feld (``body``/``query`` weggelassen, Indizes
    als ``punkte[2].lat``), ``type`` den Fehler; die Grenzwerte stehen in
    ``ctx``."""
    teile = []
    for f in fehler:
        pfad = ""
        for stueck in f.get("loc") or ():
            if stueck in ("body", "query", "path"):
                continue
            if isinstance(stueck, int):
                pfad += f"[{stueck}]"
            else:
                pfad += ("." if pfad else "") + str(stueck)
        vorlage = _VALIDIERUNGS_TEXTE.get(str(f.get("type")))
        ctx = f.get("ctx") or {}
        if vorlage:
            try:
                text = vorlage.format(**ctx)
            except (KeyError, IndexError):
                text = vorlage
        else:
            text = str(f.get("msg") or "ist ungültig")
        teile.append(f"Feld {pfad}: {text}" if pfad else text)
    if not teile:
        return "Ungültige Eingabe."
    return "Ungültige Eingabe — " + "; ".join(teile) + "."
