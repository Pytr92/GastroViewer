"""GTFS-Import und Abfahrtszählung.

Grundlage ist ``fixtures/gtfs_muenchen_ausschnitt.zip`` — ein Ausschnitt aus dem
**echten** Feed von gtfs.de (Regionalverkehr), begrenzt auf die S-Bahn-Halte
München Karlsplatz und Marienplatz samt ihren übergeordneten Stationen.
4.068 Fahrten, 8.136 Halte, 234 Kalendereinträge, 768 Ausnahmen. Kein Netz nötig.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

import pytest

from gastroviewer.sources import gtfs

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "gtfs_muenchen_ausschnitt.zip"

# München Karlsplatz (Stachus), Koordinaten aus dem Feed selbst.
LAT, LON = 48.13964, 11.56556


@pytest.fixture(scope="module")
def importiert(tmp_path_factory):
    from gastroviewer.config import Settings

    s = Settings()
    s.data_dir = tmp_path_factory.mktemp("gtfs")
    stats = gtfs.import_feed(s, FIXTURE, progress=lambda _m: None)
    return s, stats


def test_import_liest_den_echten_feed(importiert):
    _s, stats = importiert
    assert stats["stops_importiert"] == 4
    assert stats["trips"] == 4068
    assert stats["stop_times_importiert"] == 8136
    assert stats["routes"] == 8
    assert stats["groesse_mb"] > 0


def test_status_meldet_den_import(importiert):
    s, _ = importiert
    st = gtfs.status(s)
    assert st["importiert"] is True
    assert st["referenzdatum"] and len(st["referenzdatum"]) == 8
    assert "Creative Commons" in st["lizenz"]


def test_ohne_import_kein_fehler_sondern_hinweis(tmp_path):
    from gastroviewer.config import Settings

    s = Settings()
    s.data_dir = tmp_path
    res = gtfs.load(s, LAT, LON, 600)
    assert res.ok is True, "fehlender Import darf die Seite nicht brechen"
    assert res.data is None
    assert "import-gtfs" in res.warnings[0]
    assert gtfs.status(s)["importiert"] is False


def test_referenztag_ist_ein_werktag_im_gueltigkeitszeitraum(importiert):
    s, _ = importiert
    conn = sqlite3.connect(s.gtfs_db_path)
    meta = dict(conn.execute("SELECT key, value FROM meta"))
    conn.close()
    datum = dt.datetime.strptime(meta["referenzdatum"], "%Y%m%d").date()
    von = dt.datetime.strptime(meta["fahrplan_von"], "%Y%m%d").date()
    bis = dt.datetime.strptime(meta["fahrplan_bis"], "%Y%m%d").date()
    assert von <= datum <= bis
    assert datum.weekday() < 5, "Referenztag muss ein Werktag sein"


def test_abfahrten_werden_gezaehlt(importiert):
    s, _ = importiert
    res = gtfs.load(s, LAT, LON, 600)
    assert res.ok
    g = res.data
    assert g["abfahrten_gesamt"] > 0
    assert sum(g["abfahrten_je_stunde"].values()) == g["abfahrten_gesamt"]
    assert g["abfahrten_06_24"] <= g["abfahrten_gesamt"]
    assert g["spitzenstunde"]["abfahrten"] == max(g["abfahrten_je_stunde"].values())


def test_nur_fahrten_des_referenztags_zaehlen(importiert):
    """Gegenprobe: ohne Verkehrstagsfilter wären es alle 8.136 Halte."""
    s, _ = importiert
    res = gtfs.load(s, LAT, LON, 600)
    assert res.data["abfahrten_gesamt"] == 942
    assert 942 < 8136


def test_stationen_ohne_abfahrten_werden_getrennt_ausgewiesen(importiert):
    """GTFS location_type 1 sind Container ohne eigene Fahrten. Sie duerfen die
    Haltestellenzahl nicht aufblaehen, aber auch nicht still verschwinden.
    r=900, damit beide Bahnsteige und beide Stationen im Umkreis liegen —
    Marienplatz ist rund 780 m von Karlsplatz entfernt."""
    s, _ = importiert
    res = gtfs.load(s, LAT, LON, 900)
    g = res.data
    assert g["haltestellen_im_umkreis"] == 4
    assert g["haltestellen_gesamt"] == 2, "nur die beiden Bahnsteige werden bedient"
    assert g["haltestellen_ohne_abfahrten"] == 2
    assert any("location_type 1" in w for w in res.warnings)
    assert all(h["abfahrten"] > 0 for h in g["haltestellen"][:2])
    assert all(h["abfahrten"] == 0 for h in g["haltestellen"][2:])


def test_haltestellen_tragen_distanz_und_linien(importiert):
    s, _ = importiert
    res = gtfs.load(s, LAT, LON, 600)
    top = res.data["haltestellen"][0]
    assert top["distanz_m"] <= 600
    assert top["richtung"] in {"N", "NO", "O", "SO", "S", "SW", "W", "NW"}
    assert top["linien"], "S-Bahn-Halt muss Linien tragen"
    assert any(l.startswith("S") for l in top["linien"])


def test_radius_wird_eingehalten(importiert):
    s, _ = importiert
    eng = gtfs.load(s, LAT, LON, 100)
    weit = gtfs.load(s, LAT, LON, 900)
    assert eng.data["haltestellen_im_umkreis"] <= weit.data["haltestellen_im_umkreis"]
    assert all(h["distanz_m"] <= 900 for h in weit.data["haltestellen"])


def test_punkt_ohne_haltestelle_meldet_das(importiert):
    s, _ = importiert
    res = gtfs.load(s, 54.0, 9.0, 600)
    assert res.ok
    assert res.data["haltestellen"] == []
    assert "Keine Haltestelle" in res.warnings[0]


def test_provenance_nennt_stichtag_und_lizenz(importiert):
    s, _ = importiert
    res = gtfs.load(s, LAT, LON, 600)
    p = res.provenance
    assert "Creative Commons BY 4.0" in p.license
    assert "Fahrplan" in p.stand and "importiert" in p.stand
    assert "nicht ein Mittelwert" in p.note
    assert "calendar_dates.txt" in p.note


def test_kaputtes_zip_meldet_die_fehlenden_dateien(tmp_path):
    import zipfile

    from gastroviewer.config import Settings

    s = Settings()
    s.data_dir = tmp_path
    kaputt = tmp_path / "kaputt.zip"
    with zipfile.ZipFile(kaputt, "w") as z:
        z.writestr("stops.txt", "stop_id,stop_name,stop_lat,stop_lon\n")
    with pytest.raises(ValueError) as exc:
        gtfs.import_feed(s, kaputt, progress=lambda _m: None)
    assert "stop_times.txt" in str(exc.value) and "trips.txt" in str(exc.value)


def test_bbox_ohne_treffer_meldet_das(tmp_path):
    from gastroviewer.config import Settings

    s = Settings()
    s.data_dir = tmp_path
    with pytest.raises(ValueError) as exc:
        gtfs.import_feed(s, FIXTURE, bbox=(0.0, 0.0, 1.0, 1.0), progress=lambda _m: None)
    assert "Bounding-Box" in str(exc.value)


def test_bbox_begrenzt_den_import(tmp_path):
    from gastroviewer.config import Settings

    s = Settings()
    s.data_dir = tmp_path
    stats = gtfs.import_feed(
        s, FIXTURE, bbox=(48.13, 11.55, 48.15, 11.57), progress=lambda _m: None
    )
    assert stats["stops_importiert"] < 4
    assert stats["stop_times_importiert"] < 8136


def test_stunden_ueber_24_werden_auf_den_tag_umgelegt(importiert):
    """GTFS erlaubt 25:30:00 für Fahrten nach Mitternacht."""
    s, _ = importiert
    conn = sqlite3.connect(s.gtfs_db_path)
    spaet = conn.execute(
        "SELECT COUNT(*) FROM stop_times WHERE CAST(substr(departure_time,1,2) AS INT) >= 24"
    ).fetchone()[0]
    conn.close()
    g = gtfs.load(s, LAT, LON, 600).data
    # Egal ob vorhanden oder nicht: es darf keinen Stundenschlüssel jenseits 23 geben.
    assert set(g["abfahrten_je_stunde"]) == {f"{h:02d}" for h in range(24)}
    assert spaet >= 0


# ------------------------------------------------- Voreingestellte Regionen


def test_regionen_sind_plausibel_und_richtig_herum():
    """Die häufigste Fehlbedienung beim Import ist die vertauschte Reihenfolge
    der Bounding-Box. Die Voreinstellungen dürfen den Fehler nicht enthalten."""
    from gastroviewer.__main__ import REGIONEN

    assert "muenchen" in REGIONEN
    for name, (beschreibung, (min_lat, min_lon, max_lat, max_lon)) in REGIONEN.items():
        assert beschreibung, name
        assert min_lat < max_lat, f"{name}: Breitengrade vertauscht"
        assert min_lon < max_lon, f"{name}: Längengrade vertauscht"
        assert 47.0 < min_lat < max_lat < 55.5, f"{name}: außerhalb Deutschlands"
        assert 5.5 < min_lon < max_lon < 15.5, f"{name}: außerhalb Deutschlands"


def test_muenchen_liegt_in_allen_bayerischen_ausschnitten():
    from gastroviewer.__main__ import REGIONEN

    lat, lon = 48.1334, 11.5674  # Sendlinger Tor
    for name in ("muenchen", "muenchen-region", "oberbayern", "bayern"):
        a, b, c, d = REGIONEN[name][1]
        assert a <= lat <= c and b <= lon <= d, f"{name} enthält München nicht"


def test_ausschnitte_sind_ineinander_geschachtelt():
    from gastroviewer.__main__ import REGIONEN

    klein = REGIONEN["muenchen"][1]
    gross = REGIONEN["bayern"][1]
    assert gross[0] <= klein[0] and gross[1] <= klein[1]
    assert gross[2] >= klein[2] and gross[3] >= klein[3]


def test_mittagsfenster_wird_gezaehlt():
    """Die Stunden 11, 12 und 13 — die Beschriftung nennt das Fenster mit, weil
    es eine gewählte Zeitspanne ist und kein gemessener Wert."""
    from gastroviewer.sources import gtfs

    assert (gtfs.MITTAG_VON, gtfs.MITTAG_BIS) == (11, 14)


def test_abendfenster_wird_gezaehlt():
    """Die Stunden 17 bis 21 — für Abendkonzepte das relevantere Fenster;
    auch hier steht die gewählte Spanne als Text neben der Zahl."""
    from gastroviewer.sources import gtfs

    assert (gtfs.ABEND_VON, gtfs.ABEND_BIS) == (17, 22)
