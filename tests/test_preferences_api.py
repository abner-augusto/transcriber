"""PUT /api/settings/preferences keeps valid values, ignores invalid ones, and persists."""

import json

from fastapi.testclient import TestClient
import pytest

import main


@pytest.fixture
def client(monkeypatch, tmp_path):
    import config
    import preferences

    storage = tmp_path / "storage"
    monkeypatch.setattr(config.settings, "storage_path", str(storage))
    monkeypatch.setattr(preferences, "LEGACY_PREFERENCES_PATH", tmp_path / "no-legacy-file")
    client = TestClient(main.app)
    client.stored = lambda: json.loads((storage / "preferences.json").read_text(encoding="utf-8"))
    return client


def _put(client, body):
    response = client.put("/api/settings/preferences", json=body)
    assert response.status_code == 200
    return response.json()


def test_diarization_keeps_in_bounds_numbers_and_drops_the_rest(client):
    result = _put(client, {
        "diarization": {"clustering_threshold": "0.7", "Fa": 2, "Fb": 99, "ignored": 1},
    })

    expected = {
        "engine": "pyannote", "clustering_threshold": 0.7, "Fa": 2.0,
        "speech_threshold": 0.5, "min_speaker_seconds": 10.0,
    }
    assert client.stored()["diarization"] == expected
    assert result["diarization"] == expected


def test_nemotron_diarization_numbers_are_stored_and_out_of_range_ones_dropped(client):
    result = _put(client, {"diarization": {
        "engine": "nemotron-3-diarization", "speech_threshold": "0.4", "min_speaker_seconds": 2,
    }})

    assert client.stored()["diarization"]["speech_threshold"] == 0.4
    assert client.stored()["diarization"]["min_speaker_seconds"] == 2.0
    assert result["diarization"]["speech_threshold"] == 0.4
    assert result["diarization"]["min_speaker_seconds"] == 2.0

    result = _put(client, {"diarization": {
        "engine": "nemotron-3-diarization", "speech_threshold": 1.5, "min_speaker_seconds": -1,
    }})

    assert result["diarization"]["speech_threshold"] == 0.5
    assert result["diarization"]["min_speaker_seconds"] == 10.0


def test_diarization_engine_accepts_supported_ids_and_ignores_unknown(client):
    assert _put(client, {"diarization": {"engine": "nemotron-3-diarization"}})["diarization"]["engine"] == "nemotron-3-diarization"
    assert _put(client, {"diarization": {"engine": "unknown"}})["diarization"]["engine"] == "nemotron-3-diarization"
    assert _put(client, {"diarization": {"clustering_threshold": 0.4}})["diarization"]["engine"] == "nemotron-3-diarization"


@pytest.mark.parametrize(
    ("sent", "expected"),
    [("0.35", 0.35), ("nan", 0.8), (2.1, 0.8), ("not a number", 0.8)],
)
def test_switch_penalty_keeps_only_a_finite_in_bounds_number(client, sent, expected):
    _put(client, {"speaker_switch_penalty": 0.8})

    result = _put(client, {"speaker_switch_penalty": sent})

    assert client.stored()["speaker_switch_penalty"] == expected
    assert result["speaker_switch_penalty"] == expected


def test_vocabulary_correction_accepts_only_a_boolean(client):
    _put(client, {"vocabulary_correction": {"enabled": False}})
    _put(client, {"vocabulary_correction": {"enabled": "true"}})

    assert client.stored()["vocabulary_correction"] == {"enabled": False}


def test_forced_alignment_accepts_bool_and_dict_wire_shapes(client):
    _put(client, {"forced_alignment": True})
    assert client.stored()["forced_alignment"] == {"enabled": True, "model": "mms-fa", "device": "auto"}

    _put(client, {"forced_alignment": {"enabled": False, "device": "cpu"}})
    assert client.stored()["forced_alignment"] == {"enabled": False, "model": "mms-fa", "device": "cpu"}


def test_default_vocabulary_is_trimmed_and_capped(client):
    _put(client, {"default_vocabulary": "  " + "x" * 2500})

    assert client.stored()["default_vocabulary"] == "x" * 2000


def test_hf_token_is_masked_and_a_masked_echo_does_not_overwrite_it(client):
    result = _put(client, {"hf_auth_token": "hf_secret_value"})
    assert result["hf_auth_token"] == "hf_**********lue"

    _put(client, {"hf_auth_token": result["hf_auth_token"]})

    assert client.stored()["hf_auth_token"] == "hf_secret_value"
    assert client.get("/api/settings").json()["preferences"]["hf_auth_token"] == "hf_**********lue"


def test_settings_payload_lists_both_diarizers(client, monkeypatch):
    import engines
    monkeypatch.setattr(engines, "diarizer_status", lambda _engine, **_kwargs: {
        "state": "ready", "summary": "ready", "checks": [], "fingerprint": "test",
        "available": True, "reason": None,
    })
    payload = client.get("/api/settings").json()
    assert [item["id"] for item in payload["diarizers"]] == ["pyannote", "nemotron-3-diarization"]
    assert all(item["state"] == "ready" for item in payload["diarizers"])


def test_source_roots_keep_absolute_folders_and_drop_the_rest(client, tmp_path):
    folder = str(tmp_path / "projects")

    result = _put(client, {"source_roots": [folder, "relative/dir", "", 7, folder]})

    assert result["source_roots"] == [folder]
    assert client.stored()["source_roots"] == [folder]
    assert _put(client, {})["source_roots"] == [folder]  # absent: kept
    assert _put(client, {"source_roots": []})["source_roots"] == []
