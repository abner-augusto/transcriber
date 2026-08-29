"""Tests for Community-1 exclusive diarization, overlap metadata, and clustering preferences."""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np

from engines import DiarizationResult, Turn, Word
from engines.pyannote import PyannoteDiarizer, _UNSET
from models import Meeting, MeetingStatus
from tasks.shared import (
    attribution_turns_from_stored,
    build_segments,
    compute_overlaps,
    exclusive_turns_from_stored,
    overlaps_from_stored,
)


class MockTrack:
    def __init__(self, start, end):
        self.start = start
        self.end = end


class MockAnnotation:
    def __init__(self, tracks):
        # tracks is a list of (start, end, speaker)
        self._tracks = tracks

    def itertracks(self, yield_label=True):
        for start, end, speaker in self._tracks:
            yield MockTrack(start, end), None, speaker


def test_pyannote_diarize_with_community1_exclusive_output(monkeypatch):
    """When Community-1 provides both speaker_diarization and exclusive_speaker_diarization."""
    diarizer = PyannoteDiarizer()

    overlapping_tracks = [
        (0.0, 3.0, "SPEAKER_00"),
        (2.0, 5.0, "SPEAKER_01"),
    ]
    exclusive_tracks = [
        (0.0, 2.0, "SPEAKER_00"),
        (3.0, 5.0, "SPEAKER_01"),
    ]

    mock_output = SimpleNamespace(
        speaker_diarization=MockAnnotation(overlapping_tracks),
        exclusive_speaker_diarization=MockAnnotation(exclusive_tracks),
    )

    mock_pipeline = MagicMock()
    mock_pipeline.return_value = mock_output
    mock_pipeline.parameters.return_value = {"clustering": {"threshold": 0.7}}

    monkeypatch.setattr(PyannoteDiarizer, "get_pipeline", classmethod(lambda cls: mock_pipeline))
    monkeypatch.setattr(
        "engines.pyannote._load_audio_tensor",
        lambda path: (np.zeros((1, 16000)), 16000),
    )

    result = diarizer.diarize("dummy.wav")

    assert isinstance(result, DiarizationResult)
    assert result.turns == [
        Turn(start=0.0, end=3.0, speaker="SPEAKER_00"),
        Turn(start=2.0, end=5.0, speaker="SPEAKER_01"),
    ]
    assert result.exclusive_turns == [
        Turn(start=0.0, end=2.0, speaker="SPEAKER_00"),
        Turn(start=3.0, end=5.0, speaker="SPEAKER_01"),
    ]
    assert result.overlaps == [
        {"start": 2.0, "end": 3.0, "speakers": ["SPEAKER_00", "SPEAKER_01"]},
    ]


def test_pyannote_diarize_fallback_when_exclusive_unavailable(monkeypatch):
    """When running a fallback model or pipeline that does not produce exclusive diarization."""
    diarizer = PyannoteDiarizer()

    tracks = [
        (0.0, 3.0, "SPEAKER_00"),
        (2.0, 5.0, "SPEAKER_01"),
    ]
    mock_output = MockAnnotation(tracks)

    mock_pipeline = MagicMock()
    mock_pipeline.return_value = mock_output
    mock_pipeline.parameters.return_value = {"clustering": {"threshold": 0.7}}

    monkeypatch.setattr(PyannoteDiarizer, "get_pipeline", classmethod(lambda cls: mock_pipeline))
    monkeypatch.setattr(
        "engines.pyannote._load_audio_tensor",
        lambda path: (np.zeros((1, 16000)), 16000),
    )

    result = diarizer.diarize("dummy.wav")

    assert isinstance(result, DiarizationResult)
    assert result.turns == [
        Turn(start=0.0, end=3.0, speaker="SPEAKER_00"),
        Turn(start=2.0, end=5.0, speaker="SPEAKER_01"),
    ]
    assert result.exclusive_turns is None
    assert result.overlaps == [
        {"start": 2.0, "end": 3.0, "speakers": ["SPEAKER_00", "SPEAKER_01"]},
    ]


def test_pyannote_diarize_serialized_format(monkeypatch):
    """When pipeline returns an object supporting serialize()."""
    diarizer = PyannoteDiarizer()

    mock_output = MagicMock()
    del mock_output.speaker_diarization
    mock_output.serialize.return_value = {
        "diarization": [
            {"start": 0.0, "end": 3.0, "speaker": "SPEAKER_00"},
            {"start": 2.0, "end": 5.0, "speaker": "SPEAKER_01"},
        ],
        "exclusive_diarization": [
            {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"},
            {"start": 3.0, "end": 5.0, "speaker": "SPEAKER_01"},
        ],
    }

    mock_pipeline = MagicMock()
    mock_pipeline.return_value = mock_output
    mock_pipeline.parameters.return_value = {}

    monkeypatch.setattr(PyannoteDiarizer, "get_pipeline", classmethod(lambda cls: mock_pipeline))
    monkeypatch.setattr(
        "engines.pyannote._load_audio_tensor",
        lambda path: (np.zeros((1, 16000)), 16000),
    )

    result = diarizer.diarize("dummy.wav")

    assert result.turns == [
        Turn(start=0.0, end=3.0, speaker="SPEAKER_00"),
        Turn(start=2.0, end=5.0, speaker="SPEAKER_01"),
    ]
    assert result.exclusive_turns == [
        Turn(start=0.0, end=2.0, speaker="SPEAKER_00"),
        Turn(start=3.0, end=5.0, speaker="SPEAKER_01"),
    ]


def test_clustering_preferences_applied_only_when_supported(caplog, monkeypatch):
    """Clustering preferences are applied only if supported by the pipeline defaults, logging effective & ignored."""
    mock_pipeline = MagicMock()
    PyannoteDiarizer._pipeline = mock_pipeline
    PyannoteDiarizer._default_params = {
        "clustering": {"threshold": 0.704, "min_cluster_size": 12},
    }
    PyannoteDiarizer._applied_overrides = _UNSET
    PyannoteDiarizer._ignored_overrides = _UNSET

    # Preferences contain one supported parameter (threshold) and unsupported parameters (Fa, Fb, unknown_param)
    test_prefs = {
        "diarization": {
            "clustering_threshold": 0.55,
            "Fa": 0.2,
            "Fb": 0.8,
            "unsupported_knob": 42.0,
        }
    }
    monkeypatch.setattr("engines.pyannote.load_preferences", lambda: test_prefs)

    with caplog.at_level(logging.INFO):
        PyannoteDiarizer._sync_clustering_overrides()

    # Verify instantiate was called ONLY with supported parameters
    mock_pipeline.instantiate.assert_called_once_with({
        "clustering": {"threshold": 0.55, "min_cluster_size": 12},
    })
    assert PyannoteDiarizer._applied_overrides == {"threshold": 0.55}

    # Verify logs captured warning for ignored params and info for applied params
    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    infos = [r.message for r in caplog.records if r.levelno == logging.INFO]

    assert any("Ignored unsupported clustering parameter(s)" in w for w in warnings)
    assert any("Fa" in w and "Fb" in w for w in warnings)
    assert any("Applied clustering overrides {'threshold': 0.55}" in i for i in infos)


def test_clustering_preferences_cleared_restores_defaults(caplog, monkeypatch):
    """Unsetting preferences restores default pipeline hyperparameters."""
    mock_pipeline = MagicMock()
    PyannoteDiarizer._pipeline = mock_pipeline
    PyannoteDiarizer._default_params = {
        "clustering": {"threshold": 0.704},
    }
    PyannoteDiarizer._applied_overrides = {"threshold": 0.55}
    PyannoteDiarizer._ignored_overrides = {}

    monkeypatch.setattr("engines.pyannote.load_preferences", lambda: {})

    with caplog.at_level(logging.INFO):
        PyannoteDiarizer._sync_clustering_overrides()

    mock_pipeline.instantiate.assert_called_once_with({
        "clustering": {"threshold": 0.704},
    })
    assert PyannoteDiarizer._applied_overrides == {}
    assert any("Cleared clustering overrides; using pipeline defaults" in r.message for r in caplog.records)


def test_meeting_to_dict_exposes_overlap_information():
    """Meeting.to_dict(include_segments=True) returns overlap metadata."""
    raw_diar = {
        "engine": "pyannote",
        "turns": [
            {"start": 0.0, "end": 4.0, "speaker": "SPEAKER_00"},
            {"start": 3.0, "end": 6.0, "speaker": "SPEAKER_01"},
        ],
        "exclusive_turns": [
            {"start": 0.0, "end": 3.0, "speaker": "SPEAKER_00"},
            {"start": 4.0, "end": 6.0, "speaker": "SPEAKER_01"},
        ],
        "overlaps": [
            {"start": 3.0, "end": 4.0, "speakers": ["SPEAKER_00", "SPEAKER_01"]},
        ],
    }
    meeting = Meeting(
        title="Overlap Test",
        status=MeetingStatus.COMPLETED,
        raw_diarization=raw_diar,
    )

    data = meeting.to_dict(include_segments=True)
    assert "overlaps" in data
    assert data["overlaps"] == [
        {"start": 3.0, "end": 4.0, "speakers": ["SPEAKER_00", "SPEAKER_01"]},
    ]


def test_segment_attribution_uses_exclusive_turns_over_overlapping_turns():
    """Words in overlapping audio regions are attributed according to exclusive Turns."""
    words = [
        Word(start=0.0, end=1.0, text=" hello"),
        Word(start=3.2, end=3.8, text=" overlapping_word"),
        Word(start=5.0, end=6.0, text=" goodbye"),
    ]

    overlapping_turns = [
        Turn(start=0.0, end=4.0, speaker="SPEAKER_00"),
        Turn(start=3.0, end=6.0, speaker="SPEAKER_01"),
    ]

    exclusive_turns = [
        Turn(start=0.0, end=3.0, speaker="SPEAKER_00"),
        Turn(start=3.0, end=6.0, speaker="SPEAKER_01"),
    ]

    segments_exclusive = build_segments(words, exclusive_turns)
    assert segments_exclusive[0]["speaker"] == "SPEAKER_00"
    assert segments_exclusive[0]["text"] == "hello"

    assert segments_exclusive[1]["speaker"] == "SPEAKER_01"
    assert "overlapping_word" in segments_exclusive[1]["text"]


def test_process_meeting_and_rediarize_tasks_with_exclusive_turns(monkeypatch, tmp_path):
    """Full processing and re-diarization persist exclusive turns + overlaps and use exclusive attribution."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database import Base
    from models import Job, Meeting, MeetingStatus
    from models.job import JobStatus, JobType
    from tasks.process_meeting import process_meeting_task
    from tasks.reprocess_task import rediarize_task, reidentify_task
    from .fakes import FakeDiarizer, FakeTranscriber

    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=test_engine)
    TestingSessionLocal = sessionmaker(bind=test_engine)

    monkeypatch.setattr("tasks.process_meeting.SessionLocal", TestingSessionLocal)
    monkeypatch.setattr("tasks.reprocess_task.SessionLocal", TestingSessionLocal)

    db = TestingSessionLocal()

    meeting = Meeting(
        title="Task Test",
        status=MeetingStatus.UPLOADED,
        audio_filepath=str(tmp_path / "test.wav"),
    )
    db.add(meeting)
    db.commit()

    job = Job(
        meeting_id=meeting.id,
        job_type=JobType.PROCESS_MEETING,
        status=JobStatus.PENDING,
    )
    db.add(job)
    db.commit()

    words = [
        Word(start=0.0, end=1.0, text=" hello"),
        Word(start=3.2, end=3.8, text=" overlapping"),
    ]
    overlapping_turns = [
        Turn(start=0.0, end=4.0, speaker="SPEAKER_00"),
        Turn(start=3.0, end=6.0, speaker="SPEAKER_01"),
    ]
    exclusive_turns = [
        Turn(start=0.0, end=3.0, speaker="SPEAKER_00"),
        Turn(start=3.0, end=6.0, speaker="SPEAKER_01"),
    ]

    diar_result = DiarizationResult(
        turns=overlapping_turns,
        exclusive_turns=exclusive_turns,
    )

    monkeypatch.setattr("tasks.process_meeting.make_transcriber", lambda preset: FakeTranscriber(words))
    monkeypatch.setattr("tasks.process_meeting.make_diarizer", lambda: FakeDiarizer(diar_result))
    monkeypatch.setattr("tasks.reprocess_task.make_diarizer", lambda: FakeDiarizer(diar_result))
    monkeypatch.setattr("services.audio_service.AudioService.extract_audio", lambda self, fp, mid: fp)
    monkeypatch.setattr("services.audio_service.AudioService.get_duration", lambda self, fp: 10.0)
    monkeypatch.setattr("services.vad_service.VadService.compute_vad_segments", lambda self, fp: [(0.0, 10.0)])
    monkeypatch.setattr("tasks.shared.publish_event", lambda mid, data: None)

    # 1. Run process_meeting_task
    res = process_meeting_task(meeting.id, job.id)
    assert res.get("status") == "completed"

    db.refresh(meeting)
    assert meeting.raw_diarization is not None
    assert "turns" in meeting.raw_diarization
    assert "exclusive_turns" in meeting.raw_diarization
    assert "overlaps" in meeting.raw_diarization
    assert len(meeting.raw_diarization["overlaps"]) == 1
    assert meeting.raw_diarization["overlaps"][0] == {
        "start": 3.0,
        "end": 4.0,
        "speakers": ["SPEAKER_00", "SPEAKER_01"],
    }

    segments = sorted(meeting.segments, key=lambda s: s.order)
    assert len(segments) == 2
    # The overlapping word at 3.2-3.8 is attributed to SPEAKER_01 via exclusive turns
    assert segments[1].speaker.label == "SPEAKER_01"

    # 2. Run rediarize_task
    job_rediar = Job(
        meeting_id=meeting.id,
        job_type=JobType.REDIARIZE,
        status=JobStatus.PENDING,
    )
    db.add(job_rediar)
    db.commit()

    res_rediar = rediarize_task(meeting.id, job_rediar.id)
    assert res_rediar.get("status") == "completed"

    db.refresh(meeting)
    assert meeting.raw_diarization["exclusive_turns"] is not None
    segments_rediar = sorted(meeting.segments, key=lambda s: s.order)
    assert len(segments_rediar) == 2
    assert segments_rediar[1].speaker.label == "SPEAKER_01"

    # 3. Run reidentify_task
    job_reid = Job(
        meeting_id=meeting.id,
        job_type=JobType.REIDENTIFY,
        status=JobStatus.PENDING,
    )
    db.add(job_reid)
    db.commit()

    res_reid = reidentify_task(meeting.id, job_reid.id)
    assert res_reid.get("status") == "completed"

    db.refresh(meeting)
    segments_reid = sorted(meeting.segments, key=lambda s: s.order)
    assert len(segments_reid) == 2
    assert segments_reid[1].speaker.label == "SPEAKER_01"
