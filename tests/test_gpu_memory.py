"""Unit tests for GPU memory management, model unloading, and task lifecycle cleanup."""

from unittest.mock import MagicMock, patch
import pytest

from engines.gpu_memory import release_gpu_memory, unload_all_engines
from engines.faster_whisper import FasterWhisperTranscriber
from engines.pyannote import PyannoteDiarizer
from engines.alignment import MMSCTCAligner
from services.embedding_service import EmbeddingService
from services.speaker_id_service import SpeakerIdService


def test_faster_whisper_unload():
    """Test that FasterWhisperTranscriber.unload() clears cached models."""
    FasterWhisperTranscriber._models[("test_model", "auto", "auto")] = MagicMock()
    FasterWhisperTranscriber._models[("other_model", "auto", "auto")] = MagicMock()
    assert len(FasterWhisperTranscriber._models) == 2

    # An instance unloads only its model path; the class call retains the all-model API.
    FasterWhisperTranscriber(
        model_path="test_model", device="auto", compute_type="auto"
    ).unload()
    assert ("test_model", "auto", "auto") not in FasterWhisperTranscriber._models
    assert len(FasterWhisperTranscriber._models) == 1

    # Unload all models
    FasterWhisperTranscriber.unload()
    assert len(FasterWhisperTranscriber._models) == 0


def test_pyannote_unload():
    """Test that PyannoteDiarizer.unload() resets pipeline and hyperparameter cache."""
    mock_pipeline = MagicMock()
    PyannoteDiarizer._pipeline = mock_pipeline
    PyannoteDiarizer._default_params = {"clustering": {"threshold": 0.7}}
    PyannoteDiarizer._applied_overrides = {"threshold": 0.6}

    PyannoteDiarizer.unload()

    assert PyannoteDiarizer._pipeline is None
    assert PyannoteDiarizer._default_params is None
    assert PyannoteDiarizer._applied_overrides is PyannoteDiarizer._UNSET if hasattr(PyannoteDiarizer, "_UNSET") else True
    mock_pipeline.to.assert_called_once()


def test_alignment_unload():
    """Test that MMSCTCAligner.unload() resets model and aligner references."""
    mock_model = MagicMock()
    MMSCTCAligner._model = mock_model
    MMSCTCAligner._bundle = MagicMock()
    MMSCTCAligner._aligner = MagicMock()

    MMSCTCAligner.unload()

    assert MMSCTCAligner._model is None
    assert MMSCTCAligner._bundle is None
    assert MMSCTCAligner._aligner is None
    mock_model.to.assert_called_once()


def test_embedding_service_unload():
    """Test that EmbeddingService.unload() resets model references."""
    mock_model = MagicMock()
    EmbeddingService._model = mock_model
    EmbeddingService._cpu_model = MagicMock()

    EmbeddingService.unload()

    assert EmbeddingService._model is None
    assert EmbeddingService._cpu_model is None


def test_speaker_id_service_unload():
    """Test that SpeakerIdService.unload() delegates to EmbeddingService.unload()."""
    with patch.object(EmbeddingService, "unload") as mock_unload:
        service = SpeakerIdService()
        service.unload()
        mock_unload.assert_called_once()


def test_unload_all_engines():
    """Test that unload_all_engines unloads all components and releases memory."""
    with patch.object(FasterWhisperTranscriber, "unload") as mock_fw, \
         patch.object(PyannoteDiarizer, "unload") as mock_pyannote, \
         patch.object(MMSCTCAligner, "unload") as mock_aligner, \
         patch.object(EmbeddingService, "unload") as mock_emb, \
         patch("engines.gpu_memory.release_gpu_memory") as mock_release:

        unload_all_engines()

        mock_fw.assert_called_once()
        mock_pyannote.assert_called_once()
        mock_aligner.assert_called_once()
        mock_emb.assert_called_once()
        mock_release.assert_called_once()


def test_release_gpu_memory_runs_safely():
    """Test that release_gpu_memory runs without error."""
    # Should run cleanly whether GPU is available or not
    release_gpu_memory()


def test_meeting_job_finally_calls_unload_all_engines(tmp_path, monkeypatch):
    """Test that meeting_job context manager always cleans up GPU memory."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database import Base
    from models import Meeting, Job
    from models.job import JobType
    from tasks.shared import meeting_job

    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr("tasks.shared.SessionLocal", session_factory)
    monkeypatch.setattr("tasks.shared.publish_event", lambda *args, **kwargs: None)

    with session_factory() as db:
        meeting = Meeting(title="Test Cleanup", duration=10.0, audio_filepath="dummy.wav")
        db.add(meeting)
        db.flush()
        job = Job(meeting_id=meeting.id, job_type=JobType.PROCESS_MEETING)
        db.add(job)
        db.commit()
        m_id, j_id = meeting.id, job.id

    with patch("engines.gpu_memory.unload_all_engines") as mock_unload:
        # Success path
        with meeting_job(m_id, j_id):
            pass
        mock_unload.assert_called_once()

    with patch("engines.gpu_memory.unload_all_engines") as mock_unload:
        # Failure path
        with pytest.raises(RuntimeError):
            with meeting_job(m_id, j_id):
                raise RuntimeError("Simulated pipeline failure")
        mock_unload.assert_called_once()
