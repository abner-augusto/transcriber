"""Jobs read an original recording where its Source Reference says, and leave it alone."""

import services.audio_service as audio_service
from models.job import JobStatus, JobType
from services import source_reference as sources
from tasks.process_meeting import process_meeting_task
from tasks.reprocess_task import rediarize_task

from . import task_harness as h
from .fakes import FakeTranscriber


def _originals(tmp_path):
    mic = tmp_path / "project" / "mic.wav"
    system = tmp_path / "project" / "system.wav"
    mic.parent.mkdir()
    mic.write_bytes(b"m" * 100)
    system.write_bytes(b"s" * 100)
    return mic, system


def _referenced(harness, tmp_path, mic, system):
    meeting_id = harness.meeting(dual_track=True)
    with harness.session_factory() as db:
        meeting = db.get(h.Meeting, meeting_id)
        meeting.audio_filepath = None
        meeting.mic_audio_filepath = meeting.system_audio_filepath = None
        meeting.source_refs = {
            "mic": sources.reference(mic, path=str(mic)),
            "system": sources.reference(system, path=str(system)),
        }
        db.commit()
    return meeting_id


def _install(monkeypatch, tmp_path):
    harness = h.install(
        monkeypatch, tmp_path, transcriber=FakeTranscriber(h.WORDS), diarization=h.PYANNOTE
    )
    monkeypatch.setattr("tasks.process_meeting.vocabulary_correction_for_meeting", lambda *a, **k: None)
    return harness


def test_full_processing_extracts_from_the_original_where_it_lives(monkeypatch, tmp_path):
    harness = _install(monkeypatch, tmp_path)
    mic, system = _originals(tmp_path)
    meeting_id = _referenced(harness, tmp_path, mic, system)
    inputs = []

    def extract(self, mic_path, system_path, mid):
        inputs.append((mic_path, system_path))
        harness.write_dual_tracks(mid)
        return str(harness.storage / mid / "mixed.wav")

    monkeypatch.setattr(audio_service.AudioService, "extract_dual_audio", extract)

    job_id = harness.job(meeting_id, JobType.PROCESS_MEETING)
    assert process_meeting_task(meeting_id, job_id)["status"] == "completed"

    assert inputs == [(str(mic), str(system))]
    assert mic.read_bytes() == b"m" * 100 and system.read_bytes() == b"s" * 100
    meeting = harness.load(meeting_id)
    assert (meeting.mic_audio_filepath, meeting.system_audio_filepath) == (None, None)
    assert meeting.source_refs["mic"]["path"] == str(mic)


def test_full_processing_fails_the_job_with_the_repoint_message_when_the_original_is_gone(
    monkeypatch, tmp_path
):
    harness = _install(monkeypatch, tmp_path)
    mic, system = _originals(tmp_path)
    meeting_id = _referenced(harness, tmp_path, mic, system)
    mic.unlink()

    job_id = harness.job(meeting_id, JobType.PROCESS_MEETING)
    try:
        process_meeting_task(meeting_id, job_id)
    except Exception:
        pass

    job = harness.job_row(job_id)
    assert job.status == JobStatus.FAILED
    assert f"transcriber_cli set {meeting_id} --source NEW_PATH" in job.error


def _tracks_recorder(monkeypatch, harness):
    made = []

    def extract_tracks(self, mic_path, system_path, mid):
        made.append((mic_path, system_path))
        harness.write_dual_tracks(mid)

    monkeypatch.setattr(audio_service.AudioService, "extract_dual_tracks", extract_tracks, raising=False)
    return made


def _processed_without_tracks(harness, meeting_id):
    with harness.session_factory() as db:
        meeting = db.get(h.Meeting, meeting_id)
        meeting.raw_transcription = {"engine": "x", "words": [
            {"start": w.start, "end": w.end, "text": w.text} for w in h.WORDS
        ]}
        db.commit()


def test_rediarize_makes_the_tracks_from_the_original_and_removes_them_again(monkeypatch, tmp_path):
    harness = _install(monkeypatch, tmp_path)
    mic, system = _originals(tmp_path)
    meeting_id = _referenced(harness, tmp_path, mic, system)
    _processed_without_tracks(harness, meeting_id)
    made = _tracks_recorder(monkeypatch, harness)
    with harness.session_factory() as db:
        db.get(h.Meeting, meeting_id).audio_filepath = str(harness.storage / meeting_id / "audio.wav")
        db.commit()

    job_id = harness.job(meeting_id, JobType.REDIARIZE)
    assert rediarize_task(meeting_id, job_id)["status"] == "completed"

    assert made == [(str(mic), str(system))]
    assert harness.diarizer.calls[0][0].endswith("system_processed.wav")
    assert not (harness.track_dir(meeting_id) / "mic_processed.wav").exists()
    assert not (harness.track_dir(meeting_id) / "system_processed.wav").exists()
    assert mic.exists() and system.exists()


def test_rediarize_removes_the_tracks_it_made_even_when_it_fails(monkeypatch, tmp_path):
    harness = _install(monkeypatch, tmp_path)
    mic, system = _originals(tmp_path)
    meeting_id = _referenced(harness, tmp_path, mic, system)
    _processed_without_tracks(harness, meeting_id)
    _tracks_recorder(monkeypatch, harness)
    monkeypatch.setattr(
        "tasks.reprocess_task.diarize_meeting",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("diarizer failed")),
    )
    with harness.session_factory() as db:
        db.get(h.Meeting, meeting_id).audio_filepath = str(harness.storage / meeting_id / "audio.wav")
        db.commit()

    job_id = harness.job(meeting_id, JobType.REDIARIZE)
    try:
        rediarize_task(meeting_id, job_id)
    except RuntimeError:
        pass

    assert not (harness.track_dir(meeting_id) / "system_processed.wav").exists()


def test_rediarize_leaves_tracks_it_did_not_make(monkeypatch, tmp_path):
    harness = _install(monkeypatch, tmp_path)
    mic, system = _originals(tmp_path)
    meeting_id = _referenced(harness, tmp_path, mic, system)
    _processed_without_tracks(harness, meeting_id)
    made = _tracks_recorder(monkeypatch, harness)
    harness.write_dual_tracks(meeting_id)  # a Meeting processed before plan 045 still has them
    with harness.session_factory() as db:
        db.get(h.Meeting, meeting_id).audio_filepath = str(harness.storage / meeting_id / "audio.wav")
        db.commit()

    job_id = harness.job(meeting_id, JobType.REDIARIZE)
    assert rediarize_task(meeting_id, job_id)["status"] == "completed"

    assert made == []
    assert (harness.track_dir(meeting_id) / "system_processed.wav").exists()


def test_rediarize_without_tracks_or_original_fails_with_the_repoint_message(monkeypatch, tmp_path):
    harness = _install(monkeypatch, tmp_path)
    mic, system = _originals(tmp_path)
    meeting_id = _referenced(harness, tmp_path, mic, system)
    _processed_without_tracks(harness, meeting_id)
    system.unlink()
    with harness.session_factory() as db:
        db.get(h.Meeting, meeting_id).audio_filepath = str(harness.storage / meeting_id / "audio.wav")
        db.commit()

    job_id = harness.job(meeting_id, JobType.REDIARIZE)
    try:
        rediarize_task(meeting_id, job_id)
    except Exception:
        pass

    job = harness.job_row(job_id)
    assert job.status == JobStatus.FAILED
    assert "--system-source NEW_PATH" in job.error
    assert harness.diarizer.calls == []
