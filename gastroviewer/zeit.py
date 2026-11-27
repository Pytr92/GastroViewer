"""Deutsche Ortszeit (Europe/Berlin) für „heute“, Jahr und Datenalter.

Rund um Mitternacht liegt UTC ein bis zwei Stunden hinter der deutschen
Zeit; wer „heute“ aus UTC nimmt, rechnet dann mit dem Vortag (oder zu
Silvester mit dem alten Jahr). Alle Kalendertag-, Jahres- und
Altersrechnungen laufen deshalb über diese Hilfen.

Zuerst wird ``zoneinfo`` mit ``Europe/Berlin`` versucht. Fehlt die
Zeitzonen-Datenbank (Windows ohne ``tzdata``, z. B. im PyInstaller-Paket),
gilt die EU-Sommerzeitregel: MESZ (UTC+2) vom letzten Sonntag im März,
01:00 UTC, bis zum letzten Sonntag im Oktober, 01:00 UTC; sonst MEZ (UTC+1).

Zum Testen nehmen die Funktionen optional einen Zeitpunkt ``jetzt``
(aware, beliebige Zone); ohne Angabe gilt die Systemuhr (``_utc_jetzt``).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

try:  # zoneinfo gibt es ab Python 3.9; die Datenbank kann trotzdem fehlen
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover - Python < 3.9 wird nicht unterstützt
    ZoneInfo = None  # type: ignore[assignment,misc]

    class ZoneInfoNotFoundError(Exception):  # type: ignore[no-redef]
        pass

MEZ = timezone(timedelta(hours=1), "MEZ")
MESZ = timezone(timedelta(hours=2), "MESZ")


def _utc_jetzt() -> datetime:
    """Systemuhr als aware-UTC (eigene Funktion, damit Tests sie ersetzen können)."""
    return datetime.now(timezone.utc)


def _letzter_sonntag(jahr: int, monat: int) -> date:
    """Letzter Sonntag des Monats (März und Oktober haben je 31 Tage)."""
    letzter = date(jahr, monat, 31)
    return letzter - timedelta(days=(letzter.weekday() + 1) % 7)


def _berlin_zone():
    """``ZoneInfo('Europe/Berlin')`` oder None, wenn die Datenbank fehlt."""
    if ZoneInfo is None:  # pragma: no cover
        return None
    try:
        return ZoneInfo("Europe/Berlin")
    except (ZoneInfoNotFoundError, ImportError, OSError):
        return None


def _offset_eu(utc: datetime) -> timezone:
    """MEZ/MESZ nach EU-Regel für einen aware-UTC-Zeitpunkt."""
    jahr = utc.year
    beginn = datetime.combine(_letzter_sonntag(jahr, 3), datetime.min.time(),
                              tzinfo=timezone.utc) + timedelta(hours=1)
    ende = datetime.combine(_letzter_sonntag(jahr, 10), datetime.min.time(),
                            tzinfo=timezone.utc) + timedelta(hours=1)
    return MESZ if beginn <= utc < ende else MEZ


def jetzt_berlin(jetzt: datetime | None = None) -> datetime:
    """Aktuelle deutsche Ortszeit als aware-datetime.

    ``jetzt``: optionaler aware-Zeitpunkt (für Tests); ohne Angabe die Uhr."""
    if jetzt is None:
        jetzt = _utc_jetzt()
    if jetzt.tzinfo is None:
        raise ValueError("jetzt muss eine Zeitzone tragen (aware datetime).")
    utc = jetzt.astimezone(timezone.utc)
    zone = _berlin_zone()
    if zone is not None:
        return utc.astimezone(zone)
    return utc.astimezone(_offset_eu(utc))


def jetzt_mez(jetzt: datetime | None = None) -> datetime:
    """Aktuelle Zeit in festem MEZ (UTC+1, ohne Sommerzeit) als aware-datetime.

    Für Quellen, die ganzjährig in MEZ stempeln (z. B. UBA-Luftdaten)."""
    if jetzt is None:
        jetzt = _utc_jetzt()
    if jetzt.tzinfo is None:
        raise ValueError("jetzt muss eine Zeitzone tragen (aware datetime).")
    return jetzt.astimezone(MEZ)


def heute_berlin(jetzt: datetime | None = None) -> date:
    """Heutiges Kalenderdatum in Deutschland."""
    return jetzt_berlin(jetzt).date()
