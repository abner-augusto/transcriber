from main import update_preferences


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
