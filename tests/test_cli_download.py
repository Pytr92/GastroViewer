"""CLI-Download: Zeitgrenze und verständliche Fehler statt Traceback."""

from __future__ import annotations

import io
import urllib.error

import pytest

from gastroviewer import __main__ as cli


class _Antwort(io.BytesIO):
    headers = {"Content-Length": "5"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_download_uebergibt_timeout(monkeypatch, tmp_path):
    gesehen = {}

    def fake(url, *args, **kwargs):
        gesehen.update(kwargs)
        return _Antwort(b"hallo")

    monkeypatch.setattr(cli.urllib.request, "urlopen", fake)
    ziel = cli._download("https://example.invalid/x.zip", tmp_path / "x.zip")
    assert gesehen["timeout"] == cli.DOWNLOAD_TIMEOUT_S > 0
    assert ziel.read_bytes() == b"hallo"


@pytest.mark.parametrize(
    "fehler, erwartet",
    [
        (TimeoutError("timed out"), "Zeitüberschreitung"),
        (urllib.error.URLError("Name or service not known"), "Download fehlgeschlagen"),
    ],
)
def test_download_fehler_ohne_traceback(monkeypatch, tmp_path, capsys, fehler, erwartet):
    def fake(url, *args, **kwargs):
        raise fehler

    monkeypatch.setattr(cli.urllib.request, "urlopen", fake)
    with pytest.raises(SystemExit) as ende:
        cli._download("https://example.invalid/x.zip", tmp_path / "x.zip")
    assert ende.value.code == 1
    assert erwartet in capsys.readouterr().err


def test_http_fehler_nennt_statuscode(monkeypatch, tmp_path, capsys):
    def fake(url, *args, **kwargs):
        raise urllib.error.HTTPError(url, 503, "Service Unavailable", {}, None)

    monkeypatch.setattr(cli.urllib.request, "urlopen", fake)
    with pytest.raises(SystemExit):
        cli._download("https://example.invalid/x.zip", tmp_path / "x.zip")
    assert "HTTP 503" in capsys.readouterr().err


def test_abgebrochener_download_raeumt_tempverzeichnis_auf(monkeypatch, tmp_path):
    import argparse
    import tempfile

    from gastroviewer.config import Settings

    angelegt = []
    echt = tempfile.mkdtemp

    def mk(*a, **kw):
        d = echt(*a, dir=tmp_path, **{k: v for k, v in kw.items() if k != "dir"})
        angelegt.append(d)
        return d

    def fake(url, *args, **kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(cli.tempfile, "mkdtemp", mk)
    monkeypatch.setattr(cli.urllib.request, "urlopen", fake)
    args = argparse.Namespace(
        region=None, bbox=None, file=None, url="https://example.invalid/g.zip", keep=False
    )
    with pytest.raises(SystemExit):
        cli.cmd_import_gtfs(args, Settings(data_dir=tmp_path / "d"))
    assert len(angelegt) == 1
    assert not __import__("os").path.exists(angelegt[0])
