from copy import deepcopy

import preferences
from main import update_preferences
from preferences import Preferences


def _install_store(monkeypatch, values=None):
    saved = Preferences.model_validate(values or {}).model_dump(mode="json", exclude_none=True)

    def load():
        return Preferences.model_validate(deepcopy(saved))

    def update(patch):
        saved.update(deepcopy(patch))
        validated = Preferences.model_validate(saved).model_dump(mode="json", exclude_none=True)
        saved.clear()
        saved.update(validated)
        return Preferences.model_validate(saved)

    monkeypatch.setattr(preferences, "load", load)
    monkeypatch.setattr(preferences, "update", update)
    monkeypatch.setattr(preferences, "public", lambda: deepcopy(saved))
    return saved


def test_update_preferences_persists_sanitized_diarization(monkeypatch):
    saved = _install_store(monkeypatch)

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
    saved = _install_store(monkeypatch)

    result = update_preferences({"speaker_switch_penalty": "0.35"})

    assert saved["speaker_switch_penalty"] == 0.35
    assert result["speaker_switch_penalty"] == 0.35


def test_update_preferences_ignores_invalid_switch_penalty(monkeypatch):
    saved = _install_store(monkeypatch, {"speaker_switch_penalty": 0.8})

    update_preferences({"speaker_switch_penalty": "nan"})
    update_preferences({"speaker_switch_penalty": 2.1})

    assert saved["speaker_switch_penalty"] == 0.8


def test_vocabulary_correction_preference_accepts_only_a_boolean(monkeypatch):
    saved = _install_store(monkeypatch)

    update_preferences({"vocabulary_correction": {"enabled": False}})
    assert saved["vocabulary_correction"] == {"enabled": False}
    update_preferences({"vocabulary_correction": {"enabled": "false"}})
    assert saved["vocabulary_correction"] == {"enabled": False}


def test_forced_alignment_preserves_bool_and_dict_wire_shapes(monkeypatch):
    saved = _install_store(monkeypatch)

    update_preferences({"forced_alignment": True})
    assert saved["forced_alignment"] == {"enabled": True, "model": "mms-fa", "device": "auto"}
    update_preferences({"forced_alignment": {"enabled": False, "model": "mms-fa", "device": "cpu"}})
    assert saved["forced_alignment"] == {"enabled": False, "model": "mms-fa", "device": "cpu"}
