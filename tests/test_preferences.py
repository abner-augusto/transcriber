import json
from pathlib import Path

import pytest

from preferences import (
    DEFAULT_SPEAKER_SWITCH_PENALTY,
    PreferenceMigrationError,
    load,
    public,
    update,
)


def test_fresh_preferences_use_defaults_and_create_the_canonical_file(tmp_path):
    storage = tmp_path / "storage"
    legacy = tmp_path / "preferences.json"

    prefs = load(storage_dir=storage, legacy_preferences_path=legacy)

    assert prefs.default_preset is None
    assert prefs.default_vocabulary == ""
    assert prefs.speaker_profiles_enabled is False
    assert prefs.speaker_switch_penalty == DEFAULT_SPEAKER_SWITCH_PENALTY
    assert (storage / "preferences.json").exists()


@pytest.mark.parametrize(
    ("root_data", "settings_data", "expected"),
    [
        ({"default_vocabulary": "áudio"}, None, {"default_vocabulary": "áudio"}),
        (None, {"default_preset": "preset-a"}, {"default_preset": "preset-a"}),
        (
            {"default_vocabulary": "áudio", "default_preset": "root-preset"},
            {"default_preset": "storage-preset"},
            {"default_vocabulary": "áudio", "default_preset": "storage-preset"},
        ),
    ],
)
def test_legacy_sources_migrate_and_are_renamed(tmp_path, root_data, settings_data, expected):
    storage = tmp_path / "storage"
    storage.mkdir()
    legacy = tmp_path / "preferences.json"
    if root_data is not None:
        legacy.write_text(json.dumps(root_data), encoding="utf-8")
    if settings_data is not None:
        (storage / "settings.json").write_text(json.dumps(settings_data), encoding="utf-8")

    prefs = load(storage_dir=storage, legacy_preferences_path=legacy)

    assert {key: getattr(prefs, key) for key in expected} == expected
    assert (storage / "preferences.json").exists()
    if root_data is not None:
        assert (tmp_path / "preferences.json.migrated").exists()
    if settings_data is not None:
        assert (storage / "settings.json.migrated").exists()


def test_migration_drops_only_out_of_bounds_values_and_keeps_valid_values(tmp_path, caplog):
    storage = tmp_path / "storage"
    legacy = tmp_path / "preferences.json"
    legacy.write_text(json.dumps({
        "default_vocabulary": "valid",
        "speaker_switch_penalty": 9,
        "diarization": {"clustering_threshold": 0.4, "Fa": 9},
    }), encoding="utf-8")

    prefs = load(storage_dir=storage, legacy_preferences_path=legacy)

    assert prefs.default_vocabulary == "valid"
    assert prefs.speaker_switch_penalty == DEFAULT_SPEAKER_SWITCH_PENALTY
    assert prefs.diarization.clustering_threshold == 0.4
    assert prefs.diarization.Fa is None
    assert "out-of-bounds" in caplog.text


def test_migration_stops_without_renaming_when_a_value_cannot_be_preserved(tmp_path):
    storage = tmp_path / "storage"
    legacy = tmp_path / "preferences.json"
    legacy.write_text(json.dumps({"vocabulary_profiles": [{"name": "missing id"}]}), encoding="utf-8")

    with pytest.raises(PreferenceMigrationError):
        load(storage_dir=storage, legacy_preferences_path=legacy)

    assert legacy.exists()
    assert not (tmp_path / "preferences.json.migrated").exists()
    assert not (storage / "preferences.json").exists()


def test_migration_stops_on_any_other_unmodeled_field(tmp_path):
    storage = tmp_path / "storage"
    legacy = tmp_path / "preferences.json"
    legacy.write_text(json.dumps({"future_setting": "keep me"}), encoding="utf-8")

    with pytest.raises(PreferenceMigrationError):
        load(storage_dir=storage, legacy_preferences_path=legacy)

    assert legacy.exists()
    assert not (storage / "preferences.json").exists()


def test_migration_archives_retired_llm_key_without_activating_or_disclosing_it(tmp_path, caplog):
    storage = tmp_path / "storage"
    legacy = tmp_path / "preferences.json"
    original = b'{"default_vocabulary":"kept","llm_api_key":"test-secret-value"}\n'
    legacy.write_bytes(original)

    prefs = load(storage_dir=storage, legacy_preferences_path=legacy)
    active_data = json.loads((storage / "preferences.json").read_text(encoding="utf-8"))

    assert prefs.default_vocabulary == "kept"
    assert "llm_api_key" not in active_data
    assert (tmp_path / "preferences.json.migrated").read_bytes() == original
    assert "test-secret-value" not in caplog.text


def test_archive_rename_failure_keeps_the_migrated_preferences(tmp_path, monkeypatch):
    storage = tmp_path / "storage"
    storage.mkdir()
    legacy = tmp_path / "preferences.json"
    legacy_bytes = b'{ "default_vocabulary": "kept" }\n'
    settings = storage / "settings.json"
    settings.write_bytes(b'{ "default_preset": "preset-a" }\n')
    legacy.write_bytes(legacy_bytes)

    original_replace = Path.replace

    def failing_archive(source, target):
        if str(target).endswith(".migrated"):
            raise OSError("simulated archive rename failure")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", failing_archive)
    prefs = load(storage_dir=storage, legacy_preferences_path=legacy)
    monkeypatch.setattr(Path, "replace", original_replace)

    assert (prefs.default_vocabulary, prefs.default_preset) == ("kept", "preset-a")
    assert legacy.read_bytes() == legacy_bytes
    assert load(storage_dir=storage, legacy_preferences_path=legacy) == prefs


def test_deleting_the_preferences_file_resets_to_defaults_after_migration(tmp_path):
    storage = tmp_path / "storage"
    legacy = tmp_path / "preferences.json"
    legacy.write_text(json.dumps({"default_vocabulary": "old value"}), encoding="utf-8")
    assert load(storage_dir=storage, legacy_preferences_path=legacy).default_vocabulary == "old value"

    (storage / "preferences.json").unlink()

    assert load(storage_dir=storage, legacy_preferences_path=legacy).default_vocabulary == ""


def test_second_load_does_not_migrate_again(tmp_path):
    storage = tmp_path / "storage"
    legacy = tmp_path / "preferences.json"
    legacy.write_text(json.dumps({"default_vocabulary": "first"}), encoding="utf-8")
    first = load(storage_dir=storage, legacy_preferences_path=legacy)
    legacy.write_text(json.dumps({"default_vocabulary": "second"}), encoding="utf-8")

    second = load(storage_dir=storage, legacy_preferences_path=legacy)

    assert first.default_vocabulary == second.default_vocabulary == "first"
    assert json.loads((storage / "preferences.json").read_text(encoding="utf-8"))["default_vocabulary"] == "first"


def test_update_validates_merged_preferences_and_rejects_unknown_fields(tmp_path):
    storage = tmp_path / "storage"
    legacy = tmp_path / "no-legacy.json"
    load(storage_dir=storage, legacy_preferences_path=legacy)
    changed = update({"speaker_profiles_enabled": True}, storage_dir=storage)

    assert changed.speaker_profiles_enabled is True
    with pytest.raises(ValueError):
        update({"typo": True}, storage_dir=storage)


def test_public_preferences_mask_secret_and_preserve_settings_wire_shape(tmp_path):
    storage = tmp_path / "storage"
    storage.mkdir()
    (storage / "preferences.json").write_text(json.dumps({
        "default_preset": "preset-a",
        "hf_auth_token": "hf-abcdefghijk",
    }), encoding="utf-8")

    result = public(storage_dir=storage)

    assert result["hf_auth_token"] == "hf-**********ijk"
    assert "default_preset" not in result
    assert set(result) == {
        "default_vocabulary", "speaker_profiles_enabled", "hf_auth_token",
        "speaker_switch_penalty", "forced_alignment", "whisper_dtw",
        "diarization", "vocabulary_profiles", "vocabulary_correction",
    }
    assert result["diarization"]["engine"] == "pyannote"
