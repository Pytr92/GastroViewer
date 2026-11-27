"""Deutsche Ortszeit (zeit.py) — Zoneninfo-Pfad und EU-Rückfallregel.

Die Zeitpunkte sind feste Kalenderfälle der EU-Sommerzeit (Umstellung am
letzten Sonntag im März bzw. Oktober, jeweils 01:00 UTC), keine Messwerte.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from gastroviewer import zeit


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


@pytest.fixture(params=["zoneinfo", "eu_regel"])
def modus(request, monkeypatch):
    """Beide Pfade — der Rückfall wird erzwungen, als fehle tzdata."""
    if request.param == "eu_regel":
        monkeypatch.setattr(zeit, "_berlin_zone", lambda: None)
    elif zeit._berlin_zone() is None:
        pytest.skip("Zeitzonen-Datenbank fehlt (Rückfallpfad deckt den Fall ab)")
    return request.param


def test_halb_eins_mez_ist_schon_der_naechste_tag(modus):
    # 00:30 MEZ = 23:30 UTC des Vortags
    assert zeit.heute_berlin(utc(2026, 1, 14, 23, 30)) == date(2026, 1, 15)
    assert zeit.jetzt_berlin(utc(2026, 1, 14, 23, 30)).hour == 0


def test_halb_zwei_mesz_ist_schon_der_naechste_tag(modus):
    # 01:30 MESZ = 23:30 UTC des Vortags
    assert zeit.heute_berlin(utc(2026, 7, 14, 23, 30)) == date(2026, 7, 15)


def test_silvester_nachts_ist_schon_das_neue_jahr(modus):
    assert zeit.heute_berlin(utc(2026, 12, 31, 23, 30)).year == 2027


def test_umstellung_maerz(modus):
    # 2026: letzter Sonntag im März = 29.03.; Umstellung 01:00 UTC
    vor = zeit.jetzt_berlin(utc(2026, 3, 29, 0, 59))
    nach = zeit.jetzt_berlin(utc(2026, 3, 29, 1, 0))
    assert (vor.hour, vor.minute, vor.utcoffset().total_seconds()) == (1, 59, 3600)
    assert (nach.hour, nach.minute, nach.utcoffset().total_seconds()) == (3, 0, 7200)


def test_umstellung_oktober(modus):
    # 2026: letzter Sonntag im Oktober = 25.10.; Umstellung 01:00 UTC
    vor = zeit.jetzt_berlin(utc(2026, 10, 25, 0, 59))
    nach = zeit.jetzt_berlin(utc(2026, 10, 25, 1, 0))
    assert (vor.hour, vor.minute, vor.utcoffset().total_seconds()) == (2, 59, 7200)
    assert (nach.hour, nach.minute, nach.utcoffset().total_seconds()) == (2, 0, 3600)


def test_letzte_sonntage():
    assert zeit._letzter_sonntag(2026, 3) == date(2026, 3, 29)
    assert zeit._letzter_sonntag(2026, 10) == date(2026, 10, 25)
    assert zeit._letzter_sonntag(2025, 3) == date(2025, 3, 30)
    assert zeit._letzter_sonntag(2024, 10) == date(2024, 10, 27)


def test_ohne_zeitzone_wird_abgelehnt():
    with pytest.raises(ValueError):
        zeit.jetzt_berlin(datetime(2026, 1, 1, 12, 0))


def test_ohne_angabe_gilt_die_uhr(monkeypatch):
    monkeypatch.setattr(zeit, "_utc_jetzt", lambda: utc(2026, 6, 30, 22, 30))
    assert zeit.heute_berlin() == date(2026, 7, 1)


def test_jetzt_mez_ist_ganzjaehrig_utc_plus_1():
    sommer = zeit.jetzt_mez(utc(2026, 8, 8, 8, 30))
    assert (sommer.hour, sommer.minute) == (9, 30)
    assert sommer.utcoffset().total_seconds() == 3600
    winter = zeit.jetzt_mez(utc(2026, 1, 8, 8, 30))
    assert winter.hour == 9
    with pytest.raises(ValueError):
        zeit.jetzt_mez(datetime(2026, 1, 1, 12, 0))
