from main import update_preferences
from preferences import DEFAULT_SPEAKER_SWITCH_PENALTY, get_speaker_switch_penalty


def test_update_preferences_persists_sanitized_diarization(monkeypatch):
    saved = {}
    monkeypatch.setattr("preferences.load_preferences", lambda: {})
    monkeypatch.setattr("preferences.save_preferences", lambda value: saved.update(value))
    monkeypatch.setattr("preferences.get_public_preferences", lambda: saved)

    result = update_preferences({
        "diarization": {
            "clustering_threshold": "0.7",
            "Fa": 2,
            "Fb": 99,
            "ignored": 1,
        }
    })

    assert saved["diarization"] == {"clustering_threshold": 0.7, "Fa": 2.0}
    assert result["diarization"] == saved["diarization"]


def test_update_preferences_persists_bounded_switch_penalty(monkeypatch):
    saved = {}
    monkeypatch.setattr("preferences.load_preferences", lambda: {})
    monkeypatch.setattr("preferences.save_preferences", lambda value: saved.update(value))
    monkeypatch.setattr("preferences.get_public_preferences", lambda: saved)

    result = update_preferences({"speaker_switch_penalty": "0.35"})

    assert saved["speaker_switch_penalty"] == 0.35
    assert result["speaker_switch_penalty"] == 0.35


def test_invalid_stored_switch_penalty_uses_default(monkeypatch):
    monkeypatch.setattr("preferences.load_preferences", lambda: {"speaker_switch_penalty": float("nan")})

    assert get_speaker_switch_penalty() == DEFAULT_SPEAKER_SWITCH_PENALTY


def test_public_preferences_sanitizes_invalid_stored_switch_penalty(monkeypatch):
    monkeypatch.setattr("preferences.load_preferences", lambda: {"speaker_switch_penalty": 99})

    from preferences import get_public_preferences

    assert get_public_preferences()["speaker_switch_penalty"] == DEFAULT_SPEAKER_SWITCH_PENALTY


def test_update_preferences_ignores_invalid_switch_penalty(monkeypatch):
    saved = {"speaker_switch_penalty": 0.8}
    monkeypatch.setattr("preferences.load_preferences", lambda: dict(saved))
    monkeypatch.setattr("preferences.save_preferences", lambda value: saved.update(value))
    monkeypatch.setattr("preferences.get_public_preferences", lambda: saved)

    update_preferences({"speaker_switch_penalty": "nan"})
    update_preferences({"speaker_switch_penalty": 2.1})

    assert saved["speaker_switch_penalty"] == 0.8
