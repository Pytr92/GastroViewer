"""Helfer ``features_aus``: Fehlerobjekte sind Ausfall, nie „0 Treffer"."""

from __future__ import annotations

import pytest

from gastroviewer.sources.base import SourceError, features_aus


def test_leere_featurecollection_ist_gueltig():
    assert features_aus({"type": "FeatureCollection", "features": []}, "X") == []


def test_features_werden_durchgereicht():
    f = [{"type": "Feature"}]
    assert features_aus({"features": f}, "X") is f


@pytest.mark.parametrize("payload", [[], "text", None, 5])
def test_nicht_dict_ist_fehler(payload):
    with pytest.raises(SourceError) as e:
        features_aus(payload, "Quelle1")
    assert e.value.kind == "parse"
    assert "Quelle1" in e.value.message


def test_fehlendes_features_ist_fehler():
    with pytest.raises(SourceError) as e:
        features_aus({"type": "FeatureCollection"}, "X")
    assert e.value.kind == "parse" and "features" in e.value.message


@pytest.mark.parametrize("wert", [None, {}, "abc", 3])
def test_features_kein_list_ist_fehler(wert):
    with pytest.raises(SourceError) as e:
        features_aus({"features": wert}, "X")
    assert e.value.kind == "parse"


def test_fehlerobjekt_wird_zitiert():
    # Minimal konstruiert: typisches JSON-Fehlerobjekt eines Kartendienstes.
    with pytest.raises(SourceError) as e:
        features_aus({"error": {"code": 400, "message": "Invalid bbox"}}, "X")
    assert "Invalid bbox" in e.value.message
