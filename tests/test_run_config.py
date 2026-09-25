import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import Job, JobType, Meeting, MeetingStatus
from preferences import (
    DiarizationPrefs,
    ForcedAlignmentPrefs,
    Preferences,
    VocabularyCorrectionPrefs,
    WhisperDtwPrefs,
)
from run_config import RunConfig, resolve_run_config


@pytest.mark.parametrize(
    ("preset_alignment", "expected_model", "expected_device"),
    [
        (None, "mms-fa", "auto"),
        (True, "mms-fa", "auto"),
        ({"model": "mms-fa", "device": "cpu"}, "mms-fa", "cpu"),
    ],
)
def test_run_config_resolves_result_choices_without_secrets(
    monkeypatch, preset_alignment, expected_model, expected_device
):
    import presets

    preset = {
        "id": "preset-a", "engine": "whisper.cpp", "model_path": "models/model.bin",
        "dtw": False, "forced_alignment": preset_alignment,
    }
    monkeypatch.setattr(presets, "resolve_preset", lambda preset_id, **kwargs: preset)
    prefs = Preferences(
        hf_auth_token="hf-secret",
        forced_alignment=ForcedAlignmentPrefs(enabled=True, device="auto"),
        whisper_dtw=WhisperDtwPrefs(enabled=True, preset="large.v3"),
        diarization=DiarizationPrefs(clustering_threshold=0.62),
        speaker_switch_penalty=0.4,
        speaker_profiles_enabled=True,
        vocabulary_correction=VocabularyCorrectionPrefs(enabled=False),
    )

    config = resolve_run_config(Meeting(preset_id="preset-a"), preferences=prefs)
    stored = config.model_dump(mode="json", exclude_none=True)

    assert config.preset == preset
    assert config.forced_alignment is not None
    assert config.forced_alignment.model == expected_model
    assert config.forced_alignment.device == expected_device
    assert config.whisper_dtw.enabled is False
    assert config.whisper_dtw.preset == "large.v3"
    assert config.diarization.clustering_threshold == 0.62
    assert config.speaker_switch_penalty == 0.4
    assert config.speaker_profiles_enabled is True
    assert config.vocabulary_correction.enabled is False
    assert "hf_auth_token" not in stored


def test_run_config_uses_preference_dtw_when_preset_does_not_override(monkeypatch):
    import presets

    preset = {"id": "preset-a", "engine": "whisper.cpp", "model_path": "model.bin"}
    monkeypatch.setattr(presets, "resolve_preset", lambda preset_id, **kwargs: preset)

    config = resolve_run_config(
        Meeting(preset_id="preset-a"),
        preferences=Preferences(whisper_dtw=WhisperDtwPrefs(enabled=False, preset="medium")),
    )

    assert config.whisper_dtw == WhisperDtwPrefs(enabled=False, preset="medium")


@pytest.mark.parametrize("job_type", list(JobType))
def test_every_job_persists_its_run_config_when_it_starts(monkeypatch, tmp_path, job_type):
    from jobs import running
    from jobs.runners import InProcessBus
    import jobs

    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    jobs.configure(session_factory=session_factory, progress_bus=InProcessBus())

    config = RunConfig(
        preset={"id": "p", "engine": "test", "model_path": "model.bin"},
        whisper_dtw=WhisperDtwPrefs(),
        diarization=DiarizationPrefs(),
        speaker_switch_penalty=0.5,
        speaker_profiles_enabled=False,
        vocabulary_correction=VocabularyCorrectionPrefs(),
    )
    monkeypatch.setattr("run_config.resolve_run_config", lambda meeting: config)
    with session_factory() as db:
        meeting = Meeting(title="RunConfig", status=MeetingStatus.UPLOADED)
        db.add(meeting)
        db.flush()
        job = Job(meeting_id=meeting.id, job_type=job_type)
        db.add(job)
        db.commit()
        meeting_id, job_id = meeting.id, job.id

    with running(meeting_id, job_id) as (db, meeting, job):
        assert job.run_config == config.model_dump(mode="json", exclude_none=True)

    with session_factory() as db:
        job = db.get(Job, job_id)
        assert job.run_config["preset"]["id"] == "p"
        assert "hf_auth_token" not in job.run_config
        assert job.to_dict()["run_config"] == job.run_config


def test_default_preset_is_stored_in_preferences_only(tmp_path, monkeypatch):
    import config
    import presets

    storage = tmp_path / "storage"
    storage.mkdir()
    (storage / "preferences.json").write_text(
        json.dumps(Preferences().model_dump(mode="json", exclude_none=True)), encoding="utf-8"
    )
    preset_dir = tmp_path / "presets"
    preset_dir.mkdir()
    (preset_dir / "preset-a.json").write_text(
        json.dumps({"id": "preset-a", "name": "Preset A", "engine": "test", "model_path": "model.bin"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config.settings, "storage_path", str(storage))
    monkeypatch.setattr(presets, "PRESETS_DIR", preset_dir)

    assert presets.default_preset_id() == presets.FALLBACK_PRESET_ID
    presets.set_default_preset("preset-a")
    assert presets.default_preset_id() == "preset-a"
    assert json.loads((storage / "preferences.json").read_text(encoding="utf-8"))["default_preset"] == "preset-a"
    assert not (storage / "settings.json").exists()
    presets.delete_preset("preset-a")
    assert presets.default_preset_id() == presets.FALLBACK_PRESET_ID
